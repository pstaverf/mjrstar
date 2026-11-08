# One canonical backend: server.py

`server.py` is the **only Python backend source**. The former root Python modules, duplicate emoji catalog and build/rebuild script have been removed. Backend module namespaces are maintained inside this file; there are no extracted or generated `.py` modules to upload or keep synchronized.

## Hosting

Keep existing frontend assets beside `server.py`. **`sw.js`, `support.js`, HTML/CSS, other frontend scripts, images and animations stay separate and unchanged.** Tests, documentation and development diagnostic tools need not be uploaded to run the application.

Install dependencies and start:

```sh
python -m pip install -r requirements.txt
python server.py --check
python server.py
```

Required packages: `aiogram==3.31.0`, `aiohttp==3.14.5`, `aiosqlite==0.22.1`, `tonsdk==1.0.15`. External Python libraries still need installation; they are not copied into the source file.

Change the hosting startup command from `python main.py` to `python server.py`. Do not start an old process and the new server against the same database. Keep the previous working directory: `DB_PATH = "bot.db"` is unchanged, and static resources are located beside `server.py`. Do not delete/replace the existing database, WAL, backups or private seed file when updating code.

`--check` imports the complete embedded backend without starting the server, initializing a database or making payments. It is not a live provider/Telegram test.

Wallet diagnostics are built in:

```sh
python server.py --check-ton-wallet --local-only
python server.py --check-ton-wallet
```

The first verifies local mnemonic/address derivation only. The second also uses the configured own mainnet gateway to check the deployed wallet account. Neither accepts or prints a seed phrase.

## Settings and backend code

**All secrets and deployment settings are in private `conf.json` beside `server.py`.** See `CONFIGURATION.md` for every field and use `conf.example.json` on a new host. The working file is ignored by Git and must be transferred separately; it is never served as a public asset. Require owner-only permissions `0600`, and restart after edits.

```sh
python server.py --check-config
```

This validates bot startup settings without making provider/Telegram requests or printing secrets. Existing database paths are unchanged. Credentials no longer live in the embedded Python assignments or fall back to old source/env values.

`server.py` remains the sole backend source, with no rebuild step. Implementation changes belong in its labelled source sections (`main.py`, `payments_backend.py`, `ton_wallet.py`, etc.). These are internal module labels, not separate files. Preserve each source section’s surrounding raw-string delimiters. Do not put real credentials back into the Python code.

## Tests and tools

```sh
python -m unittest discover -s tests -q
```

Tests register the embedded modules via `tests/bundle_test_support.py`; fresh application fixtures come from `server.load_application(name)` without a separate `main.py`. Standalone tests also copy only `server.py` into an empty directory and verify imports, startup dispatch, in-memory initialization and local wallet failure behaviour. No source files are extracted.

Optional `tools/check_payment_providers.py` and the benchmark utility load the canonical backend too. They are development/diagnostic commands, not backend modules needed on hosting. The old rebuild tool and redundant TON wallet helper are removed.
