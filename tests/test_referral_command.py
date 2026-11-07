import asyncio
import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage


class ReferralCommandTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('referral_command_test_main', Path(__file__).resolve().parents[1] / 'main.py')
        cls.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runtime)

    async def asyncSetUp(self):
        self.message = SimpleNamespace(from_user=SimpleNamespace(id=42), answer=AsyncMock())
        self.state = SimpleNamespace(clear=AsyncMock())
        self.ref_data = {'signup_earned': 12.5, 'deposit_earned': 2.5}
        self.ref_patch = patch.object(self.runtime, 'get_ref_data', AsyncMock(return_value=self.ref_data))
        self.frozen_patch = patch.object(self.runtime, 'is_ref_frozen', AsyncMock(return_value=False))
        self.get_ref = self.ref_patch.start()
        self.frozen = self.frozen_patch.start()
        self.addCleanup(self.ref_patch.stop)
        self.addCleanup(self.frozen_patch.stop)

    def bad_request(self, message='Bad Request: DOCUMENT_INVALID'):
        return TelegramBadRequest(method=SendMessage(chat_id=42, text='test'), message=message)

    async def test_success_preserves_original_custom_emoji(self):
        await self.runtime.cmd_ref(self.message, self.state)
        self.message.answer.assert_awaited_once()
        args, options = self.message.answer.await_args
        self.assertIn('<tg-emoji', args[0])
        self.assertIn('start=ref_42', args[0])
        self.assertTrue(all(button.icon_custom_emoji_id for row in options['reply_markup'].inline_keyboard for button in row))
        self.state.clear.assert_awaited_once()

    async def test_document_invalid_retries_text_and_button_icons_without_losing_actions(self):
        self.message.answer.side_effect = [self.bad_request(), SimpleNamespace(message_id=1)]
        await self.runtime.cmd_ref(self.message, self.state)
        self.assertEqual(self.message.answer.await_count, 2)
        original, fallback = self.message.answer.await_args_list
        text = fallback.args[0]
        self.assertNotIn('<tg-emoji', text)
        self.assertNotIn('</tg-emoji>', text)
        self.assertIn('👥', text)
        self.assertIn('✅', text)
        self.assertIn('<b> Реферальная система</b>', text)
        self.assertIn('<blockquote expandable>', text)
        self.assertIn('start=ref_42', text)
        self.assertIn('15.0', text)
        self.assertIn('12.5', text)
        self.assertIn('2.5', text)
        self.assertEqual(text, re.sub(r'</?tg-emoji\b[^>]*>', '', original.args[0]))
        old = original.kwargs['reply_markup']
        new = fallback.kwargs['reply_markup']
        self.assertIsNot(old, new)
        for old_row, new_row in zip(old.inline_keyboard, new.inline_keyboard):
            for old_button, new_button in zip(old_row, new_row):
                self.assertIsNot(old_button, new_button)
                self.assertIsNotNone(old_button.icon_custom_emoji_id)
                self.assertIsNone(new_button.icon_custom_emoji_id)
                self.assertEqual(old_button.text, new_button.text)
                self.assertEqual(old_button.callback_data, new_button.callback_data)
                self.assertEqual(old_button.copy_text, new_button.copy_text)
                self.assertEqual(old_button.style, new_button.style)
        self.assertNotIn('icon_custom_emoji_id', str(new.model_dump(exclude_none=True)))
        self.assertEqual(new.inline_keyboard[0][0].callback_data, 'ref_withdraw')
        self.assertIn('start=ref_42', new.inline_keyboard[0][1].copy_text.text)
        self.get_ref.assert_awaited_once_with(42)
        self.frozen.assert_awaited_once_with(42)
        self.assertEqual(self.ref_data, {'signup_earned': 12.5, 'deposit_earned': 2.5})

    async def test_frozen_referral_keeps_status_in_fallback(self):
        self.frozen.return_value = True
        self.message.answer.side_effect = [self.bad_request(), None]
        await self.runtime.cmd_ref(self.message, self.state)
        self.assertIn('❌', self.message.answer.await_args_list[1].args[0])

    async def test_other_bad_requests_do_not_trigger_retry(self):
        error = self.bad_request("Bad Request: can't parse entities")
        self.message.answer.side_effect = error
        with self.assertRaises(TelegramBadRequest) as raised:
            await self.runtime.cmd_ref(self.message, self.state)
        self.assertIs(raised.exception, error)
        self.assertEqual(self.message.answer.await_count, 1)

    async def test_ambiguous_network_failure_is_not_retried(self):
        self.message.answer.side_effect = asyncio.TimeoutError()
        with self.assertRaises(asyncio.TimeoutError):
            await self.runtime.cmd_ref(self.message, self.state)
        self.assertEqual(self.message.answer.await_count, 1)

    async def test_failed_fallback_is_not_retried_again(self):
        second_error = self.bad_request('Bad Request: chat not found')
        self.message.answer.side_effect = [self.bad_request(), second_error]
        with self.assertRaises(TelegramBadRequest) as raised:
            await self.runtime.cmd_ref(self.message, self.state)
        self.assertIs(raised.exception, second_error)
        self.assertEqual(self.message.answer.await_count, 2)
