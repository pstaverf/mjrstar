import bundle_test_support  # Register backend modules from server.py.
import asyncio
import copy
import hashlib
import hmac
import json
import secrets
import time
import unittest
import uuid
from urllib.parse import urlencode
from unittest.mock import AsyncMock

from complete_games import CompleteGamesBackend
from games_backend import GameError
from ton_deposits import ton_address
from ton_wallet import restore_wallet_identity
from tonsdk.crypto import mnemonic_new
from tonsdk.contract.wallet import Wallets, WalletVersionEnum
import base64
import test_games_backend as fixtures


class PaymentAndFairnessTests(unittest.IsolatedAsyncioTestCase):
    backend_type = CompleteGamesBackend
    asyncTearDown = fixtures.GamesBackendTests.asyncTearDown

    @classmethod
    def setUpClass(cls):
        cls.test_mnemonic = ' '.join(mnemonic_new())
        cls.test_identity = restore_wallet_identity(cls.test_mnemonic)
        _, _, _, wallet = Wallets.from_mnemonics(cls.test_mnemonic.split(), version=WalletVersionEnum.v4r2)
        cls.test_account = {'address': cls.test_identity.address, 'status': 'active', 'balance': '1000000000', 'code_hash': cls.test_identity.code_hash, 'data_boc': base64.b64encode(wallet.create_data_cell().to_boc(False)).decode()}

    async def asyncSetUp(self):
        await fixtures.GamesBackendTests.asyncSetUp(self)
        await self.backend.cleanup_star_withdrawals()
        await self.backend.cleanup_ton_deposits()
        self.backend.fragment_jwt = 'fake-fragment-jwt'
        self.backend.ton_wallet = self.test_identity.address
        self.backend.ton_mnemonic = self.test_mnemonic
        self.backend.ton_rpc_url = 'http://127.0.0.1:8081/api/v3'
        self.backend.ton_chain_api = AsyncMock(return_value={'accounts': [dict(self.test_account)]})
        await self.backend.initialize_ton_wallet()
        self.backend.ton_usd_rate = '2'
        async with self.backend.database_lock:
            await self.backend.database().execute("INSERT INTO webapp_deposits(id,user_id,provider,stars_cents,status,created_at,expires_at) VALUES ('fixture_paid',42,'cryptobot',5000,'paid',?,?)", (self.backend.clock().isoformat(), int(time.time()) + 3600))
            await self.backend.database().commit()
        self.provider_id = str(uuid.uuid4())
        self.provider_order = {'id': self.provider_id, 'type': 'STARS', 'receiver': 'Player42', 'goods_quantity': 50, 'status': 'PENDING', 'success': None, 'price': {'currency': 'ton', 'amount': '0.4'}, 'fee': {'currency': 'ton', 'amount': '0.01'}}
        self.backend.fragment_api = AsyncMock(side_effect=lambda *args, **kwargs: dict(self.provider_order))

    def headers(self, user_id=42, key=None, username=True):
        user = {'id': user_id, 'first_name': 'Player'}
        if username:
            user['username'] = 'Player' + str(user_id)
        data = {'auth_date': str(int(time.time())), 'user': json.dumps(user)}
        secret = hmac.new(b'WebAppData', self.runtime.BOT_TOKEN.encode(), hashlib.sha256).digest()
        digest = hmac.new(secret, '\n'.join(f'{k}={v}' for k, v in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
        return {'X-Telegram-Init-Data': urlencode({**data, 'hash': digest}), 'Idempotency-Key': key or secrets.token_hex(16)}

    async def post(self, path, body, user_id=42, key=None, username=True):
        response = await self.client.post(path, json=body, headers=self.headers(user_id, key, username))
        return response.status, await response.json()

    async def get(self, path, user_id=42):
        response = await self.client.get(path, headers=self.headers(user_id))
        return response.status, await response.json()

    async def quote(self):
        status, result = await self.post('/api/withdraw/quote', {'method': 'stars', 'coin': 'XTR', 'amount': '50', 'username': 'attacker'})
        self.assertEqual(status, 200, result)
        self.assertEqual(result['username'], 'Player42')
        return result

    async def reserve(self):
        quote = await self.quote()
        body = {'token': quote['token'], 'reqId': secrets.token_hex(16)}
        status, result = await self.post('/api/withdraw/confirm', body)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['balance'], 950)
        self.assertEqual(result['status'], 'processing')
        self.backend.fragment_api.assert_not_awaited()
        return body, result

    async def test_fail_closed_and_no_username(self):
        self.backend.fragment_jwt = ''
        status, result = await self.get('/api/withdraw/info')
        self.assertFalse(result['eligible'])
        status, _ = await self.post('/api/withdraw/quote', {'method': 'stars', 'amount': 50})
        self.assertEqual(status, 503)
        self.backend.fragment_jwt = 'fake-jwt'
        status, _ = await self.post('/api/withdraw/quote', {'method': 'stars', 'amount': 50}, username=False)
        self.assertEqual(status, 400)
        self.assertEqual(await self.runtime.get_balance(42), 1000)

    async def test_limits_and_identity(self):
        for value in (49, 50.5, True, -50, '1000001', 'nan'):
            status, _ = await self.post('/api/withdraw/quote', {'method': 'stars', 'amount': value})
            self.assertEqual(status, 400, value)
        status, _ = await self.post('/api/withdraw/quote', {'uid': 99, 'method': 'stars', 'amount': 50})
        self.assertEqual(status, 403)

    async def test_confirm_atomic_idempotency_and_ownership(self):
        body, result = await self.reserve()
        attempts = await asyncio.gather(*[self.post('/api/withdraw/confirm', body) for _ in range(5)])
        self.assertTrue(all(status == 200 and row['job'] == result['job'] for status, row in attempts))
        status, replay = await self.post('/api/withdraw/confirm', {**body, 'reqId': secrets.token_hex(16)})
        self.assertEqual(replay['job'], result['job'])
        status, _ = await self.post('/api/withdraw/confirm', body, 99)
        self.assertEqual(status, 404)
        status, _ = await self.get('/api/withdraw/job?id=' + result['job'], 99)
        self.assertEqual(status, 404)
        self.assertEqual(await self.runtime.get_balance(42), 950)
        status, info = await self.get('/api/withdraw/info')
        self.assertEqual(info['activeWithdrawal']['job'], result['job'])

    async def test_pending_blockchain_sent_and_terminal_completion(self):
        _, result = await self.reserve()
        identifier = result['job']
        await asyncio.gather(self.backend.process_star_withdrawal(identifier), self.backend.process_star_withdrawal(identifier))
        self.assertEqual(sum(call.args[0] == 'POST' for call in self.backend.fragment_api.await_args_list), 1)
        post = next(call for call in self.backend.fragment_api.await_args_list if call.args[0] == 'POST')
        self.assertEqual(post.args[2], {'username': 'Player42', 'quantity': 50, 'show_sender': False, 'currency': 'ton'})
        self.provider_order.update(status='BLOCKCHAIN_SENT')
        await self.backend.process_star_withdrawal(identifier)
        _, state = await self.get('/api/withdraw/job?id=' + identifier)
        self.assertEqual(state['status'], 'processing')
        self.assertEqual(state['state'], 'blockchain_sent')
        self.provider_order.update(status='COMPLETED', success=True)
        await self.backend.process_star_withdrawal(identifier)
        _, state = await self.get('/api/withdraw/job?id=' + identifier)
        self.assertEqual(state['status'], 'done')
        self.assertEqual(state['balance'], 950)
        await self.backend.process_star_withdrawal(identifier)
        # Route shape is covered separately by the existing account suite.
        async with self.runtime.db().execute("SELECT SUM(quantity) FROM webapp_star_withdrawals WHERE state='completed'") as cursor:
            self.assertEqual((await cursor.fetchone())[0], 50)

    async def test_failed_refunds_once_and_http_errors_do_not(self):
        _, result = await self.reserve()
        identifier = result['job']
        await self.backend.process_star_withdrawal(identifier)
        self.backend.fragment_api.side_effect = GameError('temporary', 502)
        with self.assertRaises(GameError):
            await self.backend.process_star_withdrawal(identifier)
        self.assertEqual(await self.runtime.get_balance(42), 950)
        self.backend.fragment_api.side_effect = lambda *args, **kwargs: dict(self.provider_order)
        self.provider_order.update(status='FAILED', success=False)
        await asyncio.gather(self.backend.process_star_withdrawal(identifier), self.backend.process_star_withdrawal(identifier))
        self.assertEqual(await self.runtime.get_balance(42), 1000)
        async with self.runtime.db().execute("SELECT COUNT(*) FROM webapp_wallet_events WHERE kind='withdrawal_refund'") as cursor:
            self.assertEqual((await cursor.fetchone())[0], 1)

    async def test_ambiguous_post_never_retries_or_refunds(self):
        _, result = await self.reserve()
        self.backend.fragment_api.side_effect = GameError('timeout', 502)
        await self.backend.process_star_withdrawal(result['job'])
        await self.backend.process_star_withdrawal(result['job'])
        self.assertEqual(self.backend.fragment_api.await_count, 1)
        _, status = await self.get('/api/withdraw/job?id=' + result['job'])
        self.assertEqual(status['status'], 'slow')
        self.assertEqual(status['balance'], 950)

    async def test_restart_and_credentials_rotation_fail_closed(self):
        _, result = await self.reserve()
        async with self.backend.database_lock:
            db = self.backend.database()
            await db.execute("UPDATE webapp_star_withdrawals SET state='submitting' WHERE id=?", (result['job'],))
            await db.commit()
        await self.backend.initialize_star_withdrawals()
        await self.backend.cleanup_star_withdrawals()
        await self.backend.process_star_withdrawal(result['job'])
        self.backend.fragment_api.assert_not_awaited()
        _, status = await self.get('/api/withdraw/job?id=' + result['job'])
        self.assertEqual(status['state'], 'uncertain')
        self.assertEqual(status['balance'], 950)

    async def test_provider_recipient_mismatch_holds_reserve(self):
        _, result = await self.reserve()
        self.provider_order['receiver'] = 'SomeoneElse'
        await self.backend.process_star_withdrawal(result['job'])
        _, status = await self.get('/api/withdraw/job?id=' + result['job'])
        self.assertEqual(status['state'], 'mismatch')
        self.assertEqual(status['balance'], 950)

    async def test_check_wager_blocks_confirm_without_debit(self):
        quote = await self.quote()
        original = self.backend.ensure_check_wager
        self.backend.ensure_check_wager = AsyncMock(side_effect=GameError('wager', 403))
        status, _ = await self.post('/api/withdraw/confirm', {'token': quote['token'], 'reqId': secrets.token_hex(16)})
        self.assertEqual(status, 403)
        self.assertEqual(await self.runtime.get_balance(42), 1000)
        self.backend.ensure_check_wager = original

    async def create_ton(self, key=None):
        status, invoice = await self.post('/api/deposit/tonkeeper/create', {'amount': 100}, key=key)
        self.assertEqual(status, 200, invoice)
        self.assertEqual(invoice['priceCurrency'], 'TON')
        async with self.backend.database_lock:
            order = await self.backend.ton_order(self.backend.database(), invoice['invoiceId'])
        return invoice, order

    def transaction(self, order):
        return {'account': order['wallet'], 'hash': 'ab' * 32, 'lt': '1234', 'now': int(time.time()), 'mc_block_seqno': 123, 'emulated': False, 'finality': 'finalized', 'description': {'aborted': False, 'compute_ph': {'success': True}}, 'in_msg': {'source': '0:' + '56' * 32, 'destination': order['wallet'], 'value': str(order['nanotons']), 'opcode': '0x00000000', 'bounced': False, 'message_content': {'decoded': {'type': 'text_comment', 'comment': order['comment']}}}}

    async def test_ton_create_idempotency_and_atomic_chain_credit(self):
        key = secrets.token_hex(16)
        invoice, order = await self.create_ton(key)
        replay, _ = await self.create_ton(key)
        self.assertEqual(invoice['invoiceId'], replay['invoiceId'])
        self.assertEqual(order['nanotons'], 1100000000)
        self.assertEqual(await self.runtime.get_balance(42), 1000)
        self.backend.ton_transactions = AsyncMock(return_value=[self.transaction(order)])
        await asyncio.gather(self.backend.process_ton_deposit(order['id']), self.backend.process_ton_deposit(order['id']))
        self.assertEqual(await self.runtime.get_balance(42), 1100)
        _, status = await self.get('/api/deposit/tonkeeper/status?invoiceId=' + order['id'])
        self.assertTrue(status['paid'])
        code, _ = await self.get('/api/deposit/tonkeeper/status?invoiceId=' + order['id'], 99)
        self.assertEqual(code, 404)

    async def test_ton_rejects_fake_bounced_jetton_wrong_amount_wallet_comment(self):
        _, order = await self.create_ton()
        base = self.transaction(order)
        for field, value in [('emulated', True), ('finality', 'pending'), ('mc_block_seqno', 0)]:
            tx = copy.deepcopy(base)
            tx[field] = value
            self.assertFalse(self.backend.ton_payment_matches(order, tx))
        for field, value in [('bounced', True), ('opcode', '0x7362d09c'), ('value', '1'), ('destination', '0:' + '34' * 32)]:
            tx = copy.deepcopy(base)
            tx['in_msg'][field] = value
            self.assertFalse(self.backend.ton_payment_matches(order, tx))
        tx = copy.deepcopy(base)
        tx['in_msg']['message_content']['decoded']['comment'] = 'wrong'
        self.assertFalse(self.backend.ton_payment_matches(order, tx))
        tx = copy.deepcopy(base)
        tx['description']['aborted'] = True
        self.assertFalse(self.backend.ton_payment_matches(order, tx))
        self.assertTrue(self.backend.ton_payment_matches(order, base))
        self.assertEqual(await self.runtime.get_balance(42), 1000)

    async def test_ton_unconfigured_and_unsigned_calls_fail(self):
        self.backend.ton_rpc_url = ''
        status, _ = await self.post('/api/deposit/tonkeeper/create', {'amount': 100})
        self.assertEqual(status, 503)
        response = await self.client.get('/api/withdraw/info')
        self.assertEqual(response.status, 401)
        for address in ('', 'not-an-address', '0:' + '0' * 64):
            with self.assertRaises(ValueError):
                ton_address(address)

    async def test_fairness_reproduces_round_and_rejects_mismatched_seed(self):
        status, result = await self.post('/api/keno/play', {'uid': 42, 'bet': 10, 'picks': [1, 2, 3], 'risk': 'medium'})
        self.assertEqual(status, 200, result)
        query = urlencode({'roundId': result['roundId'], 'hash': result['seedHash'], 'game': 'keno'})
        status, checked = await self.get('/api/fairness/check?' + query)
        self.assertEqual(status, 200, checked)
        self.assertTrue(checked['outcomeVerified'])
        self.assertEqual(checked['expected']['drawn'], result['drawn'])
        status, checked = await self.get('/api/fairness/check?' + urlencode({'hash': result['seedHash'], 'seed': '0' * 64}))
        self.assertEqual(status, 400)
        self.assertEqual(checked['autoCode'], 'FAIRNESS_HASH_MISMATCH')
        status, checked = await self.get('/api/fairness/check?' + urlencode({'hash': result['seedHash'], 'seed': result['serverSeed']}))
        self.assertTrue(checked['found'])
        async with self.backend.database_lock:
            tampered = dict(result, drawn=[1] * 10)
            await self.backend.database().execute('UPDATE webapp_rounds SET response=? WHERE public_id=?', (json.dumps(tampered), result['roundId']))
            await self.backend.database().commit()
        _, checked = await self.get('/api/fairness/check?' + query)
        self.assertFalse(checked['outcomeVerified'])

    async def test_existing_recent_deposit_requirement_is_preserved(self):
        quote = await self.quote()
        async with self.backend.database_lock:
            await self.backend.database().execute("DELETE FROM webapp_deposits WHERE id='fixture_paid'")
            await self.backend.database().commit()
        status, result = await self.post('/api/withdraw/confirm', {'token': quote['token'], 'reqId': secrets.token_hex(16)})
        self.assertEqual(status, 403, result)
        self.assertEqual(await self.runtime.get_balance(42), 1000)

    async def test_only_modern_fragment_cost_fields_are_persisted(self):
        _, reserved = await self.reserve()
        self.provider_order.update(status='COMPLETED', success=True, ton_price='99999', fee_ton='99999')
        await self.backend.process_star_withdrawal(reserved['job'])
        async with self.backend.database_lock:
            order = await self.backend.star_order(self.backend.database(), reserved['job'])
        self.assertEqual(json.loads(order['provider_costs']), {'price': {'currency': 'ton', 'amount': '0.4'}, 'fee': {'currency': 'ton', 'amount': '0.01'}})

    async def test_rotation_does_not_repurchase_known_pending_order(self):
        _, reserved = await self.reserve()
        await self.backend.process_star_withdrawal(reserved['job'])
        count = self.backend.fragment_api.await_count
        self.backend.fragment_jwt = 'different-jwt'
        await self.backend.process_star_withdrawal(reserved['job'])
        self.assertEqual(self.backend.fragment_api.await_count, count)
        self.assertEqual(await self.runtime.get_balance(42), 950)

    async def test_live_worker_obeys_shutdown_even_if_helper_consumes_cancel(self):
        self.backend.live_task.cancel()
        await asyncio.gather(self.backend.live_task, return_exceptions=True)
        original = self.backend.advance_blackjack_pvp
        async def consume_cancel(db):
            asyncio.current_task().cancel()
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                pass
        self.backend.advance_blackjack_pvp = AsyncMock(side_effect=consume_cancel)
        task = asyncio.create_task(self.backend.live_loop())
        await asyncio.wait_for(task, timeout=2)
        self.assertEqual(self.backend.advance_blackjack_pvp.await_count, 1)
        self.backend.advance_blackjack_pvp = original
