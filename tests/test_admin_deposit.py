import bundle_test_support
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import unittest

from complete_games import CompleteGamesBackend
from games_backend import GameError
import test_games_backend as fixtures


class AdminDepositTests(unittest.IsolatedAsyncioTestCase):
    backend_type = CompleteGamesBackend
    asyncTearDown = fixtures.GamesBackendTests.asyncTearDown
    headers = fixtures.GamesBackendTests.headers

    async def asyncSetUp(self):
        await fixtures.GamesBackendTests.asyncSetUp(self)
        self.runtime.ADMIN_ID = 777
        self.runtime._wallet_backend = self.backend
        self.backend.wallet_runtime = self.runtime.__dict__
        await self.runtime.init_transfer_tables()
        await self.runtime.save_username(42, 'Durov', 'Test recipient')

    def message(self, text='/addep @durov 50', user=777, kind='private', message_id=10):
        return SimpleNamespace(text=text, from_user=SimpleNamespace(id=user), chat=SimpleNamespace(type=kind, id=user), message_id=message_id, answer=AsyncMock())

    async def grant(self, amount=50, message_id=10, username='durov'):
        return await self.runtime.admin_deposit_atomic(777, 777, message_id, username, amount)

    async def test_command_credits_balance_counts_deposit_history_stats_and_gate(self):
        message = self.message()
        await self.runtime.cmd_addep(message)
        self.assertEqual(await self.runtime.get_balance(42), 1050)
        self.assertEqual(await self.runtime.get_weekly_deposit(42), 50)
        self.assertIn('Депозит начислен', message.answer.await_args.args[0])
        await self.backend.ensure_star_withdraw_requirements(self.runtime.db(), 42)
        response = await self.client.get('/api/profile/stats', headers=self.headers())
        self.assertEqual((await response.json())['deposits'], 50)
        response = await self.client.get('/api/wallet/transactions?filter=deposit', headers=self.headers())
        data = await response.json()
        rows = [row for row in data['rows'] if row['description'] == 'Депозит от администратора']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['amount'], 50)
        self.assertEqual(rows[0]['status'], 'paid')
        async with self.runtime.db().execute('SELECT admin_id,user_id,amount FROM webapp_admin_deposits') as cursor:
            self.assertEqual(await cursor.fetchone(), (777, 42, 50))

    async def test_concurrent_replay_is_once_but_new_message_is_new_deposit(self):
        results = await asyncio.gather(*[self.grant() for _ in range(8)])
        self.assertEqual(sum(row['new'] for row in results), 1)
        self.assertEqual(await self.runtime.get_balance(42), 1050)
        self.assertEqual(await self.runtime.get_weekly_deposit(42), 50)
        await self.grant(message_id=11)
        self.assertEqual(await self.runtime.get_balance(42), 1100)
        self.assertEqual(await self.runtime.get_weekly_deposit(42), 100)

    async def test_replay_changed_payload_or_username_cannot_recredit(self):
        await self.grant()
        for kwargs in ({'amount': 51}, {'username': 'other'}):
            with self.assertRaises(GameError) as error:
                await self.grant(**kwargs)
            self.assertEqual(error.exception.status, 409)
        await self.runtime.save_username(42, 'renamed', 'Test recipient')
        replay = await self.grant()
        self.assertFalse(replay['new'])
        self.assertEqual(replay['user_id'], 42)
        self.assertEqual(await self.runtime.get_balance(42), 1050)

    async def test_referral_is_full_deposit_and_not_paid_twice(self):
        async with self.backend.database_lock:
            await self.runtime.db().execute('INSERT INTO referrals(user_id,referrer_id,joined_at,is_premium,deposited) VALUES (?,?,?,?,0)', (42, 99, self.runtime.now_msk().isoformat(), 0))
            await self.runtime.db().commit()
        await self.grant()
        await self.grant()
        async with self.runtime.db().execute('SELECT deposited FROM referrals WHERE user_id=42') as cursor:
            self.assertEqual((await cursor.fetchone())[0], 1)
        async with self.runtime.db().execute('SELECT deposit_earned FROM ref_balance WHERE user_id=99') as cursor:
            self.assertEqual((await cursor.fetchone())[0], 5)
        async with self.runtime.db().execute('SELECT COUNT(*) FROM webapp_ref_events') as cursor:
            self.assertEqual((await cursor.fetchone())[0], 1)

    async def test_failed_accounting_rolls_back_everything(self):
        original = self.backend.referral_credit
        self.backend.referral_credit = AsyncMock(side_effect=RuntimeError('test rollback'))
        with self.assertRaises(RuntimeError):
            await self.grant()
        self.assertEqual(await self.runtime.get_balance(42), 1000)
        self.assertEqual(await self.runtime.get_weekly_deposit(42), 0)
        for table in ('webapp_admin_deposits', 'payments'):
            async with self.runtime.db().execute('SELECT COUNT(*) FROM ' + table) as cursor:
                self.assertEqual((await cursor.fetchone())[0], 0)
        async with self.runtime.db().execute("SELECT COUNT(*) FROM webapp_wallet_events WHERE source LIKE 'admin-deposit:%'") as cursor:
            self.assertEqual((await cursor.fetchone())[0], 0)
        self.backend.referral_credit = original
        self.assertTrue((await self.grant())['new'])

    async def test_unknown_and_ambiguous_username_do_not_create_or_credit(self):
        with self.assertRaises(GameError) as error:
            await self.grant(username='unknown')
        self.assertEqual(error.exception.status, 404)
        await self.runtime.save_username(99, 'DUROV', 'Another record')
        with self.assertRaises(GameError) as error:
            await self.grant()
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(await self.runtime.get_balance(42), 1000)
        self.assertEqual(await self.runtime.get_weekly_deposit(42), 0)

    async def test_only_configured_admin_and_private_chat(self):
        for user, kind in ((99, 'private'), (777, 'group'), (777, 'supergroup')):
            await self.runtime.cmd_addep(self.message(user=user, kind=kind))
        with self.assertRaises(GameError):
            await self.runtime.admin_deposit_atomic(99, 99, 10, 'durov', 50)
        self.assertEqual(await self.runtime.get_balance(42), 1000)
        self.assertEqual(await self.runtime.get_weekly_deposit(42), 0)

    async def test_invalid_amount_syntax_and_incomplete_backend(self):
        for text in ('/addep', '/addep @durov', '/addep @durov 0', '/addep @durov -1', '/addep @durov 1.5', '/addep @durov nan', '/addep @durov 1000001', '/addep @durov 50 extra', '/addep durov 50', '/addep @<script> 50'):
            await self.runtime.cmd_addep(self.message(text))
        self.assertEqual(await self.runtime.get_balance(42), 1000)
        self.runtime._wallet_backend = None
        with self.assertRaises(GameError) as error:
            await self.grant()
        self.assertEqual(error.exception.status, 503)

    async def test_ack_failure_then_redelivery_does_not_duplicate_deposit(self):
        message = self.message()
        message.answer.side_effect = RuntimeError('test delivery failure')
        with self.assertRaises(RuntimeError):
            await self.runtime.cmd_addep(message)
        message.answer.side_effect = None
        await self.runtime.cmd_addep(message)
        self.assertIn('повторного начисления нет', message.answer.await_args.args[0])
        self.assertEqual(await self.runtime.get_balance(42), 1050)
        self.assertEqual(await self.runtime.get_weekly_deposit(42), 50)
