import hashlib
import hmac
import json
import math
import re
import secrets
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fractions import Fraction
from functools import lru_cache

from aiohttp import web


MIN_BET_CENTS = 10
MAX_BET_CENTS = 100000000
AUTO_MAX_ROUNDS = 100
AUTO_DELAY_MS = 450
MULTIPLIER_SCALE = 100000000
GAME_PREFIXES = {"keno": "K", "upgrade": "U", "mines": "M", "ladder": "L"}


class GameError(Exception):
    def __init__(self, message, status=400, code=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def integer(value, minimum, maximum):
    if isinstance(value, bool):
        raise GameError("Некорректное целое число.")
    if isinstance(value, str):
        if not re.fullmatch(r"[0-9]{1,10}", value):
            raise GameError("Некорректное целое число.")
        value = int(value)
    if not isinstance(value, int) or not minimum <= value <= maximum:
        raise GameError("Число вне допустимого диапазона.")
    return value


def money_cents(value, minimum=MIN_BET_CENTS, maximum=MAX_BET_CENTS):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise GameError("Некорректная сумма ставки.")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < Decimal(minimum) / 100 or amount > Decimal(maximum) / 100:
            raise GameError("Сумма ставки вне допустимого диапазона.")
        cents = amount * 100
        if cents != cents.to_integral_value():
            raise GameError("У суммы может быть не больше двух знаков после запятой.")
        return int(cents)
    except InvalidOperation:
        raise GameError("Некорректная сумма ставки.") from None


@lru_cache(maxsize=30)
def keno_paytable(risk, picks_count):
    if risk not in {"low", "medium", "high"}:
        raise GameError("Неизвестный уровень риска.")
    integer(picks_count, 1, 10)
    threshold = {"low": 1, "medium": (picks_count + 1) // 2, "high": min(picks_count, 6)}[risk]
    probabilities = tuple(
        Fraction(math.comb(picks_count, hits) * math.comb(40 - picks_count, 10 - hits), math.comb(40, 10))
        for hits in range(picks_count + 1)
    )
    weights = tuple(math.comb(hits, threshold) if hits >= threshold else 0 for hits in range(picks_count + 1))
    expectation = sum((probability * weight for probability, weight in zip(probabilities, weights)), Fraction(0))
    return tuple(
        (Fraction(9, 10) * weight / expectation * MULTIPLIER_SCALE).__floor__()
        for weight in weights
    )


def keno_draw(server_seed, round_id):
    return [
        index + 1
        for index in sorted(
            range(40),
            key=lambda index: int(hmac.new(server_seed.encode(), f"{round_id}:{index}".encode(), hashlib.sha256).hexdigest()[:13], 16),
        )[:10]
    ]


def serialize(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class GamesBackend:
    def __init__(self, database, database_lock, authenticate, clock):
        self.database = database
        self.database_lock = database_lock
        self.authenticate = authenticate
        self.clock = clock

    def register(self, application):
        application.router.add_get("/api/keno/paytable", self.handle_paytable)
        for game in ("keno", "upgrade"):
            application.router.add_post(f"/api/{game}/play", self.handle_play)
            application.router.add_get(f"/api/{game}/history", self.handle_history)
            application.router.add_get(f"/api/{game}/round", self.handle_round)
            application.router.add_get(f"/api/{game}/auto/config", self.handle_auto_config)
            application.router.add_post(f"/api/{game}/auto/start", self.handle_auto_start)
            application.router.add_post(f"/api/{game}/auto/finish", self.handle_auto_finish)
        application.router.add_get("/api/pvp/commission", self.handle_commission)

    async def initialize(self, application):
        async with self.database_lock:
            connection = self.database()
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS webapp_rounds ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, public_id TEXT NOT NULL UNIQUE, "
                "game TEXT NOT NULL, user_id INTEGER NOT NULL, username TEXT NOT NULL, "
                "bet_cents INTEGER NOT NULL, payout_cents INTEGER NOT NULL, "
                "request_id TEXT NOT NULL, request_digest TEXT NOT NULL, "
                "response TEXT NOT NULL, created_at TEXT NOT NULL, "
                "UNIQUE(user_id, request_id))"
            )
            await connection.execute("CREATE INDEX IF NOT EXISTS idx_webapp_rounds_game_date ON webapp_rounds(game, id DESC)")
            await connection.execute("CREATE INDEX IF NOT EXISTS idx_webapp_rounds_user_date ON webapp_rounds(user_id, game, id DESC)")
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS webapp_auto_sessions ("
                "id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, game TEXT NOT NULL, "
                "params TEXT NOT NULL, rounds INTEGER NOT NULL DEFAULT 0, "
                "staked_cents INTEGER NOT NULL DEFAULT 0, paid_cents INTEGER NOT NULL DEFAULT 0, "
                "last_at INTEGER NOT NULL DEFAULT 0, closed INTEGER NOT NULL DEFAULT 0, "
                "created_at INTEGER NOT NULL)"
            )
            await connection.execute("CREATE INDEX IF NOT EXISTS idx_webapp_auto_user ON webapp_auto_sessions(user_id, game, closed)")
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS webapp_requests ("
                "user_id INTEGER NOT NULL, request_id TEXT NOT NULL, request_digest TEXT NOT NULL, "
                "response TEXT NOT NULL, PRIMARY KEY(user_id, request_id))"
            )
            await connection.commit()

    def response(self, data, status=200):
        return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})

    def failure(self, error):
        payload = {"ok": False, "error": error.message}
        if error.code:
            payload["autoCode"] = error.code
        return self.response(payload, error.status)

    async def payload(self, request):
        try:
            data = await request.json()
        except (ValueError, TypeError, UnicodeDecodeError):
            raise GameError("Некорректный JSON.") from None
        if not isinstance(data, dict):
            raise GameError("Ожидается JSON-объект.")
        return data

    def validate_user(self, request, payload=None):
        user = self.authenticate(request)
        if payload is not None and "uid" in payload:
            if isinstance(payload["uid"], bool) or str(payload["uid"]) != str(user.id):
                raise GameError("Нет доступа к чужому аккаунту.", 403)
        return user

    async def balance(self, connection, user_id):
        async with connection.execute("SELECT amount FROM balances WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        return float(row[0]) if row else 0.0

    def auto_config(self):
        return {"ok": True, "enabled": True, "maxRounds": AUTO_MAX_ROUNDS, "minDelayMs": AUTO_DELAY_MS, "maxBet": MAX_BET_CENTS / 100}

    async def handle_paytable(self, request):
        self.validate_user(request)
        try:
            risk = request.query.get("risk", "medium")
            count = integer(request.query.get("picksCount", "0"), 1, 10)
            table = keno_paytable(risk, count)
            return self.response({"ok": True, "risk": risk, "picksCount": count, "table": {str(index): value / MULTIPLIER_SCALE for index, value in enumerate(table)}})
        except GameError as error:
            return self.failure(error)

    async def handle_auto_config(self, request):
        self.validate_user(request)
        return self.response(self.auto_config())

    async def handle_commission(self, request):
        self.validate_user(request)
        return self.response({"ok": True, "percent": 1})

    def auto_params(self, params):
        if not isinstance(params, dict):
            raise GameError("Некорректные настройки авто-игры.")
        result = {"rounds": integer(params.get("rounds", AUTO_MAX_ROUNDS), 0, AUTO_MAX_ROUNDS)}
        for name in ("profit", "loss", "bigWin", "cap"):
            result[name] = money_cents(params.get(name, 0), 0)
        if not isinstance(params.get("stopWin", False), bool):
            raise GameError("Некорректное условие остановки.")
        result["stopWin"] = params.get("stopWin", False)
        return result

    async def handle_auto_start(self, request):
        try:
            payload = await self.payload(request)
            game = request.path.split("/")[2]
            user = self.validate_user(request, payload)
            params = self.auto_params(payload.get("params"))
            session_id = secrets.token_hex(16)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    await connection.execute("UPDATE webapp_auto_sessions SET closed = 1 WHERE user_id = ? AND game = ? AND closed = 0", (user.id, game))
                    await connection.execute(
                        "INSERT INTO webapp_auto_sessions(id,user_id,game,params,created_at) VALUES (?,?,?,?,?)",
                        (session_id, user.id, game, serialize(params), int(time.time() * 1000)),
                    )
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
            return self.response({**self.auto_config(), "sid": session_id})
        except GameError as error:
            return self.failure(error)

    async def handle_auto_finish(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            game = request.path.split("/")[2]
            session_id = payload.get("sid")
            if not isinstance(session_id, str) or not re.fullmatch(r"[a-f0-9]{32}", session_id):
                raise GameError("Некорректная авто-сессия.")
            async with self.database_lock:
                connection = self.database()
                await connection.execute("UPDATE webapp_auto_sessions SET closed = 1 WHERE id = ? AND user_id = ? AND game = ?", (session_id, user.id, game))
                await connection.commit()
            return self.response({"ok": True})
        except GameError as error:
            return self.failure(error)

    async def validate_auto(self, connection, session_id, user_id, game, bet_cents, now):
        if not isinstance(session_id, str) or not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise GameError("Некорректная авто-сессия.", code="other")
        async with connection.execute(
            "SELECT params, rounds, staked_cents, paid_cents, last_at, closed, created_at "
            "FROM webapp_auto_sessions WHERE id = ? AND user_id = ? AND game = ?", (session_id, user_id, game)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None or row[5] or now - row[6] > 86400000:
            raise GameError("Авто-сессия завершена или не найдена.", code="other")
        params = json.loads(row[0])
        if row[1] >= (params["rounds"] or AUTO_MAX_ROUNDS):
            raise GameError("Лимит раундов исчерпан.", code="cap")
        if now - row[4] < AUTO_DELAY_MS:
            raise GameError("Подождите перед следующим раундом.", 429, "fast" if game in {"mines", "ladder"} else "wait")
        if params["cap"] and bet_cents > params["cap"]:
            raise GameError("Превышен потолок ставки авто-игры.", code="cap")
        net = row[3] - row[2]
        if (params["profit"] and net >= params["profit"]) or (params["loss"] and -net >= params["loss"]):
            raise GameError("Достигнуто условие остановки авто-игры.", code="cap")
        return params

    async def handle_play(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            bet_cents = money_cents(payload.get("bet"))
            game = request.path.split("/")[2]
            if game == "keno":
                picks = payload.get("picks")
                if not isinstance(picks, list) or not 1 <= len(picks) <= 10:
                    raise GameError("Выберите от 1 до 10 чисел.")
                picks = [integer(value, 1, 40) for value in picks]
                if len(set(picks)) != len(picks):
                    raise GameError("Выбранные числа не должны повторяться.")
                picks = sorted(picks)
                risk = payload.get("risk", "medium")
                if not isinstance(risk, str):
                    raise GameError("Неизвестный уровень риска.")
                table = keno_paytable(risk, len(picks))
                options = {"picks": picks, "risk": risk}
            elif game == "upgrade":
                chance_value = money_cents(payload.get("chance"), 200, 8000)
                options = {"chance": chance_value / 100}
            else:
                key = "minesCount" if game == "mines" else "stonesCount"
                path_key = "cells" if game == "mines" else "columns"
                count = integer(payload.get(key), 1, 24 if game == "mines" else 4)
                path = payload.get(path_key)
                maximum = 25 - count if game == "mines" else 6
                if not isinstance(path, list) or not 1 <= len(path) <= maximum:
                    raise GameError("Некорректная длина пути авто-игры.")
                path = [integer(value, 0, 24 if game == "mines" else 4) for value in path]
                if game == "mines" and len(set(path)) != len(path):
                    raise GameError("Клетки пути не должны повторяться.")
                if not payload.get("autoSid"):
                    raise GameError("Необходима авто-сессия.", code="session")
                options = {key: count, "path": path}
            request_id = request.headers.get("Idempotency-Key", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", request_id):
                raise GameError("Отсутствует корректный идентификатор запроса.")
            session_id = payload.get("autoSid")
            if session_id is not None and not isinstance(session_id, str):
                raise GameError("Некорректная авто-сессия.")
            digest = hashlib.sha256(serialize({"game": game, "bet": bet_cents, "options": options, "session": session_id}).encode()).hexdigest()
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    async with connection.execute("SELECT request_digest, response FROM webapp_rounds WHERE user_id = ? AND request_id = ?", (user.id, request_id)) as cursor:
                        previous = await cursor.fetchone()
                    if previous is None:
                        async with connection.execute("SELECT request_digest, response FROM webapp_requests WHERE user_id = ? AND request_id = ?", (user.id, request_id)) as cursor:
                            previous = await cursor.fetchone()
                    if previous:
                        if previous[0] != digest:
                            raise GameError("Идентификатор уже использован для другой ставки.", 409)
                        response = json.loads(previous[1])
                        response["balance"] = await self.balance(connection, user.id)
                        await connection.commit()
                        return self.response(response)
                    now = int(time.time() * 1000)
                    params = await self.validate_auto(connection, session_id, user.id, game, bet_cents, now) if session_id else None
                    if game in {"mines", "ladder"}:
                        async with connection.execute("SELECT 1 FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game)) as cursor:
                            if await cursor.fetchone():
                                raise GameError("Сначала завершите ручной раунд.", 409)
                    async with connection.execute("SELECT created_at FROM webapp_rounds WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user.id,)) as cursor:
                        last = await cursor.fetchone()
                    if last and (self.clock() - datetime.fromisoformat(last[0])).total_seconds() < 0.2:
                        raise GameError("Подождите перед следующей ставкой.", 429, "wait")
                    cursor = await connection.execute(
                        "UPDATE balances SET amount = ROUND(amount - ?, 2) WHERE user_id = ? AND ROUND(amount * 100) >= ?",
                        (bet_cents / 100, user.id, bet_cents),
                    )
                    if cursor.rowcount != 1:
                        raise GameError("Недостаточно средств на балансе.", code="balance")
                    round_id = GAME_PREFIXES[game] + secrets.token_hex(12).upper()
                    seed = secrets.token_hex(32)
                    if game == "keno":
                        drawn = keno_draw(seed, round_id)
                        hits = len(set(picks).intersection(drawn))
                        multiplier = table[hits]
                        result = {**options, "drawn": drawn, "hits": hits}
                        payout_cents = bet_cents * multiplier // MULTIPLIER_SCALE
                    elif game == "upgrade":
                        roll = int(hmac.new(seed.encode(), round_id.encode(), hashlib.sha256).hexdigest()[:13], 16) / 16 ** 13 * 100
                        coefficient = (Decimal(9400) / chance_value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                        multiplier = int(coefficient * MULTIPLIER_SCALE)
                        payout_cents = bet_cents * multiplier // MULTIPLIER_SCALE if 0.0946 <= roll <= options["chance"] else 0
                        result = {**options, "roll": roll}
                    else:
                        state = self.progressive_start(game, {**options, "bet": bet_cents / 100}, user, seed, round_id)
                        used = []
                        for level, cell in enumerate(path):
                            move = {"roundId": round_id, "cellIndex": cell, "column": cell, "level": level}
                            finished, won = self.progressive_move(game, "reveal" if game == "mines" else "pick", move, state)
                            used.append(cell)
                            if finished:
                                break
                        multiplier = state["_multiplier"]
                        payout_cents = bet_cents * multiplier // MULTIPLIER_SCALE if won else 0
                        state.update({"active": False, "canCashout": False, "path": used})
                        state["minePositions" if game == "mines" else "stonePositions"] = state["_positions"]
                        result = self.public_progressive_state(state)
                    await connection.execute("UPDATE balances SET amount = ROUND(amount + ?, 2) WHERE user_id = ?", (payout_cents / 100, user.id))
                    created_at = self.clock().isoformat()
                    response = {
                        "ok": True, "active": False, "roundId": round_id,
                        "seedHash": hashlib.sha256(seed.encode()).hexdigest(), "serverSeed": seed,
                        "userId": user.id, "username": " ".join(part for part in (user.first_name, user.last_name) if part),
                        "bet": bet_cents / 100, **result,
                        "multiplier": multiplier / MULTIPLIER_SCALE, "winAmount": payout_cents / 100,
                        "win": payout_cents > 0, "result": "win" if payout_cents > 0 else "lose",
                        "balance": await self.balance(connection, user.id), "createdAt": created_at, "auto": bool(session_id),
                    }
                    await connection.execute(
                        "INSERT INTO webapp_rounds(public_id,game,user_id,username,bet_cents,payout_cents,request_id,request_digest,response,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (round_id, game, user.id, response["username"], bet_cents, payout_cents, request_id, digest, serialize(response), created_at),
                    )
                    if session_id:
                        closed = bool(params["stopWin"] and payout_cents > 0 or params["bigWin"] and payout_cents >= params["bigWin"])
                        await connection.execute(
                            "UPDATE webapp_auto_sessions SET rounds = rounds + 1, staked_cents = staked_cents + ?, paid_cents = paid_cents + ?, last_at = ?, closed = ? WHERE id = ? AND user_id = ?",
                            (bet_cents, payout_cents, now, int(closed), session_id, user.id),
                        )
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)

    async def handle_history(self, request):
        try:
            user = self.validate_user(request)
            offset = integer(request.query.get("offset", "0"), 0, 1000000)
            scope = request.query.get("scope", "all")
            if scope not in {"all", "mine"}:
                raise GameError("Неизвестный фильтр истории.")
            query = request.query.get("q", "").strip()
            if len(query) > 100:
                raise GameError("Слишком длинный поисковый запрос.")
            conditions = ["game = ?"]
            values = [request.path.split("/")[2]]
            if scope == "mine":
                conditions.append("user_id = ?")
                values.append(user.id)
            if query:
                conditions.append("(public_id = ? OR CAST(user_id AS TEXT) = ? OR substr(created_at, 1, 10) = ?)")
                values.extend([query, query, query])
            values.append(offset)
            async with self.database_lock:
                async with self.database().execute(
                    "SELECT id,user_id,username,bet_cents,payout_cents,response,created_at FROM webapp_rounds WHERE " + " AND ".join(conditions) + " ORDER BY id DESC LIMIT 20 OFFSET ?", values
                ) as cursor:
                    records = await cursor.fetchall()
            rows = []
            for record in records:
                detail = json.loads(record[5])
                detail.pop("balance", None)
                rows.append({"id": record[0], "user_id": record[1], "username": record[2], "bet": record[3] / 100, "win_amount": record[4] / 100, "result": detail["result"], "meta": serialize(detail), "created_at": record[6]})
            return self.response({"ok": True, "rows": rows})
        except GameError as error:
            return self.failure(error)

    async def handle_round(self, request):
        self.validate_user(request)
        round_id = request.query.get("id", "")
        game = request.path.split("/")[2]
        if not re.fullmatch(GAME_PREFIXES[game] + r"[A-F0-9]{24}", round_id):
            return self.failure(GameError("Раунд не найден.", 404))
        async with self.database_lock:
            async with self.database().execute("SELECT response FROM webapp_rounds WHERE public_id = ? AND game = ?", (round_id, game)) as cursor:
                record = await cursor.fetchone()
        if record is None:
            return self.failure(GameError("Раунд не найден.", 404))
        response = json.loads(record[0])
        response.pop("balance", None)
        return self.response(response)


@lru_cache(maxsize=28)
def progressive_table(game, count):
    if game == "mines":
        integer(count, 1, 24)
        return {str(step): (Fraction(9, 10) * Fraction(math.comb(25, step), math.comb(25 - count, step)) * MULTIPLIER_SCALE).__floor__() for step in range(1, 26 - count)}
    integer(count, 1, 4)
    return {str(step): (Fraction(9, 10) * Fraction(5, 5 - count) ** step * MULTIPLIER_SCALE).__floor__() for step in range(1, 7)}


def progressive_positions(game, count, seed, round_id):
    if game == "mines":
        return sorted(range(25), key=lambda index: int(hmac.new(seed.encode(), f"{round_id}:{index}".encode(), hashlib.sha256).hexdigest()[:13], 16))[:count]
    positions = []
    for level in range(6):
        columns = sorted(range(5), key=lambda column: int(hmac.new(seed.encode(), f"{round_id}:{level}:{column}".encode(), hashlib.sha256).hexdigest()[:13], 16))[:count]
        positions.extend([[level, column] for column in columns])
    return positions


class ProgressiveGamesBackend(GamesBackend):
    def register(self, application):
        super().register(application)
        for game, choice in (("mines", "reveal"), ("ladder", "pick")):
            application.router.add_get(f"/api/{game}/coefs", self.handle_coefs)
            application.router.add_get(f"/api/{game}/state", self.handle_progressive_state)
            application.router.add_get(f"/api/{game}/history", self.handle_history)
            application.router.add_get(f"/api/{game}/round", self.handle_round)
            application.router.add_get(f"/api/{game}/auto/config", self.handle_auto_config)
            application.router.add_post(f"/api/{game}/auto/start", self.handle_auto_start)
            application.router.add_post(f"/api/{game}/auto/finish", self.handle_auto_finish)
            application.router.add_post(f"/api/{game}/auto/round", self.handle_play)
            for action in ("start", choice, "cashout"):
                application.router.add_post(f"/api/{game}/{action}", self.handle_progressive_action)

    async def initialize(self, application):
        await super().initialize(application)
        async with self.database_lock:
            connection = self.database()
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS webapp_active_games ("
                "user_id INTEGER NOT NULL, game TEXT NOT NULL, data TEXT NOT NULL, "
                "PRIMARY KEY(user_id, game))"
            )
            await connection.commit()

    async def handle_coefs(self, request):
        try:
            self.validate_user(request)
            game = request.path.split("/")[2]
            key = "minesCount" if game == "mines" else "stonesCount"
            count = integer(request.query.get(key, "0"), 1, 24 if game == "mines" else 4)
            table = progressive_table(game, count)
            return self.response({"ok": True, key: count, "table": {step: coefficient / MULTIPLIER_SCALE for step, coefficient in table.items()}})
        except GameError as error:
            return self.failure(error)

    def public_progressive_state(self, state):
        return {key: value for key, value in state.items() if not key.startswith("_")}

    async def handle_progressive_state(self, request):
        try:
            user = self.validate_user(request)
            game = request.path.split("/")[2]
            async with self.database_lock:
                connection = self.database()
                async with connection.execute("SELECT data FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game)) as cursor:
                    row = await cursor.fetchone()
                balance = await self.balance(connection, user.id)
            response = self.public_progressive_state(json.loads(row[0])) if row else {"ok": True, "active": False}
            response["balance"] = balance
            return self.response(response)
        except GameError as error:
            return self.failure(error)

    def progressive_start(self, game, payload, user, seed=None, round_id=None):
        bet_cents = money_cents(payload.get("bet"))
        key = "minesCount" if game == "mines" else "stonesCount"
        count = integer(payload.get(key), 1, 24 if game == "mines" else 4)
        seed = seed or secrets.token_hex(32)
        round_id = round_id or GAME_PREFIXES[game] + secrets.token_hex(12).upper()
        table = progressive_table(game, count)
        state = {
            "ok": True, "active": True, "roundId": round_id,
            "seedHash": hashlib.sha256(seed.encode()).hexdigest(),
            "_seed": seed, "_positions": progressive_positions(game, count, seed, round_id),
            "_betCents": bet_cents, "_table": table, "_multiplier": MULTIPLIER_SCALE,
            "userId": user.id, "username": " ".join(part for part in (user.first_name, user.last_name) if part),
            "createdAt": self.clock().isoformat(), "bet": bet_cents / 100,
            "multiplier": 1, "table": {step: value / MULTIPLIER_SCALE for step, value in table.items()},
            "canCashout": False, "cashoutAmount": 0, key: count,
        }
        if game == "mines":
            state.update({"cellsOpened": 0, "revealed": [], "hitIndex": None, "maxSteps": 25 - count})
        else:
            state.update({"level": 0, "picks": [], "revealedStones": [], "hitPosition": None, "maxLevels": 6})
        return state

    def progressive_move(self, game, action, payload, state):
        if payload.get("roundId") != state["roundId"]:
            raise GameError("Раунд изменился. Обновите состояние игры.", 409)
        if action == "cashout":
            if not state["canCashout"]:
                raise GameError("Сначала сделайте успешный ход.")
            return True, True
        if game == "mines":
            cell = integer(payload.get("cellIndex"), 0, 24)
            if cell in state["revealed"]:
                raise GameError("Эта клетка уже открыта.", 409)
            if cell in state["_positions"]:
                state["hitIndex"] = cell
                return True, False
            state["revealed"].append(cell)
            state["cellsOpened"] += 1
            step = state["cellsOpened"]
            maximum = state["maxSteps"]
        else:
            level = integer(payload.get("level"), 0, 5)
            if level != state["level"]:
                raise GameError("Уровень уже изменился. Обновите состояние игры.", 409)
            column = integer(payload.get("column"), 0, 4)
            state["picks"].append(column)
            if [level, column] in state["_positions"]:
                state["hitPosition"] = [level, column]
                return True, False
            state["level"] += 1
            state["revealedStones"] = [position for position in state["_positions"] if position[0] < state["level"]]
            step = state["level"]
            maximum = state["maxLevels"]
        state["_multiplier"] = state["_table"][str(step)]
        state["multiplier"] = state["_multiplier"] / MULTIPLIER_SCALE
        state["cashoutAmount"] = state["_betCents"] * state["_multiplier"] // MULTIPLIER_SCALE / 100
        state["canCashout"] = True
        return step == maximum, True

    async def handle_progressive_action(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            game, action = request.path.split("/")[2:4]
            request_id = request.headers.get("Idempotency-Key", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", request_id):
                raise GameError("Отсутствует корректный идентификатор запроса.")
            try:
                digest = hashlib.sha256(serialize({"game": game, "action": action, "payload": payload}).encode()).hexdigest()
            except ValueError:
                raise GameError("Некорректный JSON.") from None
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    async with connection.execute("SELECT request_digest,response FROM webapp_requests WHERE user_id = ? AND request_id = ?", (user.id, request_id)) as cursor:
                        previous = await cursor.fetchone()
                    if previous is None:
                        async with connection.execute("SELECT request_digest,response FROM webapp_rounds WHERE user_id = ? AND request_id = ?", (user.id, request_id)) as cursor:
                            previous = await cursor.fetchone()
                    if previous:
                        if previous[0] != digest:
                            raise GameError("Идентификатор уже использован для другого действия.", 409)
                        response = json.loads(previous[1])
                        response["balance"] = await self.balance(connection, user.id)
                        await connection.commit()
                        return self.response(response)
                    async with connection.execute("SELECT data FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game)) as cursor:
                        row = await cursor.fetchone()
                    if action == "start":
                        if row:
                            raise GameError("Сначала завершите текущий раунд.", 409)
                        state = self.progressive_start(game, payload, user)
                        cursor = await connection.execute(
                            "UPDATE balances SET amount = ROUND(amount - ?, 2) WHERE user_id = ? AND ROUND(amount * 100) >= ?",
                            (state["bet"], user.id, state["_betCents"]),
                        )
                        if cursor.rowcount != 1:
                            raise GameError("Недостаточно средств на балансе.")
                        finished, won = False, False
                    else:
                        if not row:
                            raise GameError("Активный раунд не найден.", 409)
                        state = json.loads(row[0])
                        finished, won = self.progressive_move(game, action, payload, state)
                    if finished:
                        payout_cents = state["_betCents"] * state["_multiplier"] // MULTIPLIER_SCALE if won else 0
                        await connection.execute("UPDATE balances SET amount = ROUND(amount + ?, 2) WHERE user_id = ?", (payout_cents / 100, user.id))
                        state.update({"active": False, "canCashout": False, "win": won, "winAmount": payout_cents / 100, "result": "win" if won else "lose", "serverSeed": state["_seed"]})
                        state["minePositions" if game == "mines" else "stonePositions"] = state["_positions"]
                        response = self.public_progressive_state(state)
                        await connection.execute(
                            "INSERT INTO webapp_rounds(public_id,game,user_id,username,bet_cents,payout_cents,request_id,request_digest,response,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (state["roundId"], game, user.id, state["username"], state["_betCents"], payout_cents, request_id, digest, serialize(response), self.clock().isoformat()),
                        )
                        await connection.execute("DELETE FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game))
                    else:
                        await connection.execute(
                            "INSERT INTO webapp_active_games(user_id,game,data) VALUES (?,?,?) ON CONFLICT(user_id,game) DO UPDATE SET data = excluded.data",
                            (user.id, game, serialize(state)),
                        )
                        response = self.public_progressive_state(state)
                    response["balance"] = await self.balance(connection, user.id)
                    await connection.execute(
                        "INSERT INTO webapp_requests(user_id,request_id,request_digest,response) VALUES (?,?,?,?)",
                        (user.id, request_id, digest, serialize(response)),
                    )
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)
