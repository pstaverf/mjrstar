import bundle_test_support  # Register backend modules from server.py.
import asyncio
import hashlib
import json
import secrets
import unittest
from unittest.mock import patch

from complete_games import CompleteGamesBackend
from escape_pvp import escape_duel_outcome
import test_games_backend as legacy_tests
import test_pvp_games as pvp_tests


class EscapePvpTests(unittest.IsolatedAsyncioTestCase):
    backend_type = CompleteGamesBackend
    asyncSetUp = legacy_tests.GamesBackendTests.asyncSetUp
    asyncTearDown = legacy_tests.GamesBackendTests.asyncTearDown
    headers = legacy_tests.GamesBackendTests.headers
    balance = pvp_tests.PvpGamesTests.balance

    async def action(self, action, payload, user_id=42, key=None):
        response = await self.client.post("/api/escape/pvp/" + action, json=payload, headers=self.headers(user_id, key))
        return response.status, await response.json()

    async def read(self, path="state", user_id=42):
        response = await self.client.get("/api/escape/pvp/" + path, headers=self.headers(user_id))
        return response.status, await response.json()

    async def create(self, private=False, bet=10, level="mid", key=None):
        status, result = await self.action("play", {"bet": bet, "level": level, "private": private}, key=key)
        self.assertEqual(status, 200, result)
        return result["duel"]

    async def test_commit_join_payout_seed_and_own_state(self):
        duel = await self.create()
        self.assertEqual((await self.read("howto"))[0], 200)
        self.assertEqual(duel["status"], "waiting")
        self.assertNotIn("serverSeed", duel)
        self.assertFalse(any(key.startswith("_") for key in duel))
        self.assertEqual(await self.balance(), 990)
        key = secrets.token_hex(16)
        results = await asyncio.gather(*(self.action("join", {"id": duel["id"]}, 99, key) for _ in range(8)))
        self.assertTrue(all(status == 200 for status, result in results), results)
        joined = results[0][1]["duel"]
        self.assertEqual(joined["status"], "live")
        self.assertEqual(joined["prize"], 19.8)
        self.assertEqual(joined["commission"], 0.2)
        self.assertEqual(joined["seedHash"], duel["seedHash"])
        self.assertNotIn("serverSeed", joined)
        winner = joined["winnerId"]
        self.assertEqual(await self.balance(winner), 1009.8)
        self.assertEqual(await self.balance(99 if winner == 42 else 42), 990)
        self.assertEqual((await self.read())[1]["mine"]["id"], duel["id"])
        self.assertEqual((await self.read("history"))[1]["rows"], [])
        with patch("escape_pvp.duel_now", return_value=10 ** 12):
            response = await self.client.get("/api/escape/round?id=" + duel["id"], headers=self.headers())
            finished = await response.json()
            self.assertEqual(finished["status"], "finished")
            self.assertEqual(hashlib.sha256(finished["serverSeed"].encode()).hexdigest(), duel["seedHash"])
            expected = escape_duel_outcome(finished["serverSeed"], duel["id"], "mid")
            self.assertEqual(finished["winnerSlot"], 0 if expected["creatorWins"] else 1)
            self.assertEqual(finished["params"]["t1"], expected["t1"])
            self.assertEqual(len((await self.read("history?scope=mine"))[1]["rows"]), 1)
            self.assertIsNone((await self.read())[1]["mine"])
        leaders = await self.client.get("/api/leaders?category=turnover", headers=self.headers())
        self.assertEqual((await leaders.json())["myScore"], 10)

    async def test_private_invite_not_in_lobby_and_auto_match_public(self):
        private = await self.create(True)
        self.assertEqual((await self.read("state", 99))[1]["lobby"], [])
        self.assertEqual((await self.action("join", {"id": private["id"]}, 99))[0], 200)
        with patch("escape_pvp.duel_now", return_value=10 ** 12):
            await self.create(False, 12, "lite")
            status, result = await self.action("play", {"bet": 12, "level": "lite"}, 99)
            self.assertEqual(status, 200, result)
            self.assertEqual(result["duel"]["status"], "live")
            self.assertEqual(result["duel"]["bet"], 12)

    async def test_create_cancel_replay_foreign_and_insufficient_funds(self):
        key = secrets.token_hex(16)
        duel = await self.create(True, key=key)
        replay = await self.create(True, key=key)
        self.assertEqual(replay["id"], duel["id"])
        self.assertEqual((await self.action("join", {"id": duel["id"]}))[0], 409)
        self.assertEqual((await self.action("cancel", {"id": duel["id"]}, 99))[0], 403)
        self.assertEqual((await self.action("play", {"bet": 20, "level": "mid"}))[0], 409)
        key = secrets.token_hex(16)
        results = await asyncio.gather(*(self.action("cancel", {"id": duel["id"]}, key=key) for _ in range(8)))
        self.assertTrue(all(status == 200 for status, _ in results))
        self.assertEqual(await self.balance(), 1000)
        self.assertEqual((await self.action("join", {"id": duel["id"]}, 99))[0], 409)
        self.assertEqual((await self.action("play", {"bet": 1001, "level": "mid"}))[0], 400)

    async def test_expiration_refunds_once_after_restart(self):
        duel = await self.create()
        with patch("escape_pvp.duel_now", return_value=10 ** 12):
            await self.backend.initialize_escape_pvp()
            await self.backend.initialize_escape_pvp()
            self.assertIsNone((await self.read())[1]["mine"])
        self.assertEqual(await self.balance(), 1000)
        response = await self.client.get("/api/escape/round?id=" + duel["id"], headers=self.headers())
        self.assertEqual((await response.json())["status"], "expired")

    async def test_cancel_join_race_is_atomic(self):
        duel = await self.create()
        results = await asyncio.gather(self.action("cancel", {"id": duel["id"]}), self.action("join", {"id": duel["id"]}, 99))
        self.assertEqual(sum(status == 200 for status, _ in results), 1)
        total = await self.balance() + await self.balance(99)
        self.assertIn(round(total, 2), {2000, 1999.8})

    async def test_validation_and_history_search(self):
        for payload in ({"bet": 0}, {"bet": 10, "level": []}, {"bet": 10, "private": 1}, {"bet": "NaN"}):
            self.assertEqual((await self.action("play", payload))[0], 400)
        self.assertEqual((await self.action("join", {"id": "bad"}, 99))[0], 400)
        self.assertEqual((await self.read("state?level=bad"))[0], 400)
        self.assertEqual((await self.read("history?scope=other"))[0], 400)
        self.assertEqual((await self.read("history?offset=-1"))[0], 400)
        self.assertEqual(await self.balance(), 1000)
        duel = await self.create()
        await self.action("join", {"id": duel["id"]}, 99)
        with patch("escape_pvp.duel_now", return_value=10 ** 12):
            self.assertEqual(len((await self.read("history?q=" + duel["id"]))[1]["rows"]), 1)
            self.assertEqual((await self.read("history?q=missing"))[1]["rows"], [])

    async def test_outcome_and_trajectories_match_real_javascript_engine(self):
        import subprocess
        from escape_pvp import ESCAPE_DUEL_LEVELS
        from game_rules import digest
        cases = []
        for level in ESCAPE_DUEL_LEVELS:
            for index in range(3):
                seed = hashlib.sha256(str(index).encode()).hexdigest()
                identifier = "V" + str(index).zfill(16)
                cases.append({"seed": seed, "id": identifier, "level": level, "outcome": escape_duel_outcome(seed, identifier, level["id"]), "pathSeed": digest(seed, identifier + ":pvp:path")})
        result = await asyncio.to_thread(subprocess.run, ["node", "tests/check_escape_duel.js"], input=json.dumps(cases), capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
