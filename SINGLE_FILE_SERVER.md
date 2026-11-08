# Deploying the Python backend as server.py

`server.py` is a self-contained Python backend bundle. You do **not** need to upload the separate `*_backend.py`, TON, game, wallet/rule modules or `main.py` alongside it. The emoji rules catalog is embedded too. Module namespaces remain isolated internally, so imports, mixins and identically named helpers do not overwrite each other.

## What stays separate

As requested, **`sw.js` and `support.js` are not included or modified**. All frontend HTML/JS/CSS, images, animations and other static assets remain separate. Keep the existing frontend files and directories next to `server.py`, just as they were next to `main.py`.

External Python libraries still need installation. A single source file does not include Python or its installed packages:

```sh
python -m pip install -r requirements.txt
python server.py --check
python server.py
```

If the hosting panel only lets you upload the server file, install the dependencies through its package settings: `aiogram==3.31.0`, `aiohttp==3.14.5`, `aiosqlite==0.22.1`, `tonsdk==1.0.15`.

Change the hosting startup command from `python main.py` to `python server.py`. Do not start both processes against the same production database. Keep the previous working directory: `DB_PATH = "bot.db"` is unchanged, and static resources are resolved beside `server.py`. Do not replace, delete or recreate the existing database/WAL or private seed file during upload.

`--check` imports all bundled backend modules without starting the HTTP server, initializing a database, buying Stars or sending payments. It is not a live Telegram/provider test.

Wallet diagnostics are also built in, so the helper Python file is not required on hosting:

```sh
python server.py --check-ton-wallet --local-only
python server.py --check-ton-wallet
```

The second command uses your configured own mainnet gateway; the first only checks local derivation. Neither accepts or prints a seed phrase.

## Settings

Inside `server.py`, search for the clearly labelled sections:

- `main.py`: bot/server settings already used by the application.
- `payments_backend.py`: payment settings, Fragment JWT, server wallet configuration, own TON gateway and exchange rate.

The code in these sections is readable source inside raw string literals. Preserve their surrounding delimiters. When deploying only this file, edit **its embedded section**, not an absent neighbouring `payments_backend.py`. The bundle's loader gives its embedded modules precedence over neighbouring source files on a clean process startup.

No real new seed/Fragment JWT was inserted. The recommended seed location is still a private server-only `0600` file; `.secrets/` is not an asset directory. `server.py` itself contains source configuration and must not be exposed by a web server or served from a public asset directory. Existing static-file authorization does not permit it.

## Development and rebuilding

The original Python files remain in the repository as development/test sources. They need not be uploaded. Rebuild the deployment file after changing those sources:

```sh
python tools/build_server.py
```

**Rebuilding overwrites `server.py` with the source modules' settings.** Do not rebuild over a host-local edited deployment file or copy production secrets into the repository to rebuild it. Keep private secrets/backups outside Git. Pick either source-driven development plus rebuild, or deliberate server-local configuration in the deployment file, rather than editing both and expecting automatic synchronization.

The builder never embeds frontend scripts, databases, seed files, virtual environments or arbitrary files from the checkout. Standalone tests copy only `server.py` into an empty directory and check imports, startup dispatch, in-memory backend initialization and local wallet failure behaviour without depending on the original `.py` files.
