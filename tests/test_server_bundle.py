import ast
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('server_bundle_builder', ROOT / 'tools' / 'build_server.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ServerBundleTests(unittest.TestCase):
    def test_generated_bundle_matches_sources(self):
        self.assertEqual((ROOT / 'server.py').read_text(encoding='utf-8'), builder.render(), 'Rebuild using python tools/build_server.py')

    def test_source_literals_roundtrip(self):
        for source in ('x = 1\n', 'x = "\\n"\n', "# ''' and \"\"\"\nx = 1\n", 'x = "Привет"\n'):
            self.assertEqual(ast.literal_eval(builder.source_literal(source)), source)

    def run_standalone(self, code=None, args=()):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'server.py'
            path.write_bytes((ROOT / 'server.py').read_bytes())
            command = [sys.executable, '-I']
            command += ['-c', code] if code else [str(path), *args]
            result = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ['server.py'], 'Check/import must not extract modules or create runtime files')
            return result.stdout

    def test_all_modules_import_without_any_other_project_files(self):
        output = self.run_standalone(args=('--check',))
        self.assertIn('Bundle OK:', output)
        self.assertIn('no server started', output)

    def test_isolated_entrypoint_and_original_deployment_paths(self):
        output = self.run_standalone(code='''
import runpy, sys
from pathlib import Path
bundle = runpy.run_path('server.py')
app = bundle['load_application']()
assert app.WEBAPP_ROOT == Path.cwd()
assert app.DB_PATH == 'bot.db'
assert app.WEBAPP_HOST == '0.0.0.0'
assert 'ton_wallet' in bundle['_SOURCES']
from complete_games import CompleteGamesBackend
from emoji_rules import EMOJI_CATALOG
assert EMOJI_CATALOG
from payments_backend import TON_WALLET_MNEMONIC, TON_WALLET_SEED_FILE, FRAGMENT_API_JWT
assert TON_WALLET_MNEMONIC == TON_WALLET_SEED_FILE == FRAGMENT_API_JWT == ''
app.main = lambda: print('ENTRYPOINT_OK')
sys.argv = ['server.py']
bundle['main']()
''')
        self.assertIn('ENTRYPOINT_OK', output)

    def test_backend_initializes_from_bundle_with_in_memory_database(self):
        output = self.run_standalone(code="""
import asyncio, runpy
from aiohttp import web
bundle = runpy.run_path('server.py')
runtime = bundle['load_application']()
from complete_games import CompleteGamesBackend
async def check():
    runtime.DB_PATH = ':memory:'
    await runtime.db_init()
    await runtime.init_db()
    backend = CompleteGamesBackend(runtime.db, runtime._db_lock, runtime.webapp_authenticated_user, runtime.now_msk)
    app = web.Application()
    backend.register(app)
    await backend.initialize(app)
    assert len(list(app.router.routes())) > 50
    await backend.cleanup(app)
    await runtime.db_close()
    print('BACKEND_INITIALIZED')
asyncio.run(check())
""")
        self.assertIn('BACKEND_INITIALIZED', output)

    def test_wallet_check_is_available_without_external_cli_file(self):
        output = self.run_standalone(code='''
import runpy, sys
bundle = runpy.run_path('server.py')
sys.argv = ['server.py', '--check-ton-wallet', '--local-only']
try:
    bundle['main']()
except SystemExit as error:
    assert error.code == 1
else:
    raise AssertionError('No seed configured: wallet check must fail closed')
print('EMPTY_SEED_BLOCKED')
''')
        self.assertIn('EMPTY_SEED_BLOCKED', output)

    def test_frontend_scripts_are_not_embedded(self):
        # Inspect assignments rather than importing a second set of app modules.
        names = []
        for node in ast.parse((ROOT / 'server.py').read_text(encoding='utf-8')).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Subscript):
                target = node.targets[0]
                if isinstance(target.value, ast.Name) and target.value.id == '_SOURCES':
                    names.append(ast.literal_eval(target.slice))
        self.assertIn('support_backend', names)
        self.assertNotIn('support.js', names)
        self.assertNotIn('sw.js', names)
        self.assertEqual(set(names), {p.stem for p in ROOT.glob('*.py') if p.name != 'server.py'})
