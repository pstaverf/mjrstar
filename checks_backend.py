import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from datetime import datetime, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent

from games_backend import GameError, integer, money_cents, serialize


CHECK_LIMITS = {"minAmount": 0.1, "maxAmount": 1000000, "minActivations": 2, "maxActivations": 100}


class ChecksMixin:
    def register_checks(self, application):
        for section in ("overview", "my", "detail", "settings", "history"):
            application.router.add_get("/api/checks/" + section, self.handle_checks_read)
        for action in ("start", "answer", "replay"):
            application.router.add_post("/api/checks/captcha/" + action, self.handle_check_captcha)
        for action in ("create", "activate", "cancel", "edit_settings", "notifications"):
            application.router.add_post("/api/checks/" + action, self.handle_checks_write)

    async def initialize_checks(self):
        async with self.database_lock:
            connection = self.database()
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_checks(code TEXT PRIMARY KEY,creator_id INTEGER NOT NULL,amount_cents INTEGER NOT NULL,activations INTEGER NOT NULL,remaining INTEGER NOT NULL,type TEXT NOT NULL,target_username TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'active',created_at TEXT NOT NULL,expires_at INTEGER NOT NULL,settings TEXT NOT NULL)")
            await connection.execute("CREATE INDEX IF NOT EXISTS idx_webapp_checks_creator ON webapp_checks(creator_id,created_at)")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_check_claims(code TEXT NOT NULL,user_id INTEGER NOT NULL,amount_cents INTEGER NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(code,user_id))")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_check_attempts(user_id INTEGER PRIMARY KEY,started_at INTEGER NOT NULL,attempts INTEGER NOT NULL)")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_check_captchas(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL,code TEXT NOT NULL,task TEXT NOT NULL,expires_at INTEGER NOT NULL,solved INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,replays INTEGER NOT NULL DEFAULT 2)")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_check_wagers(code TEXT NOT NULL,user_id INTEGER NOT NULL,turnover_start INTEGER NOT NULL,games_start INTEGER NOT NULL,amount_cents INTEGER NOT NULL,games INTEGER NOT NULL,PRIMARY KEY(code,user_id))")
            await connection.commit()
        self.checks_expiry_task = asyncio.create_task(self.checks_expiry_loop())

    async def checks_expiry_loop(self):
        while True:
            await asyncio.sleep(30)
            try:
                async with self.database_lock:
                    connection = self.database()
                    try:
                        await connection.execute("BEGIN IMMEDIATE")
                        await self.expire_checks(connection)
                        await connection.execute("DELETE FROM webapp_check_captchas WHERE expires_at < ?", (int(time.time()),))
                        await connection.commit()
                    except BaseException:
                        await connection.rollback()
                        raise
            except Exception:
                logging.error("Check expiry transaction failed; retrying next cycle")

    def check_password(self, password, salt=None):
        if not isinstance(password, str) or len(password) > 64:
            raise GameError("Пароль должен содержать не более 64 символов.")
        if not password:
            return ""
        salt = salt or secrets.token_hex(16)
        return salt + ":" + hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()

    def check_settings(self, payload, previous=None):
        settings = dict(previous or {"premiumOnly": False, "verifiedOnly": False, "referralOnly": False, "passwordHash": ""})
        for field in ("premiumOnly", "verifiedOnly", "referralOnly"):
            if field in payload:
                if not isinstance(payload[field], bool):
                    raise GameError("Некорректная настройка чека.")
                settings[field] = payload[field]
        if payload.get("removePassword") is True:
            settings["passwordHash"] = ""
        if payload.get("removeWager") is True:
            settings.pop("wagerAmount", None)
            settings.pop("wagerGames", None)
        for kind in ("Deposit", "Turnover", "Withdraw"):
            if payload.get("removeReq" + kind) is True:
                settings.pop("req" + kind, None)
        if "password" in payload:
            settings["passwordHash"] = self.check_password(payload["password"] or "")
        if "captchaLevel" in payload:
            settings["captchaLevel"] = integer(payload["captchaLevel"], 0, 2)
        else:
            settings.setdefault("captchaLevel", 0)
        if "wagerAmount" in payload or "wagerGames" in payload:
            amount, games = payload.get("wagerAmount"), payload.get("wagerGames")
            if not amount and not games:
                settings.pop("wagerAmount", None)
                settings.pop("wagerGames", None)
            else:
                settings["wagerAmount"] = money_cents(amount, 1, 100000000)
                settings["wagerGames"] = integer(games, 1, 1000000)
        for kind in ("Deposit", "Turnover", "Withdraw"):
            amount_key, period_key = "req" + kind + "Amount", "req" + kind + "Period"
            if amount_key in payload:
                if payload[amount_key] in (None, 0, ""):
                    settings.pop("req" + kind, None)
                else:
                    period = payload.get(period_key, "all")
                    if not isinstance(period, str) or period not in {"day", "week", "month", "3months", "6months", "all"}:
                        raise GameError("Неизвестный период условия чека.")
                    settings["req" + kind] = {"amount": money_cents(payload[amount_key], 1, 100000000) / 100, "period": period}
        return settings

    async def check_row(self, connection, code):
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{24,64}", code):
            raise GameError("Чек не найден.", 404)
        async with connection.execute("SELECT code,creator_id,amount_cents,activations,remaining,type,target_username,status,created_at,expires_at,settings FROM webapp_checks WHERE code = ?", (code,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise GameError("Чек не найден.", 404)
        result = dict(zip(("code", "creator_id", "amount_cents", "activations", "remaining", "type", "target_username", "status", "created_at", "expires_at", "settings"), row))
        result["settings"] = json.loads(result["settings"])
        return result

    async def expire_checks(self, connection):
        async with connection.execute("SELECT code,creator_id,amount_cents,remaining FROM webapp_checks WHERE status = 'active' AND expires_at <= ?", (int(time.time()),)) as cursor:
            expired = await cursor.fetchall()
        for code, creator, amount, remaining in expired:
            await connection.execute("UPDATE webapp_checks SET status = 'expired',remaining = 0 WHERE code = ? AND status = 'active'", (code,))
            await self.wallet_credit(connection, creator, amount * remaining, "check_refund", "check-expiry:" + code)

    async def check_detail(self, connection, check, user_id):
        settings = check["settings"]
        async with connection.execute("SELECT 1 FROM webapp_check_claims WHERE code = ? AND user_id = ?", (check["code"], user_id)) as cursor:
            claimed = await cursor.fetchone() is not None
        bot_username = getattr(self, "wallet_runtime", {}).get("BOT_USERNAME", "mjrstarsbot")
        detail = {"ok": True, "code": check["code"], "checkCode": check["code"], "checkType": check["type"], "amount": check["amount_cents"] / 100, "maxActivations": check["activations"], "activationsLeft": check["remaining"], "isMulti": check["type"] == "multi", "targetUsername": check["target_username"], "status": check["status"], "isCreator": user_id == check["creator_id"], "alreadyActivated": claimed, "createdAt": check["created_at"], "expiresAt": check["expires_at"], "expireHours": max(1, round((check["expires_at"] - datetime.fromisoformat(check["created_at"]).timestamp()) / 3600)), "timeLeftSeconds": max(0, check["expires_at"] - int(time.time())), "heldAmount": check["remaining"] * check["amount_cents"] / 100 if check["status"] == "active" else 0, "link": f"https://t.me/{bot_username}?startapp=check_{check['code']}", "hasPassword": bool(settings["passwordHash"]), "passwordRequired": bool(settings["passwordHash"]), "premiumOnly": settings["premiumOnly"], "verifiedOnly": settings["verifiedOnly"], "referralOnly": settings["referralOnly"], "captchaLevel": settings.get("captchaLevel", 0), "captchaFloor": 0, "hasWager": bool(settings.get("wagerAmount")), "wagerAmount": settings.get("wagerAmount", 0) / 100, "wagerGames": settings.get("wagerGames", 0), "reqPeriods": [["day", "За день"], ["week", "За неделю"], ["month", "За месяц"], ["3months", "За 3 месяца"], ["6months", "За полгода"], ["all", "За всё время"]], "wagerGamesText": "Все завершённые игры"}
        async with connection.execute("SELECT full_name FROM usernames WHERE user_id = ?", (check["creator_id"],)) as cursor:
            row = await cursor.fetchone()
        creator = await self.public_identity(connection, check["creator_id"], row[0] if row else "Игрок")
        detail.update({"creatorName": creator["name"], "creatorId": creator["id"], "canActivate": check["status"] == "active" and check["creator_id"] != user_id and not claimed, "blockedReason": "Вы уже активировали этот чек." if claimed else "Нельзя активировать собственный чек." if check["creator_id"] == user_id else "Чек недоступен."})
        for kind in ("Deposit", "Turnover", "Withdraw"):
            detail["req" + kind] = settings.get("req" + kind)
        return detail

    async def checks_overview(self, connection, user_id):
        async with connection.execute("SELECT COUNT(*),COALESCE(SUM(amount_cents*activations),0) FROM webapp_checks WHERE creator_id = ?", (user_id,)) as cursor:
            created, reserved = await cursor.fetchone()
        async with connection.execute("SELECT COUNT(*),COALESCE(SUM(amount_cents),0) FROM webapp_check_claims WHERE user_id = ?", (user_id,)) as cursor:
            activated, received = await cursor.fetchone()
        async with connection.execute("SELECT COALESCE(SUM(c.amount_cents),0) FROM webapp_check_claims c JOIN webapp_checks k ON k.code = c.code WHERE k.creator_id = ?", (user_id,)) as cursor:
            sent = (await cursor.fetchone())[0]
        async with connection.execute("SELECT check_notifications FROM webapp_preferences WHERE user_id = ?", (user_id,)) as cursor:
            pref = await cursor.fetchone()
        result = {"ok": True, "createdChecks": created, "activatedChecks": activated, "totalSent": sent / 100, "totalReceived": received / 100, "notificationsEnabled": bool(pref[0]) if pref else True, "limits": CHECK_LIMITS, "captcha": {"enabled": True, "floor": 0, "default": 0}, "advancedSettings": True}
        daily = []
        for offset in range(6, -1, -1):
            day = (self.clock() - timedelta(days=offset)).date().isoformat()
            async with connection.execute("SELECT COALESCE(SUM(CASE WHEN k.creator_id = ? THEN c.amount_cents ELSE 0 END),0),COALESCE(SUM(CASE WHEN c.user_id = ? THEN c.amount_cents ELSE 0 END),0) FROM webapp_check_claims c JOIN webapp_checks k ON k.code = c.code WHERE substr(c.created_at,1,10) = ?", (user_id, user_id, day)) as cursor:
                outgoing, incoming = await cursor.fetchone()
            daily.append({"sent": outgoing / 100, "received": incoming / 100})
        result.update({"daily": daily, "weekSent": sum(row["sent"] for row in daily), "weekReceived": sum(row["received"] for row in daily)})
        return result

    async def handle_checks_read(self, request):
        try:
            user = self.validate_user(request)
            section = request.path.split("/")[-1]
            page = self.wallet_page(request, zero=True)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    await self.expire_checks(connection)
                    if section == "overview":
                        result = await self.checks_overview(connection, user.id)
                    elif section in {"detail", "settings"}:
                        check = await self.check_row(connection, request.query.get("code", ""))
                        if section == "settings" and check["creator_id"] != user.id:
                            raise GameError("forbidden", 403)
                        result = await self.check_detail(connection, check, user.id)
                    elif section == "my":
                        async with connection.execute("SELECT code FROM webapp_checks WHERE creator_id = ? AND status = 'active' ORDER BY created_at DESC,code LIMIT 6 OFFSET ?", (user.id, page * 6)) as cursor:
                            codes = await cursor.fetchall()
                        async with connection.execute("SELECT COUNT(*) FROM webapp_checks WHERE creator_id = ? AND status = 'active'", (user.id,)) as cursor:
                            total = (await cursor.fetchone())[0]
                        rows = []
                        for code, in codes:
                            check = await self.check_row(connection, code)
                            rows.append({"check_code": code, "amount": check["amount_cents"] / 100, "check_type": check["type"], "is_multi": check["type"] == "multi", "target_username": check["target_username"]})
                        result = {"ok": True, "rows": rows, "page": page, "totalPages": max(1, (total + 5) // 6)}
                    else:
                        scope = request.query.get("scope", "all")
                        if scope not in {"all", "created", "activated"}:
                            raise GameError("Неизвестный фильтр.")
                        source = "SELECT 'created' AS type,amount_cents*activations AS amount,created_at,target_username,code AS check_code,creator_id AS user_id FROM webapp_checks UNION ALL SELECT 'activated',c.amount_cents,c.created_at,'',c.code,c.user_id FROM webapp_check_claims c"
                        condition, values = " WHERE user_id = ?", [user.id]
                        if scope != "all":
                            condition += " AND type = ?"
                            values.append(scope)
                        async with connection.execute("SELECT COUNT(*) FROM (" + source + ")" + condition, values) as cursor:
                            total = (await cursor.fetchone())[0]
                        async with connection.execute("SELECT type,amount,created_at,target_username,check_code FROM (" + source + ")" + condition + " ORDER BY created_at DESC,check_code LIMIT 10 OFFSET ?", values + [page * 10]) as cursor:
                            rows = [{"type": row[0], "amount": row[1] / 100, "time_readable": datetime.fromisoformat(row[2]).strftime("%d.%m.%Y %H:%M"), "target_username": row[3], "check_code": row[4]} for row in await cursor.fetchall()]
                        result = {"ok": True, "rows": rows, "page": page, "totalPages": max(1, (total + 9) // 10)}
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
            return self.response(result)
        except GameError as error:
            return self.failure(error)

    async def check_attempt(self, user_id):
        async with self.database_lock:
            connection = self.database()
            now = int(time.time())
            await connection.execute("INSERT INTO webapp_check_attempts(user_id,started_at,attempts) VALUES (?,?,1) ON CONFLICT(user_id) DO UPDATE SET started_at = CASE WHEN started_at < ? THEN excluded.started_at ELSE started_at END,attempts = CASE WHEN started_at < ? THEN 1 ELSE attempts + 1 END", (user_id, now, now - 60, now - 60))
            async with connection.execute("SELECT attempts FROM webapp_check_attempts WHERE user_id = ?", (user_id,)) as cursor:
                attempts = (await cursor.fetchone())[0]
            await connection.commit()
        if attempts > 10:
            raise GameError("Слишком много попыток. Подождите минуту.", 429)

    async def handle_checks_write(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            action = request.path.split("/")[-1]
            key, signature = self.request_identity(request, payload)
            if action == "activate":
                await self.check_attempt(user.id)
            notifications = []
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    await self.expire_checks(connection)
                    existing = await self.load_receipt(connection, user.id, key, signature)
                    if existing:
                        await connection.commit()
                        return self.response(existing)
                    if action == "notifications":
                        if not isinstance(payload.get("enabled"), bool):
                            raise GameError("Некорректная настройка.")
                        await connection.execute("INSERT INTO webapp_preferences(user_id,check_notifications) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET check_notifications = excluded.check_notifications", (user.id, int(payload["enabled"])))
                        result = {"ok": True, "enabled": payload["enabled"]}
                    elif action == "create":
                        check_type = payload.get("type", "normal")
                        if not isinstance(check_type, str) or check_type not in {"normal", "personal", "multi"}:
                            raise GameError("Неизвестный тип чека.")
                        amount = money_cents(payload.get("amount"), 10, 100000000)
                        activations = integer(payload.get("activations", 2), 2, 100) if check_type == "multi" else 1
                        hours = integer(payload.get("expireHours") or 48, 1, 720)
                        target = payload.get("targetUsername", "")
                        if check_type == "personal":
                            if not isinstance(target, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", target):
                                raise GameError("Укажите Telegram username получателя.")
                        else:
                            target = ""
                        settings = self.check_settings(payload)
                        code = secrets.token_urlsafe(24)
                        await self.ensure_check_wager(connection, user.id)
                        cursor = await connection.execute("UPDATE balances SET amount = ROUND(amount - ?,2) WHERE user_id = ? AND ROUND(amount*100) >= ?", (amount * activations / 100, user.id, amount * activations))
                        if cursor.rowcount != 1:
                            raise GameError("Недостаточно средств на балансе.")
                        await connection.execute("INSERT INTO webapp_checks(code,creator_id,amount_cents,activations,remaining,type,target_username,created_at,expires_at,settings) VALUES (?,?,?,?,?,?,?,?,?,?)", (code, user.id, amount, activations, activations, check_type, target, self.clock().isoformat(), int(time.time()) + hours * 3600, serialize(settings)))
                        result = await self.check_detail(connection, await self.check_row(connection, code), user.id)
                        result["balance"] = await self.balance(connection, user.id)
                        notifications.append((user.id, f"Создан чек MajorStars на {amount * activations / 100:g} Stars.\n{result['link']}"))
                    else:
                        check = await self.check_row(connection, payload.get("code", ""))
                        if check["status"] != "active":
                            raise GameError("Этот чек уже активирован, отменён или истёк.", 409)
                        if action in {"cancel", "edit_settings"} and check["creator_id"] != user.id:
                            raise GameError("Изменять чек может только создатель.", 403)
                        if action == "cancel":
                            refund = check["amount_cents"] * check["remaining"]
                            await connection.execute("UPDATE webapp_checks SET status = 'cancelled',remaining = 0 WHERE code = ?", (check["code"],))
                            await self.wallet_credit(connection, user.id, refund, "check_refund", "check-cancel:" + check["code"])
                            result = {"ok": True, "refundedAmount": refund / 100}
                        elif action == "edit_settings":
                            settings = self.check_settings(payload, check["settings"])
                            expires = check["expires_at"]
                            if "expireHours" in payload:
                                expires = int(datetime.fromisoformat(check["created_at"]).timestamp()) + integer(payload["expireHours"], 1, 720) * 3600
                                if expires <= time.time():
                                    raise GameError("Укажите срок, который ещё не истёк.")
                            await connection.execute("UPDATE webapp_checks SET settings = ?,expires_at = ? WHERE code = ?", (serialize(settings), expires, check["code"]))
                            result = {"ok": True}
                        else:
                            if user.id == check["creator_id"]:
                                raise GameError("Нельзя активировать собственный чек.")
                            async with connection.execute("SELECT 1 FROM webapp_check_claims WHERE code = ? AND user_id = ?", (check["code"], user.id)) as cursor:
                                if await cursor.fetchone():
                                    raise GameError("Вы уже активировали этот чек.", 409)
                            if check["target_username"] and (user.username or "").casefold() != check["target_username"].casefold():
                                raise GameError("Этот чек предназначен другому пользователю.", 403)
                            settings = check["settings"]
                            if settings["premiumOnly"] and not user.is_premium:
                                raise GameError("Чек доступен только пользователям Telegram Premium.", 403)
                            if settings["verifiedOnly"]:
                                async with connection.execute("SELECT created_at FROM balances WHERE user_id = ?", (user.id,)) as cursor:
                                    registration = await cursor.fetchone()
                                if registration and registration[0] and datetime.fromisoformat(registration[0]) < datetime.fromisoformat(check["created_at"]):
                                    raise GameError("Чек доступен только новым пользователям бота.", 403)
                            if settings["passwordHash"]:
                                password = payload.get("password", "")
                                salt = settings["passwordHash"].split(":")[0]
                                if not hmac.compare_digest(self.check_password(password, salt), settings["passwordHash"]):
                                    raise GameError("Неверный пароль чека.", 403)
                            level = settings.get("captchaLevel", 0)
                            if level:
                                async with connection.execute("SELECT solved FROM webapp_check_captchas WHERE token = ? AND user_id = ? AND code = ? AND expires_at > ?", (payload.get("captchaToken", ""), user.id, check["code"], int(time.time()))) as cursor:
                                    captcha = await cursor.fetchone()
                                if captcha is None or not captcha[0]:
                                    raise GameError("Сначала пройдите капчу чека.", 403)
                            await self.check_activation_requirements(connection, user.id, settings)
                            if settings.get("wagerAmount"):
                                turnover, games = await self.check_game_totals(connection, user.id)
                                await connection.execute("INSERT INTO webapp_check_wagers(code,user_id,turnover_start,games_start,amount_cents,games) VALUES (?,?,?,?,?,?)", (check["code"], user.id, turnover, games, settings["wagerAmount"], settings["wagerGames"]))
                            if settings["referralOnly"]:
                                async with connection.execute("SELECT referrer_id FROM referrals WHERE user_id = ? UNION ALL SELECT referrer_id FROM pending_referrals WHERE user_id = ?", (user.id, user.id)) as cursor:
                                    referrers = await cursor.fetchall()
                                if any(row[0] != check["creator_id"] for row in referrers):
                                    raise GameError("Чек доступен только рефералам создателя.", 403)
                                if not referrers:
                                    await connection.execute("INSERT INTO pending_referrals(user_id,referrer_id,created_at) VALUES (?,?,?)", (user.id, check["creator_id"], self.clock().isoformat()))
                            await connection.execute("INSERT INTO webapp_check_claims(code,user_id,amount_cents,created_at) VALUES (?,?,?,?)", (check["code"], user.id, check["amount_cents"], self.clock().isoformat()))
                            await connection.execute("UPDATE webapp_checks SET remaining = remaining - 1,status = CASE WHEN remaining = 1 THEN 'used' ELSE status END WHERE code = ? AND remaining > 0", (check["code"],))
                            await self.wallet_credit(connection, user.id, check["amount_cents"], "check", "check:" + check["code"] + ":" + str(user.id))
                            result = {"ok": True, "amount": check["amount_cents"] / 100, "creditedAmount": check["amount_cents"] / 100}
                            notifications.extend([(check["creator_id"], f"Ваш чек MajorStars активирован: {check['amount_cents'] / 100:g} Stars."), (user.id, f"Вы получили {check['amount_cents'] / 100:g} Stars по чеку MajorStars.")])
                        result["balance"] = await self.balance(connection, user.id)
                    await self.save_receipt(connection, user.id, key, signature, result)
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
            bot = getattr(self, "telegram_bot", None)
            if bot:
                for recipient, text in notifications:
                    async with self.database_lock:
                        async with self.database().execute("SELECT check_notifications FROM webapp_preferences WHERE user_id = ?", (recipient,)) as cursor:
                            pref = await cursor.fetchone()
                    if pref is None or pref[0]:
                        try:
                            await bot.send_message(recipient, text, parse_mode=None)
                        except Exception:
                            logging.warning("Check notification delivery failed for user %s", recipient)
            return self.response(result)
        except GameError as error:
            return self.failure(error)

    async def check_game_totals(self, connection, user_id):
        events, names = await self.leaderboard_events(connection)
        async with connection.execute("SELECT COALESCE(SUM(bet_cents),0),COUNT(*) FROM (" + events + ") WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

    async def ensure_check_wager(self, connection, user_id):
        async with connection.execute("SELECT turnover_start,games_start,amount_cents,games FROM webapp_check_wagers WHERE user_id = ?", (user_id,)) as cursor:
            wagers = await cursor.fetchall()
        if not wagers:
            return
        turnover, games = await self.check_game_totals(connection, user_id)
        if any(turnover - start < amount or games - count < required for start, count, amount, required in wagers):
            raise GameError("Сначала выполните отыгрыш полученных чеков: нужную сумму ставок и количество завершённых игр.", 403)

    async def check_activation_requirements(self, connection, user_id, settings):
        for kind in ("Deposit", "Turnover", "Withdraw"):
            requirement = settings.get("req" + kind)
            if not requirement:
                continue
            period = requirement["period"]
            days = {"day": 1, "week": 7, "month": 30, "3months": 90, "6months": 180}.get(period)
            since = (self.clock() - timedelta(days=days)).isoformat() if days else "0001-01-01"
            if kind == "Turnover":
                source, names = await self.leaderboard_events(connection)
                query = "SELECT COALESCE(SUM(bet_cents),0) FROM (" + source + ") WHERE user_id = ? AND julianday(created_at) >= julianday(?)"
                values = [user_id, since]
            elif kind == "Deposit":
                query = "SELECT COALESCE(SUM(cents),0) FROM (SELECT user_id,amount*100 AS cents,created_at FROM payments UNION ALL SELECT user_id,stars_cents,COALESCE(paid_at,created_at) FROM webapp_deposits WHERE provider != 'stars' AND status = 'paid') WHERE user_id = ? AND julianday(created_at) >= julianday(?)"
                values = [user_id, since]
            else:
                query = "SELECT COALESCE(SUM(ROUND(amount*100)),0) FROM withdrawals WHERE user_id = ? AND status = 'approved' AND julianday(created_at) >= julianday(?)"
                values = [user_id, since]
            async with connection.execute(query, values) as cursor:
                amount = (await cursor.fetchone())[0]
            if amount < round(requirement["amount"] * 100):
                label = {"Deposit": "депозитам", "Turnover": "обороту", "Withdraw": "выводам"}[kind]
                raise GameError(f"Не выполнено условие по {label}: требуется {requirement['amount']:g} Stars.", 403)

    def captcha_task(self, level, token, attempts=3, replays=2):
        sequence = list(range(6))
        secrets.SystemRandom().shuffle(sequence)
        return {"ok": True, "token": token, "chests": 6, "seq": sequence[:3 if level == 1 else 4], "level": level, "levelName": "Лёгкая" if level == 1 else "Сложная", "attempts": attempts, "replaysLeft": replays, "showMs": 600 if level == 1 else 400, "gapMs": 200, "swaps": [] if level == 1 else [[0, 3], [1, 5]], "swapMs": 640}

    async def handle_check_captcha(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            action = request.path.split("/")[-1]
            await self.check_attempt(user.id)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    check = await self.check_row(connection, payload.get("code", ""))
                    if check["status"] != "active" or check["expires_at"] <= time.time():
                        raise GameError("Чек недоступен.", 409)
                    level = check["settings"]["captchaLevel"]
                    if not level:
                        result = {"ok": True, "notNeeded": True}
                    elif action == "start":
                        token = secrets.token_urlsafe(32)
                        task = self.captcha_task(level, token)
                        await connection.execute("DELETE FROM webapp_check_captchas WHERE user_id = ? AND code = ?", (user.id, check["code"]))
                        await connection.execute("INSERT INTO webapp_check_captchas(token,user_id,code,task,expires_at) VALUES (?,?,?,?,?)", (token, user.id, check["code"], serialize(task), int(time.time()) + 300))
                        result = task
                    else:
                        async with connection.execute("SELECT task,expires_at,solved,attempts,replays FROM webapp_check_captchas WHERE token = ? AND user_id = ? AND code = ?", (payload.get("token", ""), user.id, check["code"])) as cursor:
                            row = await cursor.fetchone()
                        if not row or row[1] <= time.time():
                            result = {"ok": False, "expired": True}
                        elif row[3] >= 3:
                            result = {"ok": False, "failed": True, "wait": max(1, row[1] - int(time.time()))}
                        else:
                            task = json.loads(row[0])
                            if action == "replay":
                                if row[4] <= 0:
                                    raise GameError("Повторы закончились.")
                                task["replaysLeft"] = row[4] - 1
                                await connection.execute("UPDATE webapp_check_captchas SET replays = replays - 1 WHERE token = ?", (task["token"],))
                                result = task
                            elif row[2]:
                                result = {"ok": True, "solved": True}
                            elif payload.get("answer") == task["seq"]:
                                await connection.execute("UPDATE webapp_check_captchas SET solved = 1 WHERE token = ?", (task["token"],))
                                result = {"ok": True, "solved": True}
                            else:
                                attempts = row[3] + 1
                                task = self.captcha_task(level, task["token"], 3 - attempts, row[4])
                                await connection.execute("UPDATE webapp_check_captchas SET attempts = ?,task = ? WHERE token = ?", (attempts, serialize(task), task["token"]))
                                result = task if attempts < 3 else {"ok": True, "failed": True, "wait": max(1, row[1] - int(time.time()))}
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
            return self.response(result)
        except GameError as error:
            return self.failure(error)

    async def inline_check_results(self, user_id, query):
        bot_username = getattr(self, "wallet_runtime", {}).get("BOT_USERNAME", "mjrstarsbot")
        values = [user_id, int(time.time())]
        condition = "creator_id = ? AND status = 'active' AND expires_at > ?"
        if query.startswith("share_check_"):
            condition += " AND code = ?"
            values.append(query.removeprefix("share_check_"))
        elif query.strip():
            return []
        async with self.database_lock:
            async with self.database().execute("SELECT code,amount_cents,remaining,type FROM webapp_checks WHERE " + condition + " ORDER BY created_at DESC LIMIT 20", values) as cursor:
                checks = await cursor.fetchall()
        results = []
        for code, amount, remaining, check_type in checks:
            link = f"https://t.me/{bot_username}?startapp=check_{code}"
            title = f"Чек на {amount / 100:g} Stars"
            description = f"Осталось активаций: {remaining}" if check_type == "multi" else "Персональный чек" if check_type == "personal" else "Для любого пользователя"
            results.append(InlineQueryResultArticle(id=code, title=title, description=description, input_message_content=InputTextMessageContent(message_text=f"MajorStars · {title}\n{description}", parse_mode=None), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Активировать чек", url=link)]])))
        if not query.strip():
            link = f"https://t.me/{bot_username}?startapp=createcheck"
            results.append(InlineQueryResultArticle(id="open-check-creation", title="Создать новый чек", description="Открыть MajorStars и подтвердить создание чека", input_message_content=InputTextMessageContent(message_text="Создайте внутренний чек MajorStars в приложении.", parse_mode=None), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Создать чек", url=link)]])))
        return results
