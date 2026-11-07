import asyncio
import json
import secrets
import unittest
from itertools import product
from types import SimpleNamespace
from unittest.mock import AsyncMock

from complete_games import CompleteGamesBackend
from emoji_rules import EMOJI_CATALOG, EMOJI_FACES, EMOJI_GAMES, emoji_rule
import test_games_backend as legacy_tests
import test_pvp_games as pvp_tests


class EmojiRulesTests(unittest.TestCase):
    def test_entire_catalog_has_valid_server_rules(self):
        for game, outcomes in EMOJI_CATALOG.items():
            for outcome in outcomes:
                with self.subTest(game=game, outcome=outcome):
                    count, settle, maximum = emoji_rule(game, outcome)
                    self.assertIn(count, {1, 2, 3})
                    self.assertGreater(maximum, 0)
                    if game != "slots":
                        payments = [settle(values) for values in product(range(1, EMOJI_FACES[game] + 1), repeat=count)]
                        self.assertLessEqual(sum(payments), 90 * len(payments))
                        self.assertGreater(sum(payments), 85 * len(payments))
                        self.assertEqual(max(payments), max(maximum, 100) if outcome.startswith("Дуэль") else maximum)

    def test_dice_dynamic_and_ladder(self):
        cases = [("Точный исход 2к:1|6", [1, 6], [6, 1]), ("Точный исход 3к:1|2|3", [1, 2, 3], [3, 2, 1]), ("Дубль:1,2", [2, 2], [2, 1]), ("Трипл:6", [6, 6, 6], [6, 6, 1]), ("Хотя бы:6", [1, 6], [1, 2]), ("Итог 2к:2,12", [6, 6], [1, 2]), ("Сумма 2к:›7", [5, 5], [1, 2]), ("Коридор 3к:3-5", [1, 1, 1], [6, 6, 6]), ("Стрит:asc|123", [1, 2, 3], [3, 2, 1]), ("Комбинация:1,2,3", [3, 1, 2], [1, 1, 2])]
        for outcome, won, lost in cases:
            with self.subTest(outcome=outcome):
                count, settle, maximum = emoji_rule("dice", outcome)
                self.assertEqual(settle(won), maximum)
                self.assertEqual(settle(lost), 0)
        for outcome in ("Лесенка низкий риск", "Лесенка высокий риск"):
            _, settle, _ = emoji_rule("dice", outcome)
            self.assertLessEqual(sum(settle([face]) for face in range(1, 7)), 540)

    def test_slots_exact_counts_and_real_reel_order(self):
        cases = [("Точный исход:Бар|Виноград|Лимон", [37], [1]), ("Комбинация:Бар,Виноград,Лимон", [37], [1]), ("Кол-во:Бар:2", [2], [1]), ("Дуэль:Семёрка:>", [64, 1], [1, 64]), ("3 Семёрки", [64], [1]), ("7 в каждом x3", [64, 64, 64], [64, 1, 64])]
        for outcome, won, lost in cases:
            with self.subTest(outcome=outcome):
                count, settle, maximum = emoji_rule("slots", outcome)
                self.assertEqual(settle(won), maximum)
                self.assertEqual(settle(lost), 0)
        for outcome in ("Лесенка", "Копилка", "Лаки 7"):
            count, settle, maximum = emoji_rule("slots", outcome)
            payouts = [settle(values) for values in product(range(1, 65), repeat=count)]
            self.assertLessEqual(sum(payouts), 90 * len(payouts))
            self.assertEqual(max(payouts), maximum)

    def test_invalid_outcomes_rejected(self):
        for game, outcome in [("dice", "not an outcome"), ("dice", "Хотя бы:1,1"), ("dice", "Итог 2к:99"), ("dice", "Точный исход 2к:1"), ("dice", "Стрит:asc|789"), ("slots", "Кол-во:bad:2"), ("slots", "Комбинация:Бар"), ("slots", "Точный исход:||"), ("foot", "Выбор:1,2,3,4,5"), ("basket", "Выбор:6"), ("bowl", "Выбор:0")]:
            with self.subTest(game=game, outcome=outcome):
                from games_backend import GameError
                with self.assertRaises(GameError):
                    emoji_rule(game, outcome)


class EmojiGamesTests(unittest.IsolatedAsyncioTestCase):
    backend_type = CompleteGamesBackend
    asyncSetUp = legacy_tests.GamesBackendTests.asyncSetUp
    asyncTearDown = legacy_tests.GamesBackendTests.asyncTearDown
    headers = legacy_tests.GamesBackendTests.headers
    configure_dice = pvp_tests.PvpGamesTests.configure_dice
    balance = pvp_tests.PvpGamesTests.balance

    async def play(self, game, outcome, bet=10, user_id=42, rid=None, key=None):
        response = await self.client.post(f"/api/{game}/play", json={"uid": user_id, "outcome": outcome, "bet": bet, "rid": rid or secrets.token_hex(16)}, headers=self.headers(user_id, key))
        return response.status, await response.json()

    async def read(self, path, user_id=42):
        response = await self.client.get("/api/" + path, headers=self.headers(user_id))
        return response.status, await response.json()

    async def test_six_real_games_finances_history_and_proofs(self):
        cases = [("dice", "Шесть", 6), ("slots", "3 Семёрки", 64), ("bowl", "Страйк", 6), ("darts", "Центр", 6), ("basket", "Чистый гол", 5), ("foot", "Девятка", 5)]
        expected = 1000
        for game, outcome, value in cases:
            self.configure_dice([value])
            rid = secrets.token_hex(16)
            status, result = await self.play(game, outcome, rid=rid)
            self.assertEqual(status, 200, result)
            multiplier = emoji_rule(game, outcome)[2]
            expected = round(expected - 10 + multiplier / 10, 2)
            self.assertEqual(result["newBalance"], expected)
            self.assertEqual(await self.balance(), expected)
            self.assertTrue(result["win"])
            self.assertEqual(result["checkLinks"], ["https://t.me/mjrstars/100"])
            self.assertEqual(self.backend.telegram_bot.send_dice.call_count, 1)
            rows = (await self.read(game + "/history?scope=mine"))[1]["rows"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(rows[0]["meta"])["outcome"], outcome)
            recovered = (await self.read("play/result?rid=" + rid))[1]
            self.assertEqual(recovered["state"], "done")
            self.assertEqual(recovered["payload"], result)
            self.assertEqual((await self.read("play/result?rid=" + rid, 99))[0], 404)
        off = (await self.read("games/off"))[1]["off"]
        self.assertFalse(set(EMOJI_GAMES).intersection(off))
        leaders = (await self.read("leaders?category=turnover"))[1]
        self.assertEqual(leaders["myScore"], 60)

    async def test_concurrent_replay_sends_only_one_game(self):
        self.configure_dice([6, 5, 4])
        rid, key = secrets.token_hex(16), secrets.token_hex(16)
        results = await asyncio.gather(*(self.play("dice", "Точный исход 3к:6|5|4", rid=rid, key=key) for _ in range(8)))
        self.assertTrue(all(status == 200 for status, result in results), results)
        self.assertEqual(self.backend.telegram_bot.send_dice.call_count, 3)
        self.assertEqual(len(results[0][1]["checkLinks"]), 3)
        self.assertEqual(await self.balance(), 2934)
        replay = await self.play("dice", "Точный исход 3к:6|5|4", rid=rid)
        self.assertEqual(replay[1]["roundId"], results[0][1]["roundId"])
        self.assertEqual(self.backend.telegram_bot.send_dice.call_count, 3)
        self.assertEqual((await self.play("dice", "Шесть", rid=rid))[0], 409)
        self.assertEqual((await self.play("dice", "Шесть", rid=secrets.token_hex(16), key=key))[0], 409)

    async def test_loss_draw_and_partial_refund(self):
        self.configure_dice([1])
        result = (await self.play("dice", "Шесть"))[1]
        self.assertFalse(result["win"])
        self.assertEqual(result["newBalance"], 990)
        self.configure_dice([4, 4])
        result = (await self.play("dice", "Дуэль"))[1]
        self.assertTrue(result["isDraw"])
        self.assertEqual(result["winAmount"], 10)
        self.assertEqual(await self.balance(), 990)
        self.configure_dice([2])
        result = (await self.play("foot", "Лесенка"))[1]
        self.assertGreater(result["refund"], 0)
        self.assertLess(result["refund"], 10)
        self.assertEqual(await self.balance(), round(980 + result["refund"], 2))

    async def test_failed_second_throw_refunds_without_reroll(self):
        self.configure_dice([6])
        rid, key = secrets.token_hex(16), secrets.token_hex(16)
        with self.assertLogs(level="ERROR"):
            result = (await self.play("dice", "Точный исход 2к:6|6", rid=rid, key=key))[1]
        self.assertFalse(result["ok"])
        self.assertTrue(result["refunded"])
        self.assertEqual(await self.balance(), 1000)
        self.assertEqual((await self.read("play/result?rid=" + rid))[1]["state"], "cancelled")
        self.assertFalse((await self.play("dice", "Точный исход 2к:6|6", rid=rid, key=key))[1]["ok"])
        self.assertEqual(self.backend.telegram_bot.send_dice.call_count, 2)
        self.assertEqual((await self.read("dice/history"))[1]["rows"], [])

    async def test_validation_auth_and_no_channel(self):
        self.configure_dice([])
        for outcome, bet in [("unknown", 10), ("Шесть", 0), ("Шесть", -1), ("Шесть", "NaN"), ("Шесть", 1000001), ("Шесть", 1001), ([], 10)]:
            self.assertEqual((await self.play("dice", outcome, bet))[0], 400)
        self.assertEqual(await self.balance(), 1000)
        response = await self.client.post("/api/dice/play", json={"outcome": "Шесть", "bet": 10})
        self.assertEqual(response.status, 401)
        self.backend.telegram_bot = None
        self.assertEqual((await self.play("dice", "Шесть"))[0], 503)
        self.assertIn("dice", (await self.read("games/off"))[1]["off"])

    async def test_quotes_and_published_paytables_match_settlement(self):
        for game in EMOJI_GAMES:
            status, data = await self.read(game + "/multipliers")
            self.assertEqual(status, 200, data)
            for outcome, count in EMOJI_CATALOG[game].items():
                self.assertEqual(data["multipliers"][outcome], emoji_rule(game, outcome)[2] / 100)
        for game, outcome in [("dice", "Дубль:1,2"), ("slots", "Кол-во:Бар:2"), ("basket", "Выбор:1,2"), ("darts", "Лесенка")]:
            from urllib.parse import urlencode
            status, quote = await self.read(game + "/quote?" + urlencode({"outcome": outcome}))
            self.assertEqual(status, 200, quote)
            self.assertEqual(quote["multiplier"], emoji_rule(game, outcome)[2] / 100)
        slots = (await self.read("slots/multipliers"))[1]["paytables"]
        for count, values in {3: [64, 1], 4: [64, 4], 5: [64, 16], 6: [64, 64]}.items():
            self.assertEqual(slots["lucky"]["table"][str(count)], emoji_rule("slots", "Лаки 7")[1](values) / 100)

    async def test_database_failure_rolls_back_payout_and_refunds(self):
        self.configure_dice([6])
        async with self.runtime._db_lock:
            await self.runtime.db().execute("CREATE TRIGGER fail_emoji_insert BEFORE INSERT ON webapp_rounds WHEN NEW.game = 'dice' BEGIN SELECT RAISE(ABORT,'write failed'); END")
            await self.runtime.db().commit()
        with self.assertLogs(level="ERROR"):
            result = (await self.play("dice", "Шесть"))[1]
        self.assertTrue(result["refunded"])
        self.assertEqual(await self.balance(), 1000)
        self.assertEqual(self.backend.telegram_bot.send_dice.call_count, 1)

    async def test_restart_refunds_pending_once_and_never_rolls_again(self):
        from games_backend import serialize
        self.configure_dice([])
        rid, key = secrets.token_hex(16), secrets.token_hex(16)
        state = {"status": "pending", "userId": 42, "game": "dice", "rid": rid, "roundId": "T" + secrets.token_hex(12).upper(), "_key": key, "_signature": "digest", "_betCents": 1000}
        async with self.runtime._db_lock:
            connection = self.runtime.db()
            await self.backend.debit(connection, 42, 1000)
            await self.backend.save_receipt(connection, 42, key, "digest", {"ok": True, "pending": True})
            await connection.execute("INSERT INTO webapp_emoji_jobs(user_id,rid,game,status,data) VALUES (42,?,'dice','pending',?)", (rid, serialize(state)))
            await connection.commit()
        self.assertEqual(await self.balance(), 990)
        await self.backend.initialize_emoji()
        await self.backend.initialize_emoji()
        self.assertEqual(await self.balance(), 1000)
        self.assertEqual((await self.read("play/result?rid=" + rid))[1]["state"], "cancelled")
        self.assertEqual(self.backend.telegram_bot.send_dice.call_count, 0)

    async def test_pending_round_does_not_hold_database_lock_or_allow_second_bet(self):
        entered, released = asyncio.Event(), asyncio.Event()
        async def send(**kwargs):
            entered.set()
            await released.wait()
            return SimpleNamespace(dice=SimpleNamespace(value=6), chat=SimpleNamespace(id=-100123456, username="mjrstars"), message_id=101)
        self.configure_dice([])
        self.backend.telegram_bot.send_dice = AsyncMock(side_effect=send)
        rid = secrets.token_hex(16)
        task = asyncio.create_task(self.play("dice", "Шесть", rid=rid))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            self.assertEqual(await asyncio.wait_for(self.balance(), 2), 990)
            self.assertEqual((await self.read("play/result?rid=" + rid))[1]["state"], "pending")
            self.assertEqual((await self.play("bowl", "Страйк"))[0], 409)
            self.assertEqual(await self.balance(), 990)
        finally:
            released.set()
            status, result = await task
        self.assertEqual(status, 200, result)
        self.assertEqual(await self.balance(), 1044)
        self.assertEqual(self.backend.telegram_bot.send_dice.call_count, 1)
