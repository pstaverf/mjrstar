import asyncio
import hashlib
import json
import logging
import math
import secrets
import time
from decimal import Decimal, InvalidOperation

from pot_rules import POT_GAMES
from games_backend import GameError, money_cents, serialize
from game_rules import unit, payout


ROULETTE_OUTCOMES = [{"color": "red", "mult": 1.8, "weight": 0.45}, {"color": "black", "mult": 1.8, "weight": 0.45}, {"color": "green", "mult": 3.5, "weight": 0.1}]


class LiveGamesMixin:
    def register_live(self, application):
        for game in ("crash", "roulette"):
            application.router.add_get(f"/api/{game}/state", self.handle_live_state)
            application.router.add_get(f"/api/{game}/round", self.handle_live_round)
            application.router.add_get(f"/api/{game}/history", self.handle_history)
            application.router.add_post(f"/api/{game}/bet", self.handle_live_action)
        application.router.add_post("/api/crash/cashout", self.handle_live_action)

    async def initialize_live(self):
        async with self.database_lock:
            connection = self.database()
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_live_rounds(id TEXT PRIMARY KEY,game TEXT NOT NULL,data TEXT NOT NULL,finished INTEGER NOT NULL DEFAULT 0)")
            await connection.execute("CREATE INDEX IF NOT EXISTS idx_webapp_live_current ON webapp_live_rounds(game,finished)")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_live_bets(round_id TEXT NOT NULL,user_id INTEGER NOT NULL,data TEXT NOT NULL,PRIMARY KEY(round_id,user_id))")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_live_queue(user_id INTEGER NOT NULL,game TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(user_id,game))")
            await connection.commit()
        self.live_task = asyncio.create_task(self.live_loop())

    async def live_loop(self):
        while True:
            try:
                async with self.database_lock:
                    connection = self.database()
                    try:
                        await connection.execute("BEGIN IMMEDIATE")
                        await self.advance_blackjack_pvp(connection)
                        await self.expire_escape_duels(connection)
                        for pot_game in POT_GAMES:
                            for room in (1, 2):
                                await self.advance_pot(connection, pot_game, room)
                        for game in ("crash", "roulette"):
                            await self.advance_live(connection, game)
                        await connection.commit()
                    except BaseException:
                        await connection.rollback()
                        raise
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception("Live game processing failed")
            await asyncio.sleep(0.2)

    async def live_bets(self, connection, round_id):
        async with connection.execute("SELECT user_id,data FROM webapp_live_bets WHERE round_id = ? ORDER BY rowid", (round_id,)) as cursor:
            return {row[0]: json.loads(row[1]) for row in await cursor.fetchall()}

    async def update_live_bet(self, connection, round_id, user_id, bet):
        await connection.execute("UPDATE webapp_live_bets SET data = ? WHERE round_id = ? AND user_id = ?", (serialize(bet), round_id, user_id))

    async def advance_live(self, connection, game):
        now = int(time.time() * 1000)
        async with connection.execute("SELECT data FROM webapp_live_rounds WHERE game = ? AND finished = 0", (game,)) as cursor:
            row = await cursor.fetchone()
        stored_data = row[0] if row else None
        state = json.loads(stored_data) if row else None
        if state is not None and state.get("_nextAt", now + 1) <= now:
            await connection.execute("UPDATE webapp_live_rounds SET finished = 1 WHERE id = ?", (state["roundId"],))
            state = None
        if state is None:
            seed = secrets.token_hex(32)
            round_id = ("C" if game == "crash" else "R") + secrets.token_hex(12).upper()
            state = {"ok": True, "roundId": round_id, "_seed": seed, "seedHash": hashlib.sha256(seed.encode()).hexdigest(), "status": "waiting", "waitingStartedAt": now, "waitSeconds": 10 if game == "crash" else 15, "growth": 0.1, "spinSeconds": 6, "createdAt": self.clock().isoformat()}
            if game == "crash":
                state["_crashPoint"] = max(1, min(1000, math.floor(90 / (1 - unit(seed, round_id))) / 100))
            else:
                roll = unit(seed, round_id)
                selected = ROULETTE_OUTCOMES[0] if roll < 0.45 else ROULETTE_OUTCOMES[1] if roll < 0.9 else ROULETTE_OUTCOMES[2]
                state.update({"_outcomeColor": selected["color"], "_outcomeMult": selected["mult"], "outcomes": ROULETTE_OUTCOMES})
            stored_data = serialize(state)
            await connection.execute("INSERT INTO webapp_live_rounds(id,game,data) VALUES (?,?,?)", (round_id, game, stored_data))
        if state["status"] == "waiting":
            async with connection.execute("SELECT user_id,data FROM webapp_live_queue WHERE game = ?", (game,)) as cursor:
                queued = await cursor.fetchall()
            for identifier, data in queued:
                await connection.execute("INSERT INTO webapp_live_bets(round_id,user_id,data) VALUES (?,?,?)", (state["roundId"], identifier, data))
            if queued:
                await connection.execute("DELETE FROM webapp_live_queue WHERE game = ?", (game,))
        bets = await self.live_bets(connection, state["roundId"])
        start = state["waitingStartedAt"] + state["waitSeconds"] * 1000
        if state["status"] == "waiting" and now >= start:
            if not bets:
                state["waitingStartedAt"] = now
            elif game == "crash":
                state.update({"status": "flying", "flyingStartedAt": start})
            else:
                state.update({"status": "spinning", "spinningStartedAt": start, "outcomeColor": state["_outcomeColor"], "outcomeMult": state["_outcomeMult"]})
        finished = False
        if game == "crash" and state["status"] == "flying":
            current = math.exp(min(20, (now - state["flyingStartedAt"]) / 1000 * state["growth"]))
            crash = state["_crashPoint"]
            for user_id, bet in bets.items():
                auto = bet.get("autoCashout")
                if not bet["settled"] and auto and auto <= crash and current >= auto:
                    await self.settle_live_bet(connection, game, state, user_id, bet, auto)
            if current >= crash:
                state.update({"status": "crashed", "crashPoint": crash, "serverSeed": state["_seed"], "_nextAt": now + 4000})
                for user_id, bet in bets.items():
                    if not bet["settled"]:
                        await self.settle_live_bet(connection, game, state, user_id, bet, 0)
                finished = True
        elif game == "roulette" and state["status"] == "spinning" and now >= state["spinningStartedAt"] + state["spinSeconds"] * 1000:
            state.update({"status": "resolved", "serverSeed": state["_seed"], "_nextAt": now + 4000})
            for user_id, bet in bets.items():
                if not bet["settled"]:
                    await self.settle_live_bet(connection, game, state, user_id, bet, 0)
            finished = True
        if finished:
            for user_id, bet in bets.items():
                detail = {key: value for key, value in state.items() if not key.startswith("_")}
                detail.update({"userId": user_id, "username": bet["username"], "bet": bet["bet"], "betAmount": bet["bet"], "winAmount": bet["winAmount"], "result": "win" if bet["winAmount"] > 0 else "lose", "cashoutMult": bet.get("cashoutMult", 0), "multiplier": bet.get("cashoutMult", 0), "items": bet.get("items", []), "active": False})
                await connection.execute("INSERT INTO webapp_rounds(public_id,game,user_id,username,bet_cents,payout_cents,request_id,request_digest,response,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (state["roundId"] + "_" + str(user_id), game, user_id, bet["username"], bet["_betCents"], bet["_paidCents"], "settle_" + state["roundId"], state["seedHash"], serialize(detail), self.clock().isoformat()))
        encoded = serialize(state)
        if encoded != stored_data:
            await connection.execute("UPDATE webapp_live_rounds SET data = ? WHERE id = ?", (encoded, state["roundId"]))
        return state

    async def settle_live_bet(self, connection, game, state, user_id, bet, multiplier):
        if bet["settled"]:
            return
        if game == "roulette":
            paid = 0
            for item in bet["items"]:
                item_paid = payout(item["_betCents"], state["_outcomeMult"]) if item["color"] == state["_outcomeColor"] else 0
                item["winAmount"] = item_paid / 100
                paid += item_paid
        else:
            paid = payout(bet["_betCents"], multiplier)
            bet.update({"cashoutMult": multiplier, "cashedOut": multiplier > 0})
        bet.update({"settled": True, "winAmount": paid / 100, "_paidCents": paid})
        await self.credit(connection, user_id, paid)
        await self.update_live_bet(connection, state["roundId"], user_id, bet)

    async def live_public(self, connection, game, state, user_id):
        response = {key: value for key, value in state.items() if not key.startswith("_")}
        bets = await self.live_bets(connection, state["roundId"])
        players = []
        for identifier, item in bets.items():
            public = {key: value for key, value in item.items() if not key.startswith("_")}
            public["id"] = identifier
            public["userId"] = identifier
            public["items"] = [{key: value for key, value in entry.items() if not key.startswith("_")} for entry in item.get("items", [])]
            players.append(public)
        async with connection.execute("SELECT data FROM webapp_live_rounds WHERE game = ? AND id != ? AND json_extract(data,'$.serverSeed') IS NOT NULL ORDER BY rowid DESC LIMIT 20", (game, state["roundId"])) as cursor:
            history = [{key: value for key, value in json.loads(row[0]).items() if not key.startswith("_")} for row in await cursor.fetchall()]
        own = next((player for player in players if player["id"] == user_id), None)
        response.update({"balance": await self.balance(connection, user_id), "players": players, "history": history})
        if game == "crash":
            async with connection.execute("SELECT data FROM webapp_live_queue WHERE game = ? AND user_id = ?", (game, user_id)) as cursor:
                queued = await cursor.fetchone()
            response.update({"myBet": own, "myQueued": {key: value for key, value in json.loads(queued[0]).items() if not key.startswith("_")} if queued else None})
        else:
            response.update({"myBets": own["items"] if own else [], "myQueued": [], "bets": [{"id": player["id"], "username": player["username"], **item} for player in players for item in player["items"]]})
        return response

    async def handle_live_state(self, request):
        user = self.validate_user(request)
        game = request.path.split("/")[2]
        async with self.database_lock:
            connection = self.database()
            try:
                await connection.execute("BEGIN IMMEDIATE")
                state = await self.advance_live(connection, game)
                response = await self.live_public(connection, game, state, user.id)
                await connection.commit()
                return self.response(response)
            except BaseException:
                await connection.rollback()
                raise

    async def handle_live_action(self, request):
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
                    state = await self.advance_live(connection, game)
                    bets = await self.live_bets(connection, state["roundId"])
                    if payload.get("roundId") != state["roundId"]:
                        raise GameError("Раунд изменился. Обновите игру.", 409)
                    if action == "cashout":
                        bet = bets.get(user.id)
                        if game != "crash" or state["status"] != "flying" or not bet or bet["settled"]:
                            raise GameError("Вывод в этом раунде недоступен.", 409)
                        multiplier = math.floor(math.exp((time.time() * 1000 - state["flyingStartedAt"]) / 1000 * state["growth"]) * 100) / 100
                        if multiplier >= state["_crashPoint"]:
                            raise GameError("Раунд уже завершён.", 409)
                        await self.settle_live_bet(connection, game, state, user.id, bet, multiplier)
                    else:
                        if state["status"] != "waiting" and game != "crash":
                            raise GameError("Дождитесь следующего раунда.", 409)
                        if game == "crash":
                            async with connection.execute("SELECT 1 FROM webapp_live_queue WHERE game = ? AND user_id = ?", (game, user.id)) as cursor:
                                queued = await cursor.fetchone()
                            if user.id in bets or queued:
                                raise GameError("Ставка уже принята.", 409)
                            cents = money_cents(payload.get("bet"))
                            auto = payload.get("autoCashout")
                            if auto is not None:
                                try:
                                    auto = Decimal(str(auto))
                                    if not auto.is_finite() or not Decimal("1.01") <= auto <= 1000 or auto * 100 != (auto * 100).to_integral_value():
                                        raise ValueError
                                except (InvalidOperation, ValueError):
                                    raise GameError("Автовывод должен быть от x1.01 до x1000 с точностью 0.01.") from None
                                auto = float(auto)
                            bet = {"bet": cents / 100, "_betCents": cents, "autoCashout": auto, "cashedOut": False, "settled": False, "winAmount": 0}
                        else:
                            items = payload.get("items")
                            if not isinstance(items, list) or not 1 <= len(items) <= 3:
                                raise GameError("Выберите цвет ставки.")
                            existing = bets.get(user.id)
                            previous = existing["items"] if existing else []
                            taken = {item["color"] for item in previous}
                            valid = []
                            for item in items:
                                if not isinstance(item, dict) or not isinstance(item.get("color"), str) or item["color"] not in {"red", "black", "green"} or item["color"] in taken:
                                    raise GameError("Неизвестный или повторяющийся цвет ставки.")
                                cents = money_cents(item.get("bet"))
                                valid.append({"color": item["color"], "bet": cents / 100, "_betCents": cents, "winAmount": 0})
                                taken.add(item["color"])
                            cents = sum(item["_betCents"] for item in valid)
                            bet = {"bet": (cents + (existing["_betCents"] if existing else 0)) / 100, "_betCents": cents + (existing["_betCents"] if existing else 0), "items": previous + valid, "settled": False, "winAmount": 0}
                        await self.debit(connection, user.id, cents)
                        bet["username"] = " ".join(part for part in (user.first_name, user.last_name) if part)
                        if game == "crash" and state["status"] != "waiting":
                            await connection.execute("INSERT INTO webapp_live_queue(user_id,game,data) VALUES (?,?,?)", (user.id, game, serialize(bet)))
                        else:
                            await connection.execute("INSERT INTO webapp_live_bets(round_id,user_id,data) VALUES (?,?,?) ON CONFLICT(round_id,user_id) DO UPDATE SET data=excluded.data", (state["roundId"], user.id, serialize(bet)))
                    response = await self.live_public(connection, game, state, user.id)
                    await self.save_receipt(connection, user.id, key, signature, response)
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)

    async def handle_live_round(self, request):
        user = self.validate_user(request)
        game = request.path.split("/")[2]
        async with self.database_lock:
            connection = self.database()
            async with connection.execute("SELECT data FROM webapp_live_rounds WHERE game = ? AND id = ?", (game, request.query.get("id", ""))) as cursor:
                row = await cursor.fetchone()
            if row is None or "serverSeed" not in json.loads(row[0]):
                return self.failure(GameError("Завершённый раунд не найден.", 404))
            return self.response(await self.live_public(connection, game, json.loads(row[0]), user.id))
