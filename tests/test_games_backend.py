import bundle_test_support  # Register backend modules from server.py.
import asyncio
import hashlib
import hmac
import json
import math
import secrets
import sys
import tempfile
import time
import unittest
from fractions import Fraction
from pathlib import Path
from urllib.parse import urlencode

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from games_backend import ProgressiveGamesBackend, MULTIPLIER_SCALE, keno_draw, keno_paytable, progressive_positions


class PaytableTests(unittest.TestCase):
    def test_all_paytables(self):
        for count in range(1, 11):
            variances = []
            for risk in ("low", "medium", "high"):
                table = keno_paytable(risk, count)
                probabilities = [Fraction(math.comb(count, hits) * math.comb(40 - count, 10 - hits), math.comb(40, 10)) for hits in range(count + 1)]
                expected = sum(probability * Fraction(value, MULTIPLIER_SCALE) for probability, value in zip(probabilities, table))
                self.assertLessEqual(expected, Fraction(9, 10))
                self.assertGreaterEqual(expected, Fraction(89999999, 100000000))
                self.assertEqual(table[0], 0)
                self.assertEqual(list(table), sorted(table))
                variances.append(sum(probability * (Fraction(value, MULTIPLIER_SCALE) - expected) ** 2 for probability, value in zip(probabilities, table)))
            self.assertLessEqual(variances[0], variances[1])
            self.assertLessEqual(variances[1], variances[2])

    def test_fair_draw(self):
        seed, round_id = "a" * 64, "K" + "B" * 24
        expected = sorted(range(40), key=lambda index: int(hmac.new(seed.encode(), f"{round_id}:{index}".encode(), hashlib.sha256).hexdigest()[:13], 16))[:10]
        self.assertEqual(keno_draw(seed, round_id), [value + 1 for value in expected])
        self.assertEqual(len(set(keno_draw(seed, round_id))), 10)


class GamesBackendTests(unittest.IsolatedAsyncioTestCase):
    backend_type = ProgressiveGamesBackend

    async def asyncSetUp(self):
        self.runtime = bundle_test_support.load_application("games_test_main")
        self.directory = tempfile.TemporaryDirectory()
        self.runtime.DB_PATH = str(Path(self.directory.name) / "bot.db")
        self.runtime.BOT_TOKEN = "123456:local-test-token"
        await self.runtime.db_init()
        await self.runtime.init_db()
        await self.runtime.add_balance(42, 1000)
        await self.runtime.add_balance(99, 1000)
        self.backend = self.backend_type(self.runtime.db, self.runtime._db_lock, self.runtime.webapp_authenticated_user, self.runtime.now_msk)
        application = web.Application()
        self.backend.register(application)
        await self.backend.initialize(application)
        self.client = TestClient(TestServer(application))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.runtime.db_close()
        self.directory.cleanup()

    def headers(self, user_id=42, request_id=None):
        data = {"auth_date": str(int(time.time())), "user": json.dumps({"id": user_id, "first_name": "Player"})}
        key = hmac.new(b"WebAppData", self.runtime.BOT_TOKEN.encode(), hashlib.sha256).digest()
        signature = hmac.new(key, "\n".join(f"{name}={value}" for name, value in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
        return {"X-Telegram-Init-Data": urlencode({**data, "hash": signature}), "Idempotency-Key": request_id or secrets.token_hex(16)}

    async def play(self, payload=None, headers=None, game="keno"):
        response = await self.client.post(f"/api/{game}/play", json=payload if payload is not None else {"uid": 42, "bet": 10, "picks": [1, 2, 3], "risk": "medium"}, headers=headers or self.headers())
        return response.status, await response.json()

    async def test_play_and_history(self):
        status, result = await self.play()
        self.assertEqual(status, 200, result)
        self.assertEqual(result["drawn"], keno_draw(result["serverSeed"], result["roundId"]))
        self.assertEqual(result["seedHash"], hashlib.sha256(result["serverSeed"].encode()).hexdigest())
        self.assertEqual(result["balance"], await self.runtime.get_balance(42))
        self.assertAlmostEqual(result["balance"], 990 + result["winAmount"])
        response = await self.client.get("/api/keno/history?scope=mine&uid=42", headers=self.headers())
        history = await response.json()
        self.assertEqual(len(history["rows"]), 1)
        self.assertNotIn("balance", json.loads(history["rows"][0]["meta"]))
        response = await self.client.get("/api/keno/round?id=" + result["roundId"], headers=self.headers(99))
        detail = await response.json()
        self.assertEqual(detail["serverSeed"], result["serverSeed"])
        self.assertNotIn("balance", detail)

    async def test_concurrent_replay_and_conflict(self):
        headers = self.headers()
        replies = await asyncio.gather(*(self.play(headers=headers) for _ in range(20)))
        self.assertEqual({status for status, result in replies}, {200})
        self.assertEqual(len({result["roundId"] for status, result in replies}), 1)
        result = replies[0][1]
        self.assertAlmostEqual(await self.runtime.get_balance(42), 990 + result["winAmount"])
        status, result = await self.play({"uid": 42, "bet": 11, "picks": [1, 2, 3], "risk": "medium"}, headers=headers)
        self.assertEqual(status, 409)

    async def test_validation_and_authorization(self):
        invalid = [
            {"bet": -1, "picks": [1]}, {"bet": 0, "picks": [1]}, {"bet": True, "picks": [1]},
            {"bet": "NaN", "picks": [1]}, {"bet": "Infinity", "picks": [1]}, {"bet": 0.101, "picks": [1]},
            {"bet": 10, "picks": []}, {"bet": 10, "picks": [1, 1]}, {"bet": 10, "picks": [True]},
            {"bet": 10, "picks": [0]}, {"bet": 10, "picks": [41]}, {"bet": 10, "picks": [1], "risk": []},
            {"bet": 10, "picks": [1], "risk": "unknown"}, {"bet": 10, "picks": list(range(1, 12))},
        ]
        for payload in invalid:
            status, result = await self.play(payload)
            self.assertEqual(status, 400, (payload, result))
        status, result = await self.play({"uid": 99, "bet": 10, "picks": [1]})
        self.assertEqual(status, 403)
        response = await self.client.post("/api/keno/play", json={"bet": 10, "picks": [1]})
        self.assertEqual(response.status, 401)
        self.assertEqual(await self.runtime.get_balance(42), 1000)
        self.assertEqual(await self.runtime.get_balance(99), 1000)

    async def test_insufficient_funds_is_atomic(self):
        status, result = await self.play({"bet": 1001, "picks": [1]})
        self.assertEqual(status, 400)
        self.assertEqual(result["autoCode"], "balance")
        self.assertEqual(await self.runtime.get_balance(42), 1000)
        response = await self.client.get("/api/keno/history?scope=mine", headers=self.headers())
        self.assertEqual((await response.json())["rows"], [])

    async def test_auto_sessions(self):
        response = await self.client.post("/api/keno/auto/start", json={"uid": 42, "params": {"rounds": 1, "cap": 10}}, headers=self.headers())
        configuration = await response.json()
        self.assertEqual(response.status, 200, configuration)
        payload = {"uid": 42, "bet": 10, "picks": [1], "autoSid": configuration["sid"]}
        status, result = await self.play(payload)
        self.assertEqual(status, 200, result)
        status, result = await self.play(payload)
        self.assertEqual(status, 400)
        self.assertEqual(result["autoCode"], "cap")
        payload["uid"] = 99
        status, result = await self.play(payload, headers=self.headers(99))
        self.assertEqual(status, 400)
        self.assertEqual(await self.runtime.get_balance(99), 1000)

    async def test_rollback_on_insert_failure(self):
        async with self.runtime._db_lock:
            await self.runtime.db().execute("CREATE TRIGGER reject_webapp_round BEFORE INSERT ON webapp_rounds BEGIN SELECT RAISE(ABORT, 'test failure'); END")
            await self.runtime.db().commit()
        with self.assertLogs("aiohttp.server", level="ERROR"):
            response = await self.client.post("/api/keno/play", json={"bet": 10, "picks": [1]}, headers=self.headers())
        self.assertEqual(response.status, 500)
        self.assertEqual(await self.runtime.get_balance(42), 1000)

    async def test_upgrade(self):
        status, result = await self.play({"bet": 10, "chance": 50}, game="upgrade")
        self.assertEqual(status, 200, result)
        self.assertEqual(result["multiplier"], 1.88)
        roll = int(hmac.new(result["serverSeed"].encode(), result["roundId"].encode(), hashlib.sha256).hexdigest()[:13], 16) / 16 ** 13 * 100
        self.assertEqual(result["roll"], roll)
        self.assertEqual(result["winAmount"], 18.8 if 0.0946 <= roll <= 50 else 0)
        self.assertAlmostEqual(await self.runtime.get_balance(42), 990 + result["winAmount"])

    async def test_commission(self):
        response = await self.client.get("/api/pvp/commission", headers=self.headers())
        self.assertEqual((await response.json())["percent"], 1)

    async def action(self, game, action, payload, headers=None):
        response = await self.client.post(f"/api/{game}/{action}", json=payload, headers=headers or self.headers())
        return response.status, await response.json()

    async def private_state(self, game):
        async with self.runtime._db_lock:
            async with self.runtime.db().execute("SELECT data FROM webapp_active_games WHERE user_id = 42 AND game = ?", (game,)) as cursor:
                row = await cursor.fetchone()
        return json.loads(row[0]) if row else None

    async def test_mines_resume_and_cashout_once(self):
        status, started = await self.action("mines", "start", {"bet": 10, "minesCount": 3})
        self.assertEqual(status, 200, started)
        self.assertNotIn("serverSeed", started)
        self.assertNotIn("minePositions", started)
        self.assertFalse(any(key.startswith("_") for key in started))
        response = await self.client.get("/api/mines/state?uid=42", headers=self.headers())
        self.assertEqual((await response.json())["roundId"], started["roundId"])
        private = await self.private_state("mines")
        safe = next(cell for cell in range(25) if cell not in private["_positions"])
        status, step = await self.action("mines", "reveal", {"cellIndex": safe, "roundId": started["roundId"]})
        self.assertEqual(status, 200, step)
        self.assertEqual(step["cellsOpened"], 1)
        headers = self.headers()
        replies = await asyncio.gather(*(self.action("mines", "cashout", {"roundId": started["roundId"]}, headers) for _ in range(20)))
        self.assertEqual({status for status, result in replies}, {200})
        result = replies[0][1]
        self.assertEqual(result["minePositions"], progressive_positions("mines", 3, result["serverSeed"], result["roundId"]))
        self.assertAlmostEqual(await self.runtime.get_balance(42), 990 + result["winAmount"])
        status, result = await self.action("mines", "cashout", {"roundId": started["roundId"]})
        self.assertEqual(status, 409)
        self.assertIsNone(await self.private_state("mines"))

    async def test_mines_bomb_and_stale_actions(self):
        status, started = await self.action("mines", "start", {"bet": 10, "minesCount": 3})
        private = await self.private_state("mines")
        bomb = private["_positions"][0]
        status, result = await self.action("mines", "reveal", {"cellIndex": bomb, "roundId": started["roundId"]})
        self.assertEqual(status, 200, result)
        self.assertFalse(result["active"])
        self.assertFalse(result["win"])
        self.assertEqual(result["hitIndex"], bomb)
        self.assertEqual(await self.runtime.get_balance(42), 990)
        status, second = await self.action("mines", "start", {"bet": 10, "minesCount": 3})
        self.assertEqual(status, 200, second)
        status, result = await self.action("mines", "reveal", {"cellIndex": 0, "roundId": started["roundId"]})
        self.assertEqual(status, 409)
        self.assertEqual((await self.private_state("mines"))["roundId"], second["roundId"])

    async def test_cannot_cashout_before_first_move(self):
        status, started = await self.action("mines", "start", {"bet": 10, "minesCount": 3})
        status, result = await self.action("mines", "cashout", {"roundId": started["roundId"]})
        self.assertEqual(status, 400)
        self.assertEqual(await self.runtime.get_balance(42), 990)
        status, result = await self.action("mines", "start", {"bet": 10, "minesCount": 3})
        self.assertEqual(status, 409)
        self.assertEqual(await self.runtime.get_balance(42), 990)

    async def test_ladder_success_and_duplicate_level(self):
        status, started = await self.action("ladder", "start", {"bet": 10, "stonesCount": 2})
        self.assertEqual(status, 200, started)
        private = await self.private_state("ladder")
        for level in range(6):
            safe = next(column for column in range(5) if [level, column] not in private["_positions"])
            payload = {"roundId": started["roundId"], "column": safe, "level": level}
            status, result = await self.action("ladder", "pick", payload)
            self.assertEqual(status, 200, result)
            self.assertEqual(result["level"], level + 1)
            if level == 0:
                status, repeated = await self.action("ladder", "pick", payload)
                self.assertEqual(status, 409)
            if level < 5:
                self.assertTrue(result["active"])
                self.assertFalse(any(position[0] > level for position in result["revealedStones"]))
        self.assertFalse(result["active"])
        self.assertTrue(result["win"])
        self.assertIn("serverSeed", result)
        self.assertAlmostEqual(await self.runtime.get_balance(42), 990 + result["winAmount"])

    async def test_ladder_loss(self):
        status, started = await self.action("ladder", "start", {"bet": 10, "stonesCount": 2})
        private = await self.private_state("ladder")
        column = private["_positions"][0][1]
        status, result = await self.action("ladder", "pick", {"roundId": started["roundId"], "column": column, "level": 0})
        self.assertEqual(status, 200, result)
        self.assertFalse(result["active"])
        self.assertFalse(result["win"])
        self.assertEqual(result["winAmount"], 0)
        self.assertEqual(await self.runtime.get_balance(42), 990)


    async def test_progressive_auto_rounds(self):
        for game, count_key, path_key, path in [("mines", "minesCount", "cells", [0, 1, 2]), ("ladder", "stonesCount", "columns", [0, 1, 2])]:
            response = await self.client.post(f"/api/{game}/auto/start", json={"params": {"rounds": 5}}, headers=self.headers())
            configuration = await response.json()
            payload = {"bet": 10, count_key: 2, path_key: path, "autoSid": configuration["sid"]}
            headers = self.headers()
            status, result = await self.action(game, "auto/round", payload, headers)
            self.assertEqual(status, 200, result)
            self.assertFalse(result["active"])
            self.assertEqual(result["path"], path[:len(result["path"])])
            positions = progressive_positions(game, 2, result["serverSeed"], result["roundId"])
            won = all(cell not in positions for cell in path) if game == "mines" else all([level, cell] not in positions for level, cell in enumerate(path))
            self.assertEqual(result["win"], won)
            balance = await self.runtime.get_balance(42)
            status, replay = await self.action(game, "auto/round", payload, headers)
            self.assertEqual(status, 200, replay)
            self.assertEqual(replay["roundId"], result["roundId"])
            self.assertEqual(await self.runtime.get_balance(42), balance)
            status, delayed = await self.action(game, "auto/round", payload)
            self.assertEqual(status, 429, delayed)
            self.assertEqual(delayed["autoCode"], "fast")
            async with self.runtime._db_lock:
                await self.runtime.db().execute("UPDATE webapp_rounds SET created_at = '2000-01-01T00:00:00+03:00'")
                await self.runtime.db().commit()

    async def test_resume_after_reconnecting_database(self):
        status, started = await self.action("mines", "start", {"bet": 10, "minesCount": 3})
        self.assertEqual(status, 200)
        private = await self.private_state("mines")
        await self.runtime.db_close()
        await self.runtime.db_init()
        await self.backend.initialize(None)
        self.assertEqual(await self.private_state("mines"), private)
        self.assertEqual(await self.runtime.get_balance(42), 990)
        response = await self.client.get("/api/mines/state", headers=self.headers())
        self.assertEqual((await response.json())["roundId"], started["roundId"])



if __name__ == "__main__":
    unittest.main()
