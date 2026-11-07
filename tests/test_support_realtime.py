import asyncio
import json
import secrets
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from aiohttp import WSMsgType, web, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer
from complete_games import CompleteGamesBackend
import test_games_backend as fixtures


class SupportRealtimeTests(unittest.IsolatedAsyncioTestCase):
    backend_type = CompleteGamesBackend
    asyncSetUp = fixtures.GamesBackendTests.asyncSetUp
    asyncTearDown = fixtures.GamesBackendTests.asyncTearDown
    headers = fixtures.GamesBackendTests.headers

    async def post(self, path, payload, user=42, key=None):
        self.backend.wallet_runtime = {"ADMIN_ID": 99}
        response = await self.client.post('/api/' + path, json=payload, headers=self.headers(user, key))
        return response.status, await response.json()

    async def get(self, path, user=42):
        self.backend.wallet_runtime = {"ADMIN_ID": 99}
        response = await self.client.get('/api/' + path, headers=self.headers(user))
        return response.status, await response.json()

    async def create(self, key=None):
        status, data = await self.post('support/ticket/create', {'subject': 'Game payment', 'category': 'game', 'text': 'Please check my round'}, key=key)
        self.assertEqual(status, 200, data)
        return data

    async def test_ticket_admin_reply_close_reopen_and_unread(self):
        data = await self.create()
        tid = data['ticket']['id']
        own = (await self.get('support/state'))[1]
        self.assertEqual(len(own['tickets']), 1)
        self.assertFalse(own['isAdmin'])
        admin = (await self.get('support/state', 99))[1]
        self.assertTrue(admin['isAdmin'])
        self.assertEqual(admin['unread'], 1)
        status, reply = await self.post('support/ticket/reply', {'id': tid, 'text': 'Resolved by support'}, 99)
        self.assertEqual(status, 200, reply)
        self.assertEqual(reply['message']['author'], 'staff')
        self.assertEqual(reply['ticket']['status'], 'answered')
        self.assertEqual((await self.get('support/state'))[1]['unread'], 1)
        status, detail = await self.get(f'support/ticket?id={tid}&after=0')
        self.assertEqual(status, 200)
        self.assertEqual(len(detail['messages']), 2)
        self.assertEqual((await self.get('support/state'))[1]['unread'], 0)
        await self.post('support/ticket/close', {'id': tid}, 99)
        self.assertEqual((await self.get(f'support/ticket?id={tid}'))[1]['ticket']['status'], 'closed')
        reply = (await self.post('support/ticket/reply', {'id': tid, 'text': 'One more question'}))[1]
        self.assertEqual(reply['ticket']['status'], 'open')

    async def test_foreign_access_and_client_admin_flags_rejected(self):
        tid = (await self.create())['ticket']['id']
        for path in [f'support/ticket?id={tid}', 'support/state']:
            status, data = await self.get(path, 77)
            if path.endswith('state'):
                self.assertEqual(data['tickets'], [])
                self.assertFalse(data['isAdmin'])
            else:
                self.assertEqual(status, 404)
        self.assertEqual((await self.post('support/ticket/reply', {'id': tid, 'text': 'fake admin', 'isAdmin': True}, 77))[0], 404)
        self.assertEqual((await self.post('support/ticket/reply', {'id': tid, 'text': 'spoof uid', 'uid': 42}, 77))[0], 403)
        self.assertEqual((await self.post('support/ticket/close', {'id': tid}, 77))[0], 404)
        response = await self.client.get('/api/support/state')
        self.assertEqual(response.status, 401)

    async def test_idempotent_create_reply_and_validation(self):
        key = secrets.token_hex(16)
        a = await self.create(key)
        b = await self.create(key)
        self.assertEqual(a['ticket']['id'], b['ticket']['id'])
        tid = a['ticket']['id']
        key = secrets.token_hex(16)
        results = await asyncio.gather(*(self.post('support/ticket/reply', {'id': tid, 'text': 'one reply'}, key=key) for _ in range(5)))
        self.assertTrue(all(r[0] == 200 for r in results))
        self.assertEqual(len((await self.get(f'support/ticket?id={tid}'))[1]['messages']), 2)
        self.assertEqual((await self.post('support/ticket/reply', {'id': tid, 'text': 'changed'}, key=key))[0], 409)
        for payload in [[], {'subject': [], 'text': 'hello'}, {'subject': 'Okay', 'text': []}, {'subject': 'Okay', 'text': 'hello', 'category': []}, {'subject': 'Okay', 'text': 'hello', 'files': [[], []]}]:
            self.assertEqual((await self.post('support/ticket/create', payload))[0], 400)

    async def test_edit_delete_incremental_and_audit(self):
        created = await self.create()
        tid, mid = created['ticket']['id'], created['message']['id']
        first = (await self.get(f'support/ticket?id={tid}'))[1]
        status, edited = await self.post('support/message/edit', {'id': tid, 'mid': mid, 'text': 'Updated details'})
        self.assertEqual(status, 200)
        poll = (await self.get(f'support/ticket?id={tid}&after={mid}&rev={first["rev"]}'))[1]
        self.assertEqual(poll['messages'], [])
        self.assertEqual(poll['changed'][0]['text'], 'Updated details')
        self.assertEqual((await self.post('support/message/edit', {'id': tid, 'mid': mid, 'text': 'Admin overwrite'}, 99))[0], 403)
        self.assertEqual((await self.post('support/message/delete', {'id': tid, 'mid': mid}))[0], 200)
        detail = (await self.get(f'support/ticket?id={tid}'))[1]
        self.assertTrue(detail['messages'][0]['deleted'])
        self.assertEqual(detail['messages'][0]['text'], '')
        async with self.runtime._db_lock:
            async with self.runtime.db().execute('SELECT COUNT(*) FROM webapp_support_audit WHERE ticket_id=?', (tid,)) as cur:
                self.assertGreaterEqual((await cur.fetchone())[0], 3)

    async def test_upload_attachment_ownership_and_private_download(self):
        png = b'\x89PNG\r\n\x1a\n' + b'local test image'
        response = await self.client.post('/api/support/upload', data=png, headers={**self.headers(), 'Content-Type': 'image/png'})
        self.assertEqual(response.status, 200)
        file_id = (await response.json())['file']['id']
        response = await self.client.get('/api/support/file?t=' + file_id, headers=self.headers(77))
        self.assertEqual(response.status, 404)
        status, data = await self.post('support/ticket/create', {'subject': 'Screenshot', 'text': 'Please check', 'files': [file_id]})
        self.assertEqual(status, 200, data)
        self.assertEqual(data['message']['files'], [{'t': file_id}])
        response = await self.client.get('/api/support/file?t=' + file_id, headers=self.headers(99))
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.read(), png)
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')
        self.assertEqual((await self.post('support/ticket/create', {'subject': 'Again', 'text': 'another ticket', 'files': [file_id]}))[0], 400)
        response = await self.client.post('/api/support/upload', data=b'<svg>not an allowed upload</svg>', headers=self.headers())
        self.assertEqual(response.status, 400)

    async def test_sql_failure_rolls_back_support_and_balance_unchanged(self):
        async with self.runtime._db_lock:
            await self.runtime.db().execute("CREATE TRIGGER fail_support BEFORE INSERT ON webapp_support_messages BEGIN SELECT RAISE(ABORT,'test failure'); END")
            await self.runtime.db().commit()
        with self.assertLogs('aiohttp.server', level='ERROR'):
            response = await self.client.post('/api/support/ticket/create', json={'subject': 'Test', 'text': 'Will roll back'}, headers=self.headers())
            self.assertEqual(response.status, 500)
        self.assertEqual((await self.get('support/state'))[1]['tickets'], [])
        self.assertEqual(await self.runtime.get_balance(42), 1000)

    async def mint(self, user=42):
        status, data = await self.post('realtime/session', {}, user)
        self.assertEqual(status, 200, data)
        return data['ticket']

    async def test_websocket_own_balance_updates_and_support_revision(self):
        ticket = await self.mint()
        ws = await self.client.ws_connect('/api/ws')
        await ws.send_json({'ticket': ticket})
        self.assertEqual((await ws.receive_json(timeout=2))['type'], 'ready')
        initial = await ws.receive_json(timeout=2)
        self.assertEqual(initial['balance'], 1000)
        raw = json.dumps(initial)
        for forbidden in ['serverSeed', '_seed', '_crashPoint', 'initData', 'ticket']:
            self.assertNotIn(forbidden, raw)
        async with self.runtime._db_lock:
            await self.runtime.db().execute('UPDATE balances SET amount=1005 WHERE user_id=42')
            await self.runtime.db().commit()
        await self.create()
        changed = await ws.receive_json(timeout=5)
        self.assertEqual(changed['balance'], 1005)
        self.assertNotEqual(changed['supportRevision'], initial['supportRevision'])
        await ws.close()

    async def test_websocket_tickets_expiry_replay_and_no_wagers(self):
        ticket = await self.mint()
        ws = await self.client.ws_connect('/api/ws')
        await ws.send_json({'ticket': ticket})
        await ws.receive_json(timeout=2)
        await ws.receive_json(timeout=2)
        second = await self.client.ws_connect('/api/ws')
        await second.send_json({'ticket': ticket})
        message = await second.receive(timeout=2)
        self.assertEqual(message.type, WSMsgType.CLOSE)
        self.assertEqual(message.data, 1008)
        await second.close()
        await ws.send_json({'type': 'bet', 'amount': 100, 'userId': 99})
        self.assertEqual((await ws.receive(timeout=2)).data, 1008)
        await ws.close()
        self.assertEqual(await self.runtime.get_balance(42), 1000)
        ticket = await self.mint()
        self.backend.realtime_tickets[ticket] = (42, time.monotonic() - 1)
        expired = await self.client.ws_connect('/api/ws')
        await expired.send_json({'ticket': ticket})
        self.assertEqual((await expired.receive(timeout=2)).data, 1008)
        await expired.close()
        with self.assertRaises(WSServerHandshakeError) as error:
            await self.client.ws_connect('/api/ws', headers={'Origin': 'https://evil.example'})
        self.assertEqual(error.exception.status, 403)

    async def test_production_guard_allows_only_ws_ticket_handshake(self):
        app = web.Application(middlewares=[self.runtime.webapp_api_guard])
        app.router.add_post('/api/realtime/session', self.backend.handle_realtime_session)
        app.router.add_get('/api/ws', self.backend.handle_realtime_socket)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.post('/api/realtime/session')
            self.assertEqual(response.status, 404)
            response = await client.post('/api/realtime/session', headers=self.headers())
            ticket = (await response.json())['ticket']
            ws = await client.ws_connect('/api/ws')
            await ws.send_json({'ticket': ticket})
            self.assertEqual((await ws.receive_json(timeout=2))['type'], 'ready')
            await ws.close()
            response = await client.get('/api/ws')
            self.assertEqual(response.status, 404)
        finally:
            await client.close()

    async def test_bet_contract_and_doghouse_removed(self):
        status, data = await self.get('bets/status')
        self.assertEqual(status, 200)
        self.assertIs(data['accepting'], True)
        self.assertIn('doghouse', (await self.get('games/off'))[1]['off'])
        for path in ['doghouse/state', 'doghouse/page']:
            status, data = await self.get(path)
            self.assertEqual(status, 410)
            self.assertEqual(data['code'], 'GAME_REMOVED')
        self.assertEqual((await self.post('doghouse/play', {'bet': 10}))[0], 410)
        self.assertEqual(await self.runtime.get_balance(42), 1000)
        self.assertNotIn('doghouse', (await self.get('bet-limits'))[1]['limits'])

    async def test_subscription_uses_real_member_status(self):
        class Bot:
            async def get_chat_member(self, **kwargs):
                return SimpleNamespace(status='member')
        self.backend.telegram_bot = Bot()
        self.backend.telegram_channel = '@mjrstars'
        status, data = await self.get('subscription/check')
        self.assertEqual(status, 200)
        self.assertTrue(data['subscribed'])
        self.assertTrue(data['required'])
        self.assertEqual(data['channels'][0]['url'], 'https://t.me/mjrstars')
