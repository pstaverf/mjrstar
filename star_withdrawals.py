"""Durable Stars reservations. A Fragment POST is never automatically replayed."""
import asyncio
import hashlib
import json
import logging
import re
import secrets
from sqlite3 import IntegrityError
import time
import uuid
from decimal import Decimal, InvalidOperation
from datetime import timedelta

import aiohttp
from games_backend import GameError, integer, serialize


STATES = {'CREATED', 'PENDING', 'BLOCKCHAIN_SENT', 'COMPLETED', 'FAILED'}
OPEN_STATES = ('queued', 'submitting', 'pending', 'blockchain_sent', 'uncertain', 'mismatch')


class StarWithdrawalsMixin:
    def register_star_withdrawals(self, app):
        app.router.add_get('/api/withdraw/info', self.handle_star_withdraw_info)
        app.router.add_post('/api/withdraw/quote', self.handle_star_withdraw_quote)
        app.router.add_post('/api/withdraw/confirm', self.handle_star_withdraw_confirm)
        app.router.add_get('/api/withdraw/job', self.handle_star_withdraw_status)
        app.router.add_get('/api/withdraw/status', self.handle_star_withdraw_status)

    def fragment_settings(self):
        from payments_backend import FRAGMENT_API_JWT, FRAGMENT_CURRENCY
        token = getattr(self, 'fragment_jwt', FRAGMENT_API_JWT).strip()
        currency = getattr(self, 'fragment_currency', FRAGMENT_CURRENCY)
        if currency not in {'ton', 'usdt_ton'} or not token or not token.isascii() or any(c.isspace() for c in token):
            raise GameError('Вывод Stars ещё не настроен. Администратору нужно заполнить Fragment Connection JWT и валюту оплаты на сервере.', 503)
        return token, currency, hashlib.sha256(token.encode()).hexdigest()

    async def star_execute_commit(self, db, sql, args=()):
        try:
            cursor = await db.execute(sql, args)
            await db.commit()
            return cursor
        except BaseException:
            await db.rollback()
            raise

    async def initialize_star_withdrawals(self):
        async with self.database_lock:
            db = self.database()
            await db.execute('CREATE TABLE IF NOT EXISTS webapp_star_quotes(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,username TEXT NOT NULL,quantity INTEGER NOT NULL,expires_at INTEGER NOT NULL,created_at INTEGER NOT NULL,used_id TEXT)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_star_quotes_user ON webapp_star_quotes(user_id,created_at)')
            await db.execute('CREATE TABLE IF NOT EXISTS webapp_star_withdrawals(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,username TEXT NOT NULL,quantity INTEGER NOT NULL,state TEXT NOT NULL,provider_id TEXT UNIQUE,token_hash TEXT NOT NULL,currency TEXT NOT NULL,request_key TEXT NOT NULL,digest TEXT NOT NULL,quote_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,error_code TEXT,provider_costs TEXT,UNIQUE(user_id,request_key))')
            await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_star_withdraw_open ON webapp_star_withdrawals(user_id) WHERE state IN ('queued','submitting','pending','blockchain_sent','uncertain','mismatch')")
            # A previous process may have sent this POST. There is no documented
            # provider-side create idempotency or lookup by our local request key.
            await db.execute("UPDATE webapp_star_withdrawals SET state='uncertain',error_code='PROCESS_RESTART_DURING_POST' WHERE state='submitting'")
            await db.commit()
        self.star_withdraw_task = asyncio.create_task(self.star_withdraw_loop())

    async def cleanup_star_withdrawals(self):
        if hasattr(self, 'star_withdraw_task'):
            self.star_withdraw_task.cancel()
            await asyncio.gather(self.star_withdraw_task, return_exceptions=True)

    async def fragment_api(self, method, path, data=None, token_hash=None):
        token, currency, fingerprint = self.fragment_settings()
        if token_hash and fingerprint != token_hash:
            raise GameError('Для проверки заказа требуется исходный Fragment JWT. Автоповтор и возврат заблокированы.', 503)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.request(method, 'https://api.fragment-api.com/v1/' + path, headers={'Authorization': 'JWT ' + token, 'Accept': 'application/json'}, json=data if method == 'POST' else None, allow_redirects=False) as response:
                    if response.status not in ({200, 201, 202} if method == 'POST' else {200}):
                        # No raw body, JWT, sender phone number, or third-party error dump.
                        raise GameError('Fragment API отклонил запрос. Не повторяйте отправку автоматически.', 502, 'FRAGMENT_HTTP_' + str(response.status))
                    result = await response.json(content_type=None)
                    if not isinstance(result, dict):
                        raise ValueError
                    return result
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, UnicodeError):
            raise GameError('Результат запроса Fragment не подтверждён. Повторная покупка отключена; требуется проверка заказа.', 502, 'FRAGMENT_UNCONFIRMED') from None

    def star_username(self, user):
        username = getattr(user, 'username', None)
        if not isinstance(username, str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{2,31}', username):
            raise GameError('Для получения Stars установите Telegram username и заново откройте Mini App.', 400)
        return username

    async def star_order(self, db, identifier, user_id=None):
        sql = 'SELECT * FROM webapp_star_withdrawals WHERE id=?'
        args = [identifier]
        if user_id is not None:
            sql += ' AND user_id=?'
            args.append(user_id)
        async with db.execute(sql, args) as cursor:
            row = await cursor.fetchone()
            columns = [item[0] for item in cursor.description]
        if not row:
            raise GameError('Вывод не найден.', 404)
        return dict(zip(columns, row))

    async def star_result(self, db, order):
        state = order['state']
        status = 'done' if state == 'completed' else 'failed' if state == 'failed' else 'slow' if state in {'uncertain', 'mismatch'} else 'processing'
        return {'ok': True, 'status': status, 'state': 'done' if state == 'completed' else state, 'job': order['id'], 'withdrawalId': order['id'], 'coin': 'Stars', 'sendAmount': order['quantity'], 'usd': order['quantity'], 'username': order['username'], 'balance': await self.balance(db, order['user_id']), 'refunded': state == 'failed', 'message': 'Провайдер подтвердил отказ. Резерв возвращён на баланс.' if state == 'failed' else 'Заказ требует проверки. Сумма остаётся в резерве; не создавайте повторную заявку.' if status == 'slow' else ''}

    async def ensure_star_withdraw_requirements(self, db, user_id):
        await self.ensure_check_wager(db, user_id)
        runtime = getattr(self, 'wallet_runtime', {})
        minimum = runtime.get('WITHDRAW_MIN_DEPOSIT', 50)
        days = runtime.get('WITHDRAW_DEPOSIT_DAYS', 7)
        since = (self.clock() - timedelta(days=days)).isoformat()
        async with db.execute("SELECT COALESCE(SUM(amount),0) FROM (SELECT user_id,amount,created_at FROM payments UNION ALL SELECT user_id,stars_cents/100.0,COALESCE(paid_at,created_at) FROM webapp_deposits WHERE provider!='stars' AND status='paid') WHERE user_id=? AND julianday(created_at)>=julianday(?)", (user_id, since)) as cursor:
            deposited = (await cursor.fetchone())[0]
        if deposited < minimum:
            raise GameError(f'Для вывода нужен депозит не менее {minimum} Stars за последние {days} дней. Сейчас: {deposited:g} Stars.', 403)

    async def handle_star_withdraw_info(self, request):
        try:
            user = self.validate_user(request)
            reason = ''
            try:
                self.fragment_settings()
                username = self.star_username(user)
            except GameError as error:
                reason, username = error.message, ''
            async with self.database_lock:
                db = self.database()
                balance = await self.balance(db, user.id)
                try:
                    await self.ensure_star_withdraw_requirements(db, user.id)
                except GameError as error:
                    reason = error.message
                async with db.execute("SELECT id FROM webapp_star_withdrawals WHERE user_id=? AND state NOT IN ('completed','failed')", (user.id,)) as cursor:
                    pending = await cursor.fetchone()
                active = await self.star_result(db, await self.star_order(db, pending[0], user.id)) if pending else None
            if not reason and balance < 50:
                reason = 'Минимум вывода — 50 Stars.'
            return self.response({'ok': True, 'eligible': not reason and not pending, 'balance': balance, 'username': username, 'methods': [{'id': 'stars', 'min': 50, 'max': min(1000000, int(balance))}], 'limits': {'min': 50, 'max': min(1000000, int(balance))}, 'manual': False, 'activeWithdrawal': active, 'block': {'title': 'Вывод Stars недоступен', 'text': reason or 'Предыдущая заявка ещё обрабатывается.', 'bars': []}})
        except GameError as error:
            return self.failure(error)

    async def handle_star_withdraw_quote(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            self.fragment_settings()
            username = self.star_username(user)
            if payload.get('method') != 'stars' or payload.get('coin', 'XTR') != 'XTR':
                raise GameError('Доступен только вывод Stars.')
            quantity = integer(payload.get('amount'), 50, 1000000)
            now = int(time.time())
            async with self.database_lock:
                db = self.database()
                await self.ensure_star_withdraw_requirements(db, user.id)
                if await self.balance(db, user.id) < quantity:
                    raise GameError('Недостаточно средств.')
                async with db.execute('SELECT COUNT(*) FROM webapp_star_quotes WHERE user_id=? AND created_at>?', (user.id, now - 60)) as cursor:
                    if (await cursor.fetchone())[0] >= 10:
                        raise GameError('Слишком много запросов. Подождите минуту.', 429)
                token = secrets.token_hex(24)
                await self.star_execute_commit(db, 'INSERT INTO webapp_star_quotes(id,user_id,username,quantity,expires_at,created_at) VALUES (?,?,?,?,?,?)', (token, user.id, username, quantity, now + 300, now))
            return self.response({'ok': True, 'method': 'stars', 'token': token, 'provider': 'Fragment API', 'display': 'Stars', 'coinAmount': quantity, 'usd': quantity, 'quantity': quantity, 'username': username, 'expiresIn': 300})
        except GameError as error:
            return self.failure(error)

    async def handle_star_withdraw_confirm(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            _, digest = self.request_identity(request, payload)
            key = payload.get('reqId') or request.headers.get('Idempotency-Key')
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', key):
                raise GameError('Некорректный идентификатор запроса.')
            async with self.database_lock:
                db = self.database()
                try:
                    await db.execute('BEGIN IMMEDIATE')
                    async with db.execute('SELECT id,digest FROM webapp_star_withdrawals WHERE user_id=? AND request_key=?', (user.id, key)) as cursor:
                        replay = await cursor.fetchone()
                    if replay:
                        if replay[1] != digest:
                            raise GameError('Идентификатор уже использован для другого запроса.', 409)
                        result = await self.star_result(db, await self.star_order(db, replay[0], user.id))
                    else:
                        async with db.execute('SELECT username,quantity,expires_at,used_id FROM webapp_star_quotes WHERE id=? AND user_id=?', (payload.get('token', ''), user.id)) as cursor:
                            quote = await cursor.fetchone()
                        if not quote:
                            raise GameError('Подтверждение не найдено.', 404)
                        if quote[3]:
                            result = await self.star_result(db, await self.star_order(db, quote[3], user.id))
                        else:
                            _, currency, fingerprint = self.fragment_settings()
                            if quote[2] < time.time() or quote[0].lower() != self.star_username(user).lower():
                                raise GameError('Подтверждение устарело или username изменился. Проверьте данные заново.', 409)
                            await self.ensure_star_withdraw_requirements(db, user.id)
                            async with db.execute("SELECT 1 FROM webapp_star_withdrawals WHERE user_id=? AND state NOT IN ('completed','failed')", (user.id,)) as cursor:
                                if await cursor.fetchone():
                                    raise GameError('Сначала дождитесь результата предыдущего вывода.', 409)
                            identifier = 'sw_' + secrets.token_hex(16)
                            cursor = await db.execute('UPDATE balances SET amount=ROUND(amount-?,2) WHERE user_id=? AND ROUND(amount*100)>=?', (quote[1], user.id, quote[1] * 100))
                            if cursor.rowcount != 1:
                                raise GameError('Недостаточно средств.')
                            stamp = self.clock().isoformat()
                            await db.execute('INSERT INTO webapp_star_withdrawals(id,user_id,username,quantity,state,token_hash,currency,request_key,digest,quote_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (identifier, user.id, quote[0], quote[1], 'queued', fingerprint, currency, key, digest, payload['token'], stamp, stamp))
                            await db.execute("INSERT INTO webapp_wallet_events(user_id,kind,amount_cents,source,created_at) VALUES (?,'withdrawal_reserve',?,?,?)", (user.id, -quote[1] * 100, identifier + ':reserve', stamp))
                            await db.execute('UPDATE webapp_star_quotes SET used_id=? WHERE id=?', (identifier, payload['token']))
                            result = await self.star_result(db, await self.star_order(db, identifier, user.id))
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
            return self.response(result)
        except GameError as error:
            return self.failure(error)

    async def handle_star_withdraw_status(self, request):
        try:
            user = self.validate_user(request)
            identifier = request.query.get('id') or request.query.get('job') or request.query.get('withdrawalId', '')
            async with self.database_lock:
                result = await self.star_result(self.database(), await self.star_order(self.database(), identifier, user.id))
            return self.response(result)
        except GameError as error:
            return self.failure(error)

    def fragment_order_matches(self, order, result):
        try:
            identifier = str(uuid.UUID(result['id']))
            return (result.get('type') == 'STARS' and result.get('status') in STATES and
                    isinstance(result.get('receiver'), str) and result['receiver'].removeprefix('@').lower() == order['username'].lower() and
                    type(result.get('goods_quantity')) is int and result['goods_quantity'] == order['quantity'] and
                    (not order.get('provider_id') or identifier == order['provider_id']))
        except (ValueError, TypeError, KeyError, AttributeError):
            return False

    def fragment_costs(self, result):
        costs = {}
        for key in ('price', 'fee'):
            item = result.get(key)
            if isinstance(item, dict) and item.get('currency') in {'ton', 'usdt_ton'}:
                try:
                    amount = Decimal(item['amount'])
                    if amount.is_finite() and amount >= 0:
                        costs[key] = {'currency': item['currency'], 'amount': str(amount)}
                except (InvalidOperation, ValueError, KeyError, TypeError):
                    pass
        return serialize(costs)

    async def process_star_withdrawal(self, identifier):
        async with self.database_lock:
            db = self.database()
            order = await self.star_order(db, identifier)
            if order['state'] in {'completed', 'failed', 'uncertain', 'mismatch', 'submitting'}:
                return
            _, _, fingerprint = self.fragment_settings()
            if order['token_hash'] != fingerprint:
                return  # Original JWT is required. Never replace credentials silently.
            creating = order['state'] == 'queued'
            if creating:
                cursor = await self.star_execute_commit(db, "UPDATE webapp_star_withdrawals SET state='submitting',updated_at=? WHERE id=? AND state='queued'", (self.clock().isoformat(), identifier))
                if cursor.rowcount != 1:
                    return
        if creating:
            try:
                result = await self.fragment_api('POST', 'order/stars/', {'username': order['username'], 'quantity': order['quantity'], 'show_sender': False, 'currency': order['currency']}, token_hash=order['token_hash'])
                matched = self.fragment_order_matches(order, result)
                provider_id = str(uuid.UUID(result['id'])) if matched else None
                state = 'pending' if matched else 'mismatch'
            except GameError:
                state, provider_id = 'uncertain', None
            async with self.database_lock:
                db = self.database()
                try:
                    await self.star_execute_commit(db, 'UPDATE webapp_star_withdrawals SET state=?,provider_id=?,updated_at=? WHERE id=?', (state, provider_id, self.clock().isoformat(), identifier))
                except IntegrityError:
                    await self.star_execute_commit(db, "UPDATE webapp_star_withdrawals SET state='mismatch',error_code='DUPLICATE_PROVIDER_ORDER' WHERE id=?", (identifier,))
                    return
            if not provider_id:
                return
            order['provider_id'] = provider_id
        # All terminal transitions require an authenticated GET, not a webhook.
        result = await self.fragment_api('GET', 'order/' + order['provider_id'] + '/', token_hash=order['token_hash'])
        async with self.database_lock:
            db = self.database()
            try:
                await db.execute('BEGIN IMMEDIATE')
                current = await self.star_order(db, identifier)
                if current['state'] in {'completed', 'failed'}:
                    await db.rollback()
                    return
                if not self.fragment_order_matches(current, result):
                    state = 'mismatch'
                elif result['status'] == 'COMPLETED' and result.get('success') is True:
                    state = 'completed'
                elif result['status'] == 'FAILED' and result.get('success') is False:
                    state = 'failed'
                    await self.wallet_credit(db, current['user_id'], current['quantity'] * 100, 'withdrawal_refund', identifier + ':refund')
                else:
                    state = 'blockchain_sent' if result['status'] == 'BLOCKCHAIN_SENT' else 'pending'
                await db.execute('UPDATE webapp_star_withdrawals SET state=?,updated_at=?,provider_costs=? WHERE id=?', (state, self.clock().isoformat(), self.fragment_costs(result), identifier))
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def star_withdraw_loop(self):
        while True:
            try:
                _, _, fingerprint = self.fragment_settings()
                async with self.database_lock:
                    async with self.database().execute("SELECT id FROM webapp_star_withdrawals WHERE state IN ('queued','pending','blockchain_sent') AND token_hash=? ORDER BY updated_at LIMIT 5", (fingerprint,)) as cursor:
                        ids = [row[0] for row in await cursor.fetchall()]
                for identifier in ids:
                    try:
                        await self.process_star_withdrawal(identifier)
                    except GameError:
                        async with self.database_lock:
                            await self.database().execute('UPDATE webapp_star_withdrawals SET updated_at=? WHERE id=?', (self.clock().isoformat(), identifier))
                            await self.database().commit()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if not isinstance(error, GameError):
                    logging.warning('Stars withdrawal worker error: %s', type(error).__name__)
            await asyncio.sleep(5)
