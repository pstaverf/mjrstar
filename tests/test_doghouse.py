import bundle_test_support  # Register backend modules from server.py.
import asyncio
import hashlib
import json
import secrets
import subprocess
import unittest
from fractions import Fraction

from complete_games import CompleteGamesBackend
from doghouse_rules import DOGHOUSE_LINES, DOGHOUSE_SYMBOLS, DOGHOUSE_WEIGHTS, doghouse_expectation, doghouse_line, doghouse_spin
import test_games_backend as legacy_tests
import test_pvp_games as pvp_tests


class ArchivedDoghouseBackend(CompleteGamesBackend):
    def register(self, application):
        super().register(application)
        # Tests only: production returns 410 and never exposes the archived wagering route.
        application.router.add_get("/archive/doghouse/history", self.handle_history)
        application.router.add_get("/archive/doghouse/page", self.handle_doghouse_page)
        application.router.add_get("/archive/doghouse/state", self.handle_doghouse_state)
        application.router.add_post("/archive/doghouse/play", self.handle_doghouse_play)
        application.router.add_get("/archive/doghouse/round", self.handle_doghouse_round)


class DoghouseTests(unittest.IsolatedAsyncioTestCase):
    backend_type = ArchivedDoghouseBackend
    asyncSetUp = legacy_tests.GamesBackendTests.asyncSetUp
    asyncTearDown = legacy_tests.GamesBackendTests.asyncTearDown
    headers = legacy_tests.GamesBackendTests.headers
    balance = pvp_tests.PvpGamesTests.balance

    async def state(self):
        response = await self.client.get("/archive/doghouse/state", headers=self.headers())
        self.assertEqual(response.status, 200)
        return await response.json()

    async def play(self, state, bet=10, key=None):
        response = await self.client.post("/archive/doghouse/play", json={"bet": bet, "roundId": state["commit"]["roundId"]}, headers=self.headers(request_id=key))
        return response.status, await response.json() if response.content_type == "application/json" else {}

    async def set_seed(self, predicate):
        state = await self.state()
        while True:
            seed = secrets.token_hex(32)
            result = doghouse_spin(seed, state["commit"]["roundId"], 1000)
            if predicate(result):
                break
        async with self.runtime._db_lock:
            await self.runtime.db().execute("UPDATE webapp_commits SET seed = ? WHERE user_id = 42 AND game = 'doghouse'", (seed,))
            await self.runtime.db().commit()
        return await self.state(), seed

    async def test_win_loss_shared_balance_and_history(self):
        for predicate in (lambda result: result["payoutCents"] > 1000, lambda result: result["payoutCents"] == 0):
            state, seed = await self.set_seed(predicate)
            before = await self.balance()
            status, result = await self.play(state)
            self.assertEqual(status, 200, result)
            expected = doghouse_spin(seed, state["commit"]["roundId"], 1000)
            self.assertEqual(result["grid"], expected["grid"])
            self.assertEqual(result["payoutCents"], expected["payoutCents"])
            self.assertEqual(result["seedHash"], state["commit"]["seedHash"])
            self.assertEqual(result["serverSeed"], seed)
            self.assertAlmostEqual(await self.balance(), before - 10 + expected["payoutCents"] / 100)
            response = await self.client.get("/archive/doghouse/round?id=" + result["roundId"], headers=self.headers(99))
            detail = await response.json()
            self.assertNotIn("balance", detail)
            self.assertEqual(detail["grid"], expected["grid"])
        response = await self.client.get("/archive/doghouse/history?scope=mine", headers=self.headers())
        self.assertEqual(len((await response.json())["rows"]), 2)
        response = await self.client.get("/api/leaders?category=turnover", headers=self.headers())
        self.assertEqual((await response.json())["myScore"], 20)

    async def test_parallel_replays_and_stale_commit_never_double_debit(self):
        state = await self.state()
        key = secrets.token_hex(16)
        results = await asyncio.gather(*(self.play(state, key=key) for _ in range(8)))
        self.assertTrue(all(status == 200 for status, _ in results))
        first = results[0][1]
        self.assertEqual(await self.balance(), 990 + first["winAmount"])
        self.assertTrue(all(result["roundId"] == first["roundId"] for _, result in results))
        self.assertEqual((await self.play(state))[0], 409)
        self.assertEqual((await self.play(state, bet=20, key=key))[0], 409)
        self.assertNotEqual((await self.state())["commit"]["roundId"], state["commit"]["roundId"])

    async def test_validation_and_unauthorized_page(self):
        state = await self.state()
        for bet in (0, -1, True, "NaN", 1000001, 1001):
            self.assertEqual((await self.play(state, bet))[0], 400)
        self.assertEqual(await self.balance(), 1000)
        self.assertEqual((await self.state())["commit"], state["commit"])
        response = await self.client.get("/archive/doghouse/page")
        self.assertEqual(response.status, 401)
        response = await self.client.get("/archive/doghouse/page", headers=self.headers())
        self.assertEqual(response.status, 200)
        page = await response.text()
        self.assertIn("parent.fetch", page)
        self.assertIn("TelegramStars.png", page)
        self.assertIn("Авторская версия", page)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    async def test_database_failure_rolls_back_credit_and_preserves_commit(self):
        state, seed = await self.set_seed(lambda result: result["payoutCents"] > 0)
        async with self.runtime._db_lock:
            await self.runtime.db().execute("CREATE TRIGGER fail_doghouse_insert BEFORE INSERT ON webapp_rounds WHEN NEW.game = 'doghouse' BEGIN SELECT RAISE(ABORT,'write failed'); END")
            await self.runtime.db().commit()
        with self.assertLogs("aiohttp.server", level="ERROR"):
            self.assertEqual((await self.play(state))[0], 500)
        self.assertEqual(await self.balance(), 1000)
        self.assertEqual((await self.state())["commit"], state["commit"])
        async with self.runtime._db_lock:
            await self.runtime.db().execute("DROP TRIGGER fail_doghouse_insert")
            await self.runtime.db().commit()
        self.assertEqual((await self.play(state))[0], 200)

    async def test_expectation_paylines_and_actual_browser_verification(self):
        self.assertEqual(sum(DOGHOUSE_WEIGHTS), 100)
        self.assertEqual(len({tuple(line) for line in DOGHOUSE_LINES}), 20)
        self.assertEqual(doghouse_line(["bone"] * 5)[0], 40)
        self.assertEqual(doghouse_line(["bone", "wild", "bone", "collar", "pug"])[0], 6)
        self.assertEqual(doghouse_line(["wild"] * 5)[0], 8000)
        expectation = doghouse_expectation()
        normalization = Fraction(9 * 100 ** 5, 200 * expectation)
        self.assertEqual(20 * Fraction(expectation, 100 ** 5) * normalization, Fraction(9, 10))
        results = []
        for index in range(4):
            seed = hashlib.sha256(str(index).encode()).hexdigest()
            identifier = "DH" + str(index).zfill(24)
            spin = doghouse_spin(seed, identifier, 1000)
            self.assertTrue(all(symbol in DOGHOUSE_SYMBOLS for column in spin["grid"] for symbol in column))
            results.append({"serverSeed": seed, "seedHash": hashlib.sha256(seed.encode()).hexdigest(), "roundId": identifier, "betCents": 1000, "config": self.backend.doghouse_config(), **spin})
        result = await asyncio.to_thread(subprocess.run, ["node", "tests/check_doghouse.js"], input=json.dumps(results), capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
