import hashlib
import json
import re
import secrets
import time

from games_backend import GameError
from game_rules import deck_for, hand_total


BLACKJACK_TURN_SECONDS = 300


class BlackjackPvpMixin:
    def register_blackjack_pvp(self, application):
        application.router.add_get("/api/pvp/blackjack/state", self.handle_blackjack_pvp_state)
        for action in ("hit", "stand", "double"):
            application.router.add_post(f"/api/pvp/blackjack/{action}", self.handle_pvp_action)

    def prepare_blackjack_pvp(self, state):
        seed = secrets.token_hex(32)
        state.update({"_seed": seed, "seedHash": hashlib.sha256(seed.encode()).hexdigest(), "creatorVersion": 0, "opponentVersion": 0})

    def deal_blackjack_pvp(self, state):
        deck = deck_for(state["_seed"], state["roomId"])
        state.update({"status": "playing", "_deck": deck, "_cursor": 4, "creatorCards": [deck[0], deck[2]], "opponentCards": [deck[1], deck[3]], "_creatorBetCents": state["_betCents"], "_opponentBetCents": state["_betCents"]})
        for role in ("creator", "opponent"):
            total = hand_total(state[role + "Cards"])
            state.update({role + "Result": total, role + "Busted": False, role + "Doubled": False, role + "Done": total == 21, role + "Deadline": time.time() + BLACKJACK_TURN_SECONDS, role + "AvatarUrl": "/api/avatar/" + str(state[role + "Id"])})

    def blackjack_pvp_projection(self, response, state, user_id):
        role = "creator" if state["creatorId"] == user_id else "opponent" if state.get("opponentId") == user_id else None
        response.update({"youAre": role, "canAct": role is not None and state["status"] == "playing" and not state[role + "Done"], "version": state.get((role or "creator") + "Version", 0)})
        return response

    async def finish_blackjack_pvp(self, connection, state):
        if state["status"] != "playing" or not state["creatorDone"] or not state["opponentDone"]:
            return
        scores = [state[role + "Result"] if state[role + "Result"] <= 21 else 0 for role in ("creator", "opponent")]
        draw = scores[0] == scores[1]
        bank = state["_creatorBetCents"] + state["_opponentBetCents"]
        winner = None if draw else state["creatorId"] if scores[0] > scores[1] else state["opponentId"]
        paid = bank * 99 // 100 if not draw else 0
        if draw:
            for role in ("creator", "opponent"):
                await self.credit(connection, state[role + "Id"], state["_" + role + "BetCents"])
        else:
            await self.credit(connection, winner, paid)
        state.update({"status": "finished", "isDraw": draw, "winnerId": winner, "winAmount": paid / 100 if not draw else state["betAmount"], "feeAmount": 0 if draw else (bank - paid) / 100, "commissionPercent": 1, "totalBank": bank / 100, "creatorBetAmount": state["_creatorBetCents"] / 100, "opponentBetAmount": state["_opponentBetCents"] / 100, "creatorRefund": state["_creatorBetCents"] / 100 if draw else 0, "opponentRefund": state["_opponentBetCents"] / 100 if draw else 0, "serverSeed": state["_seed"], "finishedAt": self.clock().isoformat()})
        await self.save_pvp(connection, state)

    async def advance_blackjack_pvp(self, connection):
        now = time.time()
        async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE game = 'blackjack' AND status = 'playing' AND ((json_extract(data,'$.creatorDone') = 0 AND json_extract(data,'$.creatorDeadline') <= ?) OR (json_extract(data,'$.opponentDone') = 0 AND json_extract(data,'$.opponentDeadline') <= ?))", (now, now)) as cursor:
            states = [json.loads(row[0]) for row in await cursor.fetchall()]
        for state in states:
            for role in ("creator", "opponent"):
                if not state[role + "Done"] and state[role + "Deadline"] <= now:
                    state[role + "Done"] = True
                    state[role + "TimedOut"] = True
                    state[role + "Version"] += 1
            await self.save_pvp(connection, state)
            await self.finish_blackjack_pvp(connection, state)

    async def handle_blackjack_pvp_state(self, request):
        try:
            user = self.validate_user(request)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    await self.advance_blackjack_pvp(connection)
                    async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ? AND game = 'blackjack'", (request.query.get("roomId", ""),)) as cursor:
                        row = await cursor.fetchone()
                    if row is None:
                        raise GameError("Комната не найдена.", 404)
                    state = json.loads(row[0])
                    response = await self.pvp_response(connection, state, user.id)
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)

    async def handle_blackjack_pvp_move(self, request, payload, user, key, signature):
        try:
            action = request.path.split("/")[-1]
            if not isinstance(payload.get("roomId"), str) or not re.fullmatch(r"P[A-F0-9]{16}", payload["roomId"]):
                raise GameError("Некорректный идентификатор комнаты.")
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    replay = await self.load_receipt(connection, user.id, key, signature)
                    if replay:
                        await connection.commit()
                        return self.response(replay)
                    await self.advance_blackjack_pvp(connection)
                    async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ? AND game = 'blackjack'", (payload.get("roomId", ""),)) as cursor:
                        row = await cursor.fetchone()
                    if row is None:
                        raise GameError("Комната не найдена.", 404)
                    state = json.loads(row[0])
                    role = "creator" if state["creatorId"] == user.id else "opponent" if state.get("opponentId") == user.id else None
                    if role is None:
                        raise GameError("Нет доступа к чужой руке.", 403)
                    if state["status"] != "playing" or state[role + "Done"]:
                        raise GameError("Рука уже завершена.", 409)
                    if isinstance(payload.get("version"), bool) or payload.get("version") != state[role + "Version"]:
                        raise GameError("Состояние руки изменилось. Обновите игру.", 409)
                    cards = state[role + "Cards"]
                    if action == "double":
                        if len(cards) != 2 or state[role + "Doubled"]:
                            raise GameError("Удвоение недоступно.")
                        await self.debit(connection, user.id, state["_betCents"])
                        state["_" + role + "BetCents"] += state["_betCents"]
                        state[role + "Doubled"] = True
                    if action in {"hit", "double"}:
                        if state["_cursor"] >= len(state["_deck"]):
                            raise GameError("В колоде закончились карты.", 409)
                        cards.append(state["_deck"][state["_cursor"]])
                        state["_cursor"] += 1
                        total = hand_total(cards)
                        state[role + "Result"] = total
                        state[role + "Busted"] = total > 21
                        state[role + "Done"] = total >= 21 or action == "double"
                    else:
                        state[role + "Done"] = True
                    state[role + "Version"] += 1
                    state[role + "Deadline"] = time.time() + BLACKJACK_TURN_SECONDS
                    await self.save_pvp(connection, state)
                    await self.finish_blackjack_pvp(connection, state)
                    response = await self.pvp_response(connection, state, user.id)
                    await self.save_receipt(connection, user.id, key, signature, response)
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)
