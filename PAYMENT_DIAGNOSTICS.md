# CryptoBot / xRocket invoice creation

## Confirmed locally

- The repository's fallback xRocket JWT is malformed: its header and payload do not decode as JSON. A new, intact **Current API JWT** is required; code cannot reconstruct the credential. No credential values are printed in diagnostics.
- Previously all HTTP failures became a generic 502, and failed creates remained `creating`, including failures in xRocket's currency/rate GETs before invoice creation was even attempted.
- CryptoBot handling accepted only `bot_invoice_url`. It now also accepts `mini_app_invoice_url` and `web_app_invoice_url` with explicit HTTPS/host validation.

**CryptoBot's actual production rejection has not been established.** No live provider API access or invoice creation was performed in this sandbox. The xRocket Current request schema, rates direction, envelope and expiration units were not changed on the basis of guesses or legacy SDKs.

## Configuration and server-side check

Existing source defaults remain for compatibility. Environment overrides are now supported by `payments_backend.py`:

- `CRYPTOBOT_API_TOKEN`: Crypto Pay application token, NOT the Telegram bot token.
- `XROCKET_API_TOKEN`: original xRocket Current API JWT, without a `Bearer ` prefix.
- `XROCKET_WEBHOOK_SECRET`: secret for signed Current webhook verification, NOT the JWT.

Store credentials in the server's protected environment/service configuration, never in chat, shell command arguments, source-control commits or diagnostic output. Restart the service after updating configuration. Existing deployments that set only source constants can still use those defaults; the malformed fallback xRocket JWT must be replaced/overridden. Never strip arbitrary characters from a damaged JWT or substitute a fabricated token.

From the deployed project directory, using the application's Python environment:

```bash
PYTHONPATH=. python tools/check_payment_providers.py
```

The command performs only `CryptoBot GET getMe` and `xRocket GET /api/v1/currencies`. It does not initialize the database, create invoices, send transfers, alter balances or print provider response bodies/account details. Exit code 1 means either an API check failed or xRocket's webhook secret is missing. A successful read-only check does **not** prove invoice-create permission, webhook delivery or real settlement.

Safe diagnostic categories include:

- `XROCKET_TOKEN_MALFORMED` / `XROCKET_TOKEN_EXPIRED`: replace the JWT on the server.
- `PROVIDER_AUTH_REJECTED`: provider denied API access; check the application's token, invoice permissions, IP/network restrictions and API version.
- `PROVIDER_CONNECTION_FAILED`: verify outbound HTTPS, DNS and provider availability on the production server.
- `PROVIDER_API_VERSION`: endpoint returned 404; Current/legacy APIs must not be mixed.
- `PROVIDER_AMOUNT_REJECTED` / `PROVIDER_REQUEST_REJECTED`: provider rejected the amount or request parameters.
- `PROVIDER_RATE_LIMITED`: wait before retrying.
- `PROVIDER_BAD_RESPONSE`: response format is invalid; a POST may nevertheless have created an invoice.

Do not send full upstream bodies or tokens to users or logs. API failures expose only safe messages, category, provider and HTTP status. `/api/deposit/info` supplies safe `methodErrors`; the UI explains why an unconfigured xRocket method is unavailable instead of offering a guaranteed failing operation.

## Financial safety and retry semantics

- Explicit provider rejections and failures in pre-create GETs mark the local request `failed`; they no longer remain `creating`.
- A replay of that same request key returns 409, not a bogus usable invoice. After correcting the cause, a **new** request key can create a new order. The existing five-orders/minute limit remains.
- Ambiguous POST outcomes (timeouts, 5xx, malformed success response) remain `creating`. Replaying the same key does not resend POST. Do not blindly repeat creates after ambiguous outcomes; reconcile with the provider first. This does not add provider-side idempotency or prohibit all fresh-key requests.
- Historical `creating` rows are not mass-reset: some may correspond to real invoices. No DB/WAL files are deleted or migrated away.
- Signed webhooks, invoice/amount/currency checks and atomic once-only crediting remain in place. Stars settlement and 1 XTR = 1 internal Star / crypto 1 Star = 0.022 USD are unchanged.

## Deployment and verification

Deploy the current source, including new `payment_errors.py`, not the old `or.zip`. Frontend cache markers: `majorstars-payments-20261107-7` / `mjrstar-static-v31`.

Local verification: 163 Python tests and all 7 Node regression suites passed; syntax and diff checks passed. Tests cover safe 401/HTML/envelope errors, JWT validation, environment configuration, URL fallback and hostile hosts, definitive vs ambiguous failure states, same-key replay and UI escaping. They use synthetic credentials and mocked providers, not real payments.

After configuration/deployment: run the read-only diagnostic, then manually verify a small invoice and signed once-only settlement for each provider in the real Telegram environment. No production deployment or real payment is claimed by these tests.
