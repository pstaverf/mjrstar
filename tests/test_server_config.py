import bundle_test_support
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

server = bundle_test_support.server
ROOT = Path(__file__).resolve().parents[1]


class ServerConfigTests(unittest.TestCase):
    def write(self, directory, value, mode=0o600):
        path = Path(directory) / 'conf.json'
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding='utf-8')
        path.chmod(mode)
        return path

    def test_private_json_load_and_seed_relative_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, {'BOT_TOKEN': 'test-config-token', 'TON_WALLET_SEED_FILE': '.secrets/wallet.ton-seed', 'ADMIN_ID': 42})
            settings = server._load_config(path)
            self.assertEqual(settings['BOT_TOKEN'], 'test-config-token')
            self.assertEqual(settings['TON_WALLET_SEED_FILE'], str(Path(directory) / '.secrets/wallet.ton-seed'))
            self.assertEqual(settings['ADMIN_ID'], 42)
            self.assertEqual(settings['TON_WALLET_MNEMONIC'], '')

    def test_permissions_symlink_and_non_regular_files_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self.write(directory, {}, 0o644)
            with self.assertRaises(server.ConfigError):
                server._load_config(path)
            path.chmod(0o600)
            alias = Path(directory) / 'alias.json'
            alias.symlink_to(path)
            with self.assertRaises(server.ConfigError):
                server._load_config(alias)
            with self.assertRaises(server.ConfigError):
                server._load_config(Path(directory))
            path.write_text(' ' * 65537)
            with self.assertRaises(server.ConfigError):
                server._load_config(path)

    def test_malformed_unknown_duplicate_and_nan_never_echo_contents(self):
        marker = 'TEST-SECRET-MUST-NOT-APPEAR'
        cases = ['{"BOT_TOKEN":"' + marker, '{"BOT_TOKEN":"a","BOT_TOKEN":"' + marker + '"}', {marker: marker}, [], {'ADMIN_ID': marker}, '{"ADMIN_ID":NaN}', {'TON_WALLET_ID': True}]
        with tempfile.TemporaryDirectory() as directory:
            for value in cases:
                with self.subTest(kind=type(value).__name__):
                    path = self.write(directory, value)
                    with self.assertRaises(server.ConfigError) as error:
                        server._load_config(path)
                    self.assertNotIn(marker, str(error.exception))

    def test_valid_types_and_currency_wallet_ranges(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in ({'ADMIN_ID': True}, {'WEBAPP_PORT': 0}, {'WEBAPP_PORT': '1234'}, {'TON_WALLET_WORKCHAIN': -1}, {'TON_WALLET_VERSION': 'v5r1'}, {'FRAGMENT_CURRENCY': 'unsupported'}, {'TON_WALLET_MNEMONIC': 'seed', 'TON_WALLET_SEED_FILE': 'seed-file'}, {'TON_WALLET_ID': 2**32}):
                with self.assertRaises(server.ConfigError):
                    server._load_config(self.write(directory, value))

    def test_no_credential_literals_remain_in_embedded_assignments(self):
        expected = {'main': {'BOT_TOKEN', 'WEBHOOK_SECRET'}, 'payments_backend': {'CRYPTOBOT_API_TOKEN', 'XROCKET_API_TOKEN', 'XROCKET_WEBHOOK_SECRET', 'FRAGMENT_API_JWT', 'TON_WALLET_MNEMONIC'}}
        for module, names in expected.items():
            found = set()
            for node in ast.parse(server._SOURCES[module]).body:
                if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in names:
                    self.assertIsInstance(node.value, ast.Subscript)
                    self.assertEqual(node.value.value.id, '__server_config__')
                    found.add(node.targets[0].id)
            self.assertEqual(found, names)

    def test_safe_example_keys_match_schema_and_secrets_are_empty(self):
        settings = json.loads((ROOT / 'conf.example.json').read_text())
        self.assertEqual(set(settings), set(server._CONFIG_DEFAULTS))
        for key in ('BOT_TOKEN', 'WEBHOOK_SECRET', 'CRYPTOBOT_API_TOKEN', 'XROCKET_API_TOKEN', 'XROCKET_WEBHOOK_SECRET', 'FRAGMENT_API_JWT', 'TON_WALLET_MNEMONIC'):
            self.assertEqual(settings[key], '')

    def test_startup_required_fields_and_validation_do_not_open_network(self):
        settings = dict(server._CONFIG_DEFAULTS)
        with patch.dict(server._CONFIG, settings, clear=True):
            with self.assertRaises(server.ConfigError):
                server._require_startup_config()
        settings.update(BOT_TOKEN='123456:test-only-token', WEBHOOK_HOST='https://example.test', WEBHOOK_SECRET='test-only-secret', ADMIN_ID=42)
        with patch.dict(server._CONFIG, settings, clear=True):
            server._require_startup_config()
        settings['BOT_TOKEN'] = 'invalid-TEST-SECRET'
        with patch.dict(server._CONFIG, settings, clear=True):
            with self.assertRaises(server.ConfigError) as error:
                server._require_startup_config()
            self.assertNotIn('invalid-TEST-SECRET', str(error.exception))

    def test_standalone_conf_path_uses_server_directory_not_cwd(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as cwd:
            target = Path(directory) / 'server.py'
            target.write_bytes((ROOT / 'server.py').read_bytes())
            self.write(directory, {'BOT_TOKEN': '123456:test-config-only', 'WEBHOOK_HOST': 'https://example.test', 'WEBHOOK_SECRET': 'test-config-only', 'ADMIN_ID': 42})
            result = subprocess.run([sys.executable, '-I', str(target), '--check-config'], cwd=cwd, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Configuration OK', result.stdout)
            self.assertNotIn('test-config-only', result.stdout + result.stderr)

    def test_missing_conf_normal_start_is_blocked_before_bot_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'server.py'
            target.write_bytes((ROOT / 'server.py').read_bytes())
            result = subprocess.run([sys.executable, '-I', str(target)], cwd=directory, capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('conf.json', result.stderr)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ['server.py'])
