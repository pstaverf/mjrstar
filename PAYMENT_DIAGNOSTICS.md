# CryptoBot / xRocket invoice creation

## Configuration

At the owner's explicit request, all payment credentials remain source constants in `payments_backend.py`:

- `CRYPTOBOT_API_TOKEN`: Crypto Pay application token, NOT the Telegram bot token.
- `XROCKET_API_TOKEN`: xRocket Current API JWT, without a `Bearer ` prefix. The damaged original was replaced with the owner's supplied JWT. Its structure was checked locally; authenticity and permissions have not been verified with the provider.
- `XROCKET_WEBHOOK_SECRET`: secret for signed Current webhook verification, NOT the JWT.

There is no separate private JSON configuration or environment override. Explicit backend attributes remain available for isolated tests. Restart the service after changing source configuration. Credentials are part of Git history and visible to anyone with repository access. Do not print them in logs, responses or diagnostics; rotate them if repository access is not sufficiently restricted.

## Fixes and limits

- Previously all HTTP failures became a generic 502, and failed creates remained `creating`, including failures in xRocket's currency/rate GETs before invoice creation was attempted.
- CryptoBot handling now accepts `bot_invoice_url`, `mini_app_invoice_url` and `web_app_invoice_url` with explicit HTTPS/host validation.
- Explicit provider rejections and failures in pre-create GETs mark the local request `failed`; replaying that same key returns 409 rather than a bogus usable invoice. After correcting the cause, a new key can create a new order. The existing five-orders/minute limit remains.
- Ambiguous POST outcomes (timeouts, 5xx, malformed success response) remain `creating`. Same-key replay does not resend POST. Reconcile with the provider before creating another invoice. This does not add provider-side idempotency or prohibit all fresh-key requests.
- Historical `creating` rows are not mass-reset: some may correspond to real invoices. No DB/WAL files are deleted.
- Signed webhooks, invoice/amount/currency checks and atomic once-only crediting remain in place. Stars settlement and 1 XTR = 1 internal Star / crypto 1 Star = 0.022 USD are unchanged.

**CryptoBot's actual production rejection has not been established.** No live provider API access or invoice creation was performed in this sandbox. The xRocket Current schema, rates direction, envelope and expiration units were not changed based on guesses or legacy SDKs.

## Read-only server-side check

From the deployed project directory, using the application's Python environment:

```bash
PYTHONPATH=. python tools/check_payment_providers.py
```

This performs only `CryptoBot GET getMe` and `xRocket GET /api/v1/currencies`. It does not initialize the database, create invoices, send transfers, alter balances or print upstream bodies/account details. Exit code 1 means an API check failed or xRocket's webhook secret is missing. Success does not prove invoice-create permission, webhook delivery or settlement.

Safe diagnostic categories:

- `XROCKET_TOKEN_MALFORMED` / `XROCKET_TOKEN_EXPIRED`: replace the JWT.
- `PROVIDER_AUTH_REJECTED`: check the application's token, invoice permissions, IP/network restrictions and API version.
- `PROVIDER_CONNECTION_FAILED`: verify outbound HTTPS, DNS and provider availability on the production server.
- `PROVIDER_API_VERSION`: endpoint returned 404; Current/legacy APIs must not be mixed.
- `PROVIDER_AMOUNT_REJECTED` / `PROVIDER_REQUEST_REJECTED`: provider rejected the amount or request parameters.
- `PROVIDER_RATE_LIMITED`: wait before retrying.
- `PROVIDER_BAD_RESPONSE`: response format is invalid; a POST may nevertheless have created an invoice.

Failures expose only safe messages, category, provider and HTTP status. `/api/deposit/info` supplies safe `methodErrors`; the UI explains why an unconfigured method is unavailable.

## Deployment and verification

Deploy current source, including `payment_errors.py`, not the old `or.zip`. Frontend cache markers: `majorstars-crash-live-20261107-8` / `mjrstar-static-v32`.

Crash rounds now start without bets after the existing countdown, fly from x1 and proceed to a new round after the crash/cooldown. New bets are accepted only while waiting; flying/crashed requests are rejected before debit. Previously prepaid legacy queue entries are still honored without a second debit. Client controls and help text reflect the new restriction; cashout remains available for an existing live bet.

Regression tests cover JWT validation, safe upstream errors, source configuration, URL validation, definitive/ambiguous failure states, empty Crash lifecycle, background launch without further state requests, late-bet rejection without debit/queue, legacy queue preservation, cashout and UI locks. They use mocked providers, not real payments. After deployment, run the read-only diagnostic and manually verify a small invoice and signed once-only settlement for each provider in Telegram. No production deployment or real payment is claimed by local tests.
