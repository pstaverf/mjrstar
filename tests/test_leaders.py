import bundle_test_support  # Register backend modules from server.py.
import json
import secrets
import unittest
from datetime import datetime

from complete_games import CompleteGamesBackend
import test_games_backend as legacy_tests


class LeadersTests(unittest.IsolatedAsyncioTestCase):
    backend_type = CompleteGamesBackend
    asyncSetUp = legacy_tests.GamesBackendTests.asyncSetUp
    asyncTearDown = legacy_tests.GamesBackendTests.asyncTearDown
    headers = legacy_tests.GamesBackendTests.headers

    async def leaders(self, query="", user_id=42):
        response = await self.client.get("/api/leaders?" + query, headers=self.headers(user_id))
        return response.status, await response.json()

    async def round(self, user_id, bet, paid, when, name="Player"):
        key = secrets.token_hex(16)
        async with self.runtime._db_lock:
            await self.runtime.db().execute("INSERT INTO webapp_rounds(public_id,game,user_id,username,bet_cents,payout_cents,request_id,request_digest,response,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (key, "keno", user_id, name, bet, paid, key, key, "{}", when))
            await self.runtime.db().commit()

    async def test_balance_real_db_and_my_place_outside_top(self):
        await self.runtime.add_balance(99, 500)
        status, result = await self.leaders("category=balance&limit=1")
        self.assertEqual(status, 200, result)
        self.assertEqual(result["rows"][0]["id"], 99)
        self.assertEqual(result["rows"][0]["score"], 1500)
        self.assertEqual(result["myRank"], 2)
        self.assertEqual(result["myScore"], 1000)
        self.assertEqual(len(result["rows"]), 1)

    async def test_net_win_loss_counts_and_turnover(self):
        for bet, paid in ((1000, 2000), (1000, 400), (1000, 1000), (1000, 0)):
            await self.round(42, bet, paid, "2026-11-07T12:00:00+03:00")
        for category, metric, expected in (("turnover", "sum", 40), ("wins", "sum", 10), ("wins", "count", 1), ("losses", "sum", 16), ("losses", "count", 2)):
            with self.subTest(category=category, metric=metric):
                status, result = await self.leaders(f"category={category}&metric={metric}&period=all")
                self.assertEqual(status, 200, result)
                self.assertEqual(result["myScore"], expected)
                self.assertEqual(result["rows"][0]["score"], expected)

    async def test_periods_timezone_and_inclusive_custom_end(self):
        self.backend.clock = lambda: datetime.fromisoformat("2026-11-07T12:00:00+03:00")
        for day in ("2026-10-31", "2026-11-01", "2026-11-02", "2026-11-06", "2026-11-07"):
            await self.round(42, 1000, 0, day + "T12:00:00+03:00")
        await self.round(42, 1000, 0, "2026-11-07T23:59:59+03:00")
        await self.round(42, 1000, 0, "2026-11-06T22:00:00+00:00")
        for period, expected in (("today", 30), ("yesterday", 10), ("week", 50), ("month", 60), ("all", 70)):
            status, result = await self.leaders("category=turnover&period=" + period)
            self.assertEqual(status, 200, result)
            self.assertEqual(result["myScore"], expected, period)
        status, result = await self.leaders("category=turnover&period=custom&from=2026-11-06&to=2026-11-07")
        self.assertEqual(status, 200, result)
        self.assertEqual(result["myScore"], 40)

    async def test_bot_history_and_real_names_are_included(self):
        await self.runtime.init_dice_history()
        await self.runtime.init_transfer_tables()
        async with self.runtime._db_lock:
            connection = self.runtime.db()
            await connection.execute("INSERT INTO usernames(user_id,username,full_name,updated_at) VALUES (42,'actual_user','Имя из базы','2026-11-07')")
            await connection.execute("INSERT INTO dice_history(game,user_id,bet,player_range,dice_value,multiplier,win_amount,won,created_at) VALUES ('cube',42,10,'больше',6,2,20,1,'2026-11-07T12:00:00+03:00')")
            await connection.execute("INSERT INTO crash_games(user_id,server_seed,client_seed,nonce,crash_point,raw_crash_point,bet,multiplier,won,created_at) VALUES (42,'test_seed','test_client',0,3,3,5,2,1,'2026-11-07T12:00:00+03:00')")
            await connection.commit()
        await self.round(42, 1000, 0, "2026-11-07T12:00:00+03:00")
        status, result = await self.leaders("category=turnover&period=all")
        self.assertEqual(status, 200, result)
        self.assertEqual(result["myScore"], 25)
        self.assertEqual(result["rows"][0]["username"], "Имя из базы")
        self.assertEqual((await self.leaders("category=wins&metric=sum"))[1]["myScore"], 15)

    async def test_pvp_winner_loser_and_draw_count_once(self):
        async with self.runtime._db_lock:
            connection = self.runtime.db()
            for room_id, draw in (("P_WIN", False), ("P_DRAW", True)):
                state = {"roomId": room_id, "creatorId": 42, "opponentId": 99, "creatorName": "Creator", "opponentName": "Opponent", "_betCents": 1000, "winAmount": 10 if draw else 19.8, "winnerId": None if draw else 42, "isDraw": draw, "finishedAt": "2026-11-07T12:00:00+03:00"}
                await connection.execute("INSERT INTO webapp_pvp_rooms(id,game,creator_id,opponent_id,status,data) VALUES (?,?,?,?,?,?)", (room_id, "dice", 42, 99, "finished", json.dumps(state)))
            await connection.commit()
        self.assertEqual((await self.leaders("category=turnover"))[1]["myScore"], 20)
        self.assertEqual((await self.leaders("category=wins&metric=count"))[1]["myScore"], 1)
        self.assertEqual((await self.leaders("category=wins&metric=sum"))[1]["myScore"], 9.8)
        self.assertEqual((await self.leaders("category=losses&metric=sum", 99))[1]["myScore"], 10)

    async def test_validation_empty_scores_and_deterministic_ties(self):
        status, empty = await self.leaders("category=turnover")
        self.assertEqual(status, 200)
        self.assertEqual(empty["rows"], [])
        self.assertIsNone(empty["myRank"])
        self.assertEqual(empty["myScore"], 0)
        for query in ("category=unknown", "period=bad", "metric=unknown", "limit=1000", "period=custom&from=2026-11-07&to=2026-11-01", "period=custom&from=bad&to=2026-11-01", "period=custom&from=20261107&to=20261107", "period=custom&from=9999-12-31&to=9999-12-31"):
            self.assertEqual((await self.leaders(query))[0], 400, query)
        result = (await self.leaders("category=balance"))[1]
        self.assertEqual([row["id"] for row in result["rows"]], [42, 99])
        response = await self.client.get("/api/leaders")
        self.assertEqual(response.status, 401)
        response = await self.client.get("/api/leaders?uid=99", headers=self.headers())
        self.assertEqual(response.status, 403)
