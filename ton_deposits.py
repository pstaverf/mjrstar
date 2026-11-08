"""Native TON deposits using a server-restored wallet and own v3 chain gateway."""
import asyncio
import base64
import binascii
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import logging
import re
import secrets
import time
from urllib.parse import urlencode, quote, urlsplit

import aiohttp
from games_backend import GameError, money_cents


def ton_address(value):
    if not isinstance(value, str):
        raise ValueError('Invalid TON address')
    if re.fullmatch(r'(0|-1):[a-fA-F0-9]{64}', value):
        wc, account = value.split(':')
        raw = int(wc).to_bytes(1, 'big', signed=True) + bytes.fromhex(account)
    else:
        if not re.fullmatch(r'[a-zA-Z0-9_+/-]{48}', value):
            raise ValueError('Invalid TON address')
        data = base64.urlsafe_b64decode(value.replace('+', '-').replace('/', '_'))
        if len(data) != 36 or data[0] not in {0x11, 0x51} or binascii.crc_hqx(data[:34], 0).to_bytes(2, 'big') != data[34:]:
            raise ValueError('Invalid or testnet TON address')
        raw = data[1:34]
    wc = int.from_bytes(raw[:1], 'big', signed=True)
    if wc not in {0, -1} or not any(raw[1:]):
        raise ValueError('Invalid TON receiving account')
    return str(wc) + ':' + raw[1:].hex()


def ton_hash(value):
    if not isinstance(value, str):
        raise ValueError('Invalid transaction hash')
    if re.fullmatch(r'[a-fA-F0-9]{64}', value):
        return value.lower()
    decoded = base64.b64decode(value.replace('-', '+').replace('_', '/'), validate=True)
    if len(decoded) != 32:
        raise ValueError('Invalid transaction hash')
    return decoded.hex()


class TonDepositsMixin:
    def register_ton_deposits(self, app):
        app.router.add_post('/api/deposit/tonkeeper/create', self.handle_ton_create)
        app.router.add_get('/api/deposit/tonkeeper/info', self.handle_ton_info)
        app.router.add_get('/api/deposit/tonkeeper/status', self.handle_ton_status)

    async def initialize_ton_wallet(self):
        from payments_backend import TON_WALLET_MNEMONIC, TON_WALLET_SEED_FILE, TON_WALLET_VERSION, TON_WALLET_WORKCHAIN, TON_WALLET_ID, TONKEEPER_ADDRESS
        from ton_wallet import read_mnemonic, restore_wallet_identity, TonWalletError
        self._ton_wallet_identity = None
        self._ton_chain_valid_until = 0
        self._ton_wallet_problem = 'Seed-фраза TON не настроена на сервере.'
        self._ton_chain_check_lock = asyncio.Lock()
        def load():
            phrase = read_mnemonic(getattr(self, 'ton_mnemonic', TON_WALLET_MNEMONIC), getattr(self, 'ton_seed_file', TON_WALLET_SEED_FILE))
            return restore_wallet_identity(phrase, getattr(self, 'ton_version', TON_WALLET_VERSION), getattr(self, 'ton_workchain', TON_WALLET_WORKCHAIN), getattr(self, 'ton_wallet_id', TON_WALLET_ID), getattr(self, 'ton_wallet', TONKEEPER_ADDRESS))
        try:
            self._ton_wallet_identity = await asyncio.to_thread(load)
        except TonWalletError as error:
            self._ton_wallet_problem = str(error)  # Sanitized fixed messages only.

    def ton_settings(self):
        from payments_backend import TON_RPC_URL, TON_USD_RATE, TONKEEPER_ADDRESS
        try:
            identity = getattr(self, '_ton_wallet_identity', None)
            if identity is None:
                raise GameError(getattr(self, '_ton_wallet_problem', 'Seed-фраза TON не настроена.'), 503)
            expected = getattr(self, 'ton_wallet', TONKEEPER_ADDRESS)
            if expected and ton_address(expected) != identity.address:
                raise ValueError
            endpoint = getattr(self, 'ton_rpc_url', TON_RPC_URL).rstrip('/')
            parsed = urlsplit(endpoint)
            if (not endpoint or any(char.isspace() for char in endpoint) or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment or
                parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost', '::1'})):
                raise ValueError
            rate = Decimal(str(getattr(self, 'ton_usd_rate', TON_USD_RATE)))
            if not rate.is_finite() or not Decimal('0.001') <= rate <= Decimal('100000'):
                raise ValueError
        except (ValueError, InvalidOperation, TypeError, AttributeError):
            raise GameError('TON ещё не настроен: проверьте seed/адрес, URL своего mainnet v3-индексатора и серверный курс TON/USD.', 503) from None
        return identity.address, endpoint, rate

    def ton_ready(self):
        try:
            self.ton_settings()
            return getattr(self, '_ton_chain_valid_until', 0) > time.monotonic()
        except GameError:
            return False

    async def ton_chain_api(self, path, params):
        _, endpoint, _ = self.ton_settings()
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(endpoint + '/' + path, params=params, allow_redirects=False) as response:
                    if response.status != 200:
                        raise ValueError
                    body = await response.json()
            if not isinstance(body, dict):
                raise ValueError
            return body
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, UnicodeError):
            raise GameError('Свой TON-узел/индексатор недоступен или вернул некорректный ответ. Зачисление отключено.', 503) from None

    async def verify_ton_wallet_chain(self):
        from ton_wallet import verify_chain_account, TonWalletError
        self.ton_settings()
        async with self._ton_chain_check_lock:
            if self._ton_chain_valid_until > time.monotonic():
                return
            self._ton_chain_valid_until = 0
            try:
                body = await self.ton_chain_api('accountStates', {'address': self._ton_wallet_identity.address, 'include_boc': 'true'})
                accounts = body.get('accounts')
                if not isinstance(accounts, list) or len(accounts) != 1:
                    raise ValueError
                verify_chain_account(self._ton_wallet_identity, accounts[0])
            except (TonWalletError, ValueError, TypeError):
                raise GameError('Проверка TON-кошелька в сети не пройдена: адрес, активность, версия контракта или ключ не совпали.', 503) from None
            self._ton_chain_valid_until = time.monotonic() + 30

    async def initialize_ton_deposits(self):
        await self.initialize_ton_wallet()
        async with self.database_lock:
            db = self.database()
            await db.execute('CREATE TABLE IF NOT EXISTS webapp_ton_orders(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,request_key TEXT NOT NULL,digest TEXT NOT NULL,wallet TEXT NOT NULL,comment TEXT NOT NULL UNIQUE,nanotons INTEGER NOT NULL,stars_cents INTEGER NOT NULL,created_at INTEGER NOT NULL,expires_at INTEGER NOT NULL,scan_lt TEXT NOT NULL DEFAULT \'0\',checked_at INTEGER NOT NULL DEFAULT 0,UNIQUE(user_id,request_key))')
            await db.execute('CREATE TABLE IF NOT EXISTS webapp_ton_transactions(hash TEXT PRIMARY KEY,order_id TEXT NOT NULL UNIQUE,received_nanotons TEXT NOT NULL,created_at TEXT NOT NULL)')
            await db.commit()
        self.ton_deposit_task = asyncio.create_task(self.ton_deposit_loop())

    async def cleanup_ton_deposits(self):
        if hasattr(self, 'ton_deposit_task'):
            self.ton_deposit_task.cancel()
            await asyncio.gather(self.ton_deposit_task, return_exceptions=True)

    async def ton_order(self, db, identifier, user_id=None):
        sql, args = 'SELECT * FROM webapp_ton_orders WHERE id=?', [identifier]
        if user_id is not None:
            sql += ' AND user_id=?'
            args.append(user_id)
        async with db.execute(sql, args) as cursor:
            row = await cursor.fetchone()
            columns = [col[0] for col in cursor.description]
        if not row:
            raise GameError('TON-счёт не найден.', 404)
        return dict(zip(columns, row))

    async def ton_result(self, db, order):
        deposit = await self.deposit_row(db, order['id'], order['user_id'])
        result = self.deposit_result(deposit)
        result.update({'wallet': order['wallet'], 'comment': order['comment'], 'tonAmount': format(Decimal(order['nanotons']) / 1000000000, 'f'), 'tonDeeplink': deposit['pay_url'], 'balance': await self.balance(db, order['user_id'])})
        return result

    async def handle_ton_create(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            key, digest = self.request_identity(request, payload)
            wallet, _, rate = self.ton_settings()
            await self.verify_ton_wallet_chain()
            cents = money_cents(payload.get('amount'))
            from payments_backend import STAR_USD
            nano = int((Decimal(cents) / 100 * STAR_USD / rate * 1000000000).to_integral_value(rounding=ROUND_CEILING))
            if not 10000000 <= nano <= 1000000000000000:
                raise GameError('Сумма TON должна быть от 0.01 до 1 000 000 TON.')
            async with self.database_lock:
                db = self.database()
                try:
                    await db.execute('BEGIN IMMEDIATE')
                    async with db.execute('SELECT id,digest FROM webapp_ton_orders WHERE user_id=? AND request_key=?', (user.id, key)) as cursor:
                        replay = await cursor.fetchone()
                    if replay:
                        if replay[1] != digest:
                            raise GameError('Идентификатор уже использован.', 409)
                        order = await self.ton_order(db, replay[0], user.id)
                    else:
                        async with db.execute('SELECT COUNT(*) FROM webapp_ton_orders WHERE user_id=? AND created_at>?', (user.id, int(time.time()) - 3600)) as cursor:
                            if (await cursor.fetchone())[0] >= 10:
                                raise GameError('Слишком много TON-счетов. Попробуйте позже.', 429)
                        identifier, now = 'ms_ton_' + secrets.token_hex(16), int(time.time())
                        comment = 'mjr_' + secrets.token_hex(24)
                        link = 'https://app.tonkeeper.com/transfer/' + quote(wallet, safe='') + '?' + urlencode({'amount': str(nano), 'text': comment})
                        await db.execute('INSERT INTO webapp_ton_orders(id,user_id,request_key,digest,wallet,comment,nanotons,stars_cents,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?)', (identifier, user.id, key, digest, wallet, comment, nano, cents, now, now + 1800))
                        await db.execute("INSERT INTO webapp_deposits(id,user_id,provider,provider_id,stars_cents,price_amount,price_currency,status,created_at,expires_at,pay_url) VALUES (?,?,'tonkeeper',?,?,?,'TON','active',?,?,?)", (identifier, user.id, identifier, cents, format(Decimal(nano) / 1000000000, 'f'), self.clock().isoformat(), now + 1800, link))
                        order = await self.ton_order(db, identifier, user.id)
                    result = await self.ton_result(db, order)
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
            return self.response(result)
        except GameError as error:
            return self.failure(error)

    async def handle_ton_info(self, request):
        try:
            user = self.validate_user(request)
            self.ton_settings()
            async with self.database_lock:
                result = await self.ton_result(self.database(), await self.ton_order(self.database(), request.query.get('invoiceId', ''), user.id))
            return self.response(result)
        except GameError as error:
            return self.failure(error)

    async def handle_ton_status(self, request):
        try:
            user = self.validate_user(request)
            async with self.database_lock:
                db = self.database()
                order = await self.ton_order(db, request.query.get('invoiceId', ''), user.id)
                result = await self.ton_result(db, order)
                if not result['paid'] and order['expires_at'] < time.time():
                    result['status'] = 'expired'
            return self.response(result)
        except GameError as error:
            return self.failure(error)

    async def ton_transactions(self, order):
        await self.verify_ton_wallet_chain()
        params = {'account': order['wallet'], 'start_utime': str(order['created_at'] - 30), 'start_lt': str(int(order['scan_lt']) + 1), 'sort': 'asc', 'limit': '100'}
        body = await self.ton_chain_api('transactions', params)
        if not isinstance(body.get('transactions'), list):
            raise GameError('Свой TON-индексатор вернул некорректный список транзакций.', 503)
        return body['transactions']

    def ton_payment_matches(self, order, tx):
        try:
            message, description = tx['in_msg'], tx['description']
            decoded = message['message_content']['decoded']
            # Only a finalized, successful native internal TON transfer. Jetton
            # notifications/forward payloads are not native TON deposit proofs.
            return (tx.get('emulated') is False and tx.get('finality') == 'finalized' and
                    description.get('aborted') is False and description.get('compute_ph', {}).get('success') is True and
                    description.get('action', {}).get('success', True) is True and
                    message.get('bounced') is False and bool(message.get('source')) and
                    message.get('opcode') in {'0x00000000', '0x0', '0'} and
                    ton_address(tx['account']) == order['wallet'] and ton_address(message['destination']) == order['wallet'] and
                    isinstance(decoded, dict) and (decoded.get('type') == 'text_comment' or decoded.get('type') == 'ton_transfer' and decoded.get('encrypted') is False) and decoded.get('comment') == order['comment'] and
                    re.fullmatch(r'[0-9]{1,22}', message['value']) is not None and int(message['value']) >= order['nanotons'] and
                    type(tx['now']) is int and order['created_at'] - 30 <= tx['now'] <= order['expires_at'] + 300 and
                    type(tx.get('mc_block_seqno')) is int and tx['mc_block_seqno'] > 0)
        except (ValueError, TypeError, KeyError, AttributeError):
            return False

    async def process_ton_deposit(self, identifier):
        async with self.database_lock:
            order = await self.ton_order(self.database(), identifier)
        async with self.database_lock:
            await self.database().execute('UPDATE webapp_ton_orders SET checked_at=? WHERE id=?', (int(time.time()), identifier))
            await self.database().commit()
        transactions = await self.ton_transactions(order)
        cursor_lt = int(order['scan_lt'])
        for tx in transactions:
            if not isinstance(tx, dict) or tx.get('finality') != 'finalized':
                break  # Do not skip transactions which can still become final.
            try:
                lt = int(tx['lt'])
                if lt <= cursor_lt:
                    continue
                # Require the queried account even before advancing our cursor.
                if ton_address(tx['account']) != order['wallet']:
                    raise ValueError
                tx_hash = ton_hash(tx['hash'])
            except (ValueError, TypeError, KeyError):
                break
            if self.ton_payment_matches(order, tx):
                async with self.database_lock:
                    db = self.database()
                    try:
                        await db.execute('BEGIN IMMEDIATE')
                        deposit = await self.deposit_row(db, identifier, order['user_id'])
                        if deposit['status'] != 'paid':
                            await db.execute('INSERT INTO webapp_ton_transactions(hash,order_id,received_nanotons,created_at) VALUES (?,?,?,?)', (tx_hash, identifier, tx['in_msg']['value'], self.clock().isoformat()))
                            await self.wallet_credit(db, order['user_id'], order['stars_cents'], 'deposit', identifier)
                            await self.referral_credit(db, order['user_id'], order['stars_cents'], identifier)
                            await db.execute("UPDATE webapp_deposits SET status='paid',paid_at=? WHERE id=?", (self.clock().isoformat(), identifier))
                        await db.commit()
                    except BaseException:
                        await db.rollback()
                        raise
                return
            message = tx.get('in_msg') or {}
            if message.get('opcode') in {'0x00000000', '0x0', '0'} and not (message.get('message_content') or {}).get('decoded'):
                break
            cursor_lt = lt
        async with self.database_lock:
            db = self.database()
            await db.execute('UPDATE webapp_ton_orders SET scan_lt=?,checked_at=? WHERE id=?', (str(cursor_lt), int(time.time()), identifier))
            await db.commit()

    async def ton_deposit_loop(self):
        while True:
            try:
                self.ton_settings()
                await self.verify_ton_wallet_chain()
                if self.ton_ready():
                    async with self.database_lock:
                        async with self.database().execute("SELECT t.id FROM webapp_ton_orders t JOIN webapp_deposits d ON d.id=t.id WHERE d.status='active' AND t.created_at>? AND t.checked_at<? ORDER BY t.checked_at LIMIT 5", (int(time.time()) - 7 * 86400, int(time.time()) - 30)) as cursor:
                            ids = [row[0] for row in await cursor.fetchall()]
                    for identifier in ids:
                        try:
                            await self.process_ton_deposit(identifier)
                        except GameError:
                            pass
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if not isinstance(error, GameError):
                    logging.warning('TON deposit worker error: %s', type(error).__name__)
            await asyncio.sleep(10)
