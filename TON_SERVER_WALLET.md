# Server-side TON wallet

Toncenter and its API key are no longer mandatory or hardcoded. The server restores a wallet from a locally stored native TON mnemonic and checks its deployed identity through **your own mainnet v3-compatible read-only indexer/gateway**. A seed cannot fetch blockchain data or replace a node.

## Secret storage

Configuration is in **private `conf.json` beside `server.py`**. Use `conf.example.json` for field names; see `CONFIGURATION.md` for the full setup. Two exclusive server-only seed sources are supported:

- Recommended: set `TON_WALLET_SEED_FILE` to a private file. It must be a regular file, owned by the application user, permissions **0600**, not a symlink, at most 4096 bytes. Inside this repository, only `.secrets/` is accepted; outside the repository, keep it outside any web root. Relative paths are resolved from the configuration directory.
- Alternatively, fill `TON_WALLET_MNEMONIC` in `conf.json` only on the server. The configuration file also requires **0600**, is ignored by Git, and must not be uploaded to a public asset directory. Never put a real phrase into `server.py` or the public example.

Set only one source. Use a local editor to enter the phrase; never a shell command containing the words. `.secrets/` and `*.ton-seed` are ignored by Git. Protect directory access too (0700), keep a protected recovery backup, and do not run the app as root. The application does not automatically create/fund a new wallet, overwrite an existing phrase or persist generated private keys.

This is server-side plaintext secret storage, **not an HSM or encrypted keystore**. Compromise of the application user/server or backups can expose the wallet. Use a separate hot wallet with limited funds. Python does not guarantee erasure of immutable seed/key bytes from RAM.

## Parameters

- `TON_WALLET_VERSION`: explicitly `v4r2` (default) or `v3r2`.
- `TON_WALLET_WORKCHAIN`: 0.
- `TON_WALLET_ID`: `None` for the SDK default, otherwise the actual uint32 subwallet ID.
- `TONKEEPER_ADDRESS`: optional expected receiving address. If present, it **must** match the mnemonic/version/subwallet-derived address. If empty, the derived address is used.
- `TON_RPC_URL`: base URL of your own mainnet **v3-compatible indexer API**, for example `http://127.0.0.1:8081/api/v3` on the deployed server. HTTPS is required for non-loopback hosts. A raw lite-server or ordinary JSON-RPC endpoint is not interchangeable with this REST contract. No indexer/node was provisioned by this patch.
- `TON_USD_RATE`: server-configured USD/TON quote for deposits (not a live rate feed).

V5, multisig, highload, custom contracts, password-protected mnemonics and BIP39-only seeds are **not** silently converted into a v4 wallet. Unsupported parameters fail closed. Check the actual wallet version/ID in your wallet software; the same keys can derive different contract addresses.

The gateway must be operated against mainnet. A raw TON address or mnemonic is shared across networks and does not establish mainnet membership; this adapter trusts the operator's gateway and is not a Python consensus/light-client verifier.

## Validation

Local validation runs in a worker thread rather than blocking the async game loop:

1. Exactly 24 words from the TON mnemonic dictionary.
2. Native TON seed validation via pinned `tonsdk` (not a BIP39 checksum substitution).
3. Wallet-version/workchain/subwallet validation and key derivation.
4. Exact expected-address match, if configured.
5. Retain only the public identity for deposit processing, not a long-lived SDK private-key object.

Before creating a payable invoice and before real transaction scanning, a network preflight verifies:

- Exactly one matching account from `GET accountStates?address=...&include_boc=true`.
- Active account, matching deployed code hash and valid balance.
- Public key and wallet ID decoded from the deployed data BOC match the derived identity.
- No installed V4 plugins, whose spending authority is not supported here.

A successful preflight is cached for 30 seconds. Failed/partial responses keep payment readiness off; invalid local settings disable TON without crashing the rest of the application. The gateway must return `accounts` with `address`, `status`, `balance`, `code_hash` and `data_boc`. Transaction scanning retains the existing v3 `transactions`, finalized/non-emulated, native TON, amount, recipient, comment and unique-hash checks.

Local server commands, without secret arguments:

```sh
python server.py --check-ton-wallet --local-only
python server.py --check-ton-wallet
```

The first validates local derivation only. The second also checks the deployed account through the configured gateway. Output contains only public address/version and validation flags. No network/private-key/seed data is sent to the browser or exposed through a wallet-management HTTP endpoint. Restart the process after changing the seed or derivation parameters.

The receiving workflow is implemented. **Transfers, signing/broadcast endpoints, wallet deployment, sweeps and future spending functions are not enabled by this change.** A future sender must add explicit authorization, durable nonce/seqno coordination, amount limits and ambiguous-broadcast reconciliation before using the stored phrase to spend funds.

## Security regression

Static-file authorization now checks the canonical target of asset symlinks, blocks private dot-directories and `*.ton-seed`, and prevents public asset aliases from exposing server source or wallet files. Do not configure another web server to serve `.secrets/` or the entire source tree.

Tests use ephemeral test-only mnemonics and mocked chain responses. They do not establish that a production mnemonic controls a funded mainnet wallet, and no live transfers were made.
