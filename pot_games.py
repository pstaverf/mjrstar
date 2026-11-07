import hashlib
import json
import re
import secrets
from time import time as pot_now

from games_backend import GameError, integer, money_cents, serialize
from pot_rules import POT_GAMES, POT_COLORS, POT_CONFIG, pot_winner, pot_live_seconds, pot_balls, portal_layout, portal_motion, portal_owner


class PotGamesMixin:
    def register_pots(self, application):
        for game in POT_GAMES:
            for action in ("state", "history", "round", "howto"):
                application.router.add_get(f"/api/{game}/{action}", self.handle_pot_read)
            for action in ("join", "bet", "cancel"):
                application.router.add_post(f"/api/{game}/{action}", self.handle_pot_action)
        application.router.add_get("/api/portal/frames", self.handle_pot_read)

    async def initialize_pots(self):
        async with self.database_lock:
            connection = self.database()
            try:
                await connection.execute("BEGIN IMMEDIATE")
                await connection.execute("CREATE TABLE IF NOT EXISTS webapp_pot_rounds(id TEXT PRIMARY KEY,game TEXT NOT NULL,room INTEGER NOT NULL,seq INTEGER NOT NULL,phase TEXT NOT NULL,data TEXT NOT NULL,UNIQUE(game,room,seq))")
                await connection.execute("CREATE INDEX IF NOT EXISTS idx_pot_current ON webapp_pot_rounds(game,room,seq DESC)")
                for game in POT_GAMES:
                    for room in (1, 2):
                        await self.advance_pot(connection, game, room)
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    async def save_pot(self, connection, state):
        await connection.execute("UPDATE webapp_pot_rounds SET phase = ?,data = ? WHERE id = ?", (state["phase"], serialize(state), state["id"]))

    async def create_pot(self, connection, game, room, sequence):
        seed = secrets.token_hex(32)
        identifier = POT_GAMES[game] + secrets.token_hex(12).upper()
        state = {"id": identifier, "game": game, "roomId": room, "roomName": "Комната " + str(room), "seq": sequence, "phase": "waiting", "fee": 0.01, "commitHash": hashlib.sha256(seed.encode()).hexdigest(), "_seed": seed, "_players": [], "_createdAt": int(pot_now() * 1000)}
        await connection.execute("INSERT INTO webapp_pot_rounds(id,game,room,seq,phase,data) VALUES (?,?,?,?,?,?)", (identifier, game, room, sequence, state["phase"], serialize(state)))
        return state

    async def advance_pot(self, connection, game, room):
        now = int(pot_now() * 1000)
        async with connection.execute("SELECT data FROM webapp_pot_rounds WHERE game = ? AND room = ? ORDER BY seq DESC LIMIT 1", (game, room)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return await self.create_pot(connection, game, room, 1)
        state = json.loads(row[0])
        players = state["_players"]
        if state["phase"] == "waiting" and players and now >= state["_waitingUntil"]:
            for player in players:
                await self.credit(connection, player["uid"], player["cents"])
            state.update({"phase": "cancelled", "refunded": True})
            await self.save_pot(connection, state)
            return await self.create_pot(connection, game, room, state["seq"] + 1)
        if state["phase"] == "betting" and now >= state["bettingEndsAt"]:
            cents = [player["cents"] for player in players]
            state.update({"phase": "countdown", "countdownEndsAt": state["bettingEndsAt"] + 3000, "liveStartedAt": state["bettingEndsAt"] + 3000, "liveSec": pot_live_seconds(game, len(players))})
            if game == "portal":
                state["layout"] = portal_layout(state["_seed"], state["id"], cents)
                state["orbSpawn"], state["_frames"] = portal_motion(state["_seed"], state["id"])
                state["_winnerIdx"] = portal_owner(state["layout"], state["_frames"][-1][1:3])
                state["launchDelayMs"] = 2500
            else:
                state["_winnerIdx"] = pot_winner(state["_seed"], state["id"], cents)
        if state["phase"] == "countdown" and now >= state["countdownEndsAt"]:
            state["phase"] = "live"
        if state["phase"] == "live" and now >= state["liveStartedAt"] + round(state["liveSec"] * 1000):
            bank = sum(player["cents"] for player in players)
            paid = bank * 99 // 100
            winner = players[state["_winnerIdx"]]
            await self.credit(connection, winner["uid"], paid)
            state.update({"phase": "finish", "serverSeed": state["_seed"], "_paidCents": paid, "finishedAt": (state["liveStartedAt"] + round(state["liveSec"] * 1000)) / 1000, "resultAt": state["liveStartedAt"] + round(state["liveSec"] * 1000) + 1000, "nextRoundAt": state["liveStartedAt"] + round(state["liveSec"] * 1000) + 7000})
            for player in players:
                payout = paid if player["uid"] == winner["uid"] else 0
                detail = {"ok": True, "roundId": state["id"], "roomId": room, "seq": state["seq"], "userId": player["uid"], "username": player["name"], "bet": player["cents"] / 100, "winAmount": payout / 100, "result": "win" if payout else "lose", "multiplier": payout / player["cents"], "pot": bank / 100, "winner": winner["name"], "winnerId": winner["uid"], "seedHash": state["commitHash"], "serverSeed": state["_seed"]}
                await connection.execute("INSERT INTO webapp_rounds(public_id,game,user_id,username,bet_cents,payout_cents,request_id,request_digest,response,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (state["id"] + "_" + str(player["uid"]), game, player["uid"], player["name"], player["cents"], payout, "pot_settle_" + state["id"], state["commitHash"], serialize(detail), self.clock().isoformat()))
        if state["phase"] == "finish" and now >= state["resultAt"]:
            state["phase"] = "result"
        if serialize(state) != row[0]:
            await self.save_pot(connection, state)
        if state["phase"] == "result" and now >= state["nextRoundAt"]:
            return await self.create_pot(connection, game, room, state["seq"] + 1)
        return state

    def pot_projection(self, state, user_id):
        result = {key: value for key, value in state.items() if not key.startswith("_")}
        cents = [player["cents"] for player in state["_players"]]
        bank = sum(cents)
        balls = pot_balls(cents)
        finished = state["phase"] in {"finish", "result"}
        visible_winner = state.get("_winnerIdx") if state["phase"] in {"live", "finish", "result"} else None
        paid = state.get("_paidCents", bank * 99 // 100)
        players = []
        for index, player in enumerate(state["_players"]):
            won = finished and index == visible_winner
            players.append({"uid": player["uid"], "id": player["uid"], "name": player["name"], "avatar": "/api/avatar/" + str(player["uid"]), "color": player["color"], "contribution": player["cents"] / 100, "share": player["cents"] / bank, "balls": balls[index], "isMe": player["uid"] == user_id, "isWinner": won, "prize": paid / 100 if won else 0, "multiplier": paid / player["cents"] if won else 0})
        result.update({"players": players, "playersCount": len(players), "totalPot": bank / 100, "ballsTotal": sum(balls), "winnerIdx": visible_winner})
        result["winner"] = dict(players[visible_winner]) if finished else None
        if state["game"] == "portal":
            result["layout"] = state.get("layout") or portal_layout(state["_seed"], state["id"], cents)
        return result

    def pot_summary(self, state, user_id):
        public = self.pot_projection(state, user_id)
        winner = public["winner"]
        summary = {"id": state["id"], "seq": state["seq"], "roomId": state["roomId"], "totalPot": public["totalPot"], "playersCount": len(public["players"]), "winnerName": winner["name"], "winnerId": winner["uid"], "winnerAvatar": winner["avatar"], "winnerColor": winner["color"], "prize": winner["prize"], "multiplier": winner["multiplier"], "finishedAt": state["finishedAt"]}
        own = next((player for player in public["players"] if player["isMe"]), None)
        if own:
            summary.update({"myBet": own["contribution"], "myWon": own["isWinner"], "myPrize": own["prize"]})
        return summary

    async def pot_response(self, connection, state, user_id):
        room_states = []
        for room in (1, 2):
            room_states.append(await self.advance_pot(connection, state["game"], room))
        current = room_states[state["roomId"] - 1]
        public = self.pot_projection(current, user_id)
        own = next((player for player in public["players"] if player["isMe"]), None)
        async with connection.execute("SELECT data FROM webapp_pot_rounds WHERE game = ? AND phase IN ('finish','result') ORDER BY rowid DESC LIMIT 30", (state["game"],)) as cursor:
            recent = [self.pot_summary(json.loads(row[0]), user_id) for row in await cursor.fetchall()]
        live = [self.pot_projection(value, user_id) for value in room_states if value["phase"] in {"live", "finish", "result"}]
        return {"ok": True, "serverTime": int(pot_now() * 1000), "config": {**POT_CONFIG, "raceSec": 30}, "room": {"id": current["roomId"], "name": current["roomName"]}, "rooms": [{"id": value["roomId"], "name": value["roomName"], "phase": value["phase"], "players": len(value["_players"]), "pot": sum(player["cents"] for player in value["_players"]) / 100, "live": value["phase"] in {"live", "finish"}} for value in room_states], "round": public, "me": {"inGame": own is not None, "contribution": own["contribution"] if own else 0}, "live": live, "liveRound": next((value for value in live if any(player["isMe"] for player in value["players"])), None), "recent": recent, "balance": await self.balance(connection, user_id)}

    async def handle_pot_action(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            game, action = request.path.split("/")[2:4]
            room = integer(payload.get("room", 1), 1, 2)
            key, signature = self.request_identity(request, payload)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    replay = await self.load_receipt(connection, user.id, key, signature)
                    state = await self.advance_pot(connection, game, room)
                    if not replay:
                        if payload.get("roundId") != state["id"]:
                            raise GameError("Раунд изменился. Обновите игру.", 409)
                        players = state["_players"]
                        own = next((player for player in players if player["uid"] == user.id), None)
                        if action == "cancel":
                            if state["phase"] != "waiting" or own is None:
                                raise GameError("Ставку уже нельзя отменить.", 409)
                            await self.credit(connection, user.id, own["cents"])
                            players.remove(own)
                        else:
                            if state["phase"] not in {"waiting", "betting"}:
                                raise GameError("Приём ставок закрыт.", 409)
                            if action == "join" and own:
                                raise GameError("Вы уже участвуете в раунде.", 409)
                            if action == "bet" and own is None:
                                raise GameError("Сначала войдите в раунд.", 409)
                            if own is None and len(players) >= 12:
                                raise GameError("В комнате уже 12 игроков.", 409)
                            cents = money_cents(payload.get("bet"))
                            if (own["cents"] if own else 0) + cents > 100000000:
                                raise GameError("Превышен предел ставки за раунд.")
                            await self.debit(connection, user.id, cents)
                            if own:
                                own["cents"] += cents
                            else:
                                players.append({"uid": user.id, "name": " ".join(part for part in (user.first_name, user.last_name) if part), "color": POT_COLORS[len(players)], "cents": cents})
                            if len(players) == 1:
                                state["_waitingUntil"] = int(pot_now() * 1000) + 600000
                            if len(players) >= 2 and state["phase"] == "waiting":
                                state.update({"phase": "betting", "bettingEndsAt": int(pot_now() * 1000) + 15000})
                        await self.save_pot(connection, state)
                    response = await self.pot_response(connection, state, user.id)
                    if not replay:
                        await self.save_receipt(connection, user.id, key, signature, response)
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)

    async def handle_pot_read(self, request):
        try:
            user = self.validate_user(request)
            game, action = request.path.split("/")[2:4]
            room = integer(request.query.get("room", "1"), 0 if action == "history" else 1, 2)
            offset = integer(request.query.get("offset", "0"), 0, 1000000)
            scope = request.query.get("scope", "all")
            query = request.query.get("q", "").strip()
            if scope not in {"all", "mine"} or len(query) > 100:
                raise GameError("Некорректный фильтр истории.")
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    current = {number: await self.advance_pot(connection, game, number) for number in (1, 2)}
                    state = current[room or 1]
                    if action == "state":
                        response = await self.pot_response(connection, state, user.id)
                    elif action in {"round", "frames"}:
                        identifier = request.query.get("id", "")
                        if not re.fullmatch(POT_GAMES[game] + r"[A-F0-9]{24}", identifier):
                            raise GameError("Некорректный UID раунда.")
                        async with connection.execute("SELECT data FROM webapp_pot_rounds WHERE id = ? AND game = ?", (identifier, game)) as cursor:
                            row = await cursor.fetchone()
                        if row is None:
                            raise GameError("Раунд не найден.", 404)
                        detail = json.loads(row[0])
                        if action == "frames":
                            if detail["phase"] not in {"live", "finish", "result"}:
                                raise GameError("Раунд ещё не начался.", 409)
                            response = {"ok": True, "roundId": identifier, "frames": detail["_frames"]}
                        else:
                            if detail["phase"] not in {"finish", "result"}:
                                raise GameError("Раунд ещё не завершён.", 409)
                            response = {"ok": True, **self.pot_projection(detail, user.id), "status": "finished", "feePercent": 1, "commission": (sum(player["cents"] for player in detail["_players"]) - detail["_paidCents"]) / 100, "fairness": {"commitHash": detail["commitHash"], "serverSeed": detail["_seed"]}}
                            if game == "portal":
                                response["frames"] = detail["_frames"]
                    elif action == "howto":
                        async with connection.execute("SELECT data FROM webapp_pot_rounds WHERE game = ? AND phase IN ('finish','result') ORDER BY rowid DESC LIMIT 1", (game,)) as cursor:
                            record = await cursor.fetchone()
                        if record is None:
                            response = {"ok": False, "error": "Нет завершённого раунда для примера."}
                        else:
                            example = json.loads(record[0])
                            response = {"ok": True, **self.pot_projection(example, user.id), "roundId": example["id"], "feePercent": 1}
                            response.update({"prize": response["winner"]["prize"], "multiplier": response["winner"]["multiplier"], "courseSeed": hashlib.sha256((example["commitHash"] + ":" + example["id"] + ":course").encode()).hexdigest()})
                            if game == "portal":
                                response.update({"frames": example["_frames"], "layouts": [portal_layout(example["_seed"], example["id"], [player["cents"] for player in example["_players"][:count]]) for count in range(1, len(example["_players"]) + 1)]})
                    else:
                        conditions = ["game = ?", "phase IN ('finish','result')"]
                        values = [game]
                        if room:
                            conditions.append("room = ?")
                            values.append(room)
                        if scope == "mine":
                            conditions.append("EXISTS (SELECT 1 FROM json_each(json_extract(data,'$._players')) WHERE json_extract(value,'$.uid') = ?)")
                            values.append(user.id)
                        if query:
                            conditions.append("(id = ? OR CAST(seq AS TEXT) = ? OR date(json_extract(data,'$.finishedAt'),'unixepoch') = ?)")
                            values.extend([query, query, query])
                        async with connection.execute("SELECT data FROM webapp_pot_rounds WHERE " + " AND ".join(conditions) + " ORDER BY rowid DESC LIMIT 20 OFFSET ?", values + [offset]) as cursor:
                            records = [json.loads(row[0]) for row in await cursor.fetchall()]
                        response = {"ok": True, "rows": [self.pot_summary(value, user.id) for value in records]}
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)
