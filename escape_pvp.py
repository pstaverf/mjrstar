import hashlib
import json
import math
import re
import secrets
from time import time as duel_now

from game_rules import digest, unit
from games_backend import GameError, integer, money_cents, serialize


ESCAPE_DUEL_LEVELS = [{"id": "lite", "name": "Lite", "gapDeg": 80, "t1Min": 4, "t1Max": 7}, {"id": "mid", "name": "Mid", "gapDeg": 64, "t1Min": 5, "t1Max": 9}, {"id": "epic", "name": "Epic", "gapDeg": 50, "t1Min": 6, "t1Max": 11}]
ESCAPE_DUEL_CONFIG = {"levels": ESCAPE_DUEL_LEVELS, "commissionPercent": 1, "countdown": 3, "waitTtl": 600, "resultPad": 0.9, "minBet": 0.1, "maxBet": 1000000, "dlMin": 1.3, "dlMax": 3, "landPad": 0.08, "slack": 0.6, "slackLose": 0.3}


def escape_duel_outcome(seed, identifier, level):
    configuration = next(value for value in ESCAPE_DUEL_LEVELS if value["id"] == level)
    values = {key: unit(seed, identifier + ":" + level + ":pvp:" + key) for key in ("winner", "t1", "dl", "landw", "landl")}
    first = math.floor((configuration["t1Min"] + (configuration["t1Max"] - configuration["t1Min"]) * values["t1"]) * 20 + 0.5) / 20
    delay = math.floor((1.3 + 1.7 * values["dl"]) * 20 + 0.5) / 20
    return {"creatorWins": values["winner"] < 0.5, "t1": first, "dl": delay, "t2": math.floor((first + delay) * 20 + 0.5) / 20, "landWin": 0.5 * (0.08 + 0.84 * values["landw"]), "landLose": 0.5 + 0.5 * (0.08 + 0.84 * values["landl"])}


class EscapePvpMixin:
    def register_escape_pvp(self, application):
        for action in ("play", "join", "cancel"):
            application.router.add_post("/api/escape/pvp/" + action, self.handle_escape_pvp_action)
        for action in ("state", "history", "howto"):
            application.router.add_get("/api/escape/pvp/" + action, self.handle_escape_pvp_read)

    async def initialize_escape_pvp(self):
        async with self.database_lock:
            connection = self.database()
            try:
                await connection.execute("BEGIN IMMEDIATE")
                await connection.execute("CREATE TABLE IF NOT EXISTS webapp_escape_duels(id TEXT PRIMARY KEY,creator_id INTEGER NOT NULL,opponent_id INTEGER,status TEXT NOT NULL,data TEXT NOT NULL)")
                await connection.execute("CREATE INDEX IF NOT EXISTS idx_escape_duels_status ON webapp_escape_duels(status,creator_id)")
                await self.expire_escape_duels(connection)
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    async def save_escape_duel(self, connection, state):
        await connection.execute("UPDATE webapp_escape_duels SET status = ?,opponent_id = ?,data = ? WHERE id = ?", (state["status"], state.get("opponentId"), serialize(state), state["roomId"]))

    async def expire_escape_duels(self, connection):
        async with connection.execute("SELECT data FROM webapp_escape_duels WHERE status = 'waiting' AND json_extract(data,'$._expiresAt') <= ?", (duel_now(),)) as cursor:
            expired = [json.loads(row[0]) for row in await cursor.fetchall()]
        for state in expired:
            await self.credit(connection, state["creatorId"], state["_betCents"])
            state.update({"status": "expired", "refunded": True, "finishedAt": self.clock().isoformat()})
            await self.save_escape_duel(connection, state)

    def escape_duel_public(self, state, user_id):
        result = {key: value for key, value in state.items() if not key.startswith("_")}
        slot = 0 if state["creatorId"] == user_id else 1 if state.get("opponentId") == user_id else None
        live = state["status"] == "finished" and state["_presentationUntil"] > duel_now()
        result.update({"ok": True, "kind": "pvp", "id": state["roomId"], "bet": state["betAmount"], "pot": state["betAmount"] * 2, "prize": state["_betCents"] * 2 * 99 // 100 / 100, "commissionPercent": 1, "mySlot": slot, "mine": slot is not None, "iWon": slot is not None and slot == state.get("winnerSlot"), "status": "live" if live else state["status"], "creator": {"id": state["creatorId"], "name": state["creatorName"], "avatar": "/api/avatar/" + str(state["creatorId"]), "isMe": slot == 0}})
        result["commission"] = round(result["pot"] - result["prize"], 2)
        if state.get("opponentId"):
            result["opponent"] = {"id": state["opponentId"], "name": state["opponentName"], "avatar": "/api/avatar/" + str(state["opponentId"]), "isMe": slot == 1}
        if state["status"] == "finished":
            result["elapsed"] = duel_now() - state["_startedAt"] - 3
            if live:
                result.pop("serverSeed", None)
        result["timeText"] = state.get("finishedAt", state["createdAt"])
        return result

    async def escape_duel_response(self, connection, state, user_id):
        balance = await self.balance(connection, user_id)
        response = {"ok": True, "duel": self.escape_duel_public(state, user_id), "balance": balance, "balanceAfterBet": balance}
        if state["status"] == "finished" and state.get("winnerId") == user_id:
            response["balanceAfterBet"] = round(balance - state["winAmount"], 2)
        return response

    async def escape_user_busy(self, connection, user_id):
        async with connection.execute("SELECT 1 FROM webapp_escape_duels WHERE (creator_id = ? OR opponent_id = ?) AND (status = 'waiting' OR (status = 'finished' AND json_extract(data,'$._presentationUntil') > ?))", (user_id, user_id, duel_now())) as cursor:
            return await cursor.fetchone() is not None

    async def join_escape_duel(self, connection, state, user):
        if state["status"] != "waiting":
            raise GameError("Дуэль уже закрыта или началась.", 409)
        if state["creatorId"] == user.id:
            raise GameError("Нельзя играть против себя.")
        await self.debit(connection, user.id, state["_betCents"])
        outcome = escape_duel_outcome(state["_seed"], state["roomId"], state["level"])
        winner = state["creatorId"] if outcome["creatorWins"] else user.id
        paid = state["_betCents"] * 2 * 99 // 100
        await self.credit(connection, winner, paid)
        started = duel_now()
        params = {**outcome, "gapDeg": next(level["gapDeg"] for level in ESCAPE_DUEL_LEVELS if level["id"] == state["level"]), "countdown": 3, "slack": 0.6, "slackLose": 0.3, "finishAfter": outcome["t1"] + 1.2}
        state.update({"status": "finished", "opponentId": user.id, "opponentName": " ".join(part for part in (user.first_name, user.last_name) if part), "winnerId": winner, "winnerSlot": 0 if outcome["creatorWins"] else 1, "winAmount": paid / 100, "feeAmount": (2 * state["_betCents"] - paid) / 100, "isDraw": False, "serverSeed": state["_seed"], "pathSeed": digest(state["_seed"], state["roomId"] + ":pvp:path"), "params": params, "_startedAt": started, "_presentationUntil": started + 3 + params["finishAfter"], "finishedAt": self.clock().isoformat()})
        await self.save_escape_duel(connection, state)

    async def handle_escape_pvp_action(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            key, signature = self.request_identity(request, payload)
            action = request.path.split("/")[-1]
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    replay = await self.load_receipt(connection, user.id, key, signature)
                    if replay:
                        identifier = replay["duel"]["id"]
                        async with connection.execute("SELECT data FROM webapp_escape_duels WHERE id = ?", (identifier,)) as cursor:
                            state = json.loads((await cursor.fetchone())[0])
                        await connection.commit()
                        return self.response(await self.escape_duel_response(connection, state, user.id))
                    await self.expire_escape_duels(connection)
                    if action != "cancel" and await self.escape_user_busy(connection, user.id):
                        raise GameError("Дождитесь завершения своей дуэли.", 409)
                    if action == "play":
                        bet = money_cents(payload.get("bet"))
                        level = payload.get("level", "mid")
                        private = payload.get("private", False)
                        if not isinstance(level, str) or level not in {"lite", "mid", "epic"} or not isinstance(private, bool):
                            raise GameError("Некорректные настройки дуэли.")
                        async with connection.execute("SELECT data FROM webapp_escape_duels WHERE status = 'waiting' AND creator_id != ? AND json_extract(data,'$.private') = 0 AND json_extract(data,'$.level') = ? AND json_extract(data,'$._betCents') = ? ORDER BY rowid LIMIT 1", (user.id, level, bet)) as cursor:
                            row = await cursor.fetchone() if not private else None
                        if row:
                            state = json.loads(row[0])
                            await self.join_escape_duel(connection, state, user)
                        else:
                            await self.debit(connection, user.id, bet)
                            seed = secrets.token_hex(32)
                            identifier = "V" + secrets.token_hex(8).upper()
                            state = {"roomId": identifier, "creatorId": user.id, "creatorName": " ".join(part for part in (user.first_name, user.last_name) if part), "status": "waiting", "betAmount": bet / 100, "level": level, "private": private, "createdAt": self.clock().isoformat(), "seedHash": hashlib.sha256(seed.encode()).hexdigest(), "_seed": seed, "_betCents": bet, "_expiresAt": duel_now() + 600}
                            await connection.execute("INSERT INTO webapp_escape_duels(id,creator_id,status,data) VALUES (?,?,'waiting',?)", (identifier, user.id, serialize(state)))
                    else:
                        identifier = payload.get("id")
                        if not isinstance(identifier, str) or not re.fullmatch(r"V[A-F0-9]{16}", identifier):
                            raise GameError("Некорректный UID дуэли.")
                        async with connection.execute("SELECT data FROM webapp_escape_duels WHERE id = ?", (identifier,)) as cursor:
                            row = await cursor.fetchone()
                        if row is None:
                            raise GameError("Дуэль не найдена.", 404)
                        state = json.loads(row[0])
                        if action == "join":
                            await self.join_escape_duel(connection, state, user)
                        else:
                            if state["creatorId"] != user.id:
                                raise GameError("Нет доступа к чужой дуэли.", 403)
                            if state["status"] != "waiting":
                                raise GameError("Дуэль уже закрыта или началась.", 409)
                            await self.credit(connection, user.id, state["_betCents"])
                            state.update({"status": "cancelled", "refunded": True, "finishedAt": self.clock().isoformat()})
                            await self.save_escape_duel(connection, state)
                    response = await self.escape_duel_response(connection, state, user.id)
                    await self.save_receipt(connection, user.id, key, signature, response)
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)

    async def handle_escape_pvp_round(self, request):
        user = self.validate_user(request)
        async with self.database_lock:
            async with self.database().execute("SELECT data FROM webapp_escape_duels WHERE id = ?", (request.query.get("id", ""),)) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return self.failure(GameError("Дуэль не найдена.", 404))
        return self.response(self.escape_duel_public(json.loads(row[0]), user.id))

    async def handle_escape_pvp_read(self, request):
        try:
            user = self.validate_user(request)
            action = request.path.split("/")[-1]
            level = request.query.get("level", "")
            if level not in {"", "lite", "mid", "epic"}:
                raise GameError("Неизвестный уровень.")
            offset = integer(request.query.get("offset", "0"), 0, 1000000)
            scope = request.query.get("scope", "all")
            query = request.query.get("q", "").strip()
            if scope not in {"all", "mine"} or len(query) > 100:
                raise GameError("Некорректные параметры истории.")
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    await self.expire_escape_duels(connection)
                    if action == "howto":
                        async with connection.execute("SELECT DISTINCT creator_id,json_extract(data,'$.creatorName') FROM webapp_escape_duels ORDER BY rowid DESC LIMIT 2") as cursor:
                            records = await cursor.fetchall()
                        response = {"ok": True, "players": [{"name": name, "avatar": "/api/avatar/" + str(identifier)} for identifier, name in records]}
                    else:
                        conditions = ["status = 'finished'", "json_extract(data,'$._presentationUntil') <= ?"]
                        values = [duel_now()]
                        if scope == "mine":
                            conditions.append("(creator_id = ? OR opponent_id = ?)")
                            values.extend([user.id, user.id])
                        if level and action == "history":
                            conditions.append("json_extract(data,'$.level') = ?")
                            values.append(level)
                        if query:
                            conditions.append("(id = ? OR CAST(creator_id AS TEXT) = ? OR CAST(opponent_id AS TEXT) = ? OR substr(json_extract(data,'$.finishedAt'),1,10) = ?)")
                            values.extend([query] * 4)
                        async with connection.execute("SELECT data FROM webapp_escape_duels WHERE " + " AND ".join(conditions) + " ORDER BY rowid DESC LIMIT 20 OFFSET ?", values + [offset]) as cursor:
                            rows = [self.escape_duel_public(json.loads(row[0]), user.id) for row in await cursor.fetchall()]
                        response = {"ok": True, "rows": rows}
                        if action == "state":
                            async with connection.execute("SELECT data FROM webapp_escape_duels WHERE (creator_id = ? OR opponent_id = ?) AND (status = 'waiting' OR (status = 'finished' AND json_extract(data,'$._presentationUntil') > ?)) ORDER BY rowid DESC LIMIT 1", (user.id, user.id, duel_now())) as cursor:
                                row = await cursor.fetchone()
                            mine = json.loads(row[0]) if row else None
                            async with connection.execute("SELECT data FROM webapp_escape_duels WHERE status = 'waiting' AND json_extract(data,'$.private') = 0 ORDER BY rowid LIMIT 100") as cursor:
                                waiting = [json.loads(row[0]) for row in await cursor.fetchall()]
                            balance = await self.balance(connection, user.id)
                            response.update({"config": ESCAPE_DUEL_CONFIG, "lobby": [self.escape_duel_public(state, user.id) for state in waiting if not level or state["level"] == level], "counts": {value["id"]: sum(state["level"] == value["id"] for state in waiting) for value in ESCAPE_DUEL_LEVELS}, "chips": rows[:15], "mine": self.escape_duel_public(mine, user.id) if mine else None, "balance": balance, "balanceAfterBet": round(balance - mine["winAmount"], 2) if mine and mine["status"] == "finished" and mine["winnerId"] == user.id else balance})
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)
