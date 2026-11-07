import asyncio
import hashlib
import hmac
import json
import secrets
import time
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from complete_games import CompleteGamesBackend
from games_backend import GameError
from payments_backend import verify_crypto_signature, verify_rocket_signature
from payment_errors import PaymentProviderError, provider_rejection
import test_games_backend as legacy_tests


class WalletTests(unittest.IsolatedAsyncioTestCase):
    backend_type = CompleteGamesBackend
    asyncSetUp = legacy_tests.GamesBackendTests.asyncSetUp
    asyncTearDown = legacy_tests.GamesBackendTests.asyncTearDown
    headers = legacy_tests.GamesBackendTests.headers

    async def post(self, path, payload, user_id=42, key=None):
        response = await self.client.post(path, json=payload, headers=self.headers(user_id, key))
        return response.status, await response.json()

    async def get(self, path, user_id=42):
        response = await self.client.get(path, headers=self.headers(user_id))
        return response.status, await response.json()

    async def configure(self):
        self.backend.wallet_runtime = self.runtime.__dict__
        self.runtime._wallet_backend = self.backend
        self.backend.payment_tokens = {"cryptobot": "test-crypto-token", "xrocket": "test-rocket-token"}
        self.backend.xrocket_webhook_secret = "test-webhook-secret"
        self.backend.telegram_bot = AsyncMock()
        self.backend.telegram_bot.create_invoice_link.return_value = "https://t.me/$test"
        self.invoices = {}
        self.calls = []
        async def api(provider, method, path, data=None):
            self.calls.append((provider, method, path, data))
            if path == "createInvoice":
                invoice = {"invoice_id": len(self.invoices) + 1, "status": "active", "currency_type": "fiat", "fiat": "USD", "amount": data["amount"], "payload": data["payload"], "bot_invoice_url": "https://t.me/CryptoBot?start=test"}
                self.invoices[data["payload"]] = invoice
                return invoice.copy()
            if path == "getInvoices":
                return {"items": [dict(invoice) for invoice in self.invoices.values() if str(invoice.get("invoice_id")) == str(data.get("invoice_ids"))]}
            if path == "/api/v1/currencies":
                return [{"code": code, "kind": "crypto"} for code in ("TON", "USDT", "BTC", "ETH", "BNB")]
            if path == "/api/v1/rates":
                return [{"currency": data["assets"], "rate": "2"}]
            if path == "/api/v1/invoices":
                invoice = {**data, "id": "inv_" + str(len(self.invoices) + 1), "status": "active", "links": {"telegramBotLink": "https://t.me/xRocket?start=test"}}
                self.invoices[data["clientInvoiceId"]] = invoice
                return dict(invoice)
            if path == "/api/v1/invoice":
                return next(dict(invoice) for order_id, invoice in self.invoices.items() if order_id == data.get("clientInvoiceId") or invoice.get("id") == data.get("invoiceId"))
            if path.startswith("deleteInvoice") or method == "DELETE":
                return True
            raise AssertionError((provider, method, path, data))
        self.backend.payment_api = api

    async def create_invoice(self, provider="cryptobot", amount=10, currency="USDT", user_id=42, key=None):
        status, result = await self.post(f"/api/deposit/{provider}/create", {"amount": amount, "currency": currency}, user_id, key)
        self.assertEqual(status, 200, result)
        return result

    async def crypto_hook(self, invoice, signature=True):
        body = json.dumps({"update_type": "invoice_paid", "update_id": 123, "payload": invoice}, separators=(",", ":")).encode()
        digest = hmac.new(hashlib.sha256(b"test-crypto-token").digest(), body, hashlib.sha256).hexdigest() if signature else "0" * 64
        response = await self.client.post("/cryptobot", data=body, headers={"crypto-pay-api-signature": digest})
        return response.status, await response.json()

    async def rocket_hook(self, invoice, event_id="event-1", partial=False):
        body = json.dumps({"id": event_id, "type": "invoice", "data": {"event": "payment_status_changed" if partial else "invoice_status_changed", "invoice": {"id": invoice["id"], "status": invoice["status"]} if partial else invoice}}).encode()
        timestamp = str(int(time.time() * 1000))
        digest = hmac.new(b"test-webhook-secret", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        response = await self.client.post("/xrocket", data=body, headers={"Signature": digest, "Signature-Version": "v1", "Signature-Timestamp": timestamp})
        return response.status, await response.json()

    async def test_methods_rate_whole_stars_and_owner(self):
        await self.configure()
        status, info = await self.get("/api/deposit/info")
        self.assertEqual(info["usdPerStar"], "0.022")
        self.assertFalse(info["methods"]["tonkeeper"])
        invoice = await self.create_invoice(amount=1)
        self.assertEqual(invoice["priceAmount"], "0.022")
        self.assertEqual((await self.get("/api/deposit/cryptobot/status?invoiceId=" + invoice["invoiceId"], 99))[0], 404)
        self.assertEqual((await self.post("/api/deposit/stars/create", {"amount": 1.5}))[0], 400)
        self.assertEqual((await self.post("/api/deposit/cryptobot/create", {"amount": 10, "uid": 99}))[0], 403)
        self.assertEqual(await self.runtime.get_balance(42), 1000)

    async def test_crypto_signature_amount_and_concurrent_exactly_once(self):
        await self.configure()
        await self.runtime.add_referral(42, 99, False)
        invoice = await self.create_invoice(amount=25)
        paid = {**self.invoices[invoice["invoiceId"]], "status": "paid"}
        self.assertEqual((await self.crypto_hook(paid, False))[0], 401)
        self.assertEqual((await self.crypto_hook({**paid, "amount": "0.01"}))[0], 409)
        self.assertEqual((await self.crypto_hook({**paid, "fiat": "EUR"}))[0], 409)
        self.invoices[invoice["invoiceId"]] = paid
        results = await asyncio.gather(*(self.crypto_hook(paid) if index % 2 else self.get("/api/deposit/cryptobot/status?invoiceId=" + invoice["invoiceId"]) for index in range(12)))
        self.assertTrue(all(status == 200 for status, result in results), results)
        self.assertEqual(await self.runtime.get_balance(42), 1025)
        referral = await self.runtime.get_ref_data(99)
        self.assertEqual(referral["deposit_earned"], 2.5)
        status, stats = await self.get("/api/profile/stats")
        self.assertEqual(stats["deposits"], 25)
        second = await self.create_invoice(amount=5)
        self.assertEqual((await self.crypto_hook({**self.invoices[second["invoiceId"]], "status": "paid"}))[0], 200)
        self.assertEqual(await self.runtime.get_balance(42), 1030)

    async def test_credit_rollback_keeps_event_retryable(self):
        await self.configure()
        invoice = await self.create_invoice(amount=10)
        paid = {**self.invoices[invoice["invoiceId"]], "status": "paid"}
        connection = self.runtime.db()
        await connection.execute("CREATE TRIGGER fail_wallet_credit BEFORE INSERT ON webapp_wallet_events BEGIN SELECT RAISE(FAIL,'test failure'); END")
        await connection.commit()
        response = await self.client.post("/cryptobot", data=b"{}")
        self.assertEqual(response.status, 401)
        with self.assertRaises(Exception):
            await self.backend.settle_invoice("cryptobot", paid, "retry-test")
        self.assertEqual(await self.runtime.get_balance(42), 1000)
        async with connection.execute("SELECT status FROM webapp_deposits WHERE id = ?", (invoice["invoiceId"],)) as cursor:
            self.assertEqual((await cursor.fetchone())[0], "active")
        await connection.execute("DROP TRIGGER fail_wallet_credit")
        await connection.commit()
        await self.backend.settle_invoice("cryptobot", paid, "retry-test")
        self.assertEqual(await self.runtime.get_balance(42), 1010)

    async def test_xrocket_current_currency_price_and_event_pair(self):
        await self.configure()
        invoice = await self.create_invoice("xrocket", 10, "TONCOIN")
        self.assertEqual(invoice["priceCurrency"], "TON")
        self.assertEqual(invoice["priceAmount"], "0.11000000")
        creation = next(call for call in self.calls if call[2] == "/api/v1/invoices")
        self.assertEqual(creation[3]["expiresIn"], 1800000)
        self.assertEqual(creation[3]["callback"]["callbackUrl"], "https://mjrr.wisp.uno/xrocket")
        paid = {**self.invoices[invoice["invoiceId"]], "status": "paid"}
        self.invoices[invoice["invoiceId"]] = paid
        self.assertEqual((await self.rocket_hook(paid, "first", True))[0], 200)
        self.assertEqual((await self.rocket_hook(paid, "second"))[0], 200)
        self.assertEqual((await self.rocket_hook(paid, "second"))[0], 200)
        self.assertEqual(await self.runtime.get_balance(42), 1010)
        self.assertEqual((await self.rocket_hook({**paid, "priceCurrency": "BTC"}, "third"))[0], 409)

    async def test_create_key_replay_and_restart_state(self):
        await self.configure()
        key = secrets.token_hex(16)
        first = await self.create_invoice(key=key)
        second = await self.create_invoice(key=key)
        self.assertEqual(first["invoiceId"], second["invoiceId"])
        self.assertEqual(len([call for call in self.calls if call[2] == "createInvoice"]), 1)
        self.assertEqual((await self.post("/api/deposit/cryptobot/create", {"amount": 11, "currency": "USDT"}, key=key))[0], 409)
        await self.crypto_hook({**self.invoices[first["invoiceId"]], "status": "paid"})
        response = await self.backend.deposit_row(self.runtime.db(), first["invoiceId"], 42)
        self.assertEqual(response["status"], "paid")
        status, rows = await self.get("/api/wallet/transactions")
        self.assertEqual(rows["rows"][0]["description"], "CryptoBot")
        status, dates = await self.get("/api/wallet/transactions/page-dates?pages=1,2")
        self.assertEqual(status, 200, dates)
        self.assertIn("1", dates["dates"])

    async def test_stars_precheckout_and_charge_deduplication(self):
        await self.configure()
        await self.runtime.add_referral(42, 99, False)
        invoice = await self.create_invoice("stars", 10)
        order_id = invoice["invoiceId"]
        await self.backend.validate_stars_order(order_id, 42, "XTR", 10)
        for uid, currency, amount in ((99, "XTR", 10), (42, "USD", 10), (42, "XTR", 100)):
            with self.assertRaises(GameError):
                await self.backend.validate_stars_order(order_id, uid, currency, amount)
        results = await asyncio.gather(*(self.backend.credit_stars_order(order_id, 42, "XTR", 10, "telegram-charge") for index in range(8)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(await self.runtime.get_balance(42), 1010)
        self.assertEqual((await self.runtime.get_ref_data(99))["deposit_earned"], 1)
        second = await self.create_invoice("stars", 10)
        with self.assertRaises(GameError):
            await self.backend.credit_stars_order(second["invoiceId"], 42, "XTR", 10, "telegram-charge")
        status, stats = await self.get("/api/profile/stats")
        self.assertEqual(stats["deposits"], 10)
        status, result = await self.get("/api/deposit/stars/status?invoiceId=" + order_id)
        self.assertTrue(result["paid"])

    async def test_checks_multi_cancel_race_and_conservation(self):
        await self.configure()
        status, check = await self.post("/api/checks/create", {"type": "multi", "amount": 10, "activations": 2})
        self.assertEqual(status, 200, check)
        self.assertEqual(await self.runtime.get_balance(42), 980)
        self.assertTrue((await self.get("/api/checks/detail?code=" + check["code"], 99))[1]["canActivate"])
        self.assertEqual((await self.post("/api/checks/cancel", {"code": check["code"]}, 99))[0], 403)
        result = await self.post("/api/checks/activate", {"code": check["code"]}, 99)
        self.assertEqual(result[0], 200, result)
        self.assertEqual((await self.post("/api/checks/activate", {"code": check["code"]}, 99))[0], 409)
        status, cancelled = await self.post("/api/checks/cancel", {"code": check["code"]})
        self.assertEqual(cancelled["refundedAmount"], 10)
        self.assertEqual(await self.runtime.get_balance(42), 990)
        self.assertEqual(await self.runtime.get_balance(99), 1010)
        status, overview = await self.get("/api/checks/overview")
        self.assertEqual(overview["totalSent"], 10)
        self.assertEqual((await self.get("/api/checks/history?scope=all"))[0], 200)

    async def test_check_single_simultaneous_claim_and_cancel(self):
        await self.configure()
        status, check = await self.post("/api/checks/create", {"amount": 100, "type": "normal"})
        code = check["code"]
        results = await asyncio.gather(self.post("/api/checks/activate", {"code": code}, 99), self.post("/api/checks/cancel", {"code": code}))
        self.assertEqual(sum(status == 200 for status, data in results), 1, results)
        self.assertEqual(await self.runtime.get_balance(42) + await self.runtime.get_balance(99), 2000)

    async def test_check_expiry_password_and_settings_ownership(self):
        await self.configure()
        status, check = await self.post("/api/checks/create", {"amount": 10, "password": "correct"})
        code = check["code"]
        self.assertNotIn("passwordHash", json.dumps((await self.get("/api/checks/detail?code=" + code, 99))[1]))
        self.assertEqual((await self.get("/api/checks/settings?code=" + code, 99))[0], 403)
        self.assertEqual((await self.post("/api/checks/activate", {"code": code, "password": "wrong"}, 99))[0], 403)
        self.assertEqual((await self.post("/api/checks/edit_settings", {"code": code, "removePassword": True}))[0], 200)
        self.assertFalse((await self.get("/api/checks/settings?code=" + code))[1]["hasPassword"])
        connection = self.runtime.db()
        await connection.execute("UPDATE webapp_checks SET expires_at = ? WHERE code = ?", (int(time.time()) - 1, code))
        await connection.commit()
        self.assertEqual((await self.get("/api/checks/overview"))[0], 200)
        self.assertEqual(await self.runtime.get_balance(42), 1000)
        await self.get("/api/checks/overview")
        self.assertEqual(await self.runtime.get_balance(42), 1000)

    async def test_check_captcha_requirements_and_wager_gate(self):
        await self.configure()
        status, check = await self.post("/api/checks/create", {"amount": 10, "captchaLevel": 1, "wagerAmount": 1, "wagerGames": 1, "reqDepositAmount": 5, "reqDepositPeriod": "all"})
        self.assertEqual(status, 200, check)
        code = check["code"]
        self.assertEqual((await self.post("/api/checks/activate", {"code": code}, 99))[0], 403)
        status, task = await self.post("/api/checks/captcha/start", {"code": code}, 99)
        self.assertEqual(status, 200, task)
        self.assertEqual((await self.post("/api/checks/captcha/answer", {"code": code, "token": task["token"], "answer": task["seq"]}, 99))[1]["solved"], True)
        self.assertEqual((await self.post("/api/checks/activate", {"code": code, "captchaToken": task["token"]}, 99))[0], 403)
        await self.runtime.credit_payment("existing-payment", 99, 5)
        self.assertEqual((await self.post("/api/checks/activate", {"code": code, "captchaToken": task["token"]}, 99))[0], 200)
        self.assertEqual((await self.post("/api/checks/create", {"amount": 1}, 99))[0], 403)
        self.runtime._wallet_backend = self.backend
        self.assertFalse((await self.runtime.create_withdrawal_atomic(99, 50))[0])
        key = secrets.token_hex(16)
        await self.runtime.db().execute("INSERT INTO webapp_rounds(public_id,game,user_id,username,bet_cents,payout_cents,request_id,request_digest,response,created_at) VALUES (?,'keno',99,'Player',100,0,?,?,?,?)", (key, key, key, '{}', self.runtime.now_msk().isoformat()))
        await self.runtime.db().commit()
        self.assertEqual((await self.post("/api/checks/create", {"amount": 1}, 99))[0], 200)
        self.assertTrue((await self.runtime.create_withdrawal_atomic(99, 50))[0])

    async def test_privacy_nickname_idempotence_and_leader_visibility(self):
        await self.configure()
        key = secrets.token_hex(16)
        first = await self.post("/api/privacy/nickname", {"name": "Tester", "activate": True}, key=key)
        second = await self.post("/api/privacy/nickname", {"name": "Tester", "activate": True}, key=key)
        self.assertEqual(first[0], 200, first)
        self.assertEqual(second[1]["balance"], 999)
        self.assertEqual(await self.runtime.get_balance(42), 999)
        status, leaders = await self.get("/api/leaders?category=balance")
        self.assertEqual(next(row["username"] for row in leaders["rows"] if row["id"] == 42), "Tester")
        status, state = await self.post("/api/privacy/toggle", {"field": "hide"})
        self.assertTrue(state["hideFromLeaderboard"])
        self.assertNotIn(42, [row["id"] for row in (await self.get("/api/leaders?category=balance"))[1]["rows"]])
        self.assertEqual((await self.post("/api/privacy/nickname", {"name": "<script>"}))[0], 400)
        self.assertEqual((await self.post("/api/privacy/mode", {"mode": "hidden"}))[0], 200)
        self.assertEqual((await self.post("/api/privacy/nickname/delete", {}))[0], 200)

    async def test_existing_bonus_cooldown_and_shared_profile_history(self):
        await self.configure()
        self.backend.telegram_bot.get_chat.return_value.bio = "@mjrstars"
        status, first = await self.post("/api/bonuses/existing/claim", {})
        self.assertEqual(status, 200, first)
        self.assertTrue(first["state"]["existingBonus"]["queued"])
        self.assertEqual(await self.runtime.get_balance(42), 1000)
        self.assertFalse(await self.runtime.claim_bonus(42, 1, 999))
        queued = (self.runtime.now_msk() - timedelta(hours=13)).isoformat()
        await self.runtime.db().execute("UPDATE bonus SET queued_at = ? WHERE user_id = 42", (queued,))
        await self.runtime.db().commit()
        results = await asyncio.gather(*(self.post("/api/bonuses/existing/claim", {}) for index in range(5)))
        self.assertTrue(all(status == 200 for status, data in results), results)
        credited = sum(data["creditedAmount"] for status, data in results)
        self.assertGreaterEqual(credited, 1.1)
        self.assertLessEqual(credited, 3.1)
        self.assertEqual(round(await self.runtime.get_balance(42) - 1000, 2), credited)
        status, stats = await self.get("/api/profile/stats")
        self.assertEqual(stats["bonuses"], credited)
        self.assertEqual((await self.get("/api/profile/all-rounds"))[0], 200)

    async def test_referrals_stats_list_history_top_and_withdraw(self):
        await self.configure()
        await self.runtime.add_referral(99, 42, False)
        await self.runtime.process_referral_signup(99, False)
        invoice = await self.create_invoice(amount=100, user_id=99)
        await self.crypto_hook({**self.invoices[invoice["invoiceId"]], "status": "paid"})
        status, stats = await self.get("/api/referral/stats")
        self.assertEqual(stats["depositPercent"], 10)
        self.assertEqual(stats["signupEarnings"], 2.5)
        self.assertEqual(stats["depositEarnings"], 10)
        self.assertEqual(stats["refCount"], 1)
        self.assertEqual((await self.get("/api/referral/list"))[1]["rows"][0]["id"], 99)
        self.assertEqual(len((await self.get("/api/referral/history"))[1]["rows"]), 2)
        self.assertEqual((await self.get("/api/referral/top"))[1]["rows"][0]["c"], 1)
        key = secrets.token_hex(16)
        status, withdrawn = await self.post("/api/referral/withdraw", {}, key=key)
        self.assertEqual(status, 200, withdrawn)
        self.assertEqual(withdrawn["creditedAmount"], 12.5)
        await self.post("/api/referral/withdraw", {}, key=key)
        self.assertEqual(await self.runtime.get_balance(42), 1012.5)

    async def test_history_filters_real_bot_games_and_hidden_pending_seed(self):
        await self.configure()
        await self.runtime.init_dice_history()
        await self.runtime.db().execute("INSERT INTO dice_history(game,user_id,bet,player_range,dice_value,multiplier,win_amount,won,created_at) VALUES ('bowling',42,1,'strike',6,6,6,1,?)", (self.runtime.now_msk().isoformat(),))
        await self.runtime.db().commit()
        status, result = await self.get("/api/profile/all-rounds?game=" + "Боулинг")
        self.assertEqual(status, 200, result)
        self.assertEqual(result["total"], 1)
        self.assertEqual(json.loads(result["rows"][0]["meta"])["outcome"], "strike")
        self.assertEqual((await self.get("/api/profile/all-rounds", 99))[1]["total"], 0)
        status, result = await self.get("/api/profile/all-rounds/page-dates?pages=1,2")
        self.assertIn("1", result["dates"])

    async def test_checks_creation_replay_premium_target_and_failure_rollback(self):
        await self.configure()
        key = secrets.token_hex(16)
        first = await self.post("/api/checks/create", {"amount": 10, "premiumOnly": True}, key=key)
        second = await self.post("/api/checks/create", {"amount": 10, "premiumOnly": True}, key=key)
        self.assertEqual(first[1]["code"], second[1]["code"])
        self.assertEqual(await self.runtime.get_balance(42), 990)
        self.assertEqual((await self.post("/api/checks/activate", {"code": first[1]["code"]}, 99))[0], 403)
        self.assertEqual((await self.post("/api/checks/create", {"amount": 10000}))[0], 400)
        self.assertEqual(await self.runtime.get_balance(42), 990)
        connection = self.runtime.db()
        await connection.execute("CREATE TRIGGER fail_check BEFORE INSERT ON webapp_checks BEGIN SELECT RAISE(FAIL,'failure'); END")
        await connection.commit()
        with self.assertLogs("aiohttp.server", level="ERROR"):
            response = await self.client.post("/api/checks/create", json={"amount": 20}, headers=self.headers())
        self.assertEqual(response.status, 500)
        self.assertEqual(await self.runtime.get_balance(42), 990)
        await connection.execute("DROP TRIGGER fail_check")
        await connection.commit()
        status, check = await self.post("/api/checks/create", {"type": "personal", "amount": 10, "targetUsername": "OtherUser"})
        self.assertEqual(status, 200, check)
        self.assertEqual((await self.post("/api/checks/activate", {"code": check["code"]}, 99))[0], 403)

    async def test_inline_only_owns_active_checks_no_query_debit(self):
        await self.configure()
        status, check = await self.post("/api/checks/create", {"amount": 10})
        first = await self.backend.inline_check_results(42, "share_check_" + check["code"])
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0].id, check["code"])
        self.assertIn("startapp=check_", first[0].reply_markup.inline_keyboard[0][0].url)
        self.assertEqual(await self.backend.inline_check_results(99, "share_check_" + check["code"]), [])
        self.assertEqual(await self.backend.inline_check_results(42, "100"), [])
        self.assertEqual(await self.runtime.get_balance(42), 990)
        await self.post("/api/checks/cancel", {"code": check["code"]})
        self.assertEqual(await self.backend.inline_check_results(42, "share_check_" + check["code"]), [])

    async def test_referral_notices_obey_preferences_and_earnings_survive_withdraw(self):
        await self.configure()
        await self.runtime.add_referral(99, 42, False)
        await self.post("/api/referral/notifications", {"enabled": False})
        invoice = await self.create_invoice(amount=100, user_id=99)
        await self.crypto_hook({**self.invoices[invoice["invoiceId"]], "status": "paid"})
        await self.backend.deliver_referral_notices()
        self.backend.telegram_bot.send_message.assert_not_awaited()
        await self.post("/api/referral/withdraw", {})
        stats = (await self.get("/api/referral/stats"))[1]
        self.assertEqual(stats["totalEarnings"], 10)
        self.assertEqual(stats["availableBalance"], 0)
        await self.post("/api/referral/notifications", {"enabled": True})
        invoice = await self.create_invoice(amount=10, user_id=99)
        await self.crypto_hook({**self.invoices[invoice["invoiceId"]], "status": "paid"})
        await self.backend.deliver_referral_notices()
        self.backend.telegram_bot.send_message.assert_awaited_once()
        self.assertEqual(await self.runtime.get_weekly_deposit(99), 110)

    async def test_nickname_keys_scoped_to_owner_and_public_pot_names(self):
        await self.configure()
        key = secrets.token_hex(16)
        for user_id in (42, 99):
            result = await self.post("/api/privacy/nickname", {"name": "_Alias", "activate": True}, user_id, key)
            self.assertEqual(result[0], 200, result)
            self.assertEqual(await self.runtime.get_balance(user_id), 999)
        response = self.backend.response({"players": [{"uid": 42, "name": "Real Name"}], "winnerId": 42, "winnerName": "Real Name"})
        public = json.loads(response.body)
        self.assertEqual(public["players"][0]["name"], "_Alias")
        self.assertEqual(public["winnerName"], "_Alias")
        await self.post("/api/privacy/mode", {"mode": "hidden"})
        response = self.backend.response({"user_id": 42, "username": "Real Name"})
        self.assertEqual(json.loads(response.body)["username"], "Аноним")

    async def test_malformed_settings_fail_closed_and_missing_tokens_unavailable(self):
        self.backend.payment_tokens = {"cryptobot": None, "xrocket": None}
        for path, payload in (("/api/privacy/mode", {"mode": []}), ("/api/privacy/toggle", {"field": []}), ("/api/checks/create", {"type": [], "amount": 10}), ("/api/checks/create", {"amount": True}), ("/api/checks/create", {"amount": 10, "reqDepositAmount": 1, "reqDepositPeriod": []})):
            with self.subTest(path=path, payload=payload):
                self.assertEqual((await self.post(path, payload))[0], 400)
        info = (await self.get("/api/deposit/info"))[1]
        self.assertFalse(info["methods"]["cryptobot"])
        self.assertFalse(info["methods"]["xrocket"])
        self.assertEqual((await self.post("/api/deposit/cryptobot/create", {"amount": 10}))[0], 503)
        self.assertEqual(await self.runtime.get_balance(42), 1000)

    async def test_real_telegram_handlers_use_verified_order_not_browser_callback(self):
        await self.configure()
        invoice = await self.create_invoice("stars", 15)
        checkout = SimpleNamespace(invoice_payload=invoice["invoiceId"], from_user=SimpleNamespace(id=42), currency="XTR", total_amount=15, answer=AsyncMock())
        await self.runtime.on_pre_checkout(checkout)
        checkout.answer.assert_awaited_once_with(ok=True)
        invalid = SimpleNamespace(invoice_payload=invoice["invoiceId"], from_user=SimpleNamespace(id=42), currency="XTR", total_amount=150, answer=AsyncMock())
        await self.runtime.on_pre_checkout(invalid)
        self.assertFalse(invalid.answer.await_args.kwargs["ok"])
        self.assertEqual(await self.runtime.get_balance(42), 1000)
        payment = SimpleNamespace(invoice_payload=invoice["invoiceId"], currency="XTR", total_amount=15, telegram_payment_charge_id="handler-charge")
        message = SimpleNamespace(successful_payment=payment, from_user=SimpleNamespace(id=42), answer=AsyncMock())
        await self.runtime.on_successful_payment(message)
        await self.runtime.on_successful_payment(message)
        self.assertEqual(await self.runtime.get_balance(42), 1015)
        message.answer.assert_awaited_once()


    async def test_rejected_create_is_failed_not_stuck_and_fresh_request_works(self):
        await self.configure()
        normal_api = self.backend.payment_api
        rejected = PaymentProviderError("cryptobot", "Safe rejection", "PROVIDER_AUTH_REJECTED", 401, definitive=True)
        self.backend.payment_api = AsyncMock(side_effect=rejected)
        key = secrets.token_hex(16)
        path = "/api/deposit/cryptobot/create"
        status, data = await self.post(path, {"amount": 10}, key=key)
        self.assertEqual((status, data["code"], data["providerStatus"]), (502, "PROVIDER_AUTH_REJECTED", 401))
        async with self.runtime.db().execute("SELECT id,status FROM webapp_deposits WHERE request_key=?", (key,)) as cursor:
            order_id, state = await cursor.fetchone()
        self.assertEqual(state, "failed")
        self.assertEqual((await self.post(path, {"amount": 10}, key=key))[0], 409)
        self.assertEqual(self.backend.payment_api.await_count, 1)
        self.assertEqual((await self.get("/api/deposit/cryptobot/status?invoiceId=" + order_id))[1]["status"], "failed")
        self.assertEqual(self.backend.payment_api.await_count, 1)
        self.backend.payment_api = normal_api
        self.assertEqual((await self.post(path, {"amount": 10}, key=secrets.token_hex(16)))[0], 200)
        self.assertEqual(await self.runtime.get_balance(42), 1000)

    async def test_ambiguous_post_keeps_creating_and_same_key_never_reposts(self):
        await self.configure()
        self.backend.payment_api = AsyncMock(side_effect=PaymentProviderError("cryptobot", "Timeout", "PROVIDER_CONNECTION_FAILED"))
        key = secrets.token_hex(16)
        path = "/api/deposit/cryptobot/create"
        self.assertEqual((await self.post(path, {"amount": 10}, key=key))[0], 502)
        async with self.runtime.db().execute("SELECT status FROM webapp_deposits WHERE request_key=?", (key,)) as cursor:
            self.assertEqual((await cursor.fetchone())[0], "creating")
        self.assertEqual((await self.post(path, {"amount": 10}, key=key))[0], 409)
        self.assertEqual(self.backend.payment_api.await_count, 1)
        self.assertEqual(await self.runtime.get_balance(42), 1000)

    async def test_xrocket_get_failure_does_not_leave_ambiguous_post(self):
        await self.configure()
        self.backend.payment_api = AsyncMock(side_effect=PaymentProviderError("xrocket", "Timeout", "PROVIDER_CONNECTION_FAILED"))
        key = secrets.token_hex(16)
        self.assertEqual((await self.post("/api/deposit/xrocket/create", {"amount": 10, "currency": "USDT"}, key=key))[0], 502)
        async with self.runtime.db().execute("SELECT status FROM webapp_deposits WHERE request_key=?", (key,)) as cursor:
            self.assertEqual((await cursor.fetchone())[0], "failed")
        self.assertTrue(all(call.args[1] == "GET" for call in self.backend.payment_api.await_args_list))

    async def test_crypto_accepts_mini_app_link(self):
        await self.configure()
        normal_api = self.backend.payment_api
        async def api(provider, method, path, data=None):
            result = await normal_api(provider, method, path, data)
            if path == "createInvoice":
                result.pop("bot_invoice_url")
                result["mini_app_invoice_url"] = "https://t.me/CryptoBot/app?startapp=test"
            return result
        self.backend.payment_api = api
        invoice = await self.create_invoice()
        self.assertEqual(invoice["payUrl"], "https://t.me/CryptoBot/app?startapp=test")
        self.assertEqual(await self.runtime.get_balance(42), 1000)

    async def test_info_reports_broken_xrocket_configuration_without_token(self):
        await self.configure()
        self.backend.payment_tokens["xrocket"] = "broken.jwt.private-secret"
        status, info = await self.get("/api/deposit/info")
        self.assertEqual(status, 200)
        self.assertFalse(info["methods"]["xrocket"])
        self.assertTrue(info["methods"]["stars"])
        self.assertIn("xrocket", info["methodErrors"])
        self.assertNotIn("private-secret", json.dumps(info))


class PaymentSignatureTests(unittest.TestCase):
    def test_exact_bytes_and_rocket_timestamp_version(self):
        body = b'{ "value": 1 }'
        digest = hmac.new(hashlib.sha256(b"token").digest(), body, hashlib.sha256).hexdigest()
        self.assertTrue(verify_crypto_signature(body, digest, "token"))
        self.assertFalse(verify_crypto_signature(b'{"value":1}', digest, "token"))
        timestamp = "1794045600000"
        signature = hmac.new(b"secret", timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        headers = {"Signature": signature, "Signature-Timestamp": timestamp, "Signature-Version": "v1"}
        self.assertTrue(verify_rocket_signature(body, headers, "secret", int(timestamp) / 1000))
        self.assertFalse(verify_rocket_signature(body, headers, "secret", int(timestamp) / 1000 + 301))
        self.assertFalse(verify_rocket_signature(body, {**headers, "Signature-Version": "v2"}, "secret", int(timestamp) / 1000))
        self.assertFalse(verify_rocket_signature(body, {**headers, "Signature-Timestamp": "nan"}, "secret"))


class PaymentClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_client_envelopes_headers_and_empty_delete_response(self):
        backend = CompleteGamesBackend(None, None, None, None)
        backend.payment_tokens = {"cryptobot": "test-crypto", "xrocket": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJsb2NhbC10ZXN0In0.dGVzdA"}
        response = SimpleNamespace(status=200, read=AsyncMock())
        session = MagicMock()
        session.request.return_value.__aenter__.return_value = response
        with patch("payments_backend.aiohttp.ClientSession") as factory:
            factory.return_value.__aenter__.return_value = session
            response.read.return_value = b'{"ok":true,"result":{"invoice_id":1}}'
            self.assertEqual(await backend.payment_api("cryptobot", "POST", "createInvoice", {"amount": "0.22"}), {"invoice_id": 1})
            args, options = session.request.call_args
            self.assertEqual(args, ("POST", "https://pay.crypt.bot/api/createInvoice"))
            self.assertEqual(options["headers"], {"Crypto-Pay-API-Token": "test-crypto"})
            self.assertFalse(options["allow_redirects"])
            response.read.return_value = b'[{"currency":"TON","rate":"2"}]'
            result = await backend.payment_api("xrocket", "GET", "/api/v1/rates", {"assets": "TON"})
            self.assertEqual(result[0]["rate"], "2")
            self.assertEqual(session.request.call_args.kwargs["params"], {"assets": "TON"})
            self.assertEqual(session.request.call_args.kwargs["headers"], {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJsb2NhbC10ZXN0In0.dGVzdA"})
            response.read.return_value = b""
            self.assertEqual(await backend.payment_api("xrocket", "DELETE", "/api/v1/invoice?invoiceId=1"), {})
            response.read.return_value = b'{"ok":false}'
            with self.assertRaises(GameError):
                await backend.payment_api("cryptobot", "POST", "createInvoice", {})
            response.status = 429
            response.read.return_value = b'{}'
            with self.assertRaises(GameError) as raised:
                await backend.payment_api("xrocket", "GET", "/api/v1/rates")
            self.assertEqual(raised.exception.status, 429)

    async def test_upstream_auth_and_html_errors_are_safe(self):
        backend = CompleteGamesBackend(None, None, None, None)
        backend.payment_tokens = {"cryptobot": "secret-token"}
        response = SimpleNamespace(status=401, read=AsyncMock(return_value=b'<html>secret-token</html>'))
        session = MagicMock()
        session.request.return_value.__aenter__.return_value = response
        with patch("payments_backend.aiohttp.ClientSession") as factory:
            factory.return_value.__aenter__.return_value = session
            with self.assertRaises(PaymentProviderError) as raised:
                await backend.payment_api("cryptobot", "POST", "createInvoice", {})
            self.assertTrue(raised.exception.definitive)
            self.assertEqual(raised.exception.code, "PROVIDER_AUTH_REJECTED")
            self.assertNotIn("secret-token", str(raised.exception))
            response.status = 503
            with self.assertRaises(PaymentProviderError) as raised:
                await backend.payment_api("cryptobot", "POST", "createInvoice", {})
            self.assertFalse(raised.exception.definitive)
            response.status = 200
            response.read.return_value = b'{"ok":false,"error":{"code":401,"name":"UNAUTHORIZED","message":"secret-token"}}'
            with self.assertRaises(PaymentProviderError) as raised:
                await backend.payment_api("cryptobot", "POST", "createInvoice", {})
            self.assertEqual(raised.exception.code, "PROVIDER_AUTH_REJECTED")
            self.assertNotIn("secret-token", str(raised.exception))

    async def test_invalid_rocket_jwt_is_rejected_before_network(self):
        backend = CompleteGamesBackend(None, None, None, None)
        backend.payment_tokens = {"xrocket": "broken.jwt.secret"}
        with patch("payments_backend.aiohttp.ClientSession") as factory:
            with self.assertRaises(PaymentProviderError) as raised:
                await backend.payment_api("xrocket", "POST", "/api/v1/invoices", {})
            self.assertEqual(raised.exception.code, "XROCKET_TOKEN_MALFORMED")
            self.assertTrue(raised.exception.definitive)
            factory.assert_not_called()
