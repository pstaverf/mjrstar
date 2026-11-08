import bundle_test_support  # Register backend modules from server.py.
import asyncio
import json
import secrets
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from complete_games import CompleteGamesBackend
from games_backend import serialize
from pvp_games import PVP_EMOJI, duel_score, slot_reels
import test_games_backend as legacy_tests


class PvpGamesTests(unittest.IsolatedAsyncioTestCase):
    backend_type = CompleteGamesBackend
    asyncSetUp = legacy_tests.GamesBackendTests.asyncSetUp
    asyncTearDown = legacy_tests.GamesBackendTests.asyncTearDown
    headers = legacy_tests.GamesBackendTests.headers

    def configure_dice(self, values):
        messages = [SimpleNamespace(dice=SimpleNamespace(value=value), chat=SimpleNamespace(id=-100123456, username="mjrstars"), message_id=index + 100) for index, value in enumerate(values)]
        self.backend.telegram_bot = SimpleNamespace(send_dice=AsyncMock(side_effect=messages))
        self.backend.telegram_channel = "@mjrstars"

    async def action(self, game, action, payload, user_id=42, key=None):
        response = await self.client.post(f"/api/pvp/{game}/{action}", json={"uid": user_id, **payload}, headers=self.headers(user_id, key))
        return response.status, await response.json()

    async def read(self, path, user_id=42):
        response = await self.client.get("/api/pvp/" + path, headers=self.headers(user_id))
        return response.status, await response.json()

    async def balance(self, user_id=42):
        async with self.runtime._db_lock:
            return await self.backend.balance(self.runtime.db(), user_id)

    async def create(self, game="dice", bet=10):
        status, response = await self.action(game, "create", {"bet": bet})
        self.assertEqual(status, 200, response)
        return response

    async def test_create_cancel_and_replay(self):
        self.configure_dice([])
        key = secrets.token_hex(16)
        status, room = await self.action("dice", "create", {"bet": 10}, key=key)
        self.assertEqual(status, 200, room)
        self.assertEqual(room["balance"], 990)
        replay = await self.action("dice", "create", {"bet": 10}, key=key)
        self.assertEqual(replay[1]["roomId"], room["roomId"])
        self.assertEqual((await self.action("dice", "create", {"bet": 20}, key=key))[0], 409)
        self.assertEqual((await self.action("dice", "cancel", {"roomId": room["roomId"]}, user_id=99))[0], 403)
        key = secrets.token_hex(16)
        results = await asyncio.gather(*(self.action("dice", "cancel", {"roomId": room["roomId"]}, key=key) for _ in range(10)))
        self.assertTrue(all(status == 200 for status, _ in results))
        self.assertEqual(await self.balance(), 1000)
        self.assertEqual((await self.action("dice", "join", {"roomId": room["roomId"]}, user_id=99))[0], 409)
        self.assertEqual(self.backend.telegram_bot.send_dice.call_count, 0)

    async def test_winner_receives_99_percent_bank(self):
        self.configure_dice([6, 1])
        room = await self.create()
        key = secrets.token_hex(16)
        results = await asyncio.gather(*(self.action("dice", "join", {"roomId": room["roomId"]}, user_id=99, key=key) for _ in range(8)))
        self.assertTrue(all(status == 200 for status, _ in results), results)
        result = results[0][1]
        self.assertEqual(result["winnerId"], 42)
        self.assertEqual(result["winAmount"], 19.8)
        self.assertEqual(result["feeAmount"], 0.2)
        self.assertEqual(result["commissionPercent"], 1)
        self.assertFalse(result["isDraw"])
        self.assertEqual(await self.balance(), 1009.8)
        self.assertEqual(await self.balance(99), 990)
        self.assertEqual(self.backend.telegram_bot.send_dice.call_count, 2)
        self.assertEqual(result["creatorCheckLink"], "https://t.me/mjrstars/100")
        self.assertFalse(any(key.startswith("_") for key in result))
        self.assertEqual((await self.read("dice/round?id=" + room["roomId"]))[1]["creatorResult"], 6)
        rows = (await self.read("dice/history?scope=mine"))[1]["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["roomId"], room["roomId"])
        self.assertEqual((await self.read("dice/my-rooms"))[1]["rooms"], [])

    async def test_draw_returns_full_bets(self):
        self.configure_dice([3, 3])
        room = await self.create(bet=0.1)
        status, result = await self.action("dice", "join", {"roomId": room["roomId"]}, user_id=99)
        self.assertEqual(status, 200, result)
        self.assertTrue(result["isDraw"])
        self.assertIsNone(result["winnerId"])
        self.assertEqual(result["feeAmount"], 0)
        self.assertEqual(result["winAmount"], 0.1)
        self.assertEqual(await self.balance(), 1000)
        self.assertEqual(await self.balance(99), 1000)

    async def test_all_six_telegram_game_rules(self):
        cases = [("dice", 2, 5, 99), ("bowling", 1, 6, 99), ("darts", 2, 3, None), ("basketball", 5, 4, 42), ("football", 3, 5, None), ("slots", 1, 64, 99)]
        for game, first, second, winner in cases:
            with self.subTest(game=game):
                self.configure_dice([first, second])
                room = await self.create(game)
                status, result = await self.action(game, "join", {"roomId": room["roomId"]}, user_id=99)
                self.assertEqual(status, 200, result)
                self.assertEqual(result["winnerId"], winner)
                self.assertEqual(self.backend.telegram_bot.send_dice.call_args.kwargs["emoji"], PVP_EMOJI[game])
                if game == "slots":
                    self.assertEqual(result["creatorReels"], ["Бар"] * 3)
                    self.assertEqual(result["opponentReels"], ["Семёрка"] * 3)

    async def test_self_join_insufficient_funds_and_concurrent_join(self):
        self.configure_dice([6, 2])
        room = await self.create(bet=1000)
        self.assertEqual((await self.action("dice", "join", {"roomId": room["roomId"]}))[0], 400)
        await self.runtime.add_balance(99, -999)
        self.assertEqual((await self.action("dice", "join", {"roomId": room["roomId"]}, user_id=99))[0], 400)
        self.assertEqual((await self.read("dice/room?id=" + room["roomId"]))[1]["status"], "waiting")
        await self.runtime.add_balance(99, 999)
        replies = await asyncio.gather(*(self.action("dice", "join", {"roomId": room["roomId"]}, user_id=99) for _ in range(5)))
        self.assertEqual(sum(status == 200 for status, _ in replies), 1)
        self.assertEqual(self.backend.telegram_bot.send_dice.call_count, 2)
        self.assertEqual(await self.balance(99), 0)
        self.assertEqual(await self.balance(), 1980)

    async def test_telegram_failure_refunds_both_once(self):
        self.configure_dice([6])
        room = await self.create()
        key = secrets.token_hex(16)
        with self.assertLogs(level="ERROR"):
            status, result = await self.action("dice", "join", {"roomId": room["roomId"]}, user_id=99, key=key)
        self.assertEqual(status, 200, result)
        self.assertFalse(result["ok"])
        self.assertTrue(result["refunded"])
        self.assertEqual(await self.balance(), 1000)
        self.assertEqual(await self.balance(99), 1000)
        replay = await self.action("dice", "join", {"roomId": room["roomId"]}, user_id=99, key=key)
        self.assertFalse(replay[1]["ok"])
        self.assertEqual(await self.balance(), 1000)
        self.assertEqual(self.backend.telegram_bot.send_dice.call_count, 2)

    async def test_waiting_room_persists_and_interrupted_join_refunds(self):
        self.configure_dice([])
        room = await self.create()
        async with self.runtime._db_lock:
            connection = self.runtime.db()
            async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ?", (room["roomId"],)) as cursor:
                state = json.loads((await cursor.fetchone())[0])
            await self.backend.debit(connection, 99, 1000)
            state.update({"status": "active", "opponentId": 99, "opponentName": "Opponent", "_joinKey": "interrupted_request_123"})
            await self.backend.save_pvp(connection, state)
            await self.backend.save_receipt(connection, 99, state["_joinKey"], "signature", {"ok": True, "status": "active", "roomId": room["roomId"]})
            await connection.commit()
        await self.backend.initialize_pvp()
        self.assertEqual(await self.balance(), 1000)
        self.assertEqual(await self.balance(99), 1000)
        await self.backend.initialize_pvp()
        self.assertEqual(await self.balance(), 1000)
        self.assertEqual(await self.balance(99), 1000)
        self.assertEqual((await self.read("dice/room?id=" + room["roomId"]))[1]["status"], "error")

    async def test_search_lists_filter_and_enabled_switches(self):
        self.configure_dice([])
        room = await self.create("football")
        self.assertEqual((await self.read("active-all"))[1]["rooms"][0]["roomId"], room["roomId"])
        self.assertEqual((await self.read("dice/active"))[1]["rooms"], [])
        self.assertEqual((await self.read("search?id=" + room["roomId"]))[1]["game"], "football")
        self.assertEqual((await self.read("football/active-search?id=" + room["roomId"]))[0], 200)
        self.assertEqual((await self.read("football/active?scope=mine", user_id=99))[1]["rooms"], [])
        response = await self.client.get("/api/games/off", headers=self.headers())
        off = (await response.json())["off"]
        for game in ("pvp_dice", "pvp_bowling", "pvp_darts", "pvp_basketball", "pvp_football", "pvp_slots"):
            self.assertNotIn(game, off)
        self.assertNotIn("pvp_blackjack", off)

    async def test_create_failure_rolls_back_debit(self):
        self.configure_dice([])
        async with self.runtime._db_lock:
            await self.runtime.db().execute("CREATE TRIGGER reject_pvp BEFORE INSERT ON webapp_pvp_rooms BEGIN SELECT RAISE(ABORT,'failure'); END")
            await self.runtime.db().commit()
        with self.assertLogs("aiohttp.server", level="ERROR"):
            response = await self.client.post("/api/pvp/dice/create", json={"bet": 10}, headers=self.headers())
        self.assertEqual(response.status, 500)
        self.assertEqual(await self.balance(), 1000)

    async def test_waiting_room_survives_reinitialization(self):
        self.configure_dice([6, 1])
        room = await self.create()
        await self.backend.initialize_pvp()
        self.assertEqual(await self.balance(), 990)
        rooms = (await self.read("dice/my-rooms"))[1]["rooms"]
        self.assertEqual(rooms[0]["roomId"], room["roomId"])
        self.assertEqual((await self.action("dice", "join", {"roomId": room["roomId"]}, user_id=99))[0], 200)
        self.assertEqual(await self.balance(), 1009.8)

    async def test_unconfigured_telegram_rejects_without_debit(self):
        status, result = await self.action("dice", "create", {"bet": 10})
        self.assertEqual(status, 503, result)
        self.assertEqual(await self.balance(), 1000)

    async def test_settlement_error_rolls_back_then_refunds_without_reroll(self):
        self.configure_dice([6, 1])
        room = await self.create()
        original = self.backend.save_pvp

        async def save(connection, state):
            if state["status"] == "finished":
                raise RuntimeError("Settlement failure")
            await original(connection, state)

        self.backend.save_pvp = save
        with self.assertLogs(level="ERROR"):
            status, result = await self.action("dice", "join", {"roomId": room["roomId"]}, user_id=99)
        self.assertEqual(status, 200, result)
        self.assertFalse(result["ok"])
        self.assertTrue(result["refunded"])
        self.assertEqual(await self.balance(), 1000)
        self.assertEqual(await self.balance(99), 1000)
        self.assertEqual(self.backend.telegram_bot.send_dice.call_count, 2)
        self.assertEqual((await self.action("dice", "join", {"roomId": room["roomId"]}, user_id=99))[0], 409)


class DuelRuleTests(unittest.TestCase):
    def test_rules_and_slot_encoding(self):
        self.assertEqual(slot_reels(1), ["Бар"] * 3)
        self.assertEqual(slot_reels(64), ["Семёрка"] * 3)
        self.assertEqual(len({tuple(slot_reels(value)) for value in range(1, 65)}), 64)
        self.assertEqual(duel_score("darts", 2), duel_score("darts", 3))
        self.assertEqual(duel_score("football", 3), duel_score("football", 5))
        self.assertGreater(duel_score("slots", 1), duel_score("slots", 43))
