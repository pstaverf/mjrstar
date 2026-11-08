# Stars withdrawals, native TON deposits, fairness

## Configuration (disabled by default)

Source configuration remains in `payments_backend.py`, as requested. Never print these values in logs or API responses.

- `FRAGMENT_API_JWT`: raw **Fragment Connection JWT**, created in the provider dashboard. Not a Telegram bot token, not `/auth/authentication`.
- `FRAGMENT_CURRENCY`: `ton` or `usdt_ton`. USDT settlement needs provider-wallet USDT **and TON for gas**. This does not enable USDT deposits.
- `TONKEEPER_ADDRESS`: mainnet receiving wallet, raw or checksum-valid friendly address. Testnet-tagged and zero/burn addresses are rejected. A raw address/seed alone cannot identify the network: the operator must connect the gateway to mainnet. Use an initialized, funded wallet: verification requires a successful compute phase.
- `TON_WALLET_MNEMONIC` or `TON_WALLET_SEED_FILE`: server-only native TON 24-word mnemonic. See `TON_SERVER_WALLET.md` for storage and verification.
- `TON_WALLET_VERSION`, `TON_WALLET_WORKCHAIN`, `TON_WALLET_ID`: explicit wallet derivation parameters; currently v3r2/v4r2, workchain 0.
- `TON_RPC_URL`: your own mainnet v3-compatible read-only node/indexer gateway. No Toncenter account or key is used.
- `TON_USD_RATE`: explicit server-configured decimal USD price for one TON. **This is not a live market-rate feed.** Maintain it before enabling and while accepting payments. Each invoice locks its amount for 30 minutes; 1 internal Star = USD 0.022. Do not let the browser choose this rate.

Receiving TON technically does not need a seed; this application now restores a server-side wallet at the owner’s request. Never send its seed to the browser, node API or Git. Empty/incomplete configuration keeps the relevant method disabled. Outbound provider access must be allowed on the deployed server. These integrations were tested with mocks, not live monetary transactions.

## Stars withdrawal invariants

- Own username exclusively, obtained from signed Telegram data; a client-supplied recipient is never used. Reopen the Mini App after changing username.
- Integer quantity 50–1,000,000, also limited by the available balance. 1 internal Star is reserved per outgoing Telegram Star.
- Existing check-wager restrictions and the existing minimum recent deposit policy remain in force, rechecked inside confirmation transaction. Defaults: deposit >=50 Stars in the past 7 days.
- A 5-minute server quote binds owner, username and quantity. Confirmation atomically records a unique withdrawal, subtracts spendable balance, appends the reservation ledger event and consumes the quote. A reused request/quote cannot reserve twice.
- SQLite records `queued` **before** submission; a conditional claim changes it to `submitting` and commits **before** the only POST. Network calls are outside the database lock.
- POST `/v1/order/stars/` is asynchronous. An authenticated GET `/v1/order/{id}/` using the original JWT must confirm the order ID, type, quantity and receiver. `CREATED`, `PENDING` and `BLOCKCHAIN_SENT` are nonterminal. No webhook endpoint is trusted/needed.
- `COMPLETED` + `success=true`: final success. `FAILED` + `success=false`: atomic refund, once, with unique ledger source. HTTP errors, malformed responses, recipient mismatches, nullable success or timeouts are **not** grounds for refunding.
- Uses and persists modern `price`/`fee` objects for cost audit, not deprecated fields. These costs never change the quoted number of internal Stars.
- Pending orders with a known provider ID resume GET polling after restart. A restarted `submitting` order becomes `uncertain`; **no automatic POST retry**. The same applies to an ambiguous POST without a usable ID. The API has no documented caller-side create idempotency key.
- JWT fingerprints prevent polling/submitting an existing order with another Fragment connection. Restore the original credential to resume its pending GETs; changing credentials never triggers a second purchase.
- One unresolved withdrawal per user. Reopening withdrawals restores its current status. History and account cashout totals include this separate ledger; legacy admin approval does not manage these orders.

### Uncertain orders require reconciliation

Keep the reservation. Use the local ID (`sw_...`) and the provider's authenticated order records to investigate; check the actual recipient, quantity, transaction, provider wallet and whether Stars were delivered. Do not delete the record, mark it failed, credit the balance manually or send another POST merely because the HTTP request timed out. Without a trustworthy provider order ID, automatic resolution is intentionally unavailable. This conservative hold is necessary to avoid spending the same balance twice.

Read-only diagnosis (no credentials):

```sql
SELECT id,user_id,username,quantity,state,provider_id,error_code,created_at,updated_at
FROM webapp_star_withdrawals
WHERE state NOT IN ('completed','failed');
```

Fragment is an unofficial third-party integration; availability and delivery remain provider dependencies.

## Native TON

POST `/api/deposit/tonkeeper/create` creates an owner-bound, idempotent invoice: fixed Star amount, integer nanotons (rounded upward), receiving account and a cryptographically random, unique comment. The Tonkeeper transfer link includes amount and comment. Info/status reads are owner-only. No client callback can credit funds.

A background worker reads **transactions from the configured own mainnet v3-compatible indexer** after local mnemonic/address derivation and deployed code/public-key/subwallet validation and verifies account and destination, unique comment, minimum nanotons, native text-comment opcode, non-bounced successful transaction, non-emulated data, finalized masterchain status and invoice time window. Jetton notification opcodes, USDT/GRAM, failed transfers, wrong accounts/comments and insufficient amounts do not qualify. Finality/decoded fields are required; unsupported/partial API shapes fail closed. Verify the deployed provider contract before enabling real receipts.

- Transaction hashes are normalized, globally unique and consumed in the same SQLite transaction as deposit credit, paid status and referral accounting.
- Paginated ascending logical-time scans retain a durable cursor. Not-yet-finalized/undecoded transfers are not skipped. A client closing the Mini App does not stop reconciliation.
- An invoice lasts 30 minutes, with a five-minute chain-time grace. Matching transactions sent within that window continue being checked for seven days, even if the client timer expired.
- Send the exact quoted amount. Overpayment credits only the quoted Stars; the observed value is retained for support review. Network gas is separate. Other currencies and late/nonmatching transfers require manual support, not a client-side "paid" button.

## Fairness scope

GET `/api/fairness/check` accepts two of `roundId`, `hash`, `seed`, optionally `game`. **Do not use `uid` for a round ID**: authentication reserves `uid` for the signed user's account. Auth checks were not relaxed.

Only finished, disclosed rounds are searched. Hashes and supplied seeds must match the stored commitment. Keno draws, Upgrade rolls, Mines/Ladder positions, Crash points, Roulette colors, Wheel numbers, Claw rolls and Baccarat deals are deterministically reproduced. The UI explicitly distinguishes:

- matching seed commitment;
- reproduced random outcome (or a mismatch);
- commitment-only verification for other games.

This does not independently audit payouts, prove when a commitment was published, or provide a full fairness certificate for unsupported games. A round card is a separate action, not proof of verification. Telegram dice/PvP proof routes remain separate.

## Tests and runtime

`tests/test_stars_ton_fairness.py` covers ownership/auth, minimums, client-recipient tampering, concurrent confirms, quote/request replay, pending/blockchain states, refunds, ambiguous POSTs, restart, original credentials, wager/recent-deposit gates, modern costs, TON verification and deterministic fairness/tampering. `tests/test_stars_ton_fairness_ui.js` checks UI contracts and nonterminal history statuses. Existing suites remain regression coverage, not Telegram/browser/provider E2E.

A regression run exposed a live worker remaining in a cancelling state at its next sleep. The loop now checks requested cancellation before opening another transaction. This is a shutdown safeguard, **not** a diagnosis of the earlier production profile/crash report. No production database path, database/WAL files, deployment or real payouts were changed.
