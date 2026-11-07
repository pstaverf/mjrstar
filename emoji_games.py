import asyncio
import json
import logging
import re
import secrets

from emoji_rules import EMOJI_CATALOG, EMOJI_GAMES, EMOJI_FACES, LADDERS, emoji_rule
from games_backend import GameError, money_cents, serialize
from pvp_games import slot_reels


class EmojiGamesMixin:
    def register_emoji(self, application):
        for game in EMOJI_GAMES:
            application.router.add_post(f"/api/{game}/play", self.handle_emoji_play)
            application.router.add_get(f"/api/{game}/multipliers", self.handle_emoji_multipliers)
            application.router.add_get(f"/api/{game}/quote", self.handle_emoji_quote)
            application.router.add_get(f"/api/{game}/history", self.handle_history)
        application.router.add_get("/api/play/result", self.handle_emoji_result)

    async def initialize_emoji(self):
        self.emoji_tasks = {}
        async with self.database_lock:
            connection = self.database()
            try:
                await connection.execute("BEGIN IMMEDIATE")
                await connection.execute("CREATE TABLE IF NOT EXISTS webapp_emoji_jobs(user_id INTEGER NOT NULL,rid TEXT NOT NULL,game TEXT NOT NULL,status TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(user_id,rid))")
                async with connection.execute("SELECT data FROM webapp_emoji_jobs WHERE status = 'pending'") as cursor:
                    interrupted = [json.loads(row[0]) for row in await cursor.fetchall()]
                for state in interrupted:
                    await self.refund_emoji(connection, state, "Игра прервана перезапуском сервера. Ставка возвращена.")
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    async def cleanup_emoji(self):
        if self.emoji_tasks:
            await asyncio.gather(*list(self.emoji_tasks.values()), return_exceptions=True)

    def emoji_quote(self, game, outcome):
        count, settle, maximum = emoji_rule(game, outcome)
        return {"ok": True, "outcome": outcome, "throws": count, "multiplier": maximum / 100, "variable": outcome == "Лесенка" or outcome in LADDERS or outcome in {"Копилка", "Лаки 7"}}

    async def handle_emoji_quote(self, request):
        try:
            self.validate_user(request)
            return self.response(await asyncio.to_thread(self.emoji_quote, request.path.split("/")[2], request.query.get("outcome", "")))
        except GameError as error:
            return self.failure(error)

    def emoji_multipliers(self, game):
        outcomes = list(EMOJI_CATALOG[game])
        if game == "dice":
            outcomes.extend(["Лесенка низкий риск", "Лесенка высокий риск"])
        elif game == "slots":
            outcomes.extend(["Лесенка", "Копилка", "Лаки 7"])
        else:
            outcomes.append("Лесенка")
        multipliers = {outcome: emoji_rule(game, outcome)[2] / 100 for outcome in outcomes}
        response = {"ok": True, "multipliers": multipliers, "families": {}, "rtp": 0.9}
        if game == "dice":
            for outcome in LADDERS:
                if outcome.startswith("Лесенка "):
                    for face in range(1, 7):
                        multipliers[outcome + ":" + str(face)] = emoji_rule(game, outcome)[1]([face]) / 100
        elif game == "slots":
            paytables = {}
            symbols = ["Бар", "Виноград", "Лимон", "Семёрка"]
            for kind, outcome in (("ladder", "Лесенка"), ("piggy", "Копилка")):
                settle = emoji_rule(game, outcome)[1]
                table = {symbol: settle([1 + index * 21]) / (300 if kind == "piggy" else 100) for index, symbol in enumerate(symbols)}
                paytables[kind] = {"table": table, "max": multipliers[outcome]}
            settle = emoji_rule(game, "Лаки 7")[1]
            examples = {3: [64, 1], 4: [64, 4], 5: [64, 16], 6: [64, 64]}
            paytables["lucky"] = {"table": {str(count): settle(values) / 100 for count, values in examples.items()}, "max": multipliers["Лаки 7"]}
            paytables["count"] = {str(count): emoji_rule(game, "Кол-во:Бар:" + str(count))[2] / 100 for count in (1, 2)}
            response["paytables"] = paytables
        else:
            settle = emoji_rule(game, "Лесенка")[1]
            response["ladder"] = {"table": {str(face): settle([face]) / 100 for face in range(1, EMOJI_FACES[game] + 1)}}
            response["pick"] = {str(count): emoji_rule(game, "Выбор:" + ",".join(str(value) for value in range(1, count + 1)))[2] / 100 for count in range(1, EMOJI_FACES[game])}
        return response

    async def handle_emoji_multipliers(self, request):
        try:
            self.validate_user(request)
            return self.response(await asyncio.to_thread(self.emoji_multipliers, request.path.split("/")[2]))
        except GameError as error:
            return self.failure(error)

    async def save_emoji(self, connection, state):
        await connection.execute("UPDATE webapp_emoji_jobs SET status = ?,data = ? WHERE user_id = ? AND rid = ?", (state["status"], serialize(state), state["userId"], state["rid"]))
        await connection.execute("UPDATE webapp_requests SET response = ? WHERE user_id = ? AND request_id = ?", (serialize(state["response"]), state["userId"], state["_key"]))

    async def refund_emoji(self, connection, state, message):
        if state["status"] != "pending":
            return
        await self.credit(connection, state["userId"], state["_betCents"])
        state.update({"status": "cancelled", "response": {"ok": False, "refunded": True, "error": message, "roundId": state["roundId"], "balance": await self.balance(connection, state["userId"]), "newBalance": await self.balance(connection, state["userId"])}})
        await self.save_emoji(connection, state)

    async def settle_emoji(self, user_id, rid):
        try:
            async with self.database_lock:
                async with self.database().execute("SELECT data FROM webapp_emoji_jobs WHERE user_id = ? AND rid = ? AND status = 'pending'", (user_id, rid)) as cursor:
                    row = await cursor.fetchone()
            if row is None:
                return
            state = json.loads(row[0])
            count, settle, maximum = emoji_rule(state["game"], state["outcome"])
            async with self.pvp_telegram_lock:
                async with asyncio.timeout(90):
                    rolls = [await self.telegram_duel_roll(EMOJI_GAMES[state["game"]]) for _ in range(count)]
            values, links = [roll[0] for roll in rolls], [roll[1] for roll in rolls]
            multiplier = settle(values)
            paid = state["_betCents"] * multiplier // 100
            draw = multiplier == 100 and (state["outcome"] == "Дуэль" or state["outcome"].startswith("Дуэль - ")) and values[0] == values[1]
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    async with connection.execute("SELECT status FROM webapp_emoji_jobs WHERE user_id = ? AND rid = ?", (user_id, rid)) as cursor:
                        current = await cursor.fetchone()
                    if current is not None and current[0] == "pending":
                        await self.credit(connection, user_id, paid)
                        response = {"ok": True, "roundId": state["roundId"], "outcome": state["outcome"], "userId": user_id, "username": state["username"], "bet": state["_betCents"] / 100, "betAmount": state["_betCents"] / 100, "win": multiplier > 100, "isDraw": draw, "refund": paid / 100 if 0 < multiplier < 100 else 0, "winAmount": paid / 100, "multiplier": multiplier / 100, "mult": multiplier / 100, "result": "draw" if draw else "win" if multiplier > 100 else "lose", "values": values, "dice": values, "checkLink": links[0], "checkLinks": links, "details": " · ".join(map(str, values)), "createdAt": self.clock().isoformat(), "balance": await self.balance(connection, user_id), "newBalance": await self.balance(connection, user_id)}
                        if state["game"] == "slots":
                            response["reels"] = slot_reels(values[0]) if count == 1 else [slot_reels(value) for value in values]
                        state.update({"status": "done", "response": response})
                        await connection.execute("INSERT INTO webapp_rounds(public_id,game,user_id,username,bet_cents,payout_cents,request_id,request_digest,response,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (state["roundId"], state["game"], user_id, state["username"], state["_betCents"], paid, state["_key"], state["_signature"], serialize(response), response["createdAt"]))
                        await self.save_emoji(connection, state)
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
        except Exception:
            logging.exception("Telegram solo round failed for %s", rid)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    async with connection.execute("SELECT data FROM webapp_emoji_jobs WHERE user_id = ? AND rid = ? AND status = 'pending'", (user_id, rid)) as cursor:
                        row = await cursor.fetchone()
                    if row:
                        await self.refund_emoji(connection, json.loads(row[0]), "Не удалось завершить игру. Ставка возвращена.")
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
        finally:
            self.emoji_tasks.pop((user_id, rid), None)

    async def handle_emoji_play(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            game = request.path.split("/")[2]
            key, signature = self.request_identity(request, payload)
            rid = payload.get("rid", key)
            if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", rid):
                raise GameError("Некорректный идентификатор игры.")
            bet = money_cents(payload.get("bet"))
            outcome = payload.get("outcome")
            if not isinstance(outcome, str):
                raise GameError("Укажите исход игры.")
            await asyncio.to_thread(emoji_rule, game, outcome)
            if not getattr(self, "telegram_bot", None) or not getattr(self, "telegram_channel", None):
                raise GameError("Игровой канал Telegram недоступен.", 503)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    replay = await self.load_receipt(connection, user.id, key, signature)
                    if replay and not replay.get("pending"):
                        await connection.commit()
                        return self.response(replay)
                    async with connection.execute("SELECT data FROM webapp_emoji_jobs WHERE user_id = ? AND rid = ?", (user.id, rid)) as cursor:
                        row = await cursor.fetchone()
                    if row:
                        state = json.loads(row[0])
                        if state["_signature"] != signature:
                            raise GameError("Идентификатор игры уже использован.", 409)
                        if state["status"] != "pending":
                            await connection.commit()
                            return self.response(state["response"])
                        if (user.id, rid) not in self.emoji_tasks:
                            await self.refund_emoji(connection, state, "Игра прервана. Ставка возвращена.")
                    else:
                        async with connection.execute("SELECT 1 FROM webapp_emoji_jobs WHERE user_id = ? AND status = 'pending'", (user.id,)) as cursor:
                            if await cursor.fetchone():
                                raise GameError("Дождитесь предыдущей игры.", 409)
                        await self.debit(connection, user.id, bet)
                        state = {"rid": rid, "game": game, "outcome": outcome, "userId": user.id, "username": " ".join(part for part in (user.first_name, user.last_name) if part), "roundId": "T" + secrets.token_hex(12).upper(), "status": "pending", "_betCents": bet, "_key": key, "_signature": signature, "response": {"ok": True, "pending": True}}
                        await connection.execute("INSERT INTO webapp_emoji_jobs(user_id,rid,game,status,data) VALUES (?,?,?,?,?)", (user.id, rid, game, "pending", serialize(state)))
                        await self.save_receipt(connection, user.id, key, signature, state["response"])
                    await connection.commit()
                    if state["status"] == "pending" and (user.id, rid) not in self.emoji_tasks:
                        self.emoji_tasks[(user.id, rid)] = asyncio.create_task(self.settle_emoji(user.id, rid))
                except BaseException:
                    await connection.rollback()
                    raise
            task = self.emoji_tasks.get((user.id, rid))
            if task:
                await asyncio.shield(task)
            async with self.database_lock:
                async with self.database().execute("SELECT data FROM webapp_emoji_jobs WHERE user_id = ? AND rid = ?", (user.id, rid)) as cursor:
                    state = json.loads((await cursor.fetchone())[0])
            return self.response(state["response"])
        except GameError as error:
            return self.failure(error)

    async def handle_emoji_result(self, request):
        try:
            user = self.validate_user(request)
            rid = request.query.get("rid", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", rid):
                raise GameError("Некорректный идентификатор игры.")
            async with self.database_lock:
                async with self.database().execute("SELECT status,data FROM webapp_emoji_jobs WHERE user_id = ? AND rid = ?", (user.id, rid)) as cursor:
                    row = await cursor.fetchone()
            if row is None:
                raise GameError("Игра не найдена.", 404)
            return self.response({"ok": True, "state": row[0], "payload": json.loads(row[1])["response"] if row[0] == "done" else None})
        except GameError as error:
            return self.failure(error)
