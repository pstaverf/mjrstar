import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from decimal import Decimal, InvalidOperation, ROUND_UP
from urllib.parse import urlencode

import aiohttp
from aiogram.types import LabeledPrice

from games_backend import GameError, integer, money_cents


STAR_USD = Decimal("0.022")
PAYMENT_LIFETIME = 1800
CRYPTOBOT_API_TOKEN = '670149:AAXxMq9ZqH1wddhRrFi2WG6abLgvQHh8GKu'
XROCKET_API_TOKEN = 'eyJhbGci0iJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhcHBJZCI6IjMWODI20CIsImpOaS161mFwcDozMDgyNjg6ZTIOMmYyMDAtZTgz0C00Y2ExLTg2NTYtZDNkYzU4ZDZKMmUO1iwiaWFOIjoxNzkOMDA4Nzk1fQ.CLQ-B6fyiBbZYk_eEAfFHs0p0oB6H7SZ5nn9TW1XXIs'
XROCKET_WEBHOOK_SECRET = '7dffd69477299e2783f6cfee665149d19bcc23393ae4a02829f52050070acdd7'


def decimal_amount(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0:
            raise ValueError
        return amount
    except (InvalidOperation, ValueError, TypeError):
        raise GameError("Некорректная сумма платежа.") from None


def verify_crypto_signature(body, signature, token):
    if not token or not re.fullmatch(r"[a-fA-F0-9]{64}", signature or ""):
        return False
    expected = hmac.new(hashlib.sha256(token.encode()).digest(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


def verify_rocket_signature(body, headers, secret, now=None):
    signature = headers.get("Signature", "")
    timestamp = headers.get("Signature-Timestamp", "")
    if not secret or headers.get("Signature-Version") != "v1" or not re.fullmatch(r"[0-9]{13}", timestamp) or not re.fullmatch(r"[a-fA-F0-9]{64}", signature):
        return False
    if abs((time.time() if now is None else now) * 1000 - int(timestamp)) > 300000:
        return False
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.lower())


class PaymentsMixin:
    def register_payments(self, application):
        application.router.add_get("/api/deposit/info", self.handle_deposit_info)
        for provider in ("cryptobot", "xrocket", "stars"):
            application.router.add_post(f"/api/deposit/{provider}/create", self.handle_deposit_create)
            application.router.add_get(f"/api/deposit/{provider}/status", self.handle_deposit_status)
        application.router.add_post("/api/deposit/cryptobot/cancel", self.handle_deposit_cancel)
        application.router.add_post("/api/deposit/xrocket/cancel", self.handle_deposit_cancel)
        application.router.add_post("/cryptobot", self.handle_crypto_webhook)
        application.router.add_post("/xrocket", self.handle_rocket_webhook)
        application.router.add_get("/api/wallet/transactions/page-dates", self.handle_wallet_dates)
        application.router.add_get("/api/wallet/transactions", self.handle_wallet_transactions)

    async def initialize_payments(self):
        async with self.database_lock:
            connection = self.database()
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_deposits(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,provider TEXT NOT NULL,provider_id TEXT,stars_cents INTEGER NOT NULL,price_amount TEXT,price_currency TEXT,status TEXT NOT NULL,created_at TEXT NOT NULL,expires_at INTEGER NOT NULL,pay_url TEXT,request_key TEXT,request_digest TEXT,UNIQUE(provider,provider_id),UNIQUE(user_id,request_key))")
            async with connection.execute("PRAGMA table_info(webapp_deposits)") as cursor:
                columns = {row[1] for row in await cursor.fetchall()}
            if "paid_at" not in columns:
                await connection.execute("ALTER TABLE webapp_deposits ADD COLUMN paid_at TEXT")
            await connection.execute("CREATE INDEX IF NOT EXISTS idx_webapp_deposits_user ON webapp_deposits(user_id,created_at)")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_wallet_events(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,kind TEXT NOT NULL,amount_cents INTEGER NOT NULL,source TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL)")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_ref_events(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,referral_id INTEGER NOT NULL,kind TEXT NOT NULL,amount_cents INTEGER NOT NULL,source TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL)")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_ref_baselines(user_id INTEGER PRIMARY KEY,signup_cents INTEGER NOT NULL,deposit_cents INTEGER NOT NULL,captured_at TEXT NOT NULL)")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_wallet_metadata(name TEXT PRIMARY KEY,value TEXT NOT NULL)")
            async with connection.execute("SELECT value FROM webapp_wallet_metadata WHERE name = 'journal_started_at'") as cursor:
                started = await cursor.fetchone()
            if started is None:
                started_at = self.clock().isoformat()
                await connection.execute("INSERT INTO webapp_ref_baselines(user_id,signup_cents,deposit_cents,captured_at) SELECT b.user_id,MAX(0,ROUND(b.signup_earned*100)-COALESCE((SELECT SUM(amount_cents) FROM webapp_ref_events WHERE user_id=b.user_id AND kind='signup'),0)),MAX(0,ROUND(b.deposit_earned*100)-COALESCE((SELECT SUM(amount_cents) FROM webapp_ref_events WHERE user_id=b.user_id AND kind='deposit'),0)),? FROM ref_balance b", (started_at,))
                await connection.execute("INSERT INTO webapp_wallet_metadata(name,value) VALUES ('journal_started_at',?)", (started_at,))
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_ref_notices(source TEXT PRIMARY KEY,user_id INTEGER NOT NULL,amount_cents INTEGER NOT NULL,next_at INTEGER NOT NULL DEFAULT 0,delivered INTEGER NOT NULL DEFAULT 0)")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_payment_events(provider TEXT NOT NULL,event_id TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(provider,event_id))")
            await connection.commit()
        self.deposit_create_locks = {}
        self.referral_notices_task = asyncio.create_task(self.referral_notices_loop())

    def payment_token(self, provider):
        return getattr(self, "payment_tokens", {}).get(provider, {"cryptobot": CRYPTOBOT_API_TOKEN, "xrocket": XROCKET_API_TOKEN}.get(provider))

    def rocket_secret(self):
        return getattr(self, "xrocket_webhook_secret", XROCKET_WEBHOOK_SECRET)

    async def payment_api(self, provider, method, path, data=None):
        token = self.payment_token(provider)
        if not token:
            raise GameError("Платёжный провайдер ещё не настроен.", 503)
        if not hasattr(self, "provider_retry_until"):
            self.provider_retry_until = {}
        endpoint = provider + ":" + path.split("?")[0]
        if self.provider_retry_until.get(endpoint, 0) > time.monotonic():
            raise GameError("Платёжный сервис просит подождать. Статус оплаты будет проверен позже.", 429)
        base = "https://pay.crypt.bot/api/" if provider == "cryptobot" else "https://pay.api.xrocket.exchange"
        headers = {"Crypto-Pay-API-Token": token} if provider == "cryptobot" else {"Authorization": "Bearer " + token}
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.request(method, base + path, headers=headers, params=data if method == "GET" else None, json=data if method != "GET" else None, allow_redirects=False) as response:
                    raw = await response.read()
                    if response.status == 429:
                        try:
                            retry_after = max(1, int(getattr(response, "headers", {}).get("Retry-After", "60")))
                        except (ValueError, TypeError):
                            retry_after = 60
                        self.provider_retry_until[endpoint] = time.monotonic() + retry_after
                        raise GameError("Платёжный сервис занят. Повторите позже.", 429)
                    result = json.loads(raw) if raw else {} if method == "DELETE" else None
                    if response.status >= 300 or (provider == "cryptobot" and (not isinstance(result, dict) or result.get("ok") is not True)):
                        raise GameError("Провайдер отклонил запрос. Счёт не создан или недоступен.", 502)
                    return result.get("result") if provider == "cryptobot" else result
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            raise GameError("Нет ответа от платёжного сервиса. Проверьте статус позже.", 502) from None

    async def handle_deposit_info(self, request):
        self.validate_user(request)
        return self.response({"ok": True, "methods": {"cryptobot": bool(self.payment_token("cryptobot")), "xrocket": bool(self.payment_token("xrocket") and self.rocket_secret()), "stars": getattr(self, "telegram_bot", None) is not None, "tonkeeper": False, "sbp": False, "laveshka": False}, "limits": {"min_deposit_cryptobot": 1, "min_deposit_xrocket": 1, "min_deposit_stars": 1}, "usdPerStar": str(STAR_USD), "promo": None, "tagPromo": None})

    async def deposit_row(self, connection, order_id, user_id=None):
        sql = "SELECT id,user_id,provider,provider_id,stars_cents,price_amount,price_currency,status,created_at,expires_at,pay_url FROM webapp_deposits WHERE id = ?"
        values = [order_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            values.append(user_id)
        async with connection.execute(sql, values) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise GameError("Счёт не найден.", 404)
        return dict(zip(("id", "user_id", "provider", "provider_id", "stars_cents", "price_amount", "price_currency", "status", "created_at", "expires_at", "pay_url"), row))

    def deposit_result(self, order):
        return {"ok": True, "invoiceId": order["id"], "invoiceLink": order["pay_url"], "payUrl": order["pay_url"], "expiresIn": max(0, order["expires_at"] - int(time.time())), "status": order["status"], "paid": order["status"] == "paid", "creditedAmount": order["stars_cents"] / 100 if order["status"] == "paid" else 0, "amount": order["stars_cents"] / 100, "priceAmount": order["price_amount"], "priceCurrency": order["price_currency"]}

    async def handle_deposit_create(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            provider = request.path.split("/")[3]
            cents = money_cents(payload.get("amount"), 100, 1000000)
            if provider == "stars" and cents % 100:
                raise GameError("Telegram Stars принимаются только целым числом.")
            if provider != "stars" and (not self.payment_token(provider) or provider == "xrocket" and not self.rocket_secret()):
                raise GameError("Платёжный провайдер ещё не настроен.", 503)
            if provider == "stars" and getattr(self, "telegram_bot", None) is None:
                raise GameError("Telegram-оплата недоступна.", 503)
            key, signature = self.request_identity(request, payload)
            lock = self.deposit_create_locks.setdefault(user.id, asyncio.Lock())
            async with lock:
                async with self.database_lock:
                    connection = self.database()
                    async with connection.execute("SELECT id,request_digest FROM webapp_deposits WHERE user_id = ? AND request_key = ?", (user.id, key)) as cursor:
                        existing = await cursor.fetchone()
                    if existing:
                        if existing[1] != signature:
                            raise GameError("Идентификатор использован для другого счёта.", 409)
                        order = await self.deposit_row(connection, existing[0], user.id)
                        if order["status"] == "creating":
                            raise GameError("Счёт ещё создаётся. Не оплачивайте другой счёт до проверки.", 409)
                        return self.response(self.deposit_result(order))
                    async with connection.execute("SELECT COUNT(*) FROM webapp_deposits WHERE user_id = ? AND created_at >= ?", (user.id, self.clock().fromtimestamp(time.time() - 60, self.clock().tzinfo).isoformat())) as cursor:
                        if (await cursor.fetchone())[0] >= 5:
                            raise GameError("Слишком много счетов. Подождите минуту.", 429)
                    order_id = "ms_" + secrets.token_hex(16)
                    price = Decimal(cents) / 100 * STAR_USD
                    currency = "USD" if provider == "cryptobot" else "XTR" if provider == "stars" else payload.get("currency", "USDT")
                    if provider == "stars":
                        price = Decimal(cents // 100)
                    elif provider == "xrocket":
                        currency = "TON" if currency == "TONCOIN" else currency
                        if not isinstance(currency, str) or currency not in {"TON", "USDT", "BTC", "ETH", "BNB"}:
                            raise GameError("Неподдерживаемая валюта.")
                    try:
                        await connection.execute("INSERT INTO webapp_deposits(id,user_id,provider,stars_cents,price_amount,price_currency,status,created_at,expires_at,request_key,request_digest) VALUES (?,?,?,?,?,?,'creating',?,?,?,?)", (order_id, user.id, provider, cents, str(price), currency, self.clock().isoformat(), int(time.time()) + PAYMENT_LIFETIME, key, signature))
                        await connection.commit()
                    except BaseException:
                        await connection.rollback()
                        raise
                try:
                    if provider == "stars":
                        pay_url = await self.telegram_bot.create_invoice_link(title="MajorStars", description=f"Пополнение баланса на {cents // 100} Stars", payload=order_id, currency="XTR", prices=[LabeledPrice(label="Stars", amount=cents // 100)], provider_token="")
                        provider_id = order_id
                    elif provider == "cryptobot":
                        invoice = await self.payment_api(provider, "POST", "createInvoice", {"currency_type": "fiat", "fiat": "USD", "amount": str(price), "payload": order_id, "expires_in": PAYMENT_LIFETIME, "description": f"MajorStars: {cents / 100:g} Stars", "allow_comments": False, "allow_anonymous": False})
                        provider_id, pay_url = str(invoice["invoice_id"]), invoice["bot_invoice_url"]
                    else:
                        currency = await self.rocket_currency(currency)
                        rates = await self.payment_api(provider, "GET", "/api/v1/rates", {"base": "USD", "assets": currency})
                        rate = next((decimal_amount(item.get("rate")) for item in rates if item.get("currency") == currency), None)
                        if rate is None:
                            raise GameError("Нет курса выбранной валюты.", 502)
                        price = (price / rate).quantize(Decimal("0.00000001"), rounding=ROUND_UP)
                        async with self.database_lock:
                            connection = self.database()
                            await connection.execute("UPDATE webapp_deposits SET price_amount = ?,price_currency = ? WHERE id = ?", (str(price), currency, order_id))
                            await connection.commit()
                        invoice = await self.payment_api(provider, "POST", "/api/v1/invoices", {"priceAmount": str(price), "priceCurrency": currency, "numPayments": 1, "clientInvoiceId": order_id, "expiresIn": PAYMENT_LIFETIME * 1000, "description": f"MajorStars: {cents / 100:g} Stars", "callback": {"callbackUrl": "https://mjrr.wisp.uno/xrocket", "payload": {"orderId": order_id}}})
                        provider_id, pay_url = str(invoice["id"]), invoice["links"]["telegramBotLink"]
                    if not isinstance(pay_url, str) or not pay_url.startswith("https://t.me/"):
                        raise GameError("Провайдер вернул некорректную ссылку.", 502)
                except (KeyError, TypeError, StopIteration):
                    raise GameError("Некорректный ответ платёжного сервиса.", 502) from None
                async with self.database_lock:
                    connection = self.database()
                    try:
                        await connection.execute("UPDATE webapp_deposits SET provider_id = COALESCE(provider_id,?),pay_url = ?,status = CASE WHEN status = 'creating' THEN 'active' ELSE status END WHERE id = ?", (provider_id, pay_url, order_id))
                        await connection.commit()
                    except BaseException:
                        await connection.rollback()
                        raise
                    order = await self.deposit_row(connection, order_id, user.id)
                return self.response(self.deposit_result(order))
        except GameError as error:
            return self.failure(error)

    def invoice_matches(self, order, invoice):
        if not isinstance(invoice, dict):
            return False
        try:
            if order["provider"] == "cryptobot":
                return str(invoice.get("invoice_id")) == str(order["provider_id"]) and invoice.get("payload") == order["id"] and invoice.get("currency_type") == "fiat" and invoice.get("fiat") == "USD" and decimal_amount(invoice.get("amount")) == decimal_amount(order["price_amount"])
            return str(invoice.get("id")) == str(order["provider_id"]) and invoice.get("clientInvoiceId") == order["id"] and invoice.get("priceCurrency") == order["price_currency"] and decimal_amount(invoice.get("priceAmount")) == decimal_amount(order["price_amount"])
        except GameError:
            return False

    async def wallet_credit(self, connection, user_id, cents, kind, source):
        await connection.execute("INSERT INTO webapp_wallet_events(user_id,kind,amount_cents,source,created_at) VALUES (?,?,?,?,?)", (user_id, kind, cents, source, self.clock().isoformat()))
        await connection.execute("INSERT INTO balances(user_id,amount,created_at) VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET amount = ROUND(amount + excluded.amount,2)", (user_id, cents / 100, self.clock().isoformat()))

    async def referral_credit(self, connection, user_id, cents, source):
        async with connection.execute("SELECT referrer_id FROM referrals WHERE user_id = ?", (user_id,)) as cursor:
            referral = await cursor.fetchone()
        if not referral:
            return
        percent = Decimal(str(getattr(self, "wallet_runtime", {}).get("REF_DEPOSIT_PERCENT", 0.10)))
        earned = int((Decimal(cents) * percent).quantize(Decimal("1")))
        if earned <= 0:
            return
        referrer = referral[0]
        await connection.execute("INSERT INTO webapp_ref_events(user_id,referral_id,kind,amount_cents,source,created_at) VALUES (?,?,'deposit',?,?,?)", (referrer, user_id, earned, source, self.clock().isoformat()))
        await connection.execute("INSERT INTO webapp_ref_notices(source,user_id,amount_cents) VALUES (?,?,?)", (source, referrer, earned))
        await connection.execute("UPDATE referrals SET deposited = 1 WHERE user_id = ?", (user_id,))
        await connection.execute("INSERT INTO ref_balance(user_id,deposit_earned) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET deposit_earned = ROUND(deposit_earned + excluded.deposit_earned,2)", (referrer, earned / 100))
        runtime = getattr(self, "wallet_runtime", {})
        base = runtime.get("REF_BASE_LIMIT", 2)
        step = runtime.get("REF_LIMIT_PER_DEPOSIT", 2)
        await connection.execute("UPDATE ref_balance SET frozen = ((SELECT COUNT(*) FROM referrals WHERE referrer_id = ?) + (SELECT COUNT(*) FROM pending_referrals WHERE referrer_id = ?) > ? + ? * (SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND deposited = 1)) WHERE user_id = ?", (referrer, referrer, base, step, referrer, referrer))

    async def settle_invoice(self, provider, invoice, event_id=None):
        order_id = invoice.get("payload") if provider == "cryptobot" else invoice.get("clientInvoiceId")
        if not isinstance(order_id, str) or not order_id.startswith("ms_"):
            return
        async with self.database_lock:
            connection = self.database()
            try:
                await connection.execute("BEGIN IMMEDIATE")
                if provider == "xrocket" and event_id:
                    async with connection.execute("SELECT 1 FROM webapp_payment_events WHERE provider = 'xrocket' AND event_id = ?", (event_id,)) as cursor:
                        if await cursor.fetchone():
                            await connection.rollback()
                            return
                order = await self.deposit_row(connection, order_id)
                if order["provider"] != provider:
                    raise GameError("Провайдер не совпадает.", 409)
                if order["provider_id"] is None:
                    provider_id = invoice.get("invoice_id") if provider == "cryptobot" else invoice.get("id")
                    if not provider_id:
                        raise GameError("Отсутствует номер счёта.", 409)
                    order["provider_id"] = str(provider_id)
                    await connection.execute("UPDATE webapp_deposits SET provider_id = ? WHERE id = ?", (order["provider_id"], order_id))
                if not self.invoice_matches(order, invoice):
                    raise GameError("Данные счёта не совпадают.", 409)
                if invoice.get("status") == "paid" and order["status"] != "paid":
                    await connection.execute("UPDATE webapp_deposits SET status = 'paid',paid_at = ? WHERE id = ?", (self.clock().isoformat(), order_id))
                    await self.wallet_credit(connection, order["user_id"], order["stars_cents"], "deposit", "deposit:" + order_id)
                    await self.referral_credit(connection, order["user_id"], order["stars_cents"], "deposit:" + order_id)
                elif invoice.get("status") in {"expired", "cancelled"} and order["status"] != "paid":
                    await connection.execute("UPDATE webapp_deposits SET status = ? WHERE id = ?", (invoice["status"], order_id))
                if event_id:
                    await connection.execute("INSERT OR IGNORE INTO webapp_payment_events(provider,event_id,created_at) VALUES (?,?,?)", (provider, event_id, self.clock().isoformat()))
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    async def handle_deposit_status(self, request):
        try:
            user = self.validate_user(request)
            provider = request.path.split("/")[3]
            async with self.database_lock:
                order = await self.deposit_row(self.database(), request.query.get("invoiceId", ""), user.id)
            if order["provider"] != provider:
                raise GameError("Счёт не найден.", 404)
            if provider != "stars" and order["status"] != "paid":
                if provider == "cryptobot" and order["provider_id"]:
                    result = await self.payment_api(provider, "GET", "getInvoices", {"invoice_ids": order["provider_id"]})
                    invoices = result.get("items", [])
                    invoice = next((item for item in invoices if str(item.get("invoice_id")) == order["provider_id"]), None)
                elif provider == "xrocket":
                    invoice = await self.payment_api(provider, "GET", "/api/v1/invoice", {"clientInvoiceId": order["id"]})
                else:
                    invoice = None
                if invoice:
                    await self.settle_invoice(provider, invoice)
            async with self.database_lock:
                order = await self.deposit_row(self.database(), order["id"], user.id)
                balance = await self.balance(self.database(), user.id)
            result = self.deposit_result(order)
            result["balance"] = balance
            if order["status"] in {"active", "creating"} and order["expires_at"] < time.time():
                result["status"] = "expired"
            return self.response(result)
        except GameError as error:
            return self.failure(error)

    async def handle_deposit_cancel(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            async with self.database_lock:
                order = await self.deposit_row(self.database(), payload.get("invoiceId", ""), user.id)
            provider = request.path.split("/")[3]
            if order["provider"] != provider:
                raise GameError("Счёт не найден.", 404)
            if order["status"] == "paid":
                return self.response(self.deposit_result(order))
            if not order["provider_id"]:
                raise GameError("Счёт ещё создаётся. Проверьте статус позже.", 409)
            if provider == "cryptobot":
                await self.payment_api(provider, "POST", "deleteInvoice", {"invoice_id": int(order["provider_id"])})
            else:
                await self.payment_api(provider, "DELETE", "/api/v1/invoice?" + urlencode({"invoiceId": order["provider_id"]}))
            async with self.database_lock:
                connection = self.database()
                await connection.execute("UPDATE webapp_deposits SET status = 'cancelled' WHERE id = ? AND status != 'paid'", (order["id"],))
                await connection.commit()
                order = await self.deposit_row(connection, order["id"], user.id)
            return self.response(self.deposit_result(order))
        except GameError as error:
            return self.failure(error)

    async def handle_crypto_webhook(self, request):
        body = await request.read()
        if not verify_crypto_signature(body, request.headers.get("crypto-pay-api-signature"), self.payment_token("cryptobot")):
            return self.response({"ok": False}, 401)
        try:
            event = json.loads(body)
            if not isinstance(event, dict):
                raise ValueError
            if event.get("update_type") == "invoice_paid":
                invoice = event.get("payload")
                if not isinstance(invoice, dict):
                    raise ValueError
                await self.settle_invoice("cryptobot", invoice, str(event.get("update_id", "")))
            return self.response({"ok": True})
        except (ValueError, TypeError):
            return self.response({"ok": False}, 400)
        except GameError as error:
            return self.failure(error)

    async def handle_rocket_webhook(self, request):
        body = await request.read()
        if not verify_rocket_signature(body, request.headers, self.rocket_secret()):
            return self.response({"ok": False}, 401)
        try:
            event = json.loads(body)
            if not isinstance(event, dict) or not isinstance(event.get("id"), str):
                raise ValueError
            async with self.database_lock:
                async with self.database().execute("SELECT 1 FROM webapp_payment_events WHERE provider = 'xrocket' AND event_id = ?", (event["id"],)) as cursor:
                    if await cursor.fetchone():
                        return self.response({"ok": True})
            if event.get("type") == "invoice":
                data = event.get("data")
                if not isinstance(data, dict):
                    raise ValueError
                if data.get("event") in {"invoice_status_changed", "payment_status_changed"}:
                    invoice = data.get("invoice")
                    if not isinstance(invoice, dict) or not isinstance(invoice.get("id"), str):
                        raise ValueError
                    if "priceAmount" not in invoice or "clientInvoiceId" not in invoice:
                        invoice = await self.payment_api("xrocket", "GET", "/api/v1/invoice", {"invoiceId": invoice["id"]})
                    await self.settle_invoice("xrocket", invoice, event["id"])
            return self.response({"ok": True})
        except (ValueError, TypeError):
            return self.response({"ok": False}, 400)
        except GameError as error:
            return self.failure(error)

    async def validate_stars_order(self, order_id, user_id, currency, amount):
        async with self.database_lock:
            order = await self.deposit_row(self.database(), order_id, user_id)
        if order["provider"] != "stars" or currency != "XTR" or amount * 100 != order["stars_cents"] or order["status"] not in {"active", "creating"} or order["expires_at"] < time.time():
            raise GameError("Счёт устарел или данные оплаты не совпадают.")
        return order

    async def credit_stars_order(self, order_id, user_id, currency, amount, charge_id):
        async with self.database_lock:
            connection = self.database()
            try:
                await connection.execute("BEGIN IMMEDIATE")
                order = await self.deposit_row(connection, order_id, user_id)
                if order["provider"] != "stars" or currency != "XTR" or amount * 100 != order["stars_cents"] or not charge_id:
                    raise GameError("Данные оплаты не совпадают.")
                if order["status"] == "paid":
                    await connection.rollback()
                    return None
                cursor = await connection.execute("INSERT OR IGNORE INTO payments(charge_id,user_id,amount,created_at) VALUES (?,?,?,?)", (charge_id, user_id, amount, self.clock().isoformat()))
                if cursor.rowcount != 1:
                    raise GameError("Платёж уже привязан к другому счёту.", 409)
                await self.wallet_credit(connection, user_id, amount * 100, "deposit", "deposit:" + order_id)
                await self.referral_credit(connection, user_id, amount * 100, "deposit:" + order_id)
                await connection.execute("UPDATE webapp_deposits SET status = 'paid',paid_at = ?,provider_id = ? WHERE id = ?", (self.clock().isoformat(), charge_id, order_id))
                balance = await self.balance(connection, user_id)
                await connection.commit()
                return balance
            except BaseException:
                await connection.rollback()
                raise

    async def handle_wallet_transactions(self, request):
        try:
            user = self.validate_user(request)
            page = self.wallet_page(request)
            filter_name = request.query.get("filter", "all")
            if filter_name not in {"all", "deposit", "withdrawal", "deposits", "withdrawals"}:
                raise GameError("Неизвестный фильтр.")
            async with self.database_lock:
                connection = self.database()
                sources = ["SELECT 'deposit' AS type,stars_cents/100.0 AS amount,CASE provider WHEN 'cryptobot' THEN 'CryptoBot' WHEN 'xrocket' THEN 'xRocket' ELSE 'Stars' END AS description,status,strftime('%s',COALESCE(paid_at,created_at)) AS created_at,user_id FROM webapp_deposits WHERE status != 'creating'", "SELECT 'deposit',amount,'Stars','paid',strftime('%s',created_at),user_id FROM payments WHERE charge_id NOT IN (SELECT provider_id FROM webapp_deposits WHERE provider_id IS NOT NULL)", "SELECT 'withdrawal',amount,'Stars',status,strftime('%s',created_at),user_id FROM withdrawals"]
                condition = " WHERE user_id = ?"
                values = [user.id]
                if filter_name != "all":
                    condition += " AND type = ?"
                    values.append("withdrawal" if filter_name.startswith("withdrawal") else "deposit")
                source = "(" + " UNION ALL ".join(sources) + ")"
                async with connection.execute("SELECT COUNT(*) FROM " + source + condition, values) as cursor:
                    total = (await cursor.fetchone())[0]
                async with connection.execute("SELECT type,amount,description,status,created_at FROM " + source + condition + " ORDER BY created_at DESC LIMIT 10 OFFSET ?", values + [(page - 1) * 10]) as cursor:
                    rows = [dict(zip(("type", "amount", "description", "status", "created_at"), row)) for row in await cursor.fetchall()]
            for row in rows:
                row["created_at"] = int(row["created_at"] or 0)
            return self.response({"ok": True, "rows": rows, "page": page, "totalPages": max(1, (total + 9) // 10), "total": total})
        except GameError as error:
            return self.failure(error)

    async def handle_wallet_dates(self, request):
        try:
            self.validate_user(request)
            pages = [integer(value, 1, 1000000) for value in request.query.get("pages", "1").split(",")]
            if len(pages) > 20:
                raise GameError("Слишком много страниц.")
            dates = {}
            for page in pages:
                query = dict(request.query)
                query["page"] = str(page)
                response = await self.handle_wallet_transactions(request.clone(rel_url=request.rel_url.with_query(query)))
                if response.status != 200:
                    return response
                data = json.loads(response.body)
                if data["rows"]:
                    dates[str(page)] = self.clock().fromtimestamp(data["rows"][0]["created_at"], self.clock().tzinfo).isoformat()
            return self.response({"ok": True, "dates": dates})
        except GameError as error:
            return self.failure(error)

    async def deliver_referral_notices(self):
        bot = getattr(self, "telegram_bot", None)
        if bot is None:
            return
        async with self.database_lock:
            async with self.database().execute("SELECT n.source,n.user_id,n.amount_cents,COALESCE(p.ref_notifications,1) FROM webapp_ref_notices n LEFT JOIN webapp_preferences p ON p.user_id = n.user_id WHERE n.delivered = 0 AND n.next_at <= ? LIMIT 10", (int(time.time()),)) as cursor:
                notices = await cursor.fetchall()
        for source, user_id, cents, enabled in notices:
            delivered = not enabled
            if enabled:
                try:
                    await bot.send_message(user_id, f"Реферальное начисление: +{cents / 100:g} Stars от пополнения вашего реферала.", parse_mode=None)
                    delivered = True
                except Exception:
                    delivered = False
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("UPDATE webapp_ref_notices SET delivered = ?,next_at = ? WHERE source = ?", (int(delivered), int(time.time()) + 60, source))
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise

    async def referral_notices_loop(self):
        while True:
            await asyncio.sleep(2)
            try:
                await self.deliver_referral_notices()
            except Exception:
                logging.error("Referral notification delivery cycle failed")

    async def rocket_currency(self, requested):
        if getattr(self, "rocket_currencies_until", 0) < time.monotonic():
            currencies = await self.payment_api("xrocket", "GET", "/api/v1/currencies", {"kind": "crypto"})
            if not isinstance(currencies, list):
                raise GameError("Не удалось получить список валют провайдера.", 502)
            self.rocket_currencies = {item["code"] for item in currencies if isinstance(item, dict) and isinstance(item.get("code"), str) and item.get("kind") == "crypto"}
            self.rocket_currencies_until = time.monotonic() + 60
        if requested == "TON":
            currency = next((code for code in ("TON", "TONCOIN") if code in self.rocket_currencies), None)
        else:
            currency = requested if requested in self.rocket_currencies else None
        if not currency:
            raise GameError("Выбранная валюта сейчас недоступна у провайдера.", 503)
        return currency
