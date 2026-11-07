"""Read-only WebSocket updates; all money-changing commands remain signed HTTP POSTs."""
import asyncio
import json
import secrets
import time
from urllib.parse import urlsplit

from aiohttp import web, WSMsgType
from pot_rules import POT_GAMES


class RealtimeMixin:
    def register_realtime(self, app):
        self.realtime_public_cache = (0, [])
        self.realtime_pending = 0
        self.realtime_tickets = {}
        self.realtime_sockets = set()
        self.realtime_users = {}
        app.router.add_post('/api/realtime/session', self.handle_realtime_session)
        app.router.add_get('/api/ws', self.handle_realtime_socket)

    async def handle_realtime_session(self, request):
        user = self.validate_user(request)
        now = time.monotonic()
        self.realtime_tickets = {k: v for k, v in self.realtime_tickets.items() if v[1] > now}
        owned = [k for k, v in self.realtime_tickets.items() if v[0] == user.id]
        for key in owned[:-4]:
            self.realtime_tickets.pop(key, None)
        if len(self.realtime_tickets) >= 2000:
            return self.response({'ok': False, 'error': 'Попробуйте позже.'}, 429)
        ticket = secrets.token_urlsafe(32)
        self.realtime_tickets[ticket] = (user.id, now + 30)
        return self.response({'ok': True, 'ticket': ticket, 'expiresIn': 30, 'path': '/api/ws'})

    async def realtime_snapshot(self, user_id):
        async with self.database_lock:
            db = self.database()
            balance = await self.balance(db, user_id)
            where, args = ('', ()) if self.support_admin(user_id) else ('WHERE user_id=?', (user_id,))
            async with db.execute('SELECT COUNT(*),COALESCE(SUM(rev),0) FROM webapp_support_tickets ' + where, args) as cur:
                support_rev = list(await cur.fetchone())
            # Public game phases are identical for every viewer. Cache only this whitelist;
            # each user's balance and support revision are always read fresh above.
            until, live = self.realtime_public_cache
            if time.monotonic() >= until:
                async with db.execute('SELECT id,game,data FROM webapp_live_rounds WHERE finished=0 ORDER BY game,id') as cur:
                    live = [{'roundId': row[0], 'game': row[1], 'phase': json.loads(row[2]).get('status')} for row in await cur.fetchall()]
                rooms = [(game, room) for game in POT_GAMES for room in (1, 2)]
                values = ','.join('(?,?)' for _ in rooms)
                sql = f"""WITH rooms(game,room) AS (VALUES {values})
                    SELECT id,game,room,phase FROM webapp_pot_rounds WHERE id IN (
                        SELECT (SELECT id FROM webapp_pot_rounds r WHERE r.game=rooms.game AND r.room=rooms.room ORDER BY seq DESC LIMIT 1) FROM rooms
                    ) ORDER BY game,room"""
                async with db.execute(sql, [value for pair in rooms for value in pair]) as cur:
                    live += [{'roundId': row[0], 'game': row[1], 'room': row[2], 'phase': row[3]} for row in await cur.fetchall()]
                self.realtime_public_cache = (time.monotonic() + 0.5, live)
        return {'type': 'state', 'balance': balance, 'supportRevision': support_rev, 'games': live}

    async def handle_realtime_socket(self, request):
        origin = request.headers.get('Origin')
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in {'https', 'http'} or parsed.netloc != request.host:
                raise web.HTTPForbidden()
        if len(self.realtime_sockets) + self.realtime_pending >= 64:
            raise web.HTTPServiceUnavailable(headers={'Retry-After': '10'})
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4096, receive_timeout=60)
        self.realtime_pending += 1
        try:
            await ws.prepare(request)
            self.realtime_sockets.add(ws)
        finally:
            self.realtime_pending -= 1
        user_id = None
        try:
            try:
                message = await asyncio.wait_for(ws.receive(), timeout=5)
                data = json.loads(message.data) if message.type == WSMsgType.TEXT else None
                ticket = data.get('ticket') if isinstance(data, dict) else None
                auth = self.realtime_tickets.pop(ticket, None) if isinstance(ticket, str) else None
                if auth is None or auth[1] <= time.monotonic():
                    await ws.close(code=1008, message=b'Authentication required')
                    return ws
                candidate = auth[0]
                if self.realtime_users.get(candidate, 0) >= 3:
                    await ws.close(code=1008, message=b'Too many connections')
                    return ws
                user_id = candidate
                self.realtime_users[user_id] = self.realtime_users.get(user_id, 0) + 1
            except (ValueError, TypeError, asyncio.TimeoutError):
                await ws.close(code=1008, message=b'Authentication required')
                return ws
            await ws.send_json({'type': 'ready', 'readOnly': True})
            previous = None
            expires = time.monotonic() + 900
            while not ws.closed and time.monotonic() < expires:
                snapshot = await self.realtime_snapshot(user_id)
                if snapshot != previous:
                    await ws.send_json({**snapshot, 'serverTime': int(time.time() * 1000)})
                    previous = snapshot
                # Client messages never execute wagers, credits or support/admin actions.
                try:
                    incoming = await asyncio.wait_for(ws.receive(), timeout=2)
                    if incoming.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                        break
                    await ws.close(code=1008, message=b'Read-only connection')
                    break
                except asyncio.TimeoutError:
                    pass
            await ws.close(code=1000, message=b'Reconnect to renew session')
            return ws
        finally:
            self.realtime_sockets.discard(ws)
            if user_id is not None:
                self.realtime_users[user_id] -= 1
                if not self.realtime_users[user_id]:
                    self.realtime_users.pop(user_id, None)

    async def cleanup_realtime(self):
        await asyncio.gather(*(ws.close(code=1001, message=b'Server shutdown') for ws in list(self.realtime_sockets)), return_exceptions=True)
        self.realtime_tickets.clear()
