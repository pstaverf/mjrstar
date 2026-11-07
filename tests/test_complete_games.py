import asyncio
import hashlib
import json
import secrets
import time
from unittest.mock import patch

from complete_games import CompleteGamesBackend, ESCAPE_LEVELS
from game_rules import card_at, baccarat_deal, deck_for, hand_total, unit
import test_games_backend as legacy_tests


class CompleteGamesTests(legacy_tests.GamesBackendTests):
    backend_type = CompleteGamesBackend

    async def action(self, game, action, payload, key=None):
        response = await self.client.post(f"/api/{game}/{action}", json=payload, headers=key if isinstance(key, dict) else self.headers(request_id=key))
        return response.status, await response.json() if response.content_type == "application/json" else {"error": await response.text()}

    async def state(self, game):
        response = await self.client.get(f"/api/{game}/state", headers=self.headers())
        self.assertEqual(response.status, 200)
        return await response.json()

    async def set_commit(self, game, predicate):
        commit = (await self.state(game))["commit"]
        while True:
            seed = secrets.token_hex(32)
            if predicate(seed, commit["roundId"]):
                break
        async with self.runtime._db_lock:
            await self.runtime.db().execute("UPDATE webapp_commits SET seed = ? WHERE user_id = 42 AND game = ?", (seed, game))
            await self.runtime.db().commit()
        return seed, commit["roundId"]

    async def test_card_chain_version_and_cashout(self):
        seed, round_id = await self.set_commit("hilo", lambda seed, rid: card_at(seed, rid, 0)["rank"] == card_at(seed, rid, 1)["rank"])
        status, state = await self.action("hilo", "start", {"bet": 10})
        self.assertEqual(status, 200, state)
        self.assertNotIn("serverSeed", state)
        self.assertEqual(state["seedHash"], hashlib.sha256(seed.encode()).hexdigest())
        payload = {"roundId": round_id, "version": state["version"], "choice": "same"}
        key = secrets.token_hex(16)
        results = await asyncio.gather(*(self.action("hilo", "guess", payload, key) for _ in range(10)))
        self.assertTrue(all(status == 200 for status, _ in results), results)
        state = results[0][1]
        self.assertEqual(len(state["cards"]), 2)
        self.assertEqual((await self.action("hilo", "guess", payload))[0], 409)
        response = await self.state("hilo")
        self.assertEqual(response["version"], state["version"])
        status, finished = await self.action("hilo", "cashout", {"roundId": round_id, "version": state["version"]})
        self.assertEqual(status, 200, finished)
        self.assertEqual(finished["serverSeed"], seed)
        self.assertEqual(finished["winAmount"], 117)
        self.assertEqual(finished["balance"], 1107)
        self.assertEqual((await self.action("hilo", "cashout", {"roundId": round_id, "version": state["version"]}))[0], 409)

    async def test_redblack_loss_and_invalid_choice(self):
        seed, round_id = await self.set_commit("redblack", lambda seed, rid: card_at(seed, rid, 1)["suit"] in {"S", "C"})
        status, state = await self.action("redblack", "start", {"bet": 10})
        self.assertEqual(status, 200, state)
        payload = {"roundId": round_id, "version": state["version"], "choiceType": "color", "choiceValue": []}
        self.assertEqual((await self.action("redblack", "guess", payload))[0], 400)
        payload["choiceValue"] = "red"
        status, result = await self.action("redblack", "guess", payload)
        self.assertEqual(status, 200, result)
        self.assertFalse(result["active"])
        self.assertEqual(result["winAmount"], 0)
        self.assertEqual(result["balance"], 990)
        self.assertEqual(result["serverSeed"], seed)

    async def test_blackjack_natural_and_hidden_dealer(self):
        seed, round_id = await self.set_commit("blackjack", lambda seed, rid: hand_total(deck_for(seed, rid)[::2][:2]) == 21 and hand_total(deck_for(seed, rid)[1:4:2]) != 21)
        status, natural = await self.action("blackjack", "start", {"bet": 10})
        self.assertEqual(status, 200, natural)
        self.assertFalse(natural["active"])
        self.assertEqual(natural["winAmount"], 25)
        self.assertEqual(natural["balance"], 1015)
        seed, round_id = await self.set_commit("blackjack", lambda seed, rid: hand_total(deck_for(seed, rid)[::2][:2]) < 21 and hand_total(deck_for(seed, rid)[1:4:2]) < 21)
        status, state = await self.action("blackjack", "start", {"bet": 10})
        self.assertEqual(status, 200, state)
        self.assertEqual(len(state["dealerCards"]), 1)
        self.assertNotIn("_dealer", state)
        self.assertNotIn("_deck", state)
        status, finished = await self.action("blackjack", "double", {"roundId": round_id, "version": state["version"]})
        self.assertEqual(status, 200, finished)
        self.assertFalse(finished["active"])
        self.assertEqual(finished["betAmount"], 20)
        self.assertEqual(finished["balance"], 995 + finished["winAmount"])

    async def test_blackjack_split(self):
        seed, round_id = await self.set_commit("blackjack", lambda seed, rid: deck_for(seed, rid)[0]["rank"] == deck_for(seed, rid)[2]["rank"] and deck_for(seed, rid)[0]["rank"] != "A" and hand_total(deck_for(seed, rid)[1:4:2]) < 21)
        status, state = await self.action("blackjack", "start", {"bet": 10})
        self.assertEqual(status, 200, state)
        status, state = await self.action("blackjack", "split", {"roundId": round_id, "version": state["version"]})
        self.assertEqual(status, 200, state)
        self.assertEqual(len(state["hands"]), 2)
        self.assertEqual(state["balance"], 980)
        while state["active"]:
            status, state = await self.action("blackjack", "stand", {"roundId": round_id, "version": state["version"]})
            self.assertEqual(status, 200, state)
        self.assertEqual(state["balance"], 980 + state["winAmount"])

    async def test_coinflip_timing_resume_and_payout(self):
        seed, round_id = await self.set_commit("coinflip", lambda seed, rid: unit(seed, rid + ":coin:1") < 0.5)
        status, state = await self.action("coinflip", "start", {"bet": 10, "pick": "heads"})
        self.assertEqual(status, 200, state)
        self.assertTrue(state["round"]["flipping"])
        payload = {"roundId": round_id, "version": state["version"]}
        self.assertEqual((await self.action("coinflip", "cashout", payload))[0], 409)
        resumed = await self.state("coinflip")
        self.assertEqual(resumed["round"]["steps"], state["round"]["steps"])
        with patch("time.time", return_value=time.time() + 4):
            status, finished = await self.action("coinflip", "cashout", payload)
        self.assertEqual(status, 200, finished)
        self.assertEqual(finished["round"]["payout"], 19.5)
        self.assertEqual(finished["balance"], 1009.5)
        self.assertEqual(finished["round"]["serverSeed"], seed)

    async def test_claw_commit_and_server_coefficients(self):
        state = await self.state("claw")
        key = secrets.token_hex(16)
        payload = {"toy": "dog", "bet": 10, "chance": 100, "multiplier": 999999}
        status, result = await self.action("claw", "play", payload, key)
        self.assertEqual(status, 200, result)
        self.assertEqual(result["seedHash"], state["commit"]["seedHash"])
        self.assertEqual(result["multiplier"], 10)
        self.assertEqual(result["chance"], 9.6)
        self.assertEqual(result["balance"], 990 + result["winAmount"])
        self.assertEqual((await self.action("claw", "play", payload, key))[1]["roundId"], result["roundId"])
        self.assertEqual((await self.state("claw"))["recent"][0]["roundId"], result["roundId"])

    async def test_baccarat_standard_deal_and_history(self):
        state = await self.state("baccarat")
        status, result = await self.action("baccarat", "play", {"bets": {"player": 10, "pp": 1}, "mults": {"player": 1000}})
        self.assertEqual(status, 200, result)
        expected = baccarat_deal(result["serverSeed"], result["roundId"])
        self.assertEqual(result["sequence"], expected["sequence"])
        self.assertEqual(result["seedHash"], state["commit"]["seedHash"])
        self.assertEqual(result["balance"], 989 + result["winAmount"])
        self.assertEqual(result["spots"]["player"]["multiplier"], 2)
        status, rejected = await self.action("baccarat", "play", {"bets": {"player": 1, "banker": 1}})
        self.assertEqual(status, 400, rejected)
        response = await self.client.get("/api/baccarat/history?scope=mine", headers=self.headers())
        rows = (await response.json())["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows[0]["meta"])["roundId"], result["roundId"])

    async def test_wheel_valid_catalog_and_duplicate_positions(self):
        status, result = await self.action("wheel", "spin", {"items": [{"key": "n:0", "amount": 1}, {"key": "n:0", "amount": 1}, {"key": "red", "amount": 10}]})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["totalBet"], 12)
        self.assertEqual(len(result["bets"]), 2)
        self.assertEqual(result["bets"][0]["amount"], 2)
        expected = (72 if result["number"] == 0 else 0) + (20 if result["color"] == "red" else 0)
        self.assertEqual(result["totalWin"], expected)
        self.assertEqual(result["balance"], 988 + expected)
        self.assertEqual((await self.action("wheel", "spin", {"items": [{"key": "red", "amount": 1, "mult": 100000}]}))[0], 200)
        self.assertEqual((await self.action("wheel", "spin", {"items": [{"key": "invalid", "amount": 1}]}))[0], 400)

    async def test_escape_committed_formula_and_recovery(self):
        state = await self.state("escape")
        status, result = await self.action("escape", "start", {"bet": 10, "level": "mid"})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["seedHash"], state["commit"]["seedHash"])
        expected_win = unit(result["serverSeed"], result["roundId"] + ":mid:win") < 0.5
        self.assertEqual(result["win"], expected_win)
        self.assertEqual(result["balance"], 990 + result["winAmount"])
        self.assertEqual((await self.action("escape", "start", {"bet": 10, "level": "mid"}))[0], 409)
        resumed = await self.state("escape")
        self.assertTrue(resumed["active"])
        self.assertEqual(resumed["round"]["pathSeed"], result["pathSeed"])
        self.assertEqual(len(resumed["config"]["levels"]), len(ESCAPE_LEVELS))

    async def test_new_games_transaction_rollback(self):
        async with self.runtime._db_lock:
            await self.runtime.db().execute("CREATE TRIGGER reject_extended BEFORE INSERT ON webapp_rounds BEGIN SELECT RAISE(ABORT,'failure'); END")
            await self.runtime.db().commit()
        before = (await self.state("claw"))["commit"]
        with self.assertLogs("aiohttp.server", level="ERROR"):
            status, result = await self.action("claw", "play", {"toy": "duck", "bet": 10})
        self.assertEqual(status, 500)
        after = await self.state("claw")
        self.assertEqual(after["balance"], 1000)
        self.assertEqual(after["commit"], before)

    async def change_live(self, game, changes):
        async with self.runtime._db_lock:
            connection = self.runtime.db()
            async with connection.execute("SELECT id,data FROM webapp_live_rounds WHERE game = ? AND finished = 0", (game,)) as cursor:
                row = await cursor.fetchone()
            state = json.loads(row[1])
            state.update(changes)
            await connection.execute("UPDATE webapp_live_rounds SET data = ? WHERE id = ?", (json.dumps(state), row[0]))
            await connection.commit()
        return state

    async def test_crash_auto_settles_once_and_hides_seed(self):
        state = await self.state("crash")
        self.assertNotIn("_seed", state)
        self.assertNotIn("_crashPoint", state)
        self.assertNotIn("serverSeed", state)
        key = secrets.token_hex(16)
        payload = {"roundId": state["roundId"], "bet": 10, "autoCashout": 2}
        status, accepted = await self.action("crash", "bet", payload, key)
        self.assertEqual(status, 200, accepted)
        self.assertEqual(accepted["balance"], 990)
        self.assertEqual((await self.action("crash", "bet", payload, key))[1]["balance"], 990)
        await self.change_live("crash", {"_crashPoint": 3, "waitingStartedAt": int(time.time() * 1000) - 10000 - 12000})
        settled = await self.state("crash")
        self.assertEqual(settled["status"], "crashed")
        self.assertEqual(settled["myBet"]["winAmount"], 20)
        self.assertEqual(settled["balance"], 1010)
        self.assertEqual((await self.state("crash"))["balance"], 1010)
        response = await self.client.get("/api/crash/round?id=" + state["roundId"], headers=self.headers())
        self.assertEqual(response.status, 200)
        self.assertIn("serverSeed", await response.json())

    async def test_roulette_single_settlement_and_no_duplicate_color(self):
        state = await self.state("roulette")
        status, accepted = await self.action("roulette", "bet", {"roundId": state["roundId"], "items": [{"color": "red", "bet": 10}]})
        self.assertEqual(status, 200, accepted)
        self.assertEqual(accepted["balance"], 990)
        self.assertEqual((await self.action("roulette", "bet", {"roundId": state["roundId"], "items": [{"color": "red", "bet": 10}]}))[0], 400)
        await self.change_live("roulette", {"_outcomeColor": "red", "_outcomeMult": 1.8, "waitingStartedAt": int(time.time() * 1000) - 22000})
        settled = await self.state("roulette")
        self.assertEqual(settled["status"], "resolved")
        self.assertEqual(settled["balance"], 1008)
        self.assertEqual(settled["myBets"][0]["winAmount"], 18)
        self.assertEqual((await self.state("roulette"))["balance"], 1008)

    async def test_crash_persistent_queue_moves_without_second_debit(self):
        state = await self.state("crash")
        await self.change_live("crash", {"status": "flying", "flyingStartedAt": int(time.time() * 1000), "_crashPoint": 2})
        status, queued = await self.action("crash", "bet", {"roundId": state["roundId"], "bet": 10})
        self.assertEqual(status, 200, queued)
        self.assertEqual(queued["balance"], 990)
        self.assertEqual(queued["myQueued"]["bet"], 10)
        self.assertIsNone(queued["myBet"])
        self.assertEqual((await self.action("crash", "bet", {"roundId": state["roundId"], "bet": 10}))[0], 409)
        await self.change_live("crash", {"status": "crashed", "crashPoint": 2, "_nextAt": 0})
        started = await self.state("crash")
        self.assertNotEqual(started["roundId"], state["roundId"])
        self.assertEqual(started["myBet"]["bet"], 10)
        self.assertIsNone(started["myQueued"])
        self.assertEqual(started["balance"], 990)

    async def test_crash_manual_cashout_is_atomic(self):
        state = await self.state("crash")
        status, accepted = await self.action("crash", "bet", {"roundId": state["roundId"], "bet": 10})
        self.assertEqual(status, 200, accepted)
        await self.change_live("crash", {"status": "flying", "flyingStartedAt": int(time.time() * 1000) - 1000, "_crashPoint": 10})
        key = secrets.token_hex(16)
        results = await asyncio.gather(*(self.action("crash", "cashout", {"roundId": state["roundId"]}, key) for _ in range(8)))
        self.assertTrue(all(status == 200 for status, _ in results), results)
        own = results[0][1]["myBet"]
        self.assertTrue(own["cashedOut"])
        current = await self.state("crash")
        self.assertEqual(current["balance"], 990 + own["winAmount"])
        self.assertEqual((await self.action("crash", "cashout", {"roundId": state["roundId"]}))[0], 409)

    async def test_api_guard_rejects_forged_requests_without_debit(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        application = web.Application(middlewares=[self.runtime.webapp_api_guard])
        application.router.add_post("/api/auth/telegram", self.runtime.webapp_auth)
        application.router.add_get("/api/state", self.runtime.webapp_state)
        application.router.add_post("/api/claw/play", self.backend.handle_extended_action)
        application.router.add_get("/api/games/off", self.backend.handle_switches)
        application.router.add_route("*", "/api/{path:.*}", self.runtime.webapp_api_unavailable)
        async def app_page(request):
            return web.Response(text="app")

        application.router.add_get("/app", app_page)
        async with TestClient(TestServer(application)) as client:
            for headers in ({}, {"X-Forwarded-For": "78.154.103.13"}, {"X-Telegram-Init-Data": "user=42&hash=forged"}):
                response = await client.post("/api/claw/play", json={"uid": 42, "toy": "pepe", "bet": 10}, headers=headers)
                self.assertEqual(response.status, 404)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            response = await client.get("/api/state", headers=self.headers())
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["balance"], 1000)
            response = await client.post("/api/auth/telegram", json={"initData": self.headers()["X-Telegram-Init-Data"]})
            self.assertEqual(response.status, 200)
            response = await client.post("/api/auth/telegram", json={"initData": "forged"})
            self.assertEqual(response.status, 404)
            response = await client.get("/api/state?uid=99", headers=self.headers())
            self.assertEqual(response.status, 404)
            response = await client.get("/app")
            self.assertEqual(response.status, 200)
            response = await client.get("/api/games/off", headers=self.headers())
            off = (await response.json())["off"]
            for game in ("dice", "slots", "bowl", "darts", "basket", "foot", "pvp_dice", "pvp_bowling", "pvp_darts", "pvp_basketball", "pvp_football", "pvp_slots"):
                self.assertIn(game, off)
            for path in ("dice/play", "pvp/dice/create", "not-implemented/play"):
                response = await client.post("/api/" + path, json={"bet": 10}, headers=self.headers())
                self.assertEqual(response.status, 503, path)
            self.assertEqual((await self.state("claw"))["balance"], 1000)
