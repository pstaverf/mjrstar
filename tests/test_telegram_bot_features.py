import bundle_test_support
import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import unittest

from aiogram.enums import ChatType
from aiogram.methods import SendMessage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from complete_games import CompleteGamesBackend
import test_games_backend as fixtures


class TelegramBotFeatureTests(unittest.IsolatedAsyncioTestCase):
    backend_type = CompleteGamesBackend
    asyncSetUp = fixtures.GamesBackendTests.asyncSetUp
    asyncTearDown = fixtures.GamesBackendTests.asyncTearDown

    async def test_group_referrals_are_per_chat_and_do_not_replace_regular_referrer(self):
        async with self.runtime._db_lock:
            await self.runtime.db().execute(
                "INSERT INTO referrals(user_id,referrer_id,joined_at) VALUES (?,?,?)",
                (42, 7, self.runtime.now_msk().isoformat()),
            )
            await self.runtime.db().commit()

        refresh = AsyncMock(return_value=99)
        member = SimpleNamespace(
            id=42, is_bot=False, username="player", first_name="Test", last_name="User"
        )
        with patch.object(self.runtime, "refresh_telegram_group_owner", refresh):
            await self.runtime.record_telegram_group_members(
                AsyncMock(), -1001001, "First chat", [member, member]
            )
            await self.runtime.record_telegram_group_members(
                AsyncMock(), -1001002, "Second chat", [member]
            )

        async with self.runtime.db().execute(
            "SELECT chat_id,user_id,referrer_id FROM telegram_group_referrals ORDER BY chat_id"
        ) as cursor:
            self.assertEqual(
                await cursor.fetchall(),
                [(-1001002, 42, 99), (-1001001, 42, 99)],
            )
        async with self.runtime.db().execute(
            "SELECT referrer_id FROM referrals WHERE user_id=42"
        ) as cursor:
            self.assertEqual((await cursor.fetchone())[0], 7)
        self.assertEqual(refresh.await_count, 2)

    async def test_group_loss_credit_is_exact_idempotent_and_uses_each_chat_owner(self):
        connection = self.runtime.db()
        async with self.runtime._db_lock:
            await connection.execute(
                "INSERT INTO telegram_group_owners(chat_id,owner_id,chat_title,updated_at) VALUES (?,?,?,?)",
                (-1001001, 99, "First chat", self.runtime.now_msk().isoformat()),
            )
            await connection.execute(
                "INSERT INTO telegram_group_owners(chat_id,owner_id,chat_title,updated_at) VALUES (?,?,?,?)",
                (-1001002, 77, "Second chat", self.runtime.now_msk().isoformat()),
            )
            await connection.execute(
                "INSERT INTO ref_balance(user_id,signup_earned,deposit_earned,group_earned,frozen) VALUES (99,1,2,0.15,1)"
            )
            await connection.commit()

            # A three-cent net loss pays half rounded half-up to the nearest cent.
            self.assertEqual(
                await self.runtime.credit_telegram_group_loss(
                    connection, -1001001, 42, "10.03", "10.00", "stable:game:1"
                ),
                2,
            )
            # Re-delivering the same settlement does not create another reward/event.
            self.assertEqual(
                await self.runtime.credit_telegram_group_loss(
                    connection, -1001001, 42, "100", 0, "stable:game:1"
                ),
                0,
            )
            self.assertEqual(
                await self.runtime.credit_telegram_group_loss(
                    connection, -1001001, 42, 5, 5, "stable:game:draw"
                ),
                0,
            )
            self.assertEqual(
                await self.runtime.credit_telegram_group_loss(
                    connection, 42, 42, 5, 0, "stable:private-chat"
                ),
                0,
            )
            self.assertEqual(
                await self.runtime.credit_telegram_group_loss(
                    connection, -1001002, 42, 10, 4, "stable:game:2"
                ),
                300,
            )
            await connection.commit()

        async with connection.execute(
            "SELECT owner_id,loss_cents,share_cents FROM telegram_group_loss_rewards ORDER BY source"
        ) as cursor:
            self.assertEqual(await cursor.fetchall(), [(99, 3, 2), (77, 600, 300)])
        async with connection.execute(
            "SELECT user_id,signup_earned,deposit_earned,group_earned,frozen FROM ref_balance ORDER BY user_id"
        ) as cursor:
            self.assertEqual(await cursor.fetchall(), [(77, 0.0, 0.0, 3.0, 0), (99, 1.0, 2.0, 0.17, 1)])
        async with connection.execute("SELECT COUNT(*) FROM webapp_ref_events") as cursor:
            self.assertEqual((await cursor.fetchone())[0], 2)

    async def test_game_result_writer_reuses_stable_idempotency_source(self):
        connection = self.runtime.db()
        async with self.runtime._db_lock:
            await connection.execute(
                "INSERT INTO telegram_group_owners(chat_id,owner_id,chat_title,updated_at) VALUES (?,?,?,?)",
                (-1001001, 99, "Test chat", self.runtime.now_msk().isoformat()),
            )
            await connection.commit()

        # A redelivered result may add history rows in legacy storage, but its
        # referral payout must remain keyed to the original Telegram message.
        for _ in range(2):
            await self.runtime.save_football_game(
                42,
                4,
                "центр",
                "мимо",
                0,
                0,
                False,
                chat_id=-1001001,
                idempotency_key="-1001001:845",
            )
        async with connection.execute(
            "SELECT COUNT(*),SUM(share_cents) FROM telegram_group_loss_rewards"
        ) as cursor:
            self.assertEqual(await cursor.fetchone(), (1, 200))
        async with connection.execute(
            "SELECT group_earned FROM ref_balance WHERE user_id=99"
        ) as cursor:
            self.assertEqual((await cursor.fetchone())[0], 2)

    def test_profile_and_leaderboard_buttons_are_fully_localized(self):
        profile = self.runtime.telegram_profile_markup("en")
        self.assertEqual(
            [button.text for button in profile.inline_keyboard[0]],
            ["Deposit", "Withdraw"],
        )
        self.assertTrue(all(button.style is None for button in profile.inline_keyboard[0]))
        self.assertEqual(
            [button.text for button in profile.inline_keyboard[3]],
            ["Russian", "English"],
        )
        self.assertEqual(profile.inline_keyboard[3][1].style, "primary")
        self.assertIsNone(profile.inline_keyboard[3][0].style)

        localized_markups = (
            self.runtime.telegram_home_markup("en"),
            self.runtime.telegram_earn_markup("en"),
            self.runtime.telegram_settings_markup("nickname", True, "en"),
            self.runtime.telegram_transactions_markup("withdrawal", 1, 2, "en"),
        )
        for markup in localized_markups:
            for row in markup.inline_keyboard:
                for button in row:
                    self.assertNotRegex(button.text, r"[А-Яа-яЁё]")

        chooser = self.runtime.telegram_top_category_markup("en")
        self.assertEqual(
            [button.text for button in chooser.inline_keyboard[0]],
            ["Top players", "Top chats"],
        )
        self.assertEqual(
            [button.icon_custom_emoji_id for button in chooser.inline_keyboard[0]],
            ["5098271397491246244", "5891169510483823323"],
        )
        self.assertEqual(chooser.inline_keyboard[0][0].callback_data, "tg_top:players:all")
        self.assertEqual(chooser.inline_keyboard[0][1].callback_data, "tg_top:chats:all")
        self.assertEqual(chooser.inline_keyboard[1][0].text, "Back")

        page = self.runtime.telegram_top_markup("players", "yesterday", "en")
        self.assertEqual(page.inline_keyboard[0][0].style, "primary")
        self.assertIsNone(page.inline_keyboard[0][1].style)
        self.assertEqual(page.inline_keyboard[0][0].callback_data, "tg_top:players:yesterday")
        self.assertEqual(page.inline_keyboard[0][1].callback_data, "tg_top:chats:yesterday")
        self.assertEqual(
            [button.text for button in page.inline_keyboard[1]],
            ["All time", "Today"],
        )
        self.assertEqual(
            [button.text for button in page.inline_keyboard[2]],
            ["• Yesterday •", "Week", "Month"],
        )
        self.assertTrue(
            all(button.style is None for row in page.inline_keyboard[1:3] for button in row)
        )
        self.assertNotIn("success", [button.style for row in page.inline_keyboard for button in row])

    async def test_telegram_leaderboards_use_turnover_and_deduplicate_group_events(self):
        self.runtime._wallet_backend = self.backend
        self.runtime.TELEGRAM_TOP_CACHE.clear()
        connection = self.runtime.db()
        stamp = self.runtime.now_msk().isoformat()
        async with self.runtime._db_lock:
            await connection.execute(
                "INSERT INTO telegram_group_owners(chat_id,owner_id,chat_title,updated_at) VALUES (?,?,?,?)",
                (-1001001, 99, "Alpha & <Club>", stamp),
            )
            await connection.execute(
                "INSERT INTO usernames(user_id,username,full_name,updated_at) VALUES (?,?,?,?)",
                (42, "alice", "Alice & One", stamp),
            )
            await connection.commit()

        await self.runtime.save_football_game(
            42,
            10,
            "центр",
            "мимо",
            0,
            0,
            False,
            chat_id=-1001001,
            idempotency_key="-1001001:900",
        )
        async with self.runtime._db_lock:
            duplicate = await self.runtime.record_telegram_group_game(
                connection,
                -1001001,
                42,
                200,
                "bot:football:-1001001:900",
                stamp,
            )
            await connection.commit()
        self.assertFalse(duplicate)

        players = await self.runtime.telegram_top_data("players", "all", 42)
        chats = await self.runtime.telegram_top_data("chats", "all", 42)
        self.assertEqual(players["rows"][0]["score_cents"], 1000)
        self.assertEqual(players["rows"][0]["name_fallback"], "Alice & One")
        self.assertEqual(players["my_score_cents"], 1000)
        self.assertEqual(players["my_rank"], 1)
        self.assertEqual(chats["rows"][0]["score_cents"], 1000)
        self.assertEqual(chats["rows"][0]["title"], "Alpha & <Club>")

        player_text = self.runtime.telegram_top_text("players", "all", players, "en")
        self.assertIn("Top players by turnover for “all time”", player_text)
        self.assertIn("<b>Alice &amp; One</b>: 10", player_text)
        self.assertIn("Your turnover: <b>10</b>", player_text)
        self.assertIn("rank: <b>1</b>", player_text)
        self.assertIn("5451986538709686533", player_text)
        chat_text = self.runtime.telegram_top_text("chats", "all", chats, "en")
        self.assertIn("Top chats by turnover for “all time”", chat_text)
        self.assertIn("<b>Alpha &amp; &lt;Club&gt;</b>: 10", chat_text)
        self.assertNotIn("Your turnover", chat_text)

    def test_known_user_facing_fallback_phrases_are_natural_english(self):
        examples = {
            "По вашей ссылке зашёл новый пользователь: ":
                "A new user joined using your referral link: ",
            "Произошла ошибка, попробуйте ещё раз.":
                "Something went wrong. Please try again.",
            "нельзя переводить самому себе.":
                "You cannot transfer money to yourself.",
            "добро пожаловать в MajorStars": "welcome to MajorStars",
        }
        for source, expected in examples.items():
            with self.subTest(source=source):
                self.assertEqual(
                    self.runtime.translate_telegram_text(source, "en"), expected
                )

    def test_every_builtin_game_quote_has_an_exact_english_translation(self):
        def collect_strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for item in value.values():
                    yield from collect_strings(item)
            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    yield from collect_strings(item)

        quotes = set()
        for name, value in vars(self.runtime).items():
            if "QUOTE" in name and isinstance(value, (dict, list, tuple)):
                quotes.update(
                    text
                    for text in collect_strings(value)
                    if re.search(r"[А-Яа-яЁё]", text)
                )

        self.assertGreater(len(quotes), 0)
        for quote in sorted(quotes):
            with self.subTest(quote=quote):
                self.assertIn(quote, self.runtime.RU_EN_PHRASES)
                self.assertNotRegex(
                    self.runtime.translate_telegram_text(quote, "en"),
                    r"[А-Яа-яЁё]",
                )

    async def test_group_loss_failure_rolls_back_partial_credit_and_game_history(self):
        connection = self.runtime.db()
        async with self.runtime._db_lock:
            await connection.execute(
                "INSERT INTO telegram_group_owners(chat_id,owner_id,chat_title,updated_at) VALUES (?,?,?,?)",
                (-1001001, 99, "Test chat", self.runtime.now_msk().isoformat()),
            )
            await connection.execute(
                "CREATE TRIGGER fail_group_loss_event BEFORE INSERT ON webapp_ref_events "
                "WHEN NEW.kind='group_loss' BEGIN SELECT RAISE(ABORT,'simulated event failure'); END"
            )
            await connection.commit()

        with self.assertRaises(Exception):
            await self.runtime.save_football_game(
                42,
                4,
                "центр",
                "мимо",
                0,
                0,
                False,
                chat_id=-1001001,
                idempotency_key="-1001001:846",
            )

        async with connection.execute(
            "SELECT COUNT(*) FROM football_history WHERE user_id=42"
        ) as cursor:
            self.assertEqual((await cursor.fetchone())[0], 0)
        async with connection.execute(
            "SELECT COUNT(*) FROM telegram_group_loss_rewards"
        ) as cursor:
            self.assertEqual((await cursor.fetchone())[0], 0)
        async with connection.execute(
            "SELECT COUNT(*) FROM ref_balance WHERE user_id=99"
        ) as cursor:
            self.assertEqual((await cursor.fetchone())[0], 0)

    async def test_telegram_profile_and_transactions_do_not_double_count_stars_deposits(self):
        self.runtime._wallet_backend = self.backend
        now = self.runtime.now_msk().isoformat()
        async with self.runtime._db_lock:
            connection = self.runtime.db()
            await connection.execute(
                "INSERT INTO payments(charge_id,user_id,amount,created_at) VALUES (?,?,?,?)",
                ("stars-charge", 42, 5, now),
            )
            await connection.execute(
                "INSERT INTO payments(charge_id,user_id,amount,created_at) VALUES (?,?,?,?)",
                ("legacy-charge", 42, 3, now),
            )
            await connection.execute(
                "INSERT INTO webapp_deposits(id,user_id,provider,provider_id,stars_cents,price_amount,price_currency,status,created_at,expires_at,pay_url,paid_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("stars-order", 42, "stars", "stars-charge", 500, "5", "XTR", "paid", now, 2000000000, None, now),
            )
            await connection.execute(
                "INSERT INTO webapp_deposits(id,user_id,provider,provider_id,stars_cents,price_amount,price_currency,status,created_at,expires_at,pay_url,paid_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("crypto-order", 42, "cryptobot", "crypto-invoice", 700, "7", "USD", "paid", now, 2000000000, None, now),
            )
            await connection.execute(
                "INSERT INTO withdrawals(user_id,amount,status,created_at) VALUES (?,?,?,?)",
                (42, 2, "approved", now),
            )
            await connection.commit()

        stats = await self.runtime.telegram_profile_overview(42)
        self.assertEqual(stats["deposits"], 15)
        self.assertEqual(stats["withdrawals"], 2)
        records, pages = await self.runtime.get_telegram_transactions(42, "all", 1)
        self.assertEqual(pages, 1)
        self.assertEqual(len(records), 4)
        self.assertEqual(
            sorted(record["amount_cents"] for record in records if record["kind"] == "deposit"),
            [300, 500, 700],
        )
        self.assertEqual(
            [record["amount_cents"] for record in records if record["kind"] == "withdrawal"],
            [200],
        )

    async def test_menu_and_outgoing_request_localization_keep_custom_emoji(self):
        menu = self.runtime.telegram_home_markup()
        earn_button = menu.inline_keyboard[0][0]
        self.assertEqual(earn_button.callback_data, "tg_menu:earn")
        self.assertEqual(earn_button.icon_custom_emoji_id, "5472270097290634771")
        self.assertIn(
            "https://t.me/",
            self.runtime.telegram_earn_markup().inline_keyboard[0][0].url,
        )
        self.assertEqual(
            self.runtime.translate_telegram_text(
                '<tg-emoji emoji-id="5472270097290634771">💬</tg-emoji> '
                '<b>Заработок на чате</b>',
                "en",
            ),
            '<tg-emoji emoji-id="5472270097290634771">💬</tg-emoji> '
            '<b>Earn with your chat</b>',
        )

        current = self.runtime.CURRENT_TELEGRAM_LANGUAGE.set("en")
        try:
            method = SendMessage(
                chat_id=-1001001,
                text="<b>Выберите раздел MajorStars:</b>",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="Профиль", callback_data="tg_menu:profile")]
                    ]
                ),
            )

            async def capture(_bot, localized):
                return localized

            localized = await self.runtime.TelegramLocaleRequestMiddleware()(
                capture, object(), method
            )
        finally:
            self.runtime.CURRENT_TELEGRAM_LANGUAGE.reset(current)
        self.assertEqual(localized.text, "<b>Choose a MajorStars section:</b>")
        self.assertEqual(
            localized.reply_markup.inline_keyboard[0][0].text, "Profile"
        )

    def test_main_reply_keyboard_is_persistent_localized_and_uses_custom_emojis(self):
        expected_ids = [
            "5258204546391351475",
            "5258508428212445001",
            "5257965174979042426",
        ]
        for language, labels in (
            ("ru", ["Баланс", "Играть", "Меню"]),
            ("en", ["Balance", "Play", "Menu"]),
        ):
            with self.subTest(language=language):
                markup = self.runtime.telegram_main_reply_keyboard(language)
                self.assertIsInstance(markup, ReplyKeyboardMarkup)
                self.assertTrue(markup.is_persistent)
                self.assertTrue(markup.resize_keyboard)
                self.assertFalse(markup.one_time_keyboard)
                self.assertEqual([[button.text for button in row] for row in markup.keyboard], [labels])
                self.assertEqual(
                    [button.icon_custom_emoji_id for button in markup.keyboard[0]],
                    expected_ids,
                )

    async def test_reply_keyboard_text_routes_to_balance_games_and_main_menu(self):
        user = SimpleNamespace(id=42)
        bot = AsyncMock()
        state = SimpleNamespace(clear=AsyncMock())
        route = next(
            handler for handler in self.runtime.router.message.handlers
            if handler.callback is self.runtime.telegram_reply_menu_action
        )

        for label in ("Баланс", "Balance"):
            message = SimpleNamespace(
                text=label,
                chat=SimpleNamespace(type=ChatType.PRIVATE),
                from_user=user,
                answer=AsyncMock(),
            )
            self.assertTrue((await route.check(message))[0])
            with patch.object(self.runtime, "cmd_balance", new=AsyncMock()) as action:
                await self.runtime.telegram_reply_menu_action(message, state, bot)
            action.assert_awaited_once_with(message, bot, state)

        for label in ("Играть", "Play"):
            message = SimpleNamespace(
                text=label,
                chat=SimpleNamespace(type=ChatType.PRIVATE),
                from_user=user,
                answer=AsyncMock(),
            )
            self.assertTrue((await route.check(message))[0])
            with patch.object(self.runtime, "cmd_games", new=AsyncMock()) as action:
                await self.runtime.telegram_reply_menu_action(message, state, bot)
            action.assert_awaited_once_with(message, state)

        group_message = SimpleNamespace(
            text="Menu", chat=SimpleNamespace(type=ChatType.GROUP)
        )
        self.assertFalse((await route.check(group_message))[0])

        await self.runtime.set_telegram_language(user.id, "en")
        message = SimpleNamespace(
            text="Menu",
            chat=SimpleNamespace(type=ChatType.PRIVATE),
            from_user=user,
            answer=AsyncMock(),
        )
        self.assertTrue((await route.check(message))[0])
        await self.runtime.telegram_reply_menu_action(message, state, bot)
        state.clear.assert_awaited_once_with()
        message.answer.assert_awaited_once()
        self.assertEqual(message.answer.await_args.args[0], "<b>Choose a MajorStars section:</b>")
        menu = message.answer.await_args.kwargs["reply_markup"]
        self.assertEqual(menu.inline_keyboard[0][0].callback_data, "tg_menu:earn")
        self.assertEqual(menu.inline_keyboard[0][0].text, "Earn with your chat")

    async def test_start_deep_link_branches_also_install_main_reply_keyboard(self):
        user = SimpleNamespace(
            id=42,
            first_name="Test",
            last_name="User",
            username="test_user",
            is_premium=False,
            full_name="Test User",
        )
        bot = AsyncMock()
        with (
            patch.object(self.runtime, "is_subscribed", new=AsyncMock(return_value=True)),
            patch.object(self.runtime, "get_pending_referral", new=AsyncMock(return_value=None)),
            patch.object(self.runtime, "try_pay_referral_signup", new=AsyncMock()),
            patch.object(self.runtime, "show_withdraw_menu", new=AsyncMock(return_value=True)),
        ):
            for argument in ("toreplenish", "withdraw"):
                with self.subTest(argument=argument):
                    message = SimpleNamespace(
                        text=f"/start {argument}",
                        chat=SimpleNamespace(type=ChatType.PRIVATE, id=42),
                        from_user=user,
                        answer=AsyncMock(),
                        answer_photo=AsyncMock(),
                    )
                    state = SimpleNamespace(clear=AsyncMock(), set_state=AsyncMock())
                    await self.runtime.cmd_start(message, bot, state)
                    keyboard_calls = [
                        call for call in message.answer.await_args_list
                        if isinstance(call.kwargs.get("reply_markup"), ReplyKeyboardMarkup)
                    ]
                    self.assertEqual(len(keyboard_calls), 1)
                    self.assertEqual(
                        [button.text for button in keyboard_calls[0].kwargs["reply_markup"].keyboard[0]],
                        ["Баланс", "Играть", "Меню"],
                    )
                    message.answer_photo.assert_not_awaited()

    async def test_start_keeps_subscription_gate_and_sends_two_part_welcome(self):
        user = SimpleNamespace(
            id=42,
            first_name="<Test & User>",
            last_name="",
            username="test_user",
            is_premium=False,
            full_name="<Test & User>",
        )
        state = SimpleNamespace(clear=AsyncMock())
        message = SimpleNamespace(
            text="/start",
            chat=SimpleNamespace(type=ChatType.PRIVATE, id=42),
            from_user=user,
            answer=AsyncMock(),
            answer_photo=AsyncMock(),
        )
        bot = AsyncMock()
        with (
            patch.object(self.runtime, "is_subscribed", new=AsyncMock(return_value=False)),
            patch.object(self.runtime, "get_pending_referral", new=AsyncMock(return_value=None)),
        ):
            await self.runtime.cmd_start(message, bot, state)
        self.assertEqual(message.answer.await_count, 2)
        gate_call, keyboard_call = message.answer.await_args_list
        self.assertIn("вы не подписаны на обязательные каналы", gate_call.args[0])
        self.assertEqual(gate_call.kwargs["reply_markup"].inline_keyboard[0][1].callback_data, "check_sub")
        gate_keyboard = keyboard_call.kwargs["reply_markup"]
        self.assertIsInstance(gate_keyboard, ReplyKeyboardMarkup)
        self.assertEqual(
            [button.text for button in gate_keyboard.keyboard[0]],
            ["Баланс", "Играть", "Меню"],
        )
        message.answer_photo.assert_not_awaited()

        message.answer.reset_mock()
        await self.runtime.set_telegram_language(42, "en")
        with (
            patch.object(self.runtime, "is_subscribed", new=AsyncMock(return_value=True)),
            patch.object(self.runtime, "get_pending_referral", new=AsyncMock(return_value=None)),
            patch.object(self.runtime, "try_pay_referral_signup", new=AsyncMock()),
            patch.object(self.runtime, "add_balance", new=AsyncMock()),
            patch.object(self.runtime, "save_username", new=AsyncMock()),
        ):
            await self.runtime.cmd_start(message, bot, state)

        message.answer_photo.assert_awaited_once()
        photo_call = message.answer_photo.await_args
        self.assertEqual(photo_call.kwargs["photo"], "https://iili.io/o9YT4qX.md.png")
        self.assertIn("5424972470023104089", photo_call.kwargs["caption"])
        self.assertIn("Hello,", photo_call.kwargs["caption"])
        self.assertIn("&lt;Test &amp; User&gt;", photo_call.kwargs["caption"])
        welcome_keyboard = photo_call.kwargs["reply_markup"]
        self.assertIsInstance(welcome_keyboard, ReplyKeyboardMarkup)
        self.assertTrue(welcome_keyboard.is_persistent)
        self.assertEqual(
            [button.text for button in welcome_keyboard.keyboard[0]],
            ["Balance", "Play", "Menu"],
        )
        message.answer.assert_awaited_once()
        announcement, markup = message.answer.await_args.args[0], message.answer.await_args.kwargs["reply_markup"]
        self.assertIn("Updates channel", announcement)
        self.assertIn("MajorStars has been updated", announcement)
        for emoji_id in (
            "5096289879969498182",
            "5012808218385058363",
            "5021646904597939582",
        ):
            self.assertIn(emoji_id, announcement)
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "tg_menu:earn")
        self.assertEqual(markup.inline_keyboard[0][0].icon_custom_emoji_id, "5472270097290634771")
