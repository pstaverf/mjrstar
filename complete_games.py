import asyncio
import hashlib
import json
import re
import secrets
import time

from aiohttp import web

from games_backend import ProgressiveGamesBackend, GameError, GAME_PREFIXES, MIN_BET_CENTS, MAX_BET_CENTS, MULTIPLIER_SCALE, integer, money_cents, serialize
from account_backend import AccountMixin
from checks_backend import ChecksMixin
from payments_backend import PaymentsMixin
from star_withdrawals import StarWithdrawalsMixin
from ton_deposits import TonDepositsMixin
from fairness_backend import FairnessMixin
from doghouse_backend import DoghouseMixin
from support_backend import SupportMixin
from realtime_backend import RealtimeMixin
from pot_games import PotGamesMixin
from escape_pvp import EscapePvpMixin
from emoji_games import EmojiGamesMixin
from leaders_backend import LeadersMixin
from live_games import LiveGamesMixin
from pvp_games import PvpGamesMixin
from game_rules import CLAW_TOYS, BACCARAT_MULTIPLIERS, WHEEL_CATALOG, RED_NUMBERS, digest, prepare_cards, move_cards, prepare_blackjack, move_blackjack, prepare_coinflip, move_coinflip, baccarat_deal, unit, payout


CARD_GAMES = {"hilo", "redblack", "blackjack", "coinflip"}
INSTANT_GAMES = {"claw", "baccarat", "wheel", "escape"}
ESCAPE_LEVELS = [
    {"id": "lite", "name": "Lite", "chance": 0.65, "step": 0.1, "gapDeg": 80, "nMin": 11, "q": 0.20967579074919113, "minMult": 1.1, "maxMult": 6, "meanMult": 1.4769},
    {"id": "mid", "name": "Mid", "chance": 0.5, "step": 0.15, "gapDeg": 64, "nMin": 8, "q": 0.17240619184777034, "minMult": 1.2, "maxMult": 9, "meanMult": 1.92},
    {"id": "epic", "name": "Epic", "chance": 0.35, "step": 0.2, "gapDeg": 50, "nMin": 6, "q": 0.11461215543729122, "minMult": 1.2, "maxMult": 12, "meanMult": 2.7429},
]
GAME_PREFIXES.update({"hilo": "H", "redblack": "RB", "blackjack": "BJ", "coinflip": "CF", "claw": "A", "baccarat": "Q", "wheel": "W", "escape": "E", "crash": "C", "roulette": "R", "doghouse": "DH"})


class CompleteGamesBackend(TonDepositsMixin, FairnessMixin, StarWithdrawalsMixin, SupportMixin, RealtimeMixin, AccountMixin, ChecksMixin, PaymentsMixin, DoghouseMixin, PotGamesMixin, EscapePvpMixin, EmojiGamesMixin, LeadersMixin, PvpGamesMixin, LiveGamesMixin, ProgressiveGamesBackend):
    def register(self, application):
        super().register(application)
        self.register_live(application)
        self.register_pvp(application)
        self.register_leaders(application)
        self.register_emoji(application)
        self.register_escape_pvp(application)
        self.register_pots(application)
        application.router.add_route("*", "/api/doghouse/{path:.*}", self.handle_removed_doghouse)
        self.register_support(application)
        self.register_realtime(application)
        self.register_payments(application)
        self.register_account(application)
        self.register_checks(application)
        self.register_star_withdrawals(application)
        self.register_ton_deposits(application)
        self.register_fairness(application)
        for game in sorted(CARD_GAMES | INSTANT_GAMES):
            application.router.add_get(f"/api/{game}/state", self.handle_extended_state)
            application.router.add_get(f"/api/{game}/history", self.handle_history)
            application.router.add_get(f"/api/{game}/round", self.handle_extended_round)
        for game in sorted(CARD_GAMES):
            actions = ["start", "cashout", "guess"] if game != "blackjack" else ["start", "hit", "stand", "double", "split"]
            for action in actions:
                application.router.add_post(f"/api/{game}/{action}", self.handle_extended_action)
        for game, action in (("claw", "play"), ("baccarat", "play"), ("wheel", "spin"), ("escape", "start")):
            application.router.add_post(f"/api/{game}/{action}", self.handle_extended_action)
        application.router.add_get("/api/bet-limits", self.handle_limits)
        application.router.add_get("/api/bets/status", self.handle_bets_status)
        application.router.add_get("/api/outcomes/off", self.handle_outcomes)
        application.router.add_get("/api/games/off", self.handle_switches)
        application.router.add_get("/api/games/popular", self.handle_popular)
        application.router.add_get("/api/avatar/{user_id}", self.handle_avatar)
        application.router.add_get("/api/ping", self.handle_ping)
        application.router.add_get("/api/subscription/check", self.handle_subscription_check)
        application.on_shutdown.append(self.cleanup)

    async def initialize(self, application):
        await super().initialize(application)
        async with self.database_lock:
            connection = self.database()
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_commits(user_id INTEGER NOT NULL,game TEXT NOT NULL,round_id TEXT NOT NULL,seed TEXT NOT NULL,PRIMARY KEY(user_id,game))")
            await connection.commit()

        await self.initialize_payments()
        await self.initialize_account()
        await self.initialize_checks()
        await self.initialize_star_withdrawals()
        await self.initialize_ton_deposits()
        await self.initialize_pvp()
        await self.initialize_emoji()
        await self.initialize_escape_pvp()
        await self.initialize_support()
        await self.initialize_pots()
        await self.initialize_live()
        await self.initialize_fairness()

    async def handle_removed_doghouse(self, request):
        self.validate_user(request)
        return self.response({"ok": False, "error": "DogHouse удалён из доступных игр.", "code": "GAME_REMOVED"}, 410)

    async def cleanup(self, application):
        await self.cleanup_star_withdrawals()
        await self.cleanup_ton_deposits()
        await self.cleanup_realtime()
        if hasattr(self, "referral_notices_task"):
            self.referral_notices_task.cancel()
            await asyncio.gather(self.referral_notices_task, return_exceptions=True)
        if hasattr(self, "checks_expiry_task"):
            self.checks_expiry_task.cancel()
            await asyncio.gather(self.checks_expiry_task, return_exceptions=True)
        await self.cleanup_emoji()
        await self.cleanup_pvp()
        if hasattr(self, "live_task"):
            self.live_task.cancel()
            await asyncio.gather(self.live_task, return_exceptions=True)

    def public_state(self, game, state):
        def clean(value):
            if isinstance(value, dict):
                return {key: clean(item) for key, item in value.items() if not key.startswith("_")}
            if isinstance(value, list):
                return [clean(item) for item in value]
            return value
        result = clean(state)
        if game == "escape":
            result["elapsed"] = max(0, (time.time() * 1000 - state["startedAt"]) / 1000)
        if game == "coinflip":
            remaining = max(0, (state.get("_actAt", state.get("finishAt", 0)) - time.time() * 1000) / 1000)
            result.update({"flipping": remaining > 0, "finishIn": remaining, "elapsed": max(0, state.get("flipSec", 3) - remaining), "canCashout": state.get("active", False) and remaining == 0, "canGuess": state.get("active", False) and remaining == 0 and len(state["steps"]) < 15, "payout": state.get("winAmount", 0)})
            if remaining:
                result.pop("serverSeed", None)
            return {"ok": True, "active": state.get("active", False), "roundId": state["roundId"], "version": state.get("version", 0), "round": result}
        return result

    async def commit_for(self, connection, user_id, game):
        async with connection.execute("SELECT round_id, seed FROM webapp_commits WHERE user_id = ? AND game = ?", (user_id, game)) as cursor:
            row = await cursor.fetchone()
        if row:
            return row[0], row[1]
        round_id = GAME_PREFIXES[game] + secrets.token_hex(12).upper()
        seed = secrets.token_hex(32)
        await connection.execute("INSERT INTO webapp_commits(user_id,game,round_id,seed) VALUES (?,?,?,?)", (user_id, game, round_id, seed))
        return round_id, seed

    def commitment(self, pair):
        return {"roundId": pair[0], "seedHash": hashlib.sha256(pair[1].encode()).hexdigest()}

    async def handle_extended_state(self, request):
        try:
            user = self.validate_user(request)
            game = request.path.split("/")[2]
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    async with connection.execute("SELECT data FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game)) as cursor:
                        row = await cursor.fetchone()
                    if row and game == "escape":
                        resumed = json.loads(row[0])
                        if time.time() * 1000 >= resumed["_presentationUntil"]:
                            await connection.execute("DELETE FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game))
                            row = None
                    async with connection.execute("SELECT response FROM webapp_rounds WHERE game = ? AND user_id = ? ORDER BY id DESC LIMIT 24", (game, user.id)) as cursor:
                        recent = [json.loads(item[0]) for item in await cursor.fetchall()]
                    commit = self.commitment(await self.commit_for(connection, user.id, game))
                    response = self.public_state(game, json.loads(row[0])) if row else {"ok": True, "active": False}
                    response["balance"] = await self.balance(connection, user.id)
                    response["commit"] = commit
                    response["recent"] = recent
                    if game == "escape":
                        response["config"] = {"levels": ESCAPE_LEVELS, "rtp": 0.96, "tick": 0.5, "tFirst": 0.75, "nCap": 60}
                        if row:
                            response = {"ok": True, "active": True, "round": self.public_state(game, json.loads(row[0])), "balance": response["balance"], "commit": commit, "config": response["config"]}
                    if game == "coinflip" and not row and recent:
                        response.update({"round": recent[0], "next": commit})
                        if recent[0].get("finishAt", 0) > time.time() * 1000:
                            response["round"] = self.public_state(game, recent[0])["round"]
                            response["round"].pop("serverSeed", None)
                    if game == "coinflip":
                        response.update({"config": {"enabled": True, "stepMult": 1.95, "multiplier": 1.95, "maxSteps": 15, "flipSec": 3}, "recent": recent})
                    elif game == "claw":
                        response["toys"] = CLAW_TOYS
                    elif game == "baccarat":
                        response.update({"spots": [{"key": key, "label": {"player": "Игрок", "banker": "Банкир", "tie": "Ничья", "pp": "Пара игрока", "bp": "Пара банкира"}[key], "multiplier": value, "enabled": True} for key, value in BACCARAT_MULTIPLIERS.items()], "recent": recent})
                    elif game == "wheel":
                        response.update({"mults": {"straight": 36, "split": 18, "corner": 9, "column": 3, "dozen": 3, "even": 2}, "recent": recent, "commit": commit})
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)

    async def load_receipt(self, connection, user_id, request_id, digest):
        async with connection.execute("SELECT request_digest,response FROM webapp_requests WHERE user_id = ? AND request_id = ?", (user_id, request_id)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            async with connection.execute("SELECT request_digest,response FROM webapp_rounds WHERE user_id = ? AND request_id = ?", (user_id, request_id)) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        if row[0] != digest:
            raise GameError("Идентификатор использован для другого запроса.", 409)
        response = json.loads(row[1])
        response["balance"] = await self.balance(connection, user_id)
        if "newBalance" in response:
            response["newBalance"] = response["balance"]
        return response

    async def save_receipt(self, connection, user_id, request_id, digest, response):
        await connection.execute("INSERT INTO webapp_requests(user_id,request_id,request_digest,response) VALUES (?,?,?,?)", (user_id, request_id, digest, serialize(response)))

    def request_identity(self, request, payload):
        key = request.headers.get("Idempotency-Key") or payload.get("rid", "")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", key):
            raise GameError("Необходим идентификатор запроса.")
        try:
            signature = hashlib.sha256(serialize({"path": request.path, "payload": payload}).encode()).hexdigest()
        except (ValueError, TypeError):
            raise GameError("Некорректные параметры.") from None
        return key, signature

    async def debit(self, connection, user_id, cents):
        if not 0 < cents <= MAX_BET_CENTS * 4:
            raise GameError("Недопустимая сумма ставки.")
        cursor = await connection.execute("UPDATE balances SET amount = ROUND(amount - ?,2) WHERE user_id = ? AND ROUND(amount * 100) >= ?", (cents / 100, user_id, cents))
        if cursor.rowcount != 1:
            raise GameError("Недостаточно средств на балансе.")

    async def credit(self, connection, user_id, cents):
        if not isinstance(cents, int) or cents < 0:
            raise RuntimeError("Invalid payout")
        await connection.execute("UPDATE balances SET amount = ROUND(amount + ?,2) WHERE user_id = ?", (cents / 100, user_id))

    async def record_round(self, connection, game, state, user_id, key, signature):
        result = self.public_state(game, state)
        detail = result.get("round", result)
        await connection.execute(
            "INSERT INTO webapp_rounds(public_id,game,user_id,username,bet_cents,payout_cents,request_id,request_digest,response,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (state["roundId"], game, user_id, state["username"], state.get("_totalBetCents", state["_betCents"]), state["_payoutCents"], key, signature, serialize(detail), self.clock().isoformat()),
        )

    def base_state(self, game, user, pair, bet_cents):
        return {"ok": True, "active": True, "roundId": pair[0], "seedHash": hashlib.sha256(pair[1].encode()).hexdigest(), "_seed": pair[1], "_betCents": bet_cents, "_multiplier": MULTIPLIER_SCALE, "userId": user.id, "username": " ".join(part for part in (user.first_name, user.last_name) if part), "bet": bet_cents / 100, "createdAt": self.clock().isoformat(), "version": 0, "multiplier": 1}

    def validate_version(self, payload, state):
        if payload.get("roundId") != state["roundId"] or payload.get("version") != state.get("version", 0):
            raise GameError("Состояние раунда изменилось. Обновите игру.", 409)

    async def handle_extended_action(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            game, action = request.path.split("/")[2:4]
            key, signature = self.request_identity(request, payload)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    replay = await self.load_receipt(connection, user.id, key, signature)
                    if replay:
                        await connection.commit()
                        return self.response(replay)
                    async with connection.execute("SELECT data FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game)) as cursor:
                        row = await cursor.fetchone()
                    if row and game == "escape" and time.time() * 1000 >= json.loads(row[0])["_presentationUntil"]:
                        await connection.execute("DELETE FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game))
                        row = None
                    if action in {"start", "play", "spin"}:
                        if row:
                            raise GameError("Сначала завершите активный раунд.", 409)
                        if game in {"baccarat", "wheel"}:
                            bets = self.validated_bets(game, payload)
                            bet_cents = sum(bets.values())
                        else:
                            bets = None
                            bet_cents = money_cents(payload.get("bet"))
                        pair = await self.commit_for(connection, user.id, game)
                        state = self.base_state(game, user, pair, bet_cents)
                        await self.debit(connection, user.id, bet_cents)
                        await connection.execute("DELETE FROM webapp_commits WHERE user_id = ? AND game = ?", (user.id, game))
                        finished, won = False, False
                        if game in {"hilo", "redblack"}:
                            prepare_cards(game, state, payload)
                        elif game == "blackjack":
                            prepare_blackjack(state)
                            finished = state.pop("_finished", False)
                            won = state.get("_payoutCents", 0) > 0
                        elif game == "coinflip":
                            prepare_coinflip(state)
                            finished, won = move_coinflip(state, payload, "guess")
                        else:
                            self.instant_result(game, state, payload, bets)
                            finished, won = True, state["_payoutCents"] > (state["_betCents"] if game == "baccarat" else 0)
                    else:
                        if not row:
                            raise GameError("Активный раунд не найден.", 409)
                        state = json.loads(row[0])
                        self.validate_version(payload, state)
                        if game in {"hilo", "redblack"}:
                            finished, won = move_cards(game, state, payload, action)
                        elif game == "blackjack":
                            finished, won = move_blackjack(state, payload, action)
                        else:
                            finished, won = move_coinflip(state, payload, action)
                        extra = state.pop("_extraBetCents", 0)
                        if extra:
                            if state.get("betAmount", 0) > MAX_BET_CENTS * 4 / 100:
                                raise GameError("Превышен предел общей ставки.")
                            await self.debit(connection, user.id, extra)
                    state["version"] += 1
                    if finished:
                        cents = state["_payoutCents"]
                        await self.credit(connection, user.id, cents)
                        state.update({"active": False, "win": won, "winAmount": cents / 100, "payout": cents / 100, "betAmount": state.get("betAmount", state["bet"]), "serverSeed": state["_seed"], "result": state.get("result", "win" if won else "lose")})
                        await self.record_round(connection, game, state, user.id, key, signature)
                        await connection.execute("DELETE FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game))
                        if game == "escape":
                            await connection.execute("INSERT INTO webapp_active_games(user_id,game,data) VALUES (?,?,?)", (user.id, game, serialize(state)))
                    else:
                        await connection.execute("INSERT INTO webapp_active_games(user_id,game,data) VALUES (?,?,?) ON CONFLICT(user_id,game) DO UPDATE SET data=excluded.data", (user.id, game, serialize(state)))
                    state["balanceAfterBet"] = round(await self.balance(connection, user.id) - (state.get("_payoutCents", 0) / 100 if finished else 0), 2)
                    next_commit = self.commitment(await self.commit_for(connection, user.id, game))
                    response = self.public_state(game, state)
                    response.update({"balance": await self.balance(connection, user.id), "nextCommit": next_commit, "next": next_commit})
                    await self.save_receipt(connection, user.id, key, signature, response)
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)

    def validated_bets(self, game, payload):
        if game == "baccarat":
            raw = payload.get("bets")
            if not isinstance(raw, dict) or not raw or len(raw) > 5:
                raise GameError("Поставьте на одно из полей.")
            if any(key not in BACCARAT_MULTIPLIERS for key in raw):
                raise GameError("Неизвестное поле ставки.")
            if raw.get("player") and raw.get("banker"):
                raise GameError("Нельзя одновременно ставить на Игрока и Банкира.")
            bets = {key: money_cents(value) for key, value in raw.items()}
        else:
            raw = payload.get("items")
            if not isinstance(raw, list) or not 1 <= len(raw) <= len(WHEEL_CATALOG):
                raise GameError("Поставьте на одно из полей.")
            bets = {}
            for item in raw:
                if not isinstance(item, dict) or item.get("key") not in WHEEL_CATALOG:
                    raise GameError("Неизвестная позиция рулетки.")
                key = item["key"]
                bets[key] = bets.get(key, 0) + money_cents(item.get("bet", item.get("amount")))
        if not MIN_BET_CENTS <= sum(bets.values()) <= MAX_BET_CENTS:
            raise GameError("Общая сумма ставок вне допустимого диапазона.")
        return bets

    def instant_result(self, game, state, payload, bets):
        seed, round_id = state["_seed"], state["roundId"]
        if game == "claw":
            toy = next((item for item in CLAW_TOYS if item["key"] == payload.get("toy")), None)
            if toy is None:
                raise GameError("Неизвестная игрушка.")
            roll = unit(seed, round_id) * 100
            state.update({"toy": toy["key"], "toyLabel": toy["label"], "chance": toy["chance"], "multiplier": toy["multiplier"], "roll": roll})
            state["_payoutCents"] = payout(state["_betCents"], toy["multiplier"]) if roll < toy["chance"] else 0
        elif game == "baccarat":
            deal = baccarat_deal(seed, round_id)
            state.update(deal)
            spots = {}
            for key, cents in bets.items():
                won = key == deal["winner"] or key == "pp" and deal["playerPair"] or key == "bp" and deal["bankerPair"]
                push = deal["winner"] == "tie" and key in {"player", "banker"}
                paid = payout(cents, BACCARAT_MULTIPLIERS[key]) if won else cents if push else 0
                spots[key] = {"bet": cents / 100, "multiplier": BACCARAT_MULTIPLIERS[key], "winAmount": paid / 100, "win": paid / 100, "result": "win" if won else "push" if push else "lose"}
            state["spots"] = spots
            state["bets"] = {key: cents / 100 for key, cents in bets.items()}
            state["mults"] = BACCARAT_MULTIPLIERS
            state["_payoutCents"] = sum(round(item["winAmount"] * 100) for item in spots.values())
            state["push"] = state["_payoutCents"] == state["_betCents"]
            state["result"] = "win" if state["_payoutCents"] > state["_betCents"] else "draw" if state["push"] else "lose"
            state["recent"] = [{"roundId": round_id, "winner": deal["winner"]}]
        elif game == "escape":
            import math
            level = next((entry for entry in ESCAPE_LEVELS if entry["id"] == payload.get("level")), None)
            if level is None:
                raise GameError("Неизвестная сложность.")
            prefix = round_id + ":" + level["id"] + ":"
            won = unit(seed, prefix + "win") < level["chance"]
            ticks = min(60, level["nMin"] + int(math.log(1 - unit(seed, prefix + "ticks")) / math.log(1 - level["q"])))
            low, high = (0, level["chance"]) if won else (level["chance"], 1)
            land = low + (high - low) * (0.06 + 0.88 * unit(seed, prefix + "land"))
            multiplier = round(ticks * level["step"], 2)
            started = int(time.time() * 1000)
            paid = payout(state["_betCents"], multiplier) if won else 0
            state.update({"kind": "solo", "level": level["id"], "params": level, "N": ticks, "landU": land, "mult": multiplier, "multiplier": multiplier, "pathSeed": digest(seed, round_id + ":path"), "win": won, "startedAt": started, "finishAt": started + int((1.75 + ticks * 0.5) * 1000), "_presentationUntil": started + int((1.75 + ticks * 0.5) * 1000), "_payoutCents": paid})
        else:
            number = int(unit(seed, round_id) * 37)
            items = []
            total = 0
            for key, cents in bets.items():
                entry = WHEEL_CATALOG[key]
                paid = cents * entry["multiplier"] if number in entry["nums"] else 0
                total += paid
                items.append({**entry, "bet": cents / 100, "amount": cents / 100, "winAmount": paid / 100, "mult": entry["multiplier"], "win": paid / 100})
            state.update({"number": number, "color": "green" if number == 0 else "red" if number in RED_NUMBERS else "black", "items": items, "bets": items, "totalBet": state["bet"], "totalWin": total / 100, "_payoutCents": total, "mode": "solo"})

    async def handle_history(self, request):
        response = await super().handle_history(request)
        if request.path.split("/")[2] == "coinflip" and response.status == 200:
            data = json.loads(response.body)
            for row in data.get("rows", []):
                detail = json.loads(row["meta"])
                if detail.get("finishAt", 0) > time.time() * 1000:
                    detail.pop("serverSeed", None)
                    row["meta"] = serialize(detail)
            return self.response(data)
        return response

    async def handle_extended_round(self, request):
        user = self.validate_user(request)
        game = request.path.split("/")[2]
        identifier = request.query.get("id", "")
        if game == "escape" and identifier.startswith("V"):
            return await self.handle_escape_pvp_round(request)
        async with self.database_lock:
            async with self.database().execute("SELECT response FROM webapp_rounds WHERE game = ? AND public_id = ?", (game, identifier)) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return self.failure(GameError("Раунд не найден.", 404))
        result = json.loads(row[0])
        if game == "coinflip" and result.get("finishAt", 0) > time.time() * 1000:
            result.pop("serverSeed", None)
        result.pop("balance", None)
        return self.response(result)

    async def handle_limits(self, request):
        self.validate_user(request)
        keys = ["dice", "slots", "foot", "basket", "bowl", "darts", "keno", "upgrade", "mines", "ladder", "hilo", "redblack", "blackjack", "coinflip", "claw", "baccarat", "wheel", "crash", "roulette", "escape", "portal", "race", "bomb", "sumo", "arena", "arenahub", "escape_pvp"]
        return self.response({"ok": True, "limits": {key: {"min": MIN_BET_CENTS / 100, "max": MAX_BET_CENTS / 100} for key in keys + ["pvp_" + game for game in ("dice", "slots", "football", "basketball", "bowling", "foot", "basket", "bowl", "darts", "blackjack")]}})

    async def handle_bets_status(self, request):
        self.validate_user(request)
        return self.response({"ok": True, "accepting": True, "accepted": True, "betsAccepted": True, "paused": False})

    async def handle_outcomes(self, request):
        self.validate_user(request)
        return self.response({"ok": True, "off": {}, "families": {}, "ver": 1})

    async def handle_switches(self, request):
        self.validate_user(request)
        off = ["doghouse"]
        if not getattr(self, "telegram_bot", None) or not getattr(self, "telegram_channel", None):
            off.extend(["dice", "slots", "bowl", "darts", "basket", "foot", "pvp", "pvp_dice", "pvp_bowling", "pvp_darts", "pvp_basketball", "pvp_football", "pvp_slots"])
        return self.response({"ok": True, "off": off, "order": [], "names": {}, "ver": 2})

    async def handle_popular(self, request):
        self.validate_user(request)
        async with self.database_lock:
            async with self.database().execute("SELECT game,COUNT(*) FROM webapp_rounds WHERE game != 'doghouse' GROUP BY game ORDER BY COUNT(*) DESC LIMIT 6") as cursor:
                rows = await cursor.fetchall()
        return self.response({"ok": True, "games": [row[0] for row in rows]})

    async def handle_subscription_check(self, request):
        user = self.validate_user(request)
        bot = getattr(self, "telegram_bot", None)
        channel = getattr(self, "telegram_channel", None)
        if not bot or not channel:
            return self.response({"ok": True, "required": False, "subscribed": False, "channels": []})
        try:
            member = await asyncio.wait_for(bot.get_chat_member(chat_id=channel, user_id=user.id), timeout=8)
            status = getattr(member.status, "value", member.status)
            subscribed = status in {"creator", "administrator", "member"} or (status == "restricted" and bool(getattr(member, "is_member", False)))
        except Exception:
            return self.response({"ok": False, "error": "Не удалось проверить подписку. Попробуйте позже."}, 503)
        url = "https://t.me/" + str(channel).lstrip("@") if str(channel).startswith("@") else ""
        return self.response({"ok": True, "required": True, "subscribed": subscribed, "channels": [{"name": "Игровой канал", "url": url, "subscribed": subscribed, "buttonText": "Открыть канал"}]})

    async def handle_avatar(self, request):
        self.validate_user(request)
        try:
            user_id = integer(request.match_info["user_id"], 1, 999999999999)
        except GameError as error:
            return self.failure(error)
        hue = user_id * 137 % 360
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96"><rect width="96" height="96" rx="48" fill="hsl({hue},45%,35%)"/><circle cx="48" cy="34" r="16" fill="white"/><path d="M18 82a30 30 0 0 1 60 0" fill="white"/></svg>'
        return web.Response(text=svg, content_type="image/svg+xml", headers={"Cache-Control": "private, max-age=3600"})

    async def handle_ping(self, request):
        self.validate_user(request)
        return self.response({"ok": True, "time": int(time.time() * 1000)})
