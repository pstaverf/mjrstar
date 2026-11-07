import asyncio
import importlib.util
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import SendMessage


class CheckReferralEmojiTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('checkr_command_test_main', Path(__file__).resolve().parents[1] / 'main.py')
        cls.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runtime)

    async def asyncSetUp(self):
        self.runtime.CHECKR_RUNNING.clear()
        self.message = SimpleNamespace(
            from_user=SimpleNamespace(id=self.runtime.ADMIN_ID),
            chat=SimpleNamespace(type='private'),
            answer=AsyncMock(),
        )
        for name in ('get_ref_data', 'is_ref_frozen', 'add_balance', 'get_balance'):
            patcher = patch.object(self.runtime, name, AsyncMock(side_effect=AssertionError('diagnostic must not access money/data operations')))
            patcher.start()
            self.addCleanup(patcher.stop)
        sleeper = patch.object(self.runtime.asyncio, 'sleep', AsyncMock())
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)
        self.probes = self.runtime.referral_emoji_probes(self.runtime.ADMIN_ID)

    def identity(self, text, reply_markup):
        if reply_markup:
            return 'button', reply_markup.inline_keyboard[0][0].icon_custom_emoji_id
        match = re.search(r'<tg-emoji emoji-id="([0-9]+)">', text)
        return ('text', match.group(1)) if match else None

    def bad_request(self, message='Bad Request: DOCUMENT_INVALID'):
        return TelegramBadRequest(method=SendMessage(chat_id=42, text='test'), message=message)

    async def test_probes_are_deduplicated_and_include_both_statuses_and_button_icons(self):
        identities = [(kind, emoji_id) for kind, emoji_id, label in self.probes]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertIn(('text', '5832229652805985405'), identities)
        self.assertIn(('text', '5273914604752216432'), identities)
        self.assertEqual(identities.count(('text', '5954135079662916434')), 1)
        for row in self.runtime.ref_markup(42).inline_keyboard:
            for button in row:
                if button.icon_custom_emoji_id:
                    self.assertIn(('button', button.icon_custom_emoji_id), identities)

    async def test_successful_sequential_probes_have_safe_buttons_and_final_summary(self):
        await self.runtime.cmd_checkr(self.message)
        identities = []
        for call in self.message.answer.await_args_list:
            text = call.args[0]
            markup = call.kwargs.get('reply_markup')
            identity = self.identity(text, markup)
            if identity:
                identities.append(identity)
                self.assertIn('<code>' + identity[1] + '</code>', text)
            if markup:
                button = markup.inline_keyboard[0][0]
                self.assertEqual(button.callback_data, 'checkr_probe')
                self.assertIsNone(button.copy_text)
                self.assertIsNone(button.url)
                self.assertNotEqual(button.callback_data, 'ref_withdraw')
        self.assertEqual(identities, [(kind, emoji_id) for kind, emoji_id, label in self.probes])
        self.assertEqual(self.message.answer.await_count, len(self.probes) + 2)
        self.assertIn(f'{len(self.probes)}/{len(self.probes)}', self.message.answer.await_args.args[0])
        self.assertIn('Не обнаружены среди проверенных', self.message.answer.await_args.args[0])
        self.assertGreaterEqual(sum(call.args[0] >= 1 for call in self.sleep.await_args_list), len(self.probes))
        self.assertFalse(self.runtime.CHECKR_RUNNING)

    async def test_invalid_text_and_button_are_reported_and_checks_continue(self):
        bad_text = next((kind, emoji_id) for kind, emoji_id, label in self.probes if kind == 'text')
        bad_button = next((kind, emoji_id) for kind, emoji_id, label in self.probes if kind == 'button')
        async def answer(text, reply_markup=None, **kwargs):
            if self.identity(text, reply_markup) in (bad_text, bad_button):
                raise self.bad_request()
        self.message.answer.side_effect = answer
        await self.runtime.cmd_checkr(self.message)
        summary = self.message.answer.await_args.args[0]
        self.assertIn('текст: <code>' + bad_text[1] + '</code>', summary)
        self.assertIn('кнопка: <code>' + bad_button[1] + '</code>', summary)
        self.assertIn(f'{len(self.probes) - 2}/{len(self.probes)}', summary)
        errors = [call for call in self.message.answer.await_args_list if '❌ DOCUMENT_INVALID' in call.args[0]]
        self.assertEqual(len(errors), 2)
        for call in errors:
            self.assertNotIn('<tg-emoji', call.args[0])
            self.assertIsNone(call.kwargs.get('reply_markup'))

    async def test_other_api_errors_are_not_mislabelled_and_are_html_escaped(self):
        target = (self.probes[0][0], self.probes[0][1])
        async def answer(text, reply_markup=None, **kwargs):
            if self.identity(text, reply_markup) == target:
                raise self.bad_request("Bad Request: can't parse <entity>")
        self.message.answer.side_effect = answer
        await self.runtime.cmd_checkr(self.message)
        summary = self.message.answer.await_args.args[0]
        self.assertIn('Не подтверждены / не проверены', summary)
        self.assertIn('Не обнаружены среди проверенных', summary)
        feedback = next(call.args[0] for call in self.message.answer.await_args_list if 'Другая ошибка Telegram' in call.args[0])
        self.assertIn('&lt;entity&gt;', feedback)
        self.assertNotIn('<entity>', feedback)

    async def test_network_timeout_stops_remaining_probes_without_retry_or_invalid_claim(self):
        target = (self.probes[1][0], self.probes[1][1])
        attempted = []
        async def answer(text, reply_markup=None, **kwargs):
            identity = self.identity(text, reply_markup)
            if identity:
                attempted.append(identity)
            if identity == target:
                raise asyncio.TimeoutError()
        self.message.answer.side_effect = answer
        await self.runtime.cmd_checkr(self.message)
        self.assertEqual(len(attempted), 2)
        self.assertEqual(attempted.count(target), 1)
        summary = self.message.answer.await_args.args[0]
        self.assertIn(f'1/{len(self.probes)}', summary)
        self.assertIn('Не обнаружены среди проверенных', summary)
        for kind, emoji_id, label in self.probes[1:]:
            self.assertIn(emoji_id, summary)
        self.assertFalse(self.runtime.CHECKR_RUNNING)

    async def test_rate_limit_waits_then_retries_only_the_rejected_probe(self):
        target = (self.probes[0][0], self.probes[0][1])
        attempts = 0
        async def answer(text, reply_markup=None, **kwargs):
            nonlocal attempts
            if self.identity(text, reply_markup) == target:
                attempts += 1
                if attempts == 1:
                    raise TelegramRetryAfter(method=SendMessage(chat_id=42, text='test'), message='retry', retry_after=2)
        self.message.answer.side_effect = answer
        await self.runtime.cmd_checkr(self.message)
        self.assertEqual(attempts, 2)
        self.assertTrue(any(call.args[0] >= 2 for call in self.sleep.await_args_list))
        self.assertIn(f'{len(self.probes)}/{len(self.probes)}', self.message.answer.await_args.args[0])
        self.assertIn('Не обнаружены среди проверенных', self.message.answer.await_args.args[0])

    async def test_only_admin_in_private_can_start(self):
        self.message.from_user = SimpleNamespace(id=self.runtime.ADMIN_ID + 1)
        await self.runtime.cmd_checkr(self.message)
        self.message.answer.assert_not_awaited()
        self.message.from_user = None
        await self.runtime.cmd_checkr(self.message)
        self.message.answer.assert_not_awaited()
        self.message.from_user = SimpleNamespace(id=self.runtime.ADMIN_ID)
        self.message.chat.type = 'group'
        await self.runtime.cmd_checkr(self.message)
        self.message.answer.assert_awaited_once()
        self.assertIn('личном чате', self.message.answer.await_args.args[0])
        self.assertFalse(self.runtime.CHECKR_RUNNING)

    async def test_second_run_cannot_overlap_and_lock_is_released(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        first = True
        async def answer(text, **kwargs):
            nonlocal first
            if first:
                first = False
                entered.set()
                await release.wait()
        self.message.answer.side_effect = answer
        task = asyncio.create_task(self.runtime.cmd_checkr(self.message))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            await self.runtime.cmd_checkr(self.message)
            self.assertEqual(self.message.answer.await_count, 1)
        finally:
            release.set()
            await task
        self.assertFalse(self.runtime.CHECKR_RUNNING)

    async def test_unexpected_send_failure_releases_run_guard(self):
        self.message.answer.side_effect = RuntimeError('test failure')
        with self.assertRaises(RuntimeError):
            await self.runtime.cmd_checkr(self.message)
        self.assertFalse(self.runtime.CHECKR_RUNNING)

    async def test_diagnostic_button_only_acknowledges(self):
        call = SimpleNamespace(from_user=SimpleNamespace(id=self.runtime.ADMIN_ID), answer=AsyncMock())
        await self.runtime.on_checkr_probe(call)
        call.answer.assert_awaited_once()
        self.assertIn('Никакие операции', call.answer.await_args.args[0])
