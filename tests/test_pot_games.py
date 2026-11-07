import asyncio
import hashlib
import json
import secrets
import subprocess
import unittest
from unittest.mock import patch

from complete_games import CompleteGamesBackend
from games_backend import serialize
from pot_rules import POT_GAMES, pot_winner, portal_layout, portal_motion, portal_owner, pot_balls
import test_games_backend as legacy_tests
import test_pvp_games as pvp_tests


class PotGamesTests(unittest.IsolatedAsyncioTestCase):
    backend_type = CompleteGamesBackend
    asyncTearDown = legacy_tests.GamesBackendTests.asyncTearDown
    headers = legacy_tests.GamesBackendTests.headers
    balance = pvp_tests.PvpGamesTests.balance

    async def asyncSetUp(self):
        await legacy_tests.GamesBackendTests.asyncSetUp(self)
        self.backend.live_task.cancel()
        await asyncio.gather(self.backend.live_task, return_exceptions=True)

    async def state(self, game, room=1, user_id=42):
        response = await self.client.get(f"/api/{game}/state?room={room}", headers=self.headers(user_id))
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def action(self, game, action, state, bet=10, user_id=42, key=None):
        response = await self.client.post(f"/api/{game}/{action}", json={"room": state["room"]["id"], "roundId": state["round"]["id"], "bet": bet}, headers=self.headers(user_id, key))
        return response.status, await response.json()

    async def read(self, game, action, query="", user_id=42):
        response = await self.client.get(f"/api/{game}/{action}?{query}", headers=self.headers(user_id))
        return response.status, await response.json()

    async def finish(self, game, state):
        milliseconds = state["round"]["bettingEndsAt"]
        with patch("pot_games.pot_now", return_value=milliseconds / 1000 + 3.001):
            live = await self.state(game)
        self.assertEqual(live["round"]["phase"], "live")
        self.assertNotIn("serverSeed", live["round"])
        self.assertIsNotNone(live["round"]["winnerIdx"])
        self.assertIsInstance(live["live"], list)
        finish = (live["round"]["liveStartedAt"] + round(live["round"]["liveSec"] * 1000)) / 1000 + 0.001
        with patch("pot_games.pot_now", return_value=finish):
            result = await self.state(game)
        self.assertEqual(result["round"]["phase"], "finish")
        return result, finish

    async def test_all_four_games_99_percent_bank_and_persistent_history(self):
        for game in POT_GAMES:
            state = await self.state(game)
            commit = state["round"]["commitHash"]
            self.assertEqual(state["round"]["players"], [])
            self.assertNotIn("serverSeed", state["round"])
            status, result = await self.action(game, "join", state)
            self.assertEqual(status, 200, result)
            status, result = await self.action(game, "join", result, bet=20, user_id=99)
            self.assertEqual(status, 200, result)
            self.assertEqual(result["round"]["phase"], "betting")
            self.assertEqual(result["round"]["commitHash"], commit)
            finished, timestamp = await self.finish(game, result)
            final = finished["round"]
            self.assertEqual(hashlib.sha256(final["serverSeed"].encode()).hexdigest(), commit)
            self.assertEqual(final["winner"]["prize"], 29.7)
            self.assertAlmostEqual(final["players"][0]["share"], 1 / 3)
            if game != "portal":
                self.assertEqual(final["winnerIdx"], pot_winner(final["serverSeed"], final["id"], [1000, 2000]))
            before = await self.balance() + await self.balance(99)
            with patch("pot_games.pot_now", return_value=timestamp):
                await self.backend.initialize_pots()
                await self.backend.initialize_pots()
                details = (await self.read(game, "round", "id=" + final["id"]))[1]
                self.assertEqual(details["status"], "finished")
                self.assertEqual(details["commission"], 0.3)
                rows = (await self.read(game, "history", "scope=mine&room=0"))[1]["rows"]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["myBet"], 10)
                self.assertEqual((await self.read(game, "howto"))[0], 200)
            self.assertAlmostEqual(await self.balance() + await self.balance(99), before)
            self.assertAlmostEqual(before, 2000 - (list(POT_GAMES).index(game) + 1) * 0.3)
        response = await self.client.get("/api/leaders?category=turnover", headers=self.headers())
        self.assertEqual((await response.json())["myScore"], 40)

    async def test_join_add_cancel_and_replays_are_atomic(self):
        state = await self.state("bomb")
        key = secrets.token_hex(16)
        results = await asyncio.gather(*(self.action("bomb", "join", state, key=key) for _ in range(8)))
        self.assertTrue(all(status == 200 for status, _ in results))
        self.assertEqual(await self.balance(), 990)
        state = results[0][1]
        self.assertEqual(len(state["round"]["players"]), 1)
        self.assertEqual((await self.action("bomb", "join", state))[0], 409)
        key = secrets.token_hex(16)
        results = await asyncio.gather(*(self.action("bomb", "bet", state, bet=5, key=key) for _ in range(8)))
        self.assertEqual(await self.balance(), 985)
        self.assertEqual(results[0][1]["me"]["contribution"], 15)
        self.assertEqual((await self.action("bomb", "cancel", state, user_id=99))[0], 409)
        key = secrets.token_hex(16)
        results = await asyncio.gather(*(self.action("bomb", "cancel", state, key=key) for _ in range(8)))
        self.assertTrue(all(status == 200 for status, _ in results))
        self.assertEqual(await self.balance(), 1000)
        self.assertEqual(results[0][1]["round"]["players"], [])
        self.assertEqual((await self.action("bomb", "bet", state))[0], 409)

    async def test_rooms_are_independent_and_stale_round_never_debits(self):
        first, second = await self.state("sumo", 1), await self.state("sumo", 2)
        self.assertNotEqual(first["round"]["id"], second["round"]["id"])
        await self.action("sumo", "join", first)
        await self.action("sumo", "join", second, bet=20)
        self.assertEqual(await self.balance(), 970)
        with patch("pot_games.pot_now", return_value=10 ** 12):
            current = await self.state("sumo")
            self.assertNotEqual(current["round"]["id"], first["round"]["id"])
            self.assertEqual((await self.action("sumo", "join", first))[0], 409)
            await self.backend.initialize_pots()
        self.assertEqual(await self.balance(), 1000)

    async def test_betting_deadline_cancel_and_invalid_financial_inputs(self):
        state = await self.state("race")
        for bet in (0, -1, "NaN", 1000001, 1001, True):
            self.assertEqual((await self.action("race", "join", state, bet=bet))[0], 400)
        result = (await self.action("race", "join", state))[1]
        result = (await self.action("race", "join", result, user_id=99))[1]
        self.assertEqual((await self.action("race", "cancel", result))[0], 409)
        with patch("pot_games.pot_now", return_value=result["round"]["bettingEndsAt"] / 1000):
            current = await self.state("race")
            self.assertEqual(current["round"]["phase"], "countdown")
            self.assertIsNone(current["round"]["winnerIdx"])
            self.assertEqual((await self.action("race", "bet", result))[0], 409)
        self.assertEqual(await self.balance(), 990)
        response = await self.client.post("/api/race/join", json={"room": 1, "roundId": state["round"]["id"], "uid": 99, "bet": 10}, headers=self.headers())
        self.assertEqual(response.status, 403)

    async def test_portal_frames_hidden_until_live_and_match_final_territory(self):
        state = await self.state("portal")
        identifier = state["round"]["id"]
        self.assertEqual((await self.read("portal", "frames", "id=" + identifier))[0], 409)
        state = (await self.action("portal", "join", state))[1]
        state = (await self.action("portal", "join", state, user_id=99))[1]
        finished, timestamp = await self.finish("portal", state)
        with patch("pot_games.pot_now", return_value=timestamp):
            frames = (await self.read("portal", "frames", "id=" + identifier))[1]["frames"]
            detail = (await self.read("portal", "round", "id=" + identifier))[1]
        self.assertEqual(len(frames), 571)
        self.assertEqual(frames[-1][0], 9500)
        self.assertEqual(portal_owner(detail["layout"], frames[-1][1:3]), detail["winnerIdx"])
        spawn, expected = portal_motion(detail["serverSeed"], identifier)
        self.assertEqual(frames, expected)
        self.assertEqual(detail["orbSpawn"], spawn)
        self.assertTrue(all(0 <= frame[1] <= 1000 and 0 <= frame[2] <= 1000 for frame in frames))

    async def test_settlement_database_failure_rolls_back_then_recovers_once(self):
        state = await self.state("bomb")
        state = (await self.action("bomb", "join", state))[1]
        state = (await self.action("bomb", "join", state, user_id=99))[1]
        timestamp = state["round"]["bettingEndsAt"] / 1000 + 3 + 12.001
        async with self.runtime._db_lock:
            connection = self.runtime.db()
            await connection.execute("CREATE TRIGGER fail_pot_insert BEFORE INSERT ON webapp_rounds WHEN NEW.game = 'bomb' BEGIN SELECT RAISE(ABORT,'write failed'); END")
            await connection.commit()
        with patch("pot_games.pot_now", return_value=timestamp), self.assertLogs("aiohttp.server", level="ERROR"):
            response = await self.client.get("/api/bomb/state", headers=self.headers())
            self.assertEqual(response.status, 500)
        self.assertEqual(await self.balance(), 990)
        self.assertEqual(await self.balance(99), 990)
        async with self.runtime._db_lock:
            await self.runtime.db().execute("DROP TRIGGER fail_pot_insert")
            await self.runtime.db().commit()
        with patch("pot_games.pot_now", return_value=timestamp):
            await self.state("bomb")
            await self.state("bomb")
        self.assertAlmostEqual(await self.balance() + await self.balance(99), 1999.8)

    async def test_real_javascript_weighted_winner_and_portal_geometry(self):
        cases = []
        for index, cents in enumerate(([1000, 2000], [10, 100000000], [10] * 12, [100, 500, 300, 200])):
            seed = hashlib.sha256(str(index).encode()).hexdigest()
            identifier = "PT" + str(index).zfill(24)
            cases.append({"seed": seed, "id": identifier, "cents": cents, "winner": pot_winner(seed, identifier, cents), "layout": portal_layout(seed, identifier, cents), "balls": pot_balls(cents)})
        result = await asyncio.to_thread(subprocess.run, ["node", "tests/check_pot_rules.js"], input=json.dumps(cases), capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    async def test_capacity_and_total_contribution_limits(self):
        state = await self.state("sumo")
        await self.runtime.add_balance(42, 1000000)
        status, state = await self.action("sumo", "join", state, bet=1000000)
        self.assertEqual(status, 200, state)
        balance = await self.balance()
        self.assertEqual((await self.action("sumo", "bet", state, bet=0.1))[0], 400)
        self.assertEqual(await self.balance(), balance)
        for user_id in range(100, 111):
            await self.runtime.add_balance(user_id, 10)
            status, state = await self.action("sumo", "join", state, bet=0.1, user_id=user_id)
            self.assertEqual(status, 200, state)
        self.assertEqual(len(state["round"]["players"]), 12)
        await self.runtime.add_balance(111, 10)
        self.assertEqual((await self.action("sumo", "join", state, bet=0.1, user_id=111))[0], 409)
        self.assertEqual(await self.balance(111), 10)
