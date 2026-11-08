import bundle_test_support  # Register backend modules from server.py.
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from complete_games import CompleteGamesBackend
import test_games_backend as fixtures


class RuntimePerformanceTests(unittest.IsolatedAsyncioTestCase):
    backend_type = CompleteGamesBackend
    asyncSetUp = fixtures.GamesBackendTests.asyncSetUp
    asyncTearDown = fixtures.GamesBackendTests.asyncTearDown
    headers = fixtures.GamesBackendTests.headers

    async def stop_live(self):
        self.backend.live_task.cancel()
        await asyncio.gather(self.backend.live_task, return_exceptions=True)

    async def seed_support(self, count=20):
        db = self.runtime.db()
        for index in range(count):
            row = await db.execute("INSERT INTO webapp_support_tickets(user_id,subject,category,status,created_at,updated_at) VALUES (42,?,'general','closed',1,1)", ('Ticket ' + str(index),))
            await db.execute("INSERT INTO webapp_support_messages(ticket_id,user_id,author,text,created_at,rev) VALUES (?,99,'staff','Reply',1,2)", (row.lastrowid,))
        await db.commit()

    async def test_support_state_and_unread_have_constant_query_count(self):
        await self.stop_live()
        self.backend.wallet_runtime = {'ADMIN_ID': 99}
        await self.seed_support(30)
        queries = []
        await self.runtime.db().set_trace_callback(queries.append)
        try:
            response = await self.client.get('/api/support/state', headers=self.headers())
            data = await response.json()
            self.assertEqual(len(data['tickets']), 30)
            self.assertEqual(data['unread'], 30)
            self.assertEqual(data['tickets'][0]['preview'], 'Reply')
            self.assertLessEqual(sum(q.lstrip().upper().startswith('SELECT') for q in queries), 2)
            queries.clear()
            response = await self.client.get('/api/support/unread', headers=self.headers())
            self.assertEqual((await response.json())['unread'], 30)
            self.assertEqual(sum(q.lstrip().upper().startswith('SELECT') for q in queries), 1)
        finally:
            await self.runtime.db().set_trace_callback(None)

    async def test_realtime_shares_only_public_queries_and_reads_fresh_money(self):
        await self.stop_live()
        first = await self.backend.realtime_snapshot(42)
        queries = []
        await self.runtime.db().set_trace_callback(queries.append)
        try:
            await self.runtime.db().execute('UPDATE balances SET amount=1111 WHERE user_id=42')
            await self.runtime.db().commit()
            own = await self.backend.realtime_snapshot(42)
            other = await self.backend.realtime_snapshot(99)
            self.assertEqual(own['balance'], 1111)
            self.assertEqual(other['balance'], 1000)
            self.assertEqual(first['games'], own['games'])
            self.assertFalse(any('webapp_pot_rounds' in q or 'webapp_live_rounds' in q for q in queries))
        finally:
            await self.runtime.db().set_trace_callback(None)

    async def test_idle_live_ticks_do_not_rewrite_rounds(self):
        await self.stop_live()
        db = self.runtime.db()
        await self.backend.advance_live(db, 'crash')
        await self.backend.advance_live(db, 'roulette')
        await db.commit()
        before = db.total_changes
        for _ in range(5):
            await self.backend.advance_live(db, 'crash')
            await self.backend.advance_live(db, 'roulette')
        await db.commit()
        self.assertEqual(db.total_changes, before)

    async def test_deleted_reply_is_not_unread(self):
        await self.stop_live()
        await self.seed_support(1)
        db = self.runtime.db()
        await db.execute('UPDATE webapp_support_messages SET deleted=1')
        await db.commit()
        for path in ['state', 'unread']:
            response = await self.client.get('/api/support/' + path, headers=self.headers())
            self.assertEqual((await response.json())['unread'], 0)

    async def test_large_after_cursor_cannot_mark_future_messages_read(self):
        await self.stop_live()
        await self.seed_support(1)
        response = await self.client.get('/api/support/ticket?id=1&after=999999999&rev=0', headers=self.headers())
        self.assertEqual(response.status, 200)
        db = self.runtime.db()
        async with db.execute('SELECT user_read FROM webapp_support_tickets WHERE id=1') as cur:
            self.assertLess((await cur.fetchone())[0], 999999999)
        await db.execute("INSERT INTO webapp_support_messages(ticket_id,user_id,author,text,created_at,rev) VALUES (1,99,'staff','New reply',2,3)")
        await db.commit()
        response = await self.client.get('/api/support/unread', headers=self.headers())
        self.assertEqual((await response.json())['unread'], 1)

    async def test_support_counters_include_tickets_outside_first_page(self):
        await self.stop_live()
        await self.seed_support(201)
        response = await self.client.get('/api/support/state', headers=self.headers())
        data = await response.json()
        self.assertEqual(len(data['tickets']), 200)
        self.assertEqual(data['unread'], 201)

    async def test_auth_cache_is_request_local_and_keyed_to_exact_signed_data(self):
        await self.stop_live()
        auth = self.runtime.webapp_authenticated_user
        first = make_mocked_request('GET', '/api/state', headers=self.headers())
        original = self.runtime.safe_parse_webapp_init_data
        with patch.object(self.runtime, 'safe_parse_webapp_init_data', wraps=original) as parser:
            self.assertEqual(auth(first).id, 42)
            self.assertEqual(auth(first).id, 42)
            self.assertEqual(parser.call_count, 1)
            # A different raw value must never inherit the first successful validation.
            with self.assertRaises(web.HTTPUnauthorized):
                auth(first, 'forged-init-data')
            self.assertEqual(parser.call_count, 2)
            other = make_mocked_request('GET', '/api/state', headers=self.headers(99))
            self.assertEqual(auth(other).id, 99)
            self.assertEqual(parser.call_count, 3)
            foreign = make_mocked_request('GET', '/api/state?uid=99', headers=self.headers())
            with self.assertRaises(web.HTTPForbidden):
                auth(foreign)
