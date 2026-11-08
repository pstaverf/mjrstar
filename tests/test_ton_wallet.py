import base64
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from tonsdk.contract.wallet import Wallets, WalletVersionEnum
from tonsdk.crypto import mnemonic_new

from games_backend import GameError
from ton_deposits import TonDepositsMixin
from ton_wallet import TonWalletError, read_mnemonic, restore_wallet_identity, verify_chain_account


class TonWalletTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        # Ephemeral test-only phrase: never print it or use it with real funds.
        cls.phrase = ' '.join(mnemonic_new())
        cls.identity = restore_wallet_identity(cls.phrase)
        _, _, _, wallet = Wallets.from_mnemonics(cls.phrase.split(), version=WalletVersionEnum.v4r2)
        cls.account = {'address': cls.identity.address, 'status': 'active', 'balance': '0', 'code_hash': cls.identity.code_hash, 'data_boc': base64.b64encode(wallet.create_data_cell().to_boc(False)).decode()}

    def test_valid_seed_reproducible_address_and_no_retained_private_data(self):
        identity = restore_wallet_identity(self.phrase, expected_address=self.identity.address)
        self.assertEqual(identity, self.identity)
        self.assertNotIn(self.phrase, repr(identity))
        self.assertFalse(hasattr(identity, 'private_key'))
        self.assertFalse(hasattr(identity, 'mnemonic'))
        self.assertEqual(verify_chain_account(identity, self.account)['seqno'], 0)

    def test_invalid_seed_words_parameters_and_address_fail_without_secret_errors(self):
        for phrase in ('', 'seed-DO-NOT-EXPOSE ' * 24, 'abandon ' * 23, 'abandon ' * 25):
            with self.assertRaises(TonWalletError) as error:
                restore_wallet_identity(phrase)
            self.assertNotIn('seed-DO-NOT-EXPOSE', str(error.exception))
        with self.assertRaises(TonWalletError):
            restore_wallet_identity(self.phrase, expected_address='0:' + '12' * 32)
        for kwargs in ({'version': 'v5r1'}, {'workchain': -1}, {'wallet_id': True}, {'wallet_id': -1}):
            with self.assertRaises(TonWalletError):
                restore_wallet_identity(self.phrase, **kwargs)

    def test_explicit_version_and_wallet_id_change_address(self):
        self.assertNotEqual(restore_wallet_identity(self.phrase, version='v3r2').address, self.identity.address)
        self.assertNotEqual(restore_wallet_identity(self.phrase, wallet_id=1).address, self.identity.address)

    def test_seed_file_permissions_symlinks_and_exclusive_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'wallet.ton-seed'
            path.write_text(self.phrase)
            path.chmod(0o600)
            self.assertEqual(read_mnemonic(filename=str(path)), self.phrase)
            path.chmod(0o644)
            with self.assertRaises(TonWalletError):
                read_mnemonic(filename=str(path))
            path.chmod(0o600)
            link = Path(directory) / 'linked.ton-seed'
            link.symlink_to(path)
            with self.assertRaises(TonWalletError):
                read_mnemonic(filename=str(link))
            with self.assertRaises(TonWalletError):
                read_mnemonic(inline=self.phrase, filename=str(path))
            with self.assertRaises(TonWalletError):
                read_mnemonic(filename=directory)

    def test_onchain_wrong_code_data_address_inactive_and_plugins_fail(self):
        for key, value in [('status', 'uninit'), ('address', '0:' + '12' * 32), ('code_hash', 'ab' * 32), ('data_boc', 'invalid')]:
            with self.assertRaises(TonWalletError):
                verify_chain_account(self.identity, {**self.account, key: value})
        _, _, _, wallet = Wallets.from_mnemonics(self.phrase.split(), version=WalletVersionEnum.v4r2, wallet_id=1)
        wrong_data = base64.b64encode(wallet.create_data_cell().to_boc(False)).decode()
        with self.assertRaises(TonWalletError):
            verify_chain_account(self.identity, {**self.account, 'data_boc': wrong_data})
        cell = wallet.create_data_cell()
        # Fake plugin-bearing data, but with the correct key and wallet ID.
        cell.bits.array[4:8] = self.identity.wallet_id.to_bytes(4, 'big')
        cell.bits.array[40] |= 0x80
        with self.assertRaises(TonWalletError):
            verify_chain_account(self.identity, {**self.account, 'data_boc': base64.b64encode(cell.to_boc(False)).decode()})

    async def configured(self):
        backend = TonDepositsMixin()
        backend.ton_mnemonic = self.phrase
        backend.ton_rpc_url = 'http://127.0.0.1:8081/api/v3'
        backend.ton_usd_rate = '2'
        await backend.initialize_ton_wallet()
        backend.ton_chain_api = AsyncMock(return_value={'accounts': [copy.deepcopy(self.account)]})
        return backend

    async def test_chain_gate_and_cached_public_only_requests_no_provider_key(self):
        backend = await self.configured()
        self.assertFalse(backend.ton_ready())
        await backend.verify_ton_wallet_chain()
        self.assertTrue(backend.ton_ready())
        await backend.verify_ton_wallet_chain()
        self.assertEqual(backend.ton_chain_api.await_count, 1)
        method, params = backend.ton_chain_api.await_args.args
        self.assertEqual(method, 'accountStates')
        self.assertEqual(params['address'], self.identity.address)
        self.assertNotIn(self.phrase, json.dumps(params))
        self.assertFalse(hasattr(backend, 'ton_api_key'))

    async def test_rpc_failure_or_wrong_account_disables_receipts(self):
        backend = await self.configured()
        backend.ton_chain_api.return_value = {'accounts': [{**self.account, 'code_hash': 'ab' * 32}]}
        with self.assertRaises(GameError):
            await backend.verify_ton_wallet_chain()
        self.assertFalse(backend.ton_ready())
        backend.ton_chain_api.side_effect = GameError('unavailable', 503)
        with self.assertRaises(GameError):
            await backend.verify_ton_wallet_chain()
        self.assertFalse(backend.ton_ready())

    async def test_missing_seed_and_insecure_rpc_fail_closed(self):
        backend = TonDepositsMixin()
        await backend.initialize_ton_wallet()
        self.assertFalse(backend.ton_ready())
        backend = await self.configured()
        for endpoint in ('', 'file:///etc/passwd', 'http://remote.example/api/v3', 'https://user:pass@example/api/v3', 'https://example/api/v3?key=secret'):
            backend.ton_rpc_url = endpoint
            with self.assertRaises(GameError):
                backend.ton_settings()

    async def test_seed_and_private_source_cannot_be_served_via_asset_symlinks(self):
        import importlib.util
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        spec = importlib.util.spec_from_file_location('wallet_static_test_main', Path(__file__).resolve().parents[1] / 'main.py')
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'images').mkdir()
            (root / '.secrets').mkdir()
            (root / '.secrets' / 'wallet.ton-seed').write_text('not-a-real-secret')
            (root / 'payments_backend.py').write_text('private-server-source')
            (root / 'images' / 'seed.png').symlink_to(root / '.secrets' / 'wallet.ton-seed')
            (root / 'images' / 'source.png').symlink_to(root / 'payments_backend.py')
            (root / 'images' / 'visible.png').write_bytes(b'public-asset')
            runtime.WEBAPP_ROOT = root
            app = web.Application()
            app.router.add_get('/{path:.*}', runtime.webapp_asset)
            async with TestClient(TestServer(app)) as client:
                for path in ('/images/seed.png', '/images/source.png', '/.secrets/wallet.ton-seed'):
                    response = await client.get(path)
                    self.assertEqual(response.status, 404)
                response = await client.get('/images/visible.png')
                self.assertEqual(response.status, 200)
