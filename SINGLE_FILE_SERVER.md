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

## Editing settings and backend code

Edit **`server.py` directly**. There is no rebuild step. Search for its labelled source sections, such as:

- `main.py`: existing bot/server settings and application entry logic.
- `payments_backend.py`: payment configuration, Fragment JWT, server seed configuration, own TON gateway and exchange rate.
- `ton_wallet.py`, `ton_deposits.py`, other backend names: the corresponding implementation.

These are section labels/module names, **not files that must exist on disk**. Each section is readable source inside a raw triple-quoted string. Preserve its outer delimiters. New backend code belongs in the appropriate section, not in a new root Python file. Internal imports use the embedded module loader.

No new real seed or Fragment JWT was inserted. Prefer a private server-only `0600` seed file in `.secrets/` (never a public asset folder); keep secrets out of Git, chat, logs and command arguments. `server.py` itself contains server configuration and must not be served by a web server.

## Tests and tools

```sh
python -m unittest discover -s tests -q
```

Tests register the embedded modules via `tests/bundle_test_support.py`; fresh application fixtures come from `server.load_application(name)` without a separate `main.py`. Standalone tests also copy only `server.py` into an empty directory and verify imports, startup dispatch, in-memory initialization and local wallet failure behaviour. No source files are extracted.

Optional `tools/check_payment_providers.py` and the benchmark utility load the canonical backend too. They are development/diagnostic commands, not backend modules needed on hosting. The old rebuild tool and redundant TON wallet helper are removed.
