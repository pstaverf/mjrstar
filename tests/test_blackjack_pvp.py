import asyncio
import hashlib
import json
import secrets
import time
import unittest

from complete_games import CompleteGamesBackend
from game_rules import deck_for, hand_total
import test_games_backend as legacy_tests
import test_pvp_games as pvp_tests


class BlackjackPvpTests(unittest.IsolatedAsyncioTestCase):
    backend_type = CompleteGamesBackend
    asyncSetUp = legacy_tests.GamesBackendTests.asyncSetUp
    asyncTearDown = legacy_tests.GamesBackendTests.asyncTearDown
    headers = legacy_tests.GamesBackendTests.headers
    action = pvp_tests.PvpGamesTests.action
    read = pvp_tests.PvpGamesTests.read
    balance = pvp_tests.PvpGamesTests.balance
    create = pvp_tests.PvpGamesTests.create

    async def set_deck(self, room_id, predicate):
        while True:
            seed = secrets.token_hex(32)
            deck = deck_for(seed, room_id)
            if predicate(deck):
                break
        async with self.runtime._db_lock:
            connection = self.runtime.db()
            async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ?", (room_id,)) as cursor:
                state = json.loads((await cursor.fetchone())[0])
            state.update({"_seed": seed, "seedHash": hashlib.sha256(seed.encode()).hexdigest()})
            await self.backend.save_pvp(connection, state)
            await connection.commit()
        return seed, deck

    async def state(self, room_id, user_id=42):
        response = await self.client.get("/api/pvp/blackjack/state?roomId=" + room_id, headers=self.headers(user_id))
        self.assertEqual(response.status, 200)
        return await response.json()

    async def prepare(self, predicate=None):
        room = await self.create("blackjack")
        seed, deck = await self.set_deck(room["roomId"], predicate or (lambda cards: hand_total(cards[:4:2]) < 21 and hand_total(cards[1:4:2]) < 21))
        status, joined = await self.action("blackjack", "join", {"roomId": room["roomId"]}, user_id=99)
        self.assertEqual(status, 200, joined)
        return room["roomId"], seed, deck, joined

    async def test_deal_commit_and_stand_settlement(self):
        room_id, seed, deck, state = await self.prepare()
        self.assertEqual(state["status"], "playing")
        self.assertEqual(state["youAre"], "opponent")
        self.assertTrue(state["canAct"])
        self.assertEqual(state["creatorCards"], [deck[0], deck[2]])
        self.assertEqual(state["opponentCards"], [deck[1], deck[3]])
        self.assertEqual(state["seedHash"], hashlib.sha256(seed.encode()).hexdigest())
        for key in ("serverSeed", "_seed", "_deck", "_cursor"):
            self.assertNotIn(key, state)
        status, first = await self.action("blackjack", "stand", {"roomId": room_id, "version": 0})
        self.assertEqual(status, 200, first)
        self.assertEqual(first["status"], "playing")
        self.assertFalse(first["canAct"])
        status, final = await self.action("blackjack", "stand", {"roomId": room_id, "version": 0}, user_id=99)
        self.assertEqual(status, 200, final)
        self.assertEqual(final["status"], "finished")
        self.assertEqual(final["serverSeed"], seed)
        self.assertEqual(final["totalBank"], 20)
        if final["isDraw"]:
            self.assertEqual(await self.balance(), 1000)
            self.assertEqual(await self.balance(99), 1000)
        else:
            self.assertEqual(final["winAmount"], 19.8)
            self.assertEqual(final["feeAmount"], 0.2)
            self.assertEqual(await self.balance(final["winnerId"]), 1009.8)
        self.assertEqual((await self.read("blackjack/round?id=" + room_id))[1]["serverSeed"], seed)

    async def test_hit_replay_stale_version_and_foreign_hand(self):
        room_id, seed, deck, state = await self.prepare(lambda cards: hand_total(cards[:4:2]) <= 12 and hand_total(cards[1:4:2]) < 21 and hand_total([cards[0], cards[2], cards[4]]) < 21)
        key = secrets.token_hex(16)
        results = await asyncio.gather(*(self.action("blackjack", "hit", {"roomId": room_id, "version": 0}, key=key) for _ in range(8)))
        self.assertTrue(all(status == 200 for status, _ in results), results)
        self.assertEqual(results[0][1]["creatorCards"], [deck[0], deck[2], deck[4]])
        self.assertEqual(results[0][1]["version"], 1)
        self.assertEqual((await self.action("blackjack", "hit", {"roomId": room_id, "version": 0}))[0], 409)
        self.assertEqual(len((await self.state(room_id))["creatorCards"]), 3)
        self.assertEqual((await self.action("blackjack", "hit", {"roomId": room_id, "version": True}))[0], 409)
        await self.runtime.add_balance(77, 1000)
        self.assertEqual((await self.action("blackjack", "stand", {"roomId": room_id, "version": 0}, user_id=77))[0], 403)
        self.assertEqual((await self.action("blackjack", "hit", {"roomId": [], "version": 0}))[0], 400)

    async def test_double_draw_refunds_each_actual_stake(self):
        room_id, seed, deck, state = await self.prepare(lambda cards: hand_total(cards[:4:2]) < 21 and hand_total(cards[1:4:2]) < 21 and hand_total([cards[0], cards[2], cards[4]]) == hand_total(cards[1:4:2]))
        key = secrets.token_hex(16)
        status, doubled = await self.action("blackjack", "double", {"roomId": room_id, "version": 0}, key=key)
        self.assertEqual(status, 200, doubled)
        self.assertEqual(doubled["balance"], 980)
        self.assertTrue(doubled["creatorDoubled"])
        self.assertTrue(doubled["creatorDone"])
        self.assertEqual(len(doubled["creatorCards"]), 3)
        self.assertEqual((await self.action("blackjack", "double", {"roomId": room_id, "version": 0}, key=key))[1]["balance"], 980)
        status, final = await self.action("blackjack", "stand", {"roomId": room_id, "version": 0}, user_id=99)
        self.assertEqual(status, 200, final)
        self.assertTrue(final["isDraw"])
        self.assertEqual(final["creatorRefund"], 20)
        self.assertEqual(final["opponentRefund"], 10)
        self.assertEqual(final["feeAmount"], 0)
        self.assertEqual(await self.balance(), 1000)
        self.assertEqual(await self.balance(99), 1000)

    async def test_double_insufficient_balance_rolls_back_card(self):
        room_id, seed, deck, state = await self.prepare()
        await self.runtime.add_balance(42, -990)
        self.assertEqual((await self.action("blackjack", "double", {"roomId": room_id, "version": 0}))[0], 400)
        state = await self.state(room_id)
        self.assertFalse(state["creatorDoubled"])
        self.assertEqual(len(state["creatorCards"]), 2)
        self.assertEqual(state["version"], 0)

    async def test_two_naturals_finish_with_full_refund(self):
        room_id, seed, deck, joined = await self.prepare(lambda cards: hand_total(cards[:4:2]) == 21 and hand_total(cards[1:4:2]) == 21)
        self.assertEqual(joined["status"], "finished")
        self.assertTrue(joined["isDraw"])
        self.assertEqual(await self.balance(), 1000)
        self.assertEqual(await self.balance(99), 1000)
        self.assertEqual((await self.action("blackjack", "hit", {"roomId": room_id, "version": 0}))[0], 409)

    async def test_resume_and_timeout_settles_only_once(self):
        room_id, seed, deck, state = await self.prepare()
        await self.backend.initialize_pvp()
        self.assertEqual((await self.state(room_id))["creatorCards"], [deck[0], deck[2]])
        async with self.runtime._db_lock:
            connection = self.runtime.db()
            async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ?", (room_id,)) as cursor:
                state = json.loads((await cursor.fetchone())[0])
            state.update({"creatorDeadline": time.time() - 1, "opponentDeadline": time.time() - 1})
            await self.backend.save_pvp(connection, state)
            await connection.commit()
        final = await self.state(room_id)
        self.assertEqual(final["status"], "finished")
        self.assertTrue(final["creatorTimedOut"])
        before = [await self.balance(), await self.balance(99)]
        await self.state(room_id)
        self.assertEqual(before, [await self.balance(), await self.balance(99)])

    async def test_double_winner_pays_99_percent_of_actual_bank(self):
        room_id, seed, deck, state = await self.prepare(lambda cards: hand_total(cards[:4:2]) < 21 and hand_total(cards[1:4:2]) < hand_total([cards[0], cards[2], cards[4]]) <= 21)
        status, result = await self.action("blackjack", "double", {"roomId": room_id, "version": 0})
        self.assertEqual(status, 200, result)
        key = secrets.token_hex(16)
        results = await asyncio.gather(*(self.action("blackjack", "stand", {"roomId": room_id, "version": 0}, user_id=99, key=key) for _ in range(8)))
        self.assertTrue(all(status == 200 for status, _ in results))
        final = results[0][1]
        self.assertEqual(final["winnerId"], 42)
        self.assertEqual(final["totalBank"], 30)
        self.assertEqual(final["winAmount"], 29.7)
        self.assertEqual(final["feeAmount"], 0.3)
        self.assertEqual(await self.balance(), 1009.7)
        self.assertEqual(await self.balance(99), 990)

    async def test_cancel_join_race_and_self_join(self):
        room = await self.create("blackjack")
        self.assertEqual((await self.action("blackjack", "join", {"roomId": room["roomId"]}))[0], 400)
        results = await asyncio.gather(self.action("blackjack", "cancel", {"roomId": room["roomId"]}), self.action("blackjack", "join", {"roomId": room["roomId"]}, user_id=99))
        self.assertEqual(sum(status == 200 for status, _ in results), 1)
        state = await self.state(room["roomId"])
        if state["status"] == "canceled":
            self.assertEqual(await self.balance(), 1000)
            self.assertEqual(await self.balance(99), 1000)
        else:
            self.assertIn(state["status"], {"playing", "finished"})
            self.assertEqual((await self.action("blackjack", "cancel", {"roomId": room["roomId"]}))[0], 409)
