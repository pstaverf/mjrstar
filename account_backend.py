import asyncio
import html
import json
import math
import re
import secrets
import time
from datetime import datetime, timedelta

from aiogram.types import User

from games_backend import GameError, integer, serialize
from privacy_rules import PRIVACY_CACHE, TELEGRAM_NAMES, player_identity, public_names


GAME_LABELS = {"crash": "Краш", "roulette": "Рулетка", "wheel": "Wheel", "mines": "Мины", "keno": "Кено", "hilo": "Hi-Lo", "redblack": "Red & Black", "ladder": "Лесенка", "upgrade": "Апгрейд", "dice": "Кости", "bowl": "Боулинг", "darts": "Дартс", "basket": "Баскетбол", "foot": "Футбол", "slots": "Слоты", "blackjack": "Блэкджек", "doghouse": "DogHouse", "arena": "ArenaHub", "arenahub": "ArenaHub", "portal": "ArenaHub", "escape": "Escape", "race": "Race", "bomb": "Bomb", "sumo": "Sumo", "coinflip": "Орёл-Решка", "claw": "Автомат", "baccarat": "Баккара"}


class AccountMixin:
    def response(self, data, status=200):
        return super().response(public_names(data), status)

    def register_account(self, application):
        application.router.add_get("/api/profile/stats", self.handle_profile_stats)
        application.router.add_get("/api/profile/all-rounds", self.handle_all_rounds)
        application.router.add_get("/api/profile/all-rounds/page-dates", self.handle_all_round_dates)
        application.router.add_get("/api/bonuses/state", self.handle_bonus_state)
        application.router.add_post("/api/bonuses/existing/claim", self.handle_existing_bonus)
        application.router.add_get("/api/privacy", self.handle_privacy)
        for action in ("mode", "toggle", "nickname", "nickname/delete"):
            application.router.add_post("/api/privacy/" + action, self.handle_privacy)
        for section in ("stats", "list", "history", "top", "notifications"):
            application.router.add_get("/api/referral/" + section, self.handle_referrals)
        application.router.add_post("/api/referral/notifications", self.handle_referrals)
        application.router.add_post("/api/referral/withdraw", self.handle_referral_withdraw)

    async def initialize_account(self):
        async with self.database_lock:
            connection = self.database()
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_privacy(user_id INTEGER PRIMARY KEY,mode TEXT NOT NULL DEFAULT 'username',nickname TEXT NOT NULL DEFAULT '',hidden INTEGER NOT NULL DEFAULT 0,clickable INTEGER NOT NULL DEFAULT 1,game_uid TEXT NOT NULL UNIQUE)")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_preferences(user_id INTEGER PRIMARY KEY,ref_notifications INTEGER NOT NULL DEFAULT 1,check_notifications INTEGER NOT NULL DEFAULT 1)")
            await connection.execute("CREATE TABLE IF NOT EXISTS usernames(user_id INTEGER PRIMARY KEY,username TEXT,full_name TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL)")
            async with connection.execute("SELECT user_id,mode,nickname,hidden,clickable,game_uid FROM webapp_privacy") as cursor:
                PRIVACY_CACHE.clear()
                PRIVACY_CACHE.update({row[0]: row[1:] for row in await cursor.fetchall()})
            async with connection.execute("SELECT user_id,username FROM usernames") as cursor:
                TELEGRAM_NAMES.clear()
                TELEGRAM_NAMES.update(dict(await cursor.fetchall()))
            await connection.commit()
        self.bonus_claim_locks = {}

    def wallet_page(self, request, zero=False):
        return integer(request.query.get("page", "0" if zero else "1"), 0 if zero else 1, 1000000)

    async def privacy_row(self, connection, user_id):
        await connection.execute("INSERT OR IGNORE INTO webapp_privacy(user_id,game_uid) VALUES (?,?)", (user_id, secrets.token_hex(6).upper()))
        async with connection.execute("SELECT mode,nickname,hidden,clickable,game_uid FROM webapp_privacy WHERE user_id = ?", (user_id,)) as cursor:
            mode, nickname, hidden, clickable, game_uid = await cursor.fetchone()
        return {"ok": True, "privacyMode": mode, "displayName": nickname, "hideFromLeaderboard": bool(hidden), "clickableProfile": bool(clickable), "gameUid": game_uid}

    async def public_identity(self, connection, user_id, fallback=""):
        async with connection.execute("SELECT mode,nickname,hidden,clickable,game_uid FROM webapp_privacy WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            return {"id": user_id, "name": fallback or "Игрок", "hidden": False, "clickable": True}
        mode, nickname, hidden, clickable, game_uid = row
        name, can_click = player_identity(user_id, fallback or "Игрок")
        return {"id": user_id if mode in {"username", "nickname"} and clickable else None, "name": name, "hidden": bool(hidden), "clickable": bool(clickable)}

    async def handle_privacy(self, request):
        try:
            payload = await self.payload(request) if request.method == "POST" else {}
            user = self.validate_user(request, payload)
            key, signature = self.request_identity(request, payload) if request.method == "POST" else (None, None)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    if key:
                        existing = await self.load_receipt(connection, user.id, key, signature)
                        if existing:
                            await connection.rollback()
                            return self.response(existing)
                    state = await self.privacy_row(connection, user.id)
                    action = request.path.removeprefix("/api/privacy/")
                    if request.method == "POST":
                        if action == "mode":
                            mode = payload.get("mode")
                            if not isinstance(mode, str) or mode not in {"username", "hidden", "blank", "game_id", "nickname"}:
                                raise GameError("Неизвестный режим приватности.")
                            if mode == "nickname" and not state["displayName"]:
                                raise GameError("nickname_required")
                            await connection.execute("UPDATE webapp_privacy SET mode = ? WHERE user_id = ?", (mode, user.id))
                        elif action == "toggle":
                            requested_field = payload.get("field")
                            field = {"hide": "hidden", "clickable": "clickable"}.get(requested_field) if isinstance(requested_field, str) else None
                            if not field:
                                raise GameError("Неизвестная настройка.")
                            await connection.execute(f"UPDATE webapp_privacy SET {field} = 1 - {field} WHERE user_id = ?", (user.id,))
                        elif action == "nickname/delete":
                            await connection.execute("UPDATE webapp_privacy SET nickname = '',mode = CASE WHEN mode = 'nickname' THEN 'username' ELSE mode END WHERE user_id = ?", (user.id,))
                        elif action == "nickname":
                            name = payload.get("name")
                            if not isinstance(name, str) or not re.fullmatch(r"[\w]{3,20}", name, flags=re.UNICODE):
                                raise GameError("Псевдоним: 3–20 букв, цифр или знаков подчёркивания.")
                            if not isinstance(payload.get("activate", False), bool):
                                raise GameError("Некорректный режим.")
                            await self.debit(connection, user.id, 100)
                            await connection.execute("UPDATE webapp_privacy SET nickname = ?,mode = CASE WHEN ? THEN 'nickname' ELSE mode END WHERE user_id = ?", (name, payload.get("activate", False), user.id))
                            await connection.execute("INSERT INTO webapp_wallet_events(user_id,kind,amount_cents,source,created_at) VALUES (?,'nickname',-100,?,?)", (user.id, "nickname:" + str(user.id) + ":" + key, self.clock().isoformat()))
                    result = await self.privacy_row(connection, user.id)
                    result["balance"] = await self.balance(connection, user.id)
                    if key:
                        await self.save_receipt(connection, user.id, key, signature, result)
                    await connection.commit()
                    PRIVACY_CACHE[user.id] = (result["privacyMode"], result["displayName"], result["hideFromLeaderboard"], result["clickableProfile"], result["gameUid"])
                except BaseException:
                    await connection.rollback()
                    raise
            return self.response(result)
        except GameError as error:
            return self.failure(error)

    async def handle_bonus_state(self, request):
        user = self.validate_user(request)
        async with self.database_lock:
            connection = self.database()
            async with connection.execute("SELECT queued_at,streak,last_claim FROM bonus WHERE user_id = ?", (user.id,)) as cursor:
                record = await cursor.fetchone()
            async with connection.execute("SELECT COALESCE(SUM(amount_cents),0) FROM webapp_wallet_events WHERE user_id = ? AND kind = 'bonus'", (user.id,)) as cursor:
                total = (await cursor.fetchone())[0] / 100
        runtime = getattr(self, "wallet_runtime", {})
        cooldown = runtime.get("BONUS_COOLDOWN", timedelta(hours=12)).total_seconds()
        queued = datetime.fromisoformat(record[0]).timestamp() if record and record[0] else None
        remaining = max(0, math.ceil(queued + cooldown - time.time())) if queued else 0
        return self.response({"ok": True, "existingBonus": {"bioText": runtime.get("BONUS_BIO_TEXT", "@mjrstars"), "cooldownSeconds": cooldown, "queued": queued is not None, "secondsLeft": remaining, "streak": record[1] if record else 0, "lastClaim": record[2] if record else None, "total": total, "baseMin": runtime.get("BONUS_BASE_MIN", 1), "baseMax": runtime.get("BONUS_BASE_MAX", 3), "streakBase": runtime.get("BONUS_STREAK_BASE", 0.1), "streakStep": runtime.get("BONUS_STREAK_STEP", 0.05)}})

    async def handle_existing_bonus(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            runtime = getattr(self, "wallet_runtime", {})
            process = runtime.get("process_bonus")
            bot = getattr(self, "telegram_bot", None)
            if not process or bot is None:
                raise GameError("Проверка описания Telegram временно недоступна.", 503)
            messages = []
            async def capture(text, **kwargs):
                messages.append(html.unescape(re.sub(r"<[^>]*>", "", text)))
            lock = self.bonus_claim_locks.setdefault(user.id, asyncio.Lock())
            async with lock:
                async with self.database_lock:
                    async with self.database().execute("SELECT COALESCE(MAX(id),0) FROM webapp_wallet_events WHERE user_id = ? AND kind = 'bonus'", (user.id,)) as cursor:
                        baseline = (await cursor.fetchone())[0]
                await process(user.id, User(id=user.id, is_bot=False, first_name=user.first_name, last_name=user.last_name, username=user.username, is_premium=user.is_premium), bot, capture)
            async with self.database_lock:
                balance = await self.balance(self.database(), user.id)
                async with self.database().execute("SELECT COALESCE(SUM(amount_cents),0) FROM webapp_wallet_events WHERE user_id = ? AND kind = 'bonus' AND id > ?", (user.id, baseline)) as cursor:
                    credited = (await cursor.fetchone())[0] / 100
            state_response = await self.handle_bonus_state(request)
            return self.response({"ok": True, "message": "\n".join(messages), "creditedAmount": credited, "balance": balance, "state": json.loads(state_response.body)})
        except GameError as error:
            return self.failure(error)

    async def handle_profile_stats(self, request):
        try:
            user = self.validate_user(request)
            async with self.database_lock:
                connection = self.database()
                events, names = await self.leaderboard_events(connection)
                async with connection.execute("SELECT COUNT(*),COALESCE(SUM(bet_cents),0),COALESCE(SUM(paid_cents > bet_cents),0) FROM (" + events + ") WHERE user_id = ?", (user.id,)) as cursor:
                    rounds, turnover, wins = await cursor.fetchone()
                async with connection.execute("SELECT amount,created_at FROM balances WHERE user_id = ?", (user.id,)) as cursor:
                    balance_row = await cursor.fetchone()
                async with connection.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE user_id = ?", (user.id,)) as cursor:
                    deposits = (await cursor.fetchone())[0]
                async with connection.execute("SELECT COALESCE(SUM(stars_cents),0) FROM webapp_deposits WHERE user_id = ? AND provider != 'stars' AND status = 'paid'", (user.id,)) as cursor:
                    deposits += (await cursor.fetchone())[0] / 100
                async with connection.execute("SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE user_id = ? AND status = 'approved'", (user.id,)) as cursor:
                    cashouts = (await cursor.fetchone())[0]
                async with connection.execute("SELECT COALESCE(SUM(quantity),0) FROM webapp_star_withdrawals WHERE user_id = ? AND state = 'completed'", (user.id,)) as cursor:
                    cashouts += (await cursor.fetchone())[0]
                async with connection.execute("SELECT COALESCE(SUM(amount_cents),0) FROM webapp_wallet_events WHERE user_id = ? AND kind = 'bonus'", (user.id,)) as cursor:
                    bonuses = (await cursor.fetchone())[0] / 100
            registration = balance_row[1] if balance_row else None
            days = max(0, (self.clock().date() - datetime.fromisoformat(registration).date()).days) if registration else 0
            label = "день" if days % 10 == 1 and days % 100 != 11 else "дня" if days % 10 in {2, 3, 4} and days % 100 not in {12, 13, 14} else "дней"
            return self.response({"ok": True, "balance": balance_row[0] if balance_row else 0, "turnover": turnover / 100, "winPercent": round(wins / rounds * 100, 2) if rounds else 0, "registrationDate": registration, "daysWithUs": days, "daysWithUsLabel": label, "deposits": deposits, "cashouts": cashouts, "bonuses": bonuses})
        except GameError as error:
            return self.failure(error)

    async def account_history_source(self, connection):
        sources = ["SELECT id,public_id,game,user_id,username,bet_cents,payout_cents,response,created_at FROM webapp_rounds"]
        async with connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cursor:
            tables = {row[0] for row in await cursor.fetchall()}
        for table, game in (("mines_history", "mines"), ("football_history", "foot"), ("basketball_history", "basket"), ("slot_history", "slots"), ("dice_history", "dice")):
            if table not in tables:
                continue
            game_expression = "CASE game WHEN 'bowling' THEN 'bowl' WHEN 'darts' THEN 'darts' ELSE 'dice' END" if table == "dice_history" else "'" + game + "'"
            extra = ", 'minesCount',mines_count,'cellsOpened',opened,'maxSteps',25-mines_count" if game == "mines" else ", 'outcome',player_range" if game in {"foot", "basket", "dice"} else ", 'diceValue',dice_value"
            metadata = "json_object('playedInBot',json('true'),'multiplier',multiplier,'result',CASE WHEN win_amount > bet THEN 'win' WHEN win_amount = bet THEN 'draw' ELSE 'lose' END" + extra + ")"
            sources.append(f"SELECT id,'bot-{game}-'||id,{game_expression},user_id,'',CAST(ROUND(bet*100) AS INTEGER),CAST(ROUND(win_amount*100) AS INTEGER),{metadata},created_at FROM {table}")
        if "crash_games" in tables:
            sources.append("SELECT id,'bot-crash-'||id,'crash',user_id,'',CAST(ROUND(bet*100) AS INTEGER),CASE WHEN won THEN CAST(ROUND(bet*multiplier*100) AS INTEGER) ELSE 0 END,json_object('playedInBot',json('true'),'result',CASE WHEN won THEN 'win' ELSE 'lose' END,'crashPoint',crash_point,'cashoutMult',multiplier),created_at FROM crash_games")
        return " UNION ALL ".join(sources)

    def account_history_filter(self, request, user_id):
        conditions, values = ["user_id = ?"], [user_id]
        label = request.query.get("game", "")
        if label:
            keys = [key for key, value in GAME_LABELS.items() if value == label]
            if not keys:
                raise GameError("Неизвестная игра.")
            conditions.append("game IN (" + ",".join("?" for key in keys) + ")")
            values.extend(keys)
        query = request.query.get("q", "").strip()
        if len(query) > 100:
            raise GameError("Слишком длинный запрос.")
        if query:
            conditions.append("(public_id = ? OR CAST(id AS TEXT) = ? OR substr(created_at,1,10) = ?)")
            values.extend([query, query, query])
        return " WHERE " + " AND ".join(conditions), values

    async def handle_all_rounds(self, request):
        try:
            user = self.validate_user(request)
            page = self.wallet_page(request)
            size = integer(request.query.get("pageSize", "10"), 1, 100)
            condition, values = self.account_history_filter(request, user.id)
            async with self.database_lock:
                connection = self.database()
                source = "(" + await self.account_history_source(connection) + ")"
                async with connection.execute("SELECT COUNT(*) FROM " + source + condition, values) as cursor:
                    total = (await cursor.fetchone())[0]
                async with connection.execute("SELECT id,public_id,game,username,bet_cents,payout_cents,response,created_at FROM " + source + condition + " ORDER BY julianday(created_at) DESC,public_id DESC LIMIT ? OFFSET ?", values + [size, (page - 1) * size]) as cursor:
                    records = await cursor.fetchall()
            rows = []
            for row in records:
                detail = json.loads(row[6])
                detail.pop("balance", None)
                if row[2] == "coinflip" and detail.get("finishAt", 0) > time.time() * 1000:
                    detail.pop("serverSeed", None)
                for name in list(detail):
                    if name.startswith("_"):
                        detail.pop(name)
                rows.append({"id": row[0], "publicId": row[1], "game": GAME_LABELS.get(row[2], row[2]), "user_id": user.id, "username": row[3], "bet": row[4] / 100, "win_amount": row[5] / 100, "result": detail.get("result", "win" if row[5] > row[4] else "draw" if row[5] == row[4] else "lose"), "meta": serialize(detail), "created_at": row[7]})
            return self.response({"ok": True, "rows": rows, "page": page, "total": total, "totalPages": max(1, (total + size - 1) // size)})
        except GameError as error:
            return self.failure(error)

    async def handle_all_round_dates(self, request):
        try:
            user = self.validate_user(request)
            size = integer(request.query.get("pageSize", "10"), 1, 100)
            pages = [integer(value, 1, 1000000) for value in request.query.get("pages", "1").split(",")]
            if len(pages) > 20:
                raise GameError("Слишком много страниц.")
            condition, values = self.account_history_filter(request, user.id)
            dates = {}
            async with self.database_lock:
                connection = self.database()
                source = "(" + await self.account_history_source(connection) + ")"
                for page in pages:
                    async with connection.execute("SELECT created_at FROM " + source + condition + " ORDER BY julianday(created_at) DESC,public_id DESC LIMIT 1 OFFSET ?", values + [(page - 1) * size]) as cursor:
                        row = await cursor.fetchone()
                    if row:
                        dates[str(page)] = row[0]
            return self.response({"ok": True, "dates": dates})
        except GameError as error:
            return self.failure(error)

    async def referral_records(self, connection, user_id):
        async with connection.execute("SELECT r.user_id,r.joined_at,COALESCE(n.username,''),COALESCE(n.full_name,''),r.is_premium FROM referrals r LEFT JOIN usernames n ON n.user_id = r.user_id WHERE r.referrer_id = ? UNION ALL SELECT p.user_id,p.created_at,COALESCE(n.username,''),COALESCE(n.full_name,''),0 FROM pending_referrals p LEFT JOIN usernames n ON n.user_id = p.user_id WHERE p.referrer_id = ? AND NOT EXISTS (SELECT 1 FROM referrals r WHERE r.user_id = p.user_id) ORDER BY 2 DESC,1", (user_id, user_id)) as cursor:
            return await cursor.fetchall()

    async def handle_referrals(self, request):
        try:
            payload = await self.payload(request) if request.method == "POST" else {}
            user = self.validate_user(request, payload)
            section = request.path.split("/")[-1]
            page = self.wallet_page(request)
            runtime = getattr(self, "wallet_runtime", {})
            async with self.database_lock:
                connection = self.database()
                if section == "notifications":
                    if request.method == "POST":
                        if not isinstance(payload.get("enabled"), bool):
                            raise GameError("Некорректная настройка.")
                        await connection.execute("INSERT INTO webapp_preferences(user_id,ref_notifications) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET ref_notifications = excluded.ref_notifications", (user.id, int(payload["enabled"])))
                        await connection.commit()
                    async with connection.execute("SELECT ref_notifications FROM webapp_preferences WHERE user_id = ?", (user.id,)) as cursor:
                        row = await cursor.fetchone()
                    return self.response({"ok": True, "enabled": bool(row[0]) if row else True})
                if section == "top":
                    async with connection.execute("SELECT referrer_id,COUNT(*) FROM (SELECT user_id,referrer_id FROM referrals UNION ALL SELECT p.user_id,p.referrer_id FROM pending_referrals p WHERE NOT EXISTS (SELECT 1 FROM referrals r WHERE r.user_id = p.user_id)) GROUP BY referrer_id ORDER BY COUNT(*) DESC,referrer_id LIMIT 100") as cursor:
                        records = await cursor.fetchall()
                    rows = []
                    for referrer, count in records:
                        async with connection.execute("SELECT full_name FROM usernames WHERE user_id = ?", (referrer,)) as cursor:
                            name = await cursor.fetchone()
                        identity = await self.public_identity(connection, referrer, name[0] if name else "Игрок")
                        if not identity["hidden"]:
                            rows.append({"id": identity["id"], "name": identity["name"], "c": count})
                    return self.response({"ok": True, "rows": rows[:5]})
                records = await self.referral_records(connection, user.id)
                if section == "list":
                    query = request.query.get("q", "").strip().casefold()
                    if len(query) > 100:
                        raise GameError("Слишком длинный запрос.")
                    all_count = len(records)
                    rows = [{"id": row[0], "join_date": row[1], "username": row[2], "name": row[3] or row[2] or "Игрок", "is_premium": bool(row[4])} for row in records if not query or query in " ".join(str(value) for value in row[:4]).casefold()]
                    return self.response({"ok": True, "rows": rows[(page - 1) * 10:page * 10], "page": page, "totalPages": max(1, (len(rows) + 9) // 10), "totalCount": len(rows), "allCount": all_count})
                async with connection.execute("SELECT kind,amount_cents,created_at,referral_id FROM webapp_ref_events WHERE user_id = ? ORDER BY id DESC", (user.id,)) as cursor:
                    journal = await cursor.fetchall()
                if section == "history":
                    period = request.query.get("period", "all")
                    if period not in {"all", "today", "week", "month"}:
                        raise GameError("Неизвестный период.")
                    start = None if period == "all" else self.clock().replace(hour=0, minute=0, second=0, microsecond=0) if period == "today" else self.clock() - timedelta(days=7 if period == "week" else 30)
                    rows = []
                    for kind, cents, created, referral in journal:
                        if start and datetime.fromisoformat(created) < start:
                            continue
                        async with connection.execute("SELECT username,full_name FROM usernames WHERE user_id = ?", (referral,)) as cursor:
                            name = await cursor.fetchone()
                        rows.append({"type": kind, "amount": cents / 100, "date": created, "percent": runtime.get("REF_DEPOSIT_PERCENT", 0.10) * 100 if kind == "deposit" else None, "referral_id": referral, "referral_username": name[0] if name else "", "referral_name": name[1] if name else ""})
                    return self.response({"ok": True, "rows": rows[(page - 1) * 10:page * 10], "page": page, "totalPages": max(1, (len(rows) + 9) // 10)})
                async with connection.execute("SELECT signup_earned,deposit_earned,frozen FROM ref_balance WHERE user_id = ?", (user.id,)) as cursor:
                    balance = await cursor.fetchone() or (0, 0, 0)
                deposits = [row[1] / 100 for row in journal if row[0] == "deposit"]
                signups = [row[1] / 100 for row in journal if row[0] == "signup"]
                week = sum(row[1] for row in journal if datetime.fromisoformat(row[2]) >= self.clock() - timedelta(days=7)) / 100
                async with connection.execute("SELECT signup_cents,deposit_cents,captured_at FROM webapp_ref_baselines WHERE user_id = ?", (user.id,)) as cursor:
                    baseline = await cursor.fetchone() or (0, 0, None)
                signup_total = round(sum(signups) + baseline[0] / 100, 2)
                deposit_total = round(sum(deposits) + baseline[1] / 100, 2)
                return self.response({"ok": True, "refCount": len(records), "totalEarnings": round(signup_total + deposit_total, 2), "signupBase": runtime.get("REF_SIGNUP_BASE", 2.5), "signupPremium": runtime.get("REF_SIGNUP_PREMIUM", 5), "signupEarnings": signup_total, "signupCount": len(signups), "avgSignup": sum(signups) / len(signups) if signups else 0, "maxSignup": max(signups, default=0), "depositEarnings": deposit_total, "gameEarnings": 0, "depositPercent": runtime.get("REF_DEPOSIT_PERCENT", 0.10) * 100, "lossPercent": 0, "weekEarnings": week, "totalCount": len(journal), "depositCount": len(deposits), "gameCount": 0, "avgDeposit": sum(deposits) / len(deposits) if deposits else 0, "avgGame": 0, "maxDeposit": max(deposits, default=0), "maxGame": 0, "availableBalance": round(balance[0] + balance[1], 2), "frozen": bool(balance[2]), "minimumWithdraw": runtime.get("REF_MIN_WITHDRAW", 10), "historySince": baseline[2], "openingBalance": (baseline[0] + baseline[1]) / 100})
        except GameError as error:
            return self.failure(error)

    async def handle_referral_withdraw(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            key, signature = self.request_identity(request, payload)
            runtime = getattr(self, "wallet_runtime", {})
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    existing = await self.load_receipt(connection, user.id, key, signature)
                    if existing:
                        await connection.rollback()
                        return self.response(existing)
                    records = await self.referral_records(connection, user.id)
                    async with connection.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND deposited = 1", (user.id,)) as cursor:
                        deposited = (await cursor.fetchone())[0]
                    if len(records) > runtime.get("REF_BASE_LIMIT", 2) + runtime.get("REF_LIMIT_PER_DEPOSIT", 2) * deposited:
                        raise GameError("Заработок с приглашений заморожен.")
                    async with connection.execute("SELECT signup_earned + deposit_earned FROM ref_balance WHERE user_id = ?", (user.id,)) as cursor:
                        row = await cursor.fetchone()
                    cents = round(row[0] * 100) if row else 0
                    if cents < runtime.get("REF_MIN_WITHDRAW", 10) * 100:
                        raise GameError("Недостаточно средств на реферальном балансе.")
                    await connection.execute("UPDATE ref_balance SET signup_earned = 0,deposit_earned = 0 WHERE user_id = ?", (user.id,))
                    await self.wallet_credit(connection, user.id, cents, "referral_withdraw", "referral:" + str(user.id) + ":" + key)
                    result = {"ok": True, "creditedAmount": cents / 100, "balance": await self.balance(connection, user.id)}
                    await self.save_receipt(connection, user.id, key, signature, result)
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
            return self.response(result)
        except GameError as error:
            return self.failure(error)
