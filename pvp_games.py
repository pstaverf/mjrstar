import asyncio
import json
import logging
import re
import secrets

from aiogram.exceptions import TelegramRetryAfter

from blackjack_pvp import BlackjackPvpMixin
from games_backend import GameError, integer, money_cents, serialize


PVP_EMOJI = {"dice": "🎲", "bowling": "🎳", "darts": "🎯", "basketball": "🏀", "football": "⚽", "slots": "🎰"}
PVP_GAMES = set(PVP_EMOJI) | {"blackjack"}
SLOT_SYMBOLS = ["Бар", "Виноград", "Лимон", "Семёрка"]


def slot_reels(value):
    return [SLOT_SYMBOLS[(value - 1) // 4 ** index % 4] for index in range(3)]


def duel_score(game, value):
    if game == "slots":
        reels = slot_reels(value)
        return {"Семёрка": 4, "Бар": 3, "Виноград": 2, "Лимон": 1}[reels[0]] if len(set(reels)) == 1 else 0
    if game == "football":
        return int(value >= 3)
    if game == "darts":
        return [0, 0, 1, 1, 2, 2, 3][value]
    return value


class PvpGamesMixin(BlackjackPvpMixin):
    def register_pvp(self, application):
        self.register_blackjack_pvp(application)
        for game in sorted(PVP_GAMES):
            for action in ("create", "join", "cancel"):
                application.router.add_post(f"/api/pvp/{game}/{action}", self.handle_pvp_action)
            for action in ("active", "active-search", "my-rooms", "room", "round", "history"):
                application.router.add_get(f"/api/pvp/{game}/{action}", self.handle_pvp_read)
        application.router.add_get("/api/pvp/search", self.handle_pvp_read)
        application.router.add_get("/api/pvp/active-all", self.handle_pvp_read)
        application.router.add_get("/api/pvp/my-rounds", self.handle_pvp_read)

    async def initialize_pvp(self):
        self.pvp_tasks = {}
        self.pvp_telegram_lock = asyncio.Lock()
        async with self.database_lock:
            connection = self.database()
            try:
                await connection.execute("BEGIN IMMEDIATE")
                await connection.execute("CREATE TABLE IF NOT EXISTS webapp_pvp_rooms(id TEXT PRIMARY KEY,game TEXT NOT NULL,creator_id INTEGER NOT NULL,opponent_id INTEGER,status TEXT NOT NULL,data TEXT NOT NULL)")
                await connection.execute("CREATE INDEX IF NOT EXISTS idx_webapp_pvp_list ON webapp_pvp_rooms(game,status,creator_id)")
                async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE status = 'active'") as cursor:
                    interrupted = [json.loads(row[0]) for row in await cursor.fetchall()]
                for state in interrupted:
                    await self.refund_pvp(connection, state, "Раунд прерван перезапуском сервера. Обе ставки возвращены.")
                await self.advance_blackjack_pvp(connection)
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    async def cleanup_pvp(self):
        if self.pvp_tasks:
            await asyncio.gather(*list(self.pvp_tasks.values()), return_exceptions=True)

    def pvp_public(self, state):
        result = {key: value for key, value in state.items() if not key.startswith("_")}
        result.update({"id": state["roomId"], "bet": state["betAmount"], "bet_amount": state["betAmount"], "created_at": state["createdAt"], "avatarUrl": "/api/avatar/" + str(state["creatorId"])})
        return result

    async def save_pvp(self, connection, state):
        await connection.execute("UPDATE webapp_pvp_rooms SET status = ?,opponent_id = ?,data = ? WHERE id = ?", (state["status"], state.get("opponentId"), serialize(state), state["roomId"]))

    async def pvp_response(self, connection, state, user_id):
        response = {"ok": state["status"] != "error", **self.pvp_public(state), "balance": await self.balance(connection, user_id)}
        if state["game"] == "blackjack":
            self.blackjack_pvp_projection(response, state, user_id)
        return response

    async def refund_pvp(self, connection, state, message):
        if state["status"] != "active":
            return
        await self.credit(connection, state["creatorId"], state["_betCents"])
        await self.credit(connection, state["opponentId"], state["_betCents"])
        state.update({"ok": False, "status": "error", "error": message, "refunded": True, "feeAmount": 0, "winAmount": 0, "finishedAt": self.clock().isoformat()})
        await self.save_pvp(connection, state)
        await connection.execute("UPDATE webapp_requests SET response = ? WHERE user_id = ? AND request_id = ?", (serialize(await self.pvp_response(connection, state, state["opponentId"])), state["opponentId"], state["_joinKey"]))

    async def telegram_duel_roll(self, game):
        if not getattr(self, "telegram_bot", None) or not getattr(self, "telegram_channel", None):
            raise RuntimeError("Telegram game channel is not configured")
        for attempt in range(3):
            try:
                message = await self.telegram_bot.send_dice(chat_id=self.telegram_channel, emoji=PVP_EMOJI[game], request_timeout=20)
                value = integer(message.dice.value, 1, 64 if game == "slots" else 5 if game in {"football", "basketball"} else 6)
                username = message.chat.username
                if username:
                    link = f"https://t.me/{username}/{message.message_id}"
                elif str(message.chat.id).startswith("-100"):
                    link = f"https://t.me/c/{str(message.chat.id)[4:]}/{message.message_id}"
                else:
                    raise RuntimeError("Dice proof must point to the game channel")
                return value, link
            except TelegramRetryAfter as error:
                if attempt == 2 or error.retry_after > 20:
                    raise
                await asyncio.sleep(error.retry_after)

    async def play_pvp_duel(self, room_id):
        try:
            async with self.database_lock:
                async with self.database().execute("SELECT data FROM webapp_pvp_rooms WHERE id = ? AND status = 'active'", (room_id,)) as cursor:
                    row = await cursor.fetchone()
            if row is None:
                return
            state = json.loads(row[0])
            try:
                async with asyncio.timeout(90):
                    async with self.pvp_telegram_lock:
                        first = await self.telegram_duel_roll(state["game"])
                        second = await self.telegram_duel_roll(state["game"])
                error_message = None
            except Exception:
                logging.exception("Telegram PvP rolls failed for %s", room_id)
                error_message = "Не удалось провести бой. Обе ставки возвращены."
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ? AND status = 'active'", (room_id,)) as cursor:
                        row = await cursor.fetchone()
                    if row:
                        state = json.loads(row[0])
                        if error_message:
                            await self.refund_pvp(connection, state, error_message)
                        else:
                            scores = [duel_score(state["game"], first[0]), duel_score(state["game"], second[0])]
                            draw = scores[0] == scores[1]
                            bank = state["_betCents"] * 2
                            paid = state["_betCents"] if draw else bank * 99 // 100
                            winner = None if draw else state["creatorId"] if scores[0] > scores[1] else state["opponentId"]
                            if draw:
                                await self.credit(connection, state["creatorId"], paid)
                                await self.credit(connection, state["opponentId"], paid)
                            else:
                                await self.credit(connection, winner, paid)
                            state.update({"status": "finished", "creatorResult": first[0], "opponentResult": second[0], "creatorCheckLink": first[1], "opponentCheckLink": second[1], "isDraw": draw, "winnerId": winner, "winAmount": paid / 100, "feeAmount": 0 if draw else (bank - paid) / 100, "commissionPercent": 1, "finishedAt": self.clock().isoformat()})
                            if state["game"] == "slots":
                                state.update({"creatorReels": slot_reels(first[0]), "opponentReels": slot_reels(second[0])})
                            if state["game"] == "bowling":
                                state.update({"creatorLabel": str([0, 1, 3, 4, 5, 6][first[0] - 1]) + " кеглей", "opponentLabel": str([0, 1, 3, 4, 5, 6][second[0] - 1]) + " кеглей"})
                            else:
                                state.update({"creatorLabel": " · ".join(state["creatorReels"]) if state["game"] == "slots" else str(first[0]), "opponentLabel": " · ".join(state["opponentReels"]) if state["game"] == "slots" else str(second[0])})
                            await self.save_pvp(connection, state)
                            await connection.execute("UPDATE webapp_requests SET response = ? WHERE user_id = ? AND request_id = ?", (serialize(await self.pvp_response(connection, state, state["opponentId"])), state["opponentId"], state["_joinKey"]))
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
        except Exception:
            logging.exception("PvP settlement failed for %s", room_id)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ? AND status = 'active'", (room_id,)) as cursor:
                        row = await cursor.fetchone()
                    if row:
                        await self.refund_pvp(connection, json.loads(row[0]), "Не удалось завершить расчёт боя. Обе ставки возвращены.")
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
        finally:
            self.pvp_tasks.pop(room_id, None)

    async def handle_pvp_action(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            game, action = request.path.split("/")[3:5]
            key, signature = self.request_identity(request, payload)
            if game == "blackjack" and action in {"hit", "stand", "double"}:
                return await self.handle_blackjack_pvp_move(request, payload, user, key, signature)
            if game != "blackjack" and action == "create" and (not getattr(self, "telegram_bot", None) or not getattr(self, "telegram_channel", None)):
                raise GameError("Telegram PvP временно недоступен.", 503)
            pending_id = None
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    replay = await self.load_receipt(connection, user.id, key, signature)
                    if replay:
                        if replay.get("status") == "active" and action == "join":
                            pending_id = replay["roomId"]
                        else:
                            await connection.commit()
                            return self.response(replay)
                    if not replay:
                        if action == "create":
                            cents = money_cents(payload.get("bet"))
                            async with connection.execute("SELECT COUNT(*) FROM webapp_pvp_rooms WHERE creator_id = ? AND game = ? AND status IN ('waiting','active','playing')", (user.id, game)) as cursor:
                                count = (await cursor.fetchone())[0]
                            if count >= 10:
                                raise GameError("Достигнут предел 10 активных комнат.", 409)
                            await self.debit(connection, user.id, cents)
                            room_id = "P" + secrets.token_hex(8).upper()
                            state = {"roomId": room_id, "game": game, "creatorId": user.id, "creatorName": " ".join(part for part in (user.first_name, user.last_name) if part), "betAmount": cents / 100, "status": "waiting", "createdAt": self.clock().isoformat(), "_betCents": cents}
                            if game == "blackjack":
                                self.prepare_blackjack_pvp(state)
                            await connection.execute("INSERT INTO webapp_pvp_rooms(id,game,creator_id,status,data) VALUES (?,?,?,?,?)", (room_id, game, user.id, state["status"], serialize(state)))
                        else:
                            room_id = payload.get("roomId")
                            if not isinstance(room_id, str) or not re.fullmatch(r"P[A-F0-9]{16}", room_id):
                                raise GameError("Некорректный идентификатор комнаты.")
                            async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ? AND game = ?", (room_id, game)) as cursor:
                                row = await cursor.fetchone()
                            if row is None:
                                raise GameError("Комната не найдена.", 404)
                            state = json.loads(row[0])
                            if state["status"] != "waiting":
                                raise GameError("Комната уже закрыта или бой начался.", 409)
                            if action == "cancel":
                                if state["creatorId"] != user.id:
                                    raise GameError("Нет доступа к чужой комнате.", 403)
                                await self.credit(connection, user.id, state["_betCents"])
                                state.update({"status": "canceled", "refunded": True, "finishedAt": self.clock().isoformat()})
                            else:
                                if state["creatorId"] == user.id:
                                    raise GameError("Нельзя играть против себя.")
                                await self.debit(connection, user.id, state["_betCents"])
                                state.update({"status": "active", "opponentId": user.id, "opponentName": " ".join(part for part in (user.first_name, user.last_name) if part), "_joinKey": key})
                                if game == "blackjack":
                                    self.deal_blackjack_pvp(state)
                                else:
                                    pending_id = room_id
                            await self.save_pvp(connection, state)
                            if game == "blackjack":
                                await self.finish_blackjack_pvp(connection, state)
                        response = await self.pvp_response(connection, state, user.id)
                        await self.save_receipt(connection, user.id, key, signature, response)
                    await connection.commit()
                    if pending_id and pending_id not in self.pvp_tasks:
                        if replay:
                            try:
                                await connection.execute("BEGIN IMMEDIATE")
                                async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ?", (pending_id,)) as cursor:
                                    state = json.loads((await cursor.fetchone())[0])
                                await self.refund_pvp(connection, state, "Не удалось завершить бой. Обе ставки возвращены.")
                                await connection.commit()
                            except BaseException:
                                await connection.rollback()
                                raise
                        else:
                            self.pvp_tasks[pending_id] = asyncio.create_task(self.play_pvp_duel(pending_id))
                    task = self.pvp_tasks.get(pending_id)
                except BaseException:
                    await connection.rollback()
                    raise
            if task:
                await asyncio.shield(task)
            if pending_id:
                async with self.database_lock:
                    connection = self.database()
                    async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ?", (pending_id,)) as cursor:
                        state = json.loads((await cursor.fetchone())[0])
                    response = await self.pvp_response(connection, state, user.id)
            return self.response(response)
        except GameError as error:
            return self.failure(error)

    async def handle_pvp_read(self, request):
        try:
            user = self.validate_user(request)
            parts = request.path.split("/")
            action = parts[-1]
            game = parts[3] if len(parts) == 5 else request.query.get("game", "")
            if game and game not in PVP_GAMES:
                raise GameError("Неизвестная PvP-игра.")
            offset = integer(request.query.get("offset", "0"), 0, 1000000)
            scope = request.query.get("scope", "all")
            if scope not in {"all", "mine"}:
                raise GameError("Неизвестный фильтр.")
            conditions, values = [], []
            if game:
                conditions.append("game = ?")
                values.append(game)
            identifier = request.query.get("id")
            if action in {"room", "round", "active-search", "search"}:
                conditions.append("id = ?")
                values.append(identifier)
            elif action in {"active", "active-all"}:
                conditions.append("status = 'waiting'")
            elif action == "my-rooms":
                conditions.append("status IN ('waiting','active','playing') AND creator_id = ?")
                values.append(user.id)
            else:
                conditions.append("status = 'finished'")
            query = request.query.get("q", "").strip()
            if len(query) > 100:
                raise GameError("Слишком длинный запрос.")
            if query:
                conditions.append("(id = ? OR CAST(creator_id AS TEXT) = ? OR CAST(opponent_id AS TEXT) = ?)")
                values.extend([query, query, query])
            if scope == "mine" or action == "my-rounds":
                conditions.append("(creator_id = ? OR opponent_id = ?)")
                values.extend([user.id, user.id])
            async with self.database_lock:
                connection = self.database()
                async with connection.execute("SELECT data FROM webapp_pvp_rooms" + (" WHERE " + " AND ".join(conditions) if conditions else "") + " ORDER BY rowid DESC LIMIT 21 OFFSET ?", values + [offset]) as cursor:
                    rows = [self.pvp_public(json.loads(row[0])) for row in await cursor.fetchall()]
                if action in {"room", "round", "active-search", "search"}:
                    if not rows or action == "round" and rows[0]["status"] != "finished" or action == "active-search" and rows[0]["status"] != "waiting":
                        raise GameError("Комната не найдена.", 404)
                    state = rows[0]
                    response = {**state, "ok": True, "room": state, "balance": await self.balance(connection, user.id)}
                else:
                    response = {"ok": True, "rows": rows[:20], "rooms": rows[:20], "hasMore": len(rows) > 20}
                return self.response(response)
        except GameError as error:
            return self.failure(error)
