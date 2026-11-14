#!/usr/bin/env python3
# Canonical backend source. All Python backend modules are maintained below.
# No neighbouring Python modules or emoji_catalog.json are required to run this file.
# Frontend assets (including sw.js and support.js) stay separate and unchanged.
# Secrets and deployment settings are read from private conf.json beside this file.
# Copy conf.example.json to conf.json on a new host; never publish the private file.
import argparse as _argparse
import asyncio as _asyncio
import importlib as _importlib
import importlib.abc as _importlib_abc
import importlib.util as _importlib_util
from pathlib import Path as _Path
import sys as _sys
import types as _types

import json as _json
import os as _os
import stat as _stat


class ConfigError(ValueError):
    """A redacted configuration error: never include JSON contents or secrets."""


_CONFIG_DEFAULTS = {'BOT_TOKEN': '', 'CHANNEL_ID': '@mjrstars', 'CHANNEL_URL': 'https://t.me/mjrstars', 'CHAT_URL': 'https://t.me/mjrstars', 'WEBHOOK_HOST': '', 'WEBHOOK_PATH': '/webhook', 'WEBHOOK_SECRET': '', 'WEBAPP_HOST': '0.0.0.0', 'WEBAPP_PORT': 16341, 'ADMIN_ID': 0, 'BOT_USERNAME': 'mjrstarsbot', 'CRYPTOBOT_API_TOKEN': '', 'XROCKET_API_TOKEN': '', 'XROCKET_WEBHOOK_SECRET': '', 'FRAGMENT_API_JWT': '', 'FRAGMENT_CURRENCY': 'ton', 'TONKEEPER_ADDRESS': '', 'TON_WALLET_MNEMONIC': '', 'TON_WALLET_SEED_FILE': '', 'TON_WALLET_VERSION': 'v4r2', 'TON_WALLET_WORKCHAIN': 0, 'TON_WALLET_ID': None, 'TON_RPC_URL': '', 'TON_USD_RATE': ''}
_CONFIG_DEFAULTS.update({'LAVESHKA_API_KEY': '', 'LAVESHKA_WEBHOOK_SECRET': ''})
_MODULE_CONFIG = {'main': ['BOT_TOKEN', 'WEBHOOK_SECRET', 'WEBHOOK_HOST', 'WEBHOOK_PATH', 'WEBAPP_HOST', 'WEBAPP_PORT', 'ADMIN_ID', 'BOT_USERNAME', 'CHANNEL_ID', 'CHANNEL_URL', 'CHAT_URL'], 'payments_backend': ['CRYPTOBOT_API_TOKEN', 'XROCKET_API_TOKEN', 'XROCKET_WEBHOOK_SECRET', 'FRAGMENT_API_JWT', 'FRAGMENT_CURRENCY', 'TONKEEPER_ADDRESS', 'TON_WALLET_MNEMONIC', 'TON_WALLET_SEED_FILE', 'TON_WALLET_VERSION', 'TON_WALLET_WORKCHAIN', 'TON_WALLET_ID', 'TON_RPC_URL', 'TON_USD_RATE']}

_MODULE_CONFIG['payments_backend'] += ['LAVESHKA_API_KEY', 'LAVESHKA_WEBHOOK_SECRET']


def _load_config(path=None):
    filename = _Path(path) if path is not None else _Path(__file__).resolve().with_name('conf.json')
    fd = None
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result
    def no_constants(value):
        raise ValueError
    try:
        fd = _os.open(filename, _os.O_RDONLY | _os.O_NOFOLLOW | _os.O_NONBLOCK)
        info = _os.fstat(fd)
        if not _stat.S_ISREG(info.st_mode) or _stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != _os.geteuid() or info.st_size > 65536:
            raise ConfigError('conf.json должен быть обычным файлом владельца процесса с правами 0600, размером до 64 КБ.')
        raw = _os.read(fd, 65537)
        if len(raw) > 65536:
            raise ValueError
        data = _json.loads(raw.decode('utf-8'), object_pairs_hook=object_pairs, parse_constant=no_constants)
    except FileNotFoundError:
        if path is None:
            return dict(_CONFIG_DEFAULTS)
        raise ConfigError('Файл конфигурации не найден.') from None
    except ConfigError:
        raise
    except (OSError, ValueError, UnicodeError):
        raise ConfigError('Не удалось прочитать conf.json: проверьте JSON, отсутствие повторяющихся ключей и доступ к файлу.') from None
    finally:
        if fd is not None:
            _os.close(fd)
    if not isinstance(data, dict) or set(data) - set(_CONFIG_DEFAULTS):
        raise ConfigError('conf.json: ожидается JSON-объект с полями из conf.example.json, без неизвестных ключей.')
    result = dict(_CONFIG_DEFAULTS)
    result.update(data)
    for key, value in result.items():
        if key in {'ADMIN_ID', 'WEBAPP_PORT', 'TON_WALLET_WORKCHAIN'}:
            valid = type(value) is int
        elif key == 'TON_WALLET_ID':
            valid = value is None or type(value) is int and 0 <= value < 2 ** 32
        elif key == 'CHANNEL_ID':
            valid = isinstance(value, str) or type(value) is int
        else:
            valid = isinstance(value, str) and len(value) <= 8192
        if not valid:
            raise ConfigError('conf.json: неверный тип поля ' + key + '. См. conf.example.json.')
    if result['ADMIN_ID'] < 0 or not 1 <= result['WEBAPP_PORT'] <= 65535 or result['TON_WALLET_WORKCHAIN'] != 0:
        raise ConfigError('conf.json: проверьте ADMIN_ID, WEBAPP_PORT и TON_WALLET_WORKCHAIN (поддержан 0).')
    if result['FRAGMENT_CURRENCY'] not in {'ton', 'usdt_ton'} or result['TON_WALLET_VERSION'] not in {'v3r2', 'v4r2'}:
        raise ConfigError('conf.json: неподдерживаемая валюта Fragment или версия TON-кошелька.')
    if result['TON_WALLET_MNEMONIC'].strip() and result['TON_WALLET_SEED_FILE'].strip():
        raise ConfigError('conf.json: задайте только TON_WALLET_MNEMONIC или TON_WALLET_SEED_FILE, не оба.')
    if result['TON_WALLET_SEED_FILE'] and not _Path(result['TON_WALLET_SEED_FILE']).is_absolute():
        result['TON_WALLET_SEED_FILE'] = str(filename.resolve().parent / result['TON_WALLET_SEED_FILE'])
    return result


_CONFIG = _load_config()


def _require_startup_config():
    # Diagnostics/imports can run without secrets; starting the bot cannot.
    required = ('BOT_TOKEN', 'WEBHOOK_HOST', 'WEBHOOK_SECRET')
    missing = [key for key in required if not _CONFIG[key].strip()]
    if missing:
        raise ConfigError('Заполните conf.json перед запуском: ' + ', '.join(missing) + '.')
    from aiogram.utils.token import validate_token
    try:
        validate_token(_CONFIG['BOT_TOKEN'])
    except Exception:
        raise ConfigError('Проверьте BOT_TOKEN в conf.json: неверный формат.') from None
    from urllib.parse import urlsplit
    import re
    try:
        url = urlsplit(_CONFIG['WEBHOOK_HOST'])
        valid_host = url.scheme == 'https' and bool(url.hostname) and not url.username and not url.password and not url.query and not url.fragment
    except ValueError:
        valid_host = False
    if not valid_host or not _CONFIG['WEBHOOK_PATH'].startswith('/'):
        raise ConfigError('В conf.json нужны HTTPS WEBHOOK_HOST и WEBHOOK_PATH, начинающийся с /.')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,256}', _CONFIG['WEBHOOK_SECRET']):
        raise ConfigError('WEBHOOK_SECRET: 1–256 символов A–Z, a–z, 0–9, _ или -.')
    if _CONFIG['ADMIN_ID'] <= 0:
        raise ConfigError('Заполните ADMIN_ID в conf.json: положительный числовой Telegram ID.')


_SOURCES = {}

# ==================== account_backend.py ====================
_SOURCES['account_backend'] = r'''import asyncio
import html
import json
import math
import re
import secrets
import time
from datetime import datetime, timedelta

from aiogram.types import User

from games_backend import GameError, integer, serialize
from privacy_rules import PRIVACY_CACHE, TELEGRAM_NAMES, player_identity, public_names


GAME_LABELS = {"crash": "Краш", "roulette": "Рулетка", "wheel": "Wheel", "mines": "Мины", "keno": "Кено", "hilo": "Hi-Lo", "redblack": "Red & Black", "ladder": "Лесенка", "upgrade": "Апгрейд", "dice": "Кости", "bowl": "Боулинг", "darts": "Дартс", "basket": "Баскетбол", "foot": "Футбол", "slots": "Слоты", "blackjack": "Блэкджек", "doghouse": "DogHouse", "arena": "ArenaHub", "arenahub": "ArenaHub", "portal": "ArenaHub", "escape": "Escape", "race": "Race", "bomb": "Bomb", "sumo": "Sumo", "coinflip": "Орёл-Решка", "claw": "Автомат", "baccarat": "Баккара"}


class AccountMixin:
    def response(self, data, status=200):
        return super().response(public_names(data), status)

    def register_account(self, application):
        application.router.add_get("/api/profile/stats", self.handle_profile_stats)
        application.router.add_get("/api/profile/all-rounds", self.handle_all_rounds)
        application.router.add_get("/api/profile/all-rounds/page-dates", self.handle_all_round_dates)
        application.router.add_get("/api/bonuses/state", self.handle_bonus_state)
        application.router.add_post("/api/bonuses/existing/claim", self.handle_existing_bonus)
        application.router.add_get("/api/privacy", self.handle_privacy)
        for action in ("mode", "toggle", "nickname", "nickname/delete"):
            application.router.add_post("/api/privacy/" + action, self.handle_privacy)
        for section in ("stats", "list", "history", "top", "notifications"):
            application.router.add_get("/api/referral/" + section, self.handle_referrals)
        application.router.add_post("/api/referral/notifications", self.handle_referrals)
        application.router.add_post("/api/referral/withdraw", self.handle_referral_withdraw)

    async def initialize_account(self):
        async with self.database_lock:
            connection = self.database()
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_privacy(user_id INTEGER PRIMARY KEY,mode TEXT NOT NULL DEFAULT 'username',nickname TEXT NOT NULL DEFAULT '',hidden INTEGER NOT NULL DEFAULT 0,clickable INTEGER NOT NULL DEFAULT 1,game_uid TEXT NOT NULL UNIQUE)")
            await connection.execute("CREATE TABLE IF NOT EXISTS ref_balance(user_id INTEGER PRIMARY KEY,signup_earned REAL NOT NULL DEFAULT 0,deposit_earned REAL NOT NULL DEFAULT 0,group_earned REAL NOT NULL DEFAULT 0,frozen INTEGER NOT NULL DEFAULT 0)")
            async with connection.execute("PRAGMA table_info(ref_balance)") as cursor:
                ref_columns = {row[1] for row in await cursor.fetchall()}
            if "group_earned" not in ref_columns:
                await connection.execute("ALTER TABLE ref_balance ADD COLUMN group_earned REAL NOT NULL DEFAULT 0")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_preferences(user_id INTEGER PRIMARY KEY,ref_notifications INTEGER NOT NULL DEFAULT 1,check_notifications INTEGER NOT NULL DEFAULT 1)")
            await connection.execute("CREATE TABLE IF NOT EXISTS usernames(user_id INTEGER PRIMARY KEY,username TEXT,full_name TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL)")
            async with connection.execute("SELECT user_id,mode,nickname,hidden,clickable,game_uid FROM webapp_privacy") as cursor:
                PRIVACY_CACHE.clear()
                PRIVACY_CACHE.update({row[0]: row[1:] for row in await cursor.fetchall()})
            async with connection.execute("SELECT user_id,username FROM usernames") as cursor:
                TELEGRAM_NAMES.clear()
                TELEGRAM_NAMES.update(dict(await cursor.fetchall()))
            await connection.commit()
        self.bonus_claim_locks = {}

    def wallet_page(self, request, zero=False):
        return integer(request.query.get("page", "0" if zero else "1"), 0 if zero else 1, 1000000)

    async def privacy_row(self, connection, user_id):
        await connection.execute("INSERT OR IGNORE INTO webapp_privacy(user_id,game_uid) VALUES (?,?)", (user_id, secrets.token_hex(6).upper()))
        async with connection.execute("SELECT mode,nickname,hidden,clickable,game_uid FROM webapp_privacy WHERE user_id = ?", (user_id,)) as cursor:
            mode, nickname, hidden, clickable, game_uid = await cursor.fetchone()
        return {"ok": True, "privacyMode": mode, "displayName": nickname, "hideFromLeaderboard": bool(hidden), "clickableProfile": bool(clickable), "gameUid": game_uid}

    async def public_identity(self, connection, user_id, fallback=""):
        async with connection.execute("SELECT mode,nickname,hidden,clickable,game_uid FROM webapp_privacy WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            return {"id": user_id, "name": fallback or "Игрок", "hidden": False, "clickable": True}
        mode, nickname, hidden, clickable, game_uid = row
        name, can_click = player_identity(user_id, fallback or "Игрок")
        return {"id": user_id if mode in {"username", "nickname"} and clickable else None, "name": name, "hidden": bool(hidden), "clickable": bool(clickable)}

    async def handle_privacy(self, request):
        try:
            payload = await self.payload(request) if request.method == "POST" else {}
            user = self.validate_user(request, payload)
            key, signature = self.request_identity(request, payload) if request.method == "POST" else (None, None)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    if key:
                        existing = await self.load_receipt(connection, user.id, key, signature)
                        if existing:
                            await connection.rollback()
                            return self.response(existing)
                    state = await self.privacy_row(connection, user.id)
                    action = request.path.removeprefix("/api/privacy/")
                    if request.method == "POST":
                        if action == "mode":
                            mode = payload.get("mode")
                            if not isinstance(mode, str) or mode not in {"username", "hidden", "blank", "game_id", "nickname"}:
                                raise GameError("Неизвестный режим приватности.")
                            if mode == "nickname" and not state["displayName"]:
                                raise GameError("nickname_required")
                            await connection.execute("UPDATE webapp_privacy SET mode = ? WHERE user_id = ?", (mode, user.id))
                        elif action == "toggle":
                            requested_field = payload.get("field")
                            field = {"hide": "hidden", "clickable": "clickable"}.get(requested_field) if isinstance(requested_field, str) else None
                            if not field:
                                raise GameError("Неизвестная настройка.")
                            await connection.execute(f"UPDATE webapp_privacy SET {field} = 1 - {field} WHERE user_id = ?", (user.id,))
                        elif action == "nickname/delete":
                            await connection.execute("UPDATE webapp_privacy SET nickname = '',mode = CASE WHEN mode = 'nickname' THEN 'username' ELSE mode END WHERE user_id = ?", (user.id,))
                        elif action == "nickname":
                            name = payload.get("name")
                            if not isinstance(name, str) or not re.fullmatch(r"[\w]{3,20}", name, flags=re.UNICODE):
                                raise GameError("Псевдоним: 3–20 букв, цифр или знаков подчёркивания.")
                            if not isinstance(payload.get("activate", False), bool):
                                raise GameError("Некорректный режим.")
                            await self.debit(connection, user.id, 100)
                            await connection.execute("UPDATE webapp_privacy SET nickname = ?,mode = CASE WHEN ? THEN 'nickname' ELSE mode END WHERE user_id = ?", (name, payload.get("activate", False), user.id))
                            await connection.execute("INSERT INTO webapp_wallet_events(user_id,kind,amount_cents,source,created_at) VALUES (?,'nickname',-100,?,?)", (user.id, "nickname:" + str(user.id) + ":" + key, self.clock().isoformat()))
                    result = await self.privacy_row(connection, user.id)
                    result["balance"] = await self.balance(connection, user.id)
                    if key:
                        await self.save_receipt(connection, user.id, key, signature, result)
                    await connection.commit()
                    PRIVACY_CACHE[user.id] = (result["privacyMode"], result["displayName"], result["hideFromLeaderboard"], result["clickableProfile"], result["gameUid"])
                except BaseException:
                    await connection.rollback()
                    raise
            return self.response(result)
        except GameError as error:
            return self.failure(error)

    async def handle_bonus_state(self, request):
        user = self.validate_user(request)
        async with self.database_lock:
            connection = self.database()
            async with connection.execute("SELECT queued_at,streak,last_claim FROM bonus WHERE user_id = ?", (user.id,)) as cursor:
                record = await cursor.fetchone()
            async with connection.execute("SELECT COALESCE(SUM(amount_cents),0) FROM webapp_wallet_events WHERE user_id = ? AND kind = 'bonus'", (user.id,)) as cursor:
                total = (await cursor.fetchone())[0] / 100
        runtime = getattr(self, "wallet_runtime", {})
        cooldown = runtime.get("BONUS_COOLDOWN", timedelta(hours=12)).total_seconds()
        queued = datetime.fromisoformat(record[0]).timestamp() if record and record[0] else None
        remaining = max(0, math.ceil(queued + cooldown - time.time())) if queued else 0
        return self.response({"ok": True, "existingBonus": {"bioText": runtime.get("BONUS_BIO_TEXT", "@mjrstars"), "cooldownSeconds": cooldown, "queued": queued is not None, "secondsLeft": remaining, "streak": record[1] if record else 0, "lastClaim": record[2] if record else None, "total": total, "baseMin": runtime.get("BONUS_BASE_MIN", 1), "baseMax": runtime.get("BONUS_BASE_MAX", 3), "streakBase": runtime.get("BONUS_STREAK_BASE", 0.1), "streakStep": runtime.get("BONUS_STREAK_STEP", 0.05)}})

    async def handle_existing_bonus(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            runtime = getattr(self, "wallet_runtime", {})
            process = runtime.get("process_bonus")
            bot = getattr(self, "telegram_bot", None)
            if not process or bot is None:
                raise GameError("Проверка описания Telegram временно недоступна.", 503)
            messages = []
            async def capture(text, **kwargs):
                messages.append(html.unescape(re.sub(r"<[^>]*>", "", text)))
            lock = self.bonus_claim_locks.setdefault(user.id, asyncio.Lock())
            async with lock:
                async with self.database_lock:
                    async with self.database().execute("SELECT COALESCE(MAX(id),0) FROM webapp_wallet_events WHERE user_id = ? AND kind = 'bonus'", (user.id,)) as cursor:
                        baseline = (await cursor.fetchone())[0]
                await process(user.id, User(id=user.id, is_bot=False, first_name=user.first_name, last_name=user.last_name, username=user.username, is_premium=user.is_premium), bot, capture)
            async with self.database_lock:
                balance = await self.balance(self.database(), user.id)
                async with self.database().execute("SELECT COALESCE(SUM(amount_cents),0) FROM webapp_wallet_events WHERE user_id = ? AND kind = 'bonus' AND id > ?", (user.id, baseline)) as cursor:
                    credited = (await cursor.fetchone())[0] / 100
            state_response = await self.handle_bonus_state(request)
            return self.response({"ok": True, "message": "\n".join(messages), "creditedAmount": credited, "balance": balance, "state": json.loads(state_response.body)})
        except GameError as error:
            return self.failure(error)

    async def handle_profile_stats(self, request):
        try:
            user = self.validate_user(request)
            async with self.database_lock:
                connection = self.database()
                events, names = await self.leaderboard_events(connection)
                async with connection.execute("SELECT COUNT(*),COALESCE(SUM(bet_cents),0),COALESCE(SUM(paid_cents > bet_cents),0) FROM (" + events + ") WHERE user_id = ?", (user.id,)) as cursor:
                    rounds, turnover, wins = await cursor.fetchone()
                async with connection.execute("SELECT amount,created_at FROM balances WHERE user_id = ?", (user.id,)) as cursor:
                    balance_row = await cursor.fetchone()
                async with connection.execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE user_id = ?", (user.id,)) as cursor:
                    deposits = (await cursor.fetchone())[0]
                async with connection.execute("SELECT COALESCE(SUM(stars_cents),0) FROM webapp_deposits WHERE user_id = ? AND provider != 'stars' AND status = 'paid'", (user.id,)) as cursor:
                    deposits += (await cursor.fetchone())[0] / 100
                async with connection.execute("SELECT COALESCE(SUM(amount),0) FROM withdrawals WHERE user_id = ? AND status = 'approved'", (user.id,)) as cursor:
                    cashouts = (await cursor.fetchone())[0]
                async with connection.execute("SELECT COALESCE(SUM(quantity),0) FROM webapp_star_withdrawals WHERE user_id = ? AND state = 'completed'", (user.id,)) as cursor:
                    cashouts += (await cursor.fetchone())[0]
                async with connection.execute("SELECT COALESCE(SUM(amount_cents),0) FROM webapp_wallet_events WHERE user_id = ? AND kind = 'bonus'", (user.id,)) as cursor:
                    bonuses = (await cursor.fetchone())[0] / 100
            registration = balance_row[1] if balance_row else None
            days = max(0, (self.clock().date() - datetime.fromisoformat(registration).date()).days) if registration else 0
            label = "день" if days % 10 == 1 and days % 100 != 11 else "дня" if days % 10 in {2, 3, 4} and days % 100 not in {12, 13, 14} else "дней"
            return self.response({"ok": True, "balance": balance_row[0] if balance_row else 0, "turnover": turnover / 100, "winPercent": round(wins / rounds * 100, 2) if rounds else 0, "registrationDate": registration, "daysWithUs": days, "daysWithUsLabel": label, "deposits": deposits, "cashouts": cashouts, "bonuses": bonuses})
        except GameError as error:
            return self.failure(error)

    async def account_history_source(self, connection):
        sources = ["SELECT id,public_id,game,user_id,username,bet_cents,payout_cents,response,created_at FROM webapp_rounds"]
        async with connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cursor:
            tables = {row[0] for row in await cursor.fetchall()}
        for table, game in (("mines_history", "mines"), ("football_history", "foot"), ("basketball_history", "basket"), ("slot_history", "slots"), ("dice_history", "dice")):
            if table not in tables:
                continue
            game_expression = "CASE game WHEN 'bowling' THEN 'bowl' WHEN 'darts' THEN 'darts' ELSE 'dice' END" if table == "dice_history" else "'" + game + "'"
            extra = ", 'minesCount',mines_count,'cellsOpened',opened,'maxSteps',25-mines_count" if game == "mines" else ", 'outcome',player_range" if game in {"foot", "basket", "dice"} else ", 'diceValue',dice_value"
            metadata = "json_object('playedInBot',json('true'),'multiplier',multiplier,'result',CASE WHEN win_amount > bet THEN 'win' WHEN win_amount = bet THEN 'draw' ELSE 'lose' END" + extra + ")"
            sources.append(f"SELECT id,'bot-{game}-'||id,{game_expression},user_id,'',CAST(ROUND(bet*100) AS INTEGER),CAST(ROUND(win_amount*100) AS INTEGER),{metadata},created_at FROM {table}")
        if "crash_games" in tables:
            sources.append("SELECT id,'bot-crash-'||id,'crash',user_id,'',CAST(ROUND(bet*100) AS INTEGER),CASE WHEN won THEN CAST(ROUND(bet*multiplier*100) AS INTEGER) ELSE 0 END,json_object('playedInBot',json('true'),'result',CASE WHEN won THEN 'win' ELSE 'lose' END,'crashPoint',crash_point,'cashoutMult',multiplier),created_at FROM crash_games")
        return " UNION ALL ".join(sources)

    def account_history_filter(self, request, user_id):
        conditions, values = ["user_id = ?"], [user_id]
        label = request.query.get("game", "")
        if label:
            keys = [key for key, value in GAME_LABELS.items() if value == label]
            if not keys:
                raise GameError("Неизвестная игра.")
            conditions.append("game IN (" + ",".join("?" for key in keys) + ")")
            values.extend(keys)
        query = request.query.get("q", "").strip()
        if len(query) > 100:
            raise GameError("Слишком длинный запрос.")
        if query:
            conditions.append("(public_id = ? OR CAST(id AS TEXT) = ? OR substr(created_at,1,10) = ?)")
            values.extend([query, query, query])
        return " WHERE " + " AND ".join(conditions), values

    async def handle_all_rounds(self, request):
        try:
            user = self.validate_user(request)
            page = self.wallet_page(request)
            size = integer(request.query.get("pageSize", "10"), 1, 100)
            condition, values = self.account_history_filter(request, user.id)
            async with self.database_lock:
                connection = self.database()
                source = "(" + await self.account_history_source(connection) + ")"
                async with connection.execute("SELECT COUNT(*) FROM " + source + condition, values) as cursor:
                    total = (await cursor.fetchone())[0]
                async with connection.execute("SELECT id,public_id,game,username,bet_cents,payout_cents,response,created_at FROM " + source + condition + " ORDER BY julianday(created_at) DESC,public_id DESC LIMIT ? OFFSET ?", values + [size, (page - 1) * size]) as cursor:
                    records = await cursor.fetchall()
            rows = []
            for row in records:
                detail = json.loads(row[6])
                detail.pop("balance", None)
                if row[2] == "coinflip" and detail.get("finishAt", 0) > time.time() * 1000:
                    detail.pop("serverSeed", None)
                for name in list(detail):
                    if name.startswith("_"):
                        detail.pop(name)
                rows.append({"id": row[0], "publicId": row[1], "game": GAME_LABELS.get(row[2], row[2]), "user_id": user.id, "username": row[3], "bet": row[4] / 100, "win_amount": row[5] / 100, "result": detail.get("result", "win" if row[5] > row[4] else "draw" if row[5] == row[4] else "lose"), "meta": serialize(detail), "created_at": row[7]})
            return self.response({"ok": True, "rows": rows, "page": page, "total": total, "totalPages": max(1, (total + size - 1) // size)})
        except GameError as error:
            return self.failure(error)

    async def handle_all_round_dates(self, request):
        try:
            user = self.validate_user(request)
            size = integer(request.query.get("pageSize", "10"), 1, 100)
            pages = [integer(value, 1, 1000000) for value in request.query.get("pages", "1").split(",")]
            if len(pages) > 20:
                raise GameError("Слишком много страниц.")
            condition, values = self.account_history_filter(request, user.id)
            dates = {}
            async with self.database_lock:
                connection = self.database()
                source = "(" + await self.account_history_source(connection) + ")"
                for page in pages:
                    async with connection.execute("SELECT created_at FROM " + source + condition + " ORDER BY julianday(created_at) DESC,public_id DESC LIMIT 1 OFFSET ?", values + [(page - 1) * size]) as cursor:
                        row = await cursor.fetchone()
                    if row:
                        dates[str(page)] = row[0]
            return self.response({"ok": True, "dates": dates})
        except GameError as error:
            return self.failure(error)

    async def referral_records(self, connection, user_id):
        async with connection.execute("SELECT r.user_id,r.joined_at,COALESCE(n.username,''),COALESCE(n.full_name,''),r.is_premium FROM referrals r LEFT JOIN usernames n ON n.user_id = r.user_id WHERE r.referrer_id = ? UNION ALL SELECT p.user_id,p.created_at,COALESCE(n.username,''),COALESCE(n.full_name,''),0 FROM pending_referrals p LEFT JOIN usernames n ON n.user_id = p.user_id WHERE p.referrer_id = ? AND NOT EXISTS (SELECT 1 FROM referrals r WHERE r.user_id = p.user_id) ORDER BY 2 DESC,1", (user_id, user_id)) as cursor:
            return await cursor.fetchall()

    async def handle_referrals(self, request):
        try:
            payload = await self.payload(request) if request.method == "POST" else {}
            user = self.validate_user(request, payload)
            section = request.path.split("/")[-1]
            page = self.wallet_page(request)
            runtime = getattr(self, "wallet_runtime", {})
            async with self.database_lock:
                connection = self.database()
                if section == "notifications":
                    if request.method == "POST":
                        if not isinstance(payload.get("enabled"), bool):
                            raise GameError("Некорректная настройка.")
                        await connection.execute("INSERT INTO webapp_preferences(user_id,ref_notifications) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET ref_notifications = excluded.ref_notifications", (user.id, int(payload["enabled"])))
                        await connection.commit()
                    async with connection.execute("SELECT ref_notifications FROM webapp_preferences WHERE user_id = ?", (user.id,)) as cursor:
                        row = await cursor.fetchone()
                    return self.response({"ok": True, "enabled": bool(row[0]) if row else True})
                if section == "top":
                    async with connection.execute("SELECT referrer_id,COUNT(*) FROM (SELECT user_id,referrer_id FROM referrals UNION ALL SELECT p.user_id,p.referrer_id FROM pending_referrals p WHERE NOT EXISTS (SELECT 1 FROM referrals r WHERE r.user_id = p.user_id)) GROUP BY referrer_id ORDER BY COUNT(*) DESC,referrer_id LIMIT 100") as cursor:
                        records = await cursor.fetchall()
                    rows = []
                    for referrer, count in records:
                        async with connection.execute("SELECT full_name FROM usernames WHERE user_id = ?", (referrer,)) as cursor:
                            name = await cursor.fetchone()
                        identity = await self.public_identity(connection, referrer, name[0] if name else "Игрок")
                        if not identity["hidden"]:
                            rows.append({"id": identity["id"], "name": identity["name"], "c": count})
                    return self.response({"ok": True, "rows": rows[:5]})
                records = await self.referral_records(connection, user.id)
                if section == "list":
                    query = request.query.get("q", "").strip().casefold()
                    if len(query) > 100:
                        raise GameError("Слишком длинный запрос.")
                    all_count = len(records)
                    rows = [{"id": row[0], "join_date": row[1], "username": row[2], "name": row[3] or row[2] or "Игрок", "is_premium": bool(row[4])} for row in records if not query or query in " ".join(str(value) for value in row[:4]).casefold()]
                    return self.response({"ok": True, "rows": rows[(page - 1) * 10:page * 10], "page": page, "totalPages": max(1, (len(rows) + 9) // 10), "totalCount": len(rows), "allCount": all_count})
                async with connection.execute("SELECT kind,amount_cents,created_at,referral_id FROM webapp_ref_events WHERE user_id = ? ORDER BY id DESC", (user.id,)) as cursor:
                    journal = await cursor.fetchall()
                if section == "history":
                    period = request.query.get("period", "all")
                    if period not in {"all", "today", "week", "month"}:
                        raise GameError("Неизвестный период.")
                    start = None if period == "all" else self.clock().replace(hour=0, minute=0, second=0, microsecond=0) if period == "today" else self.clock() - timedelta(days=7 if period == "week" else 30)
                    rows = []
                    for kind, cents, created, referral in journal:
                        if start and datetime.fromisoformat(created) < start:
                            continue
                        async with connection.execute("SELECT username,full_name FROM usernames WHERE user_id = ?", (referral,)) as cursor:
                            name = await cursor.fetchone()
                        rows.append({"type": kind, "amount": cents / 100, "date": created, "percent": runtime.get("REF_DEPOSIT_PERCENT", 0.10) * 100 if kind == "deposit" else 50 if kind == "group_loss" else None, "referral_id": referral, "referral_username": name[0] if name else "", "referral_name": name[1] if name else ""})
                    return self.response({"ok": True, "rows": rows[(page - 1) * 10:page * 10], "page": page, "totalPages": max(1, (len(rows) + 9) // 10)})
                async with connection.execute("SELECT signup_earned,deposit_earned,group_earned,frozen FROM ref_balance WHERE user_id = ?", (user.id,)) as cursor:
                    balance = await cursor.fetchone() or (0, 0, 0, 0)
                deposits = [row[1] / 100 for row in journal if row[0] == "deposit"]
                signups = [row[1] / 100 for row in journal if row[0] == "signup"]
                group_losses = [row[1] / 100 for row in journal if row[0] == "group_loss"]
                week = sum(row[1] for row in journal if datetime.fromisoformat(row[2]) >= self.clock() - timedelta(days=7)) / 100
                async with connection.execute("SELECT signup_cents,deposit_cents,captured_at FROM webapp_ref_baselines WHERE user_id = ?", (user.id,)) as cursor:
                    baseline = await cursor.fetchone() or (0, 0, None)
                signup_total = round(sum(signups) + baseline[0] / 100, 2)
                deposit_total = round(sum(deposits) + baseline[1] / 100, 2)
                group_total = round(sum(group_losses), 2)
                return self.response({"ok": True, "refCount": len(records), "totalEarnings": round(signup_total + deposit_total + group_total, 2), "signupBase": runtime.get("REF_SIGNUP_BASE", 2.5), "signupPremium": runtime.get("REF_SIGNUP_PREMIUM", 5), "signupEarnings": signup_total, "signupCount": len(signups), "avgSignup": sum(signups) / len(signups) if signups else 0, "maxSignup": max(signups, default=0), "depositEarnings": deposit_total, "gameEarnings": group_total, "depositPercent": runtime.get("REF_DEPOSIT_PERCENT", 0.10) * 100, "lossPercent": 50, "weekEarnings": week, "totalCount": len(journal), "depositCount": len(deposits), "gameCount": len(group_losses), "avgDeposit": sum(deposits) / len(deposits) if deposits else 0, "avgGame": sum(group_losses) / len(group_losses) if group_losses else 0, "maxDeposit": max(deposits, default=0), "maxGame": max(group_losses, default=0), "availableBalance": round(balance[0] + balance[1] + balance[2], 2), "frozen": bool(balance[3]), "minimumWithdraw": runtime.get("REF_MIN_WITHDRAW", 10), "historySince": baseline[2], "openingBalance": (baseline[0] + baseline[1]) / 100})
        except GameError as error:
            return self.failure(error)

    async def handle_referral_withdraw(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            key, signature = self.request_identity(request, payload)
            runtime = getattr(self, "wallet_runtime", {})
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    existing = await self.load_receipt(connection, user.id, key, signature)
                    if existing:
                        await connection.rollback()
                        return self.response(existing)
                    records = await self.referral_records(connection, user.id)
                    async with connection.execute("SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND deposited = 1", (user.id,)) as cursor:
                        deposited = (await cursor.fetchone())[0]
                    if len(records) > runtime.get("REF_BASE_LIMIT", 2) + runtime.get("REF_LIMIT_PER_DEPOSIT", 2) * deposited:
                        raise GameError("Заработок с приглашений заморожен.")
                    async with connection.execute("SELECT signup_earned + deposit_earned + group_earned FROM ref_balance WHERE user_id = ?", (user.id,)) as cursor:
                        row = await cursor.fetchone()
                    cents = round(row[0] * 100) if row else 0
                    if cents < runtime.get("REF_MIN_WITHDRAW", 10) * 100:
                        raise GameError("Недостаточно средств на реферальном балансе.")
                    await connection.execute("UPDATE ref_balance SET signup_earned = 0,deposit_earned = 0,group_earned = 0 WHERE user_id = ?", (user.id,))
                    await self.wallet_credit(connection, user.id, cents, "referral_withdraw", "referral:" + str(user.id) + ":" + key)
                    result = {"ok": True, "creditedAmount": cents / 100, "balance": await self.balance(connection, user.id)}
                    await self.save_receipt(connection, user.id, key, signature, result)
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
            return self.response(result)
        except GameError as error:
            return self.failure(error)
'''

# ==================== blackjack_pvp.py ====================
_SOURCES['blackjack_pvp'] = r'''import hashlib
import json
import re
import secrets
import time

from games_backend import GameError
from game_rules import deck_for, hand_total


BLACKJACK_TURN_SECONDS = 300


class BlackjackPvpMixin:
    def register_blackjack_pvp(self, application):
        application.router.add_get("/api/pvp/blackjack/state", self.handle_blackjack_pvp_state)
        for action in ("hit", "stand", "double"):
            application.router.add_post(f"/api/pvp/blackjack/{action}", self.handle_pvp_action)

    def prepare_blackjack_pvp(self, state):
        seed = secrets.token_hex(32)
        state.update({"_seed": seed, "seedHash": hashlib.sha256(seed.encode()).hexdigest(), "creatorVersion": 0, "opponentVersion": 0})

    def deal_blackjack_pvp(self, state):
        deck = deck_for(state["_seed"], state["roomId"])
        state.update({"status": "playing", "_deck": deck, "_cursor": 4, "creatorCards": [deck[0], deck[2]], "opponentCards": [deck[1], deck[3]], "_creatorBetCents": state["_betCents"], "_opponentBetCents": state["_betCents"]})
        for role in ("creator", "opponent"):
            total = hand_total(state[role + "Cards"])
            state.update({role + "Result": total, role + "Busted": False, role + "Doubled": False, role + "Done": total == 21, role + "Deadline": time.time() + BLACKJACK_TURN_SECONDS, role + "AvatarUrl": "/api/avatar/" + str(state[role + "Id"])})

    def blackjack_pvp_projection(self, response, state, user_id):
        role = "creator" if state["creatorId"] == user_id else "opponent" if state.get("opponentId") == user_id else None
        response.update({"youAre": role, "canAct": role is not None and state["status"] == "playing" and not state[role + "Done"], "version": state.get((role or "creator") + "Version", 0)})
        return response

    async def finish_blackjack_pvp(self, connection, state):
        if state["status"] != "playing" or not state["creatorDone"] or not state["opponentDone"]:
            return
        scores = [state[role + "Result"] if state[role + "Result"] <= 21 else 0 for role in ("creator", "opponent")]
        draw = scores[0] == scores[1]
        bank = state["_creatorBetCents"] + state["_opponentBetCents"]
        winner = None if draw else state["creatorId"] if scores[0] > scores[1] else state["opponentId"]
        paid = bank * 99 // 100 if not draw else 0
        if draw:
            for role in ("creator", "opponent"):
                await self.credit(connection, state[role + "Id"], state["_" + role + "BetCents"])
        else:
            await self.credit(connection, winner, paid)
        state.update({"status": "finished", "isDraw": draw, "winnerId": winner, "winAmount": paid / 100 if not draw else state["betAmount"], "feeAmount": 0 if draw else (bank - paid) / 100, "commissionPercent": 1, "totalBank": bank / 100, "creatorBetAmount": state["_creatorBetCents"] / 100, "opponentBetAmount": state["_opponentBetCents"] / 100, "creatorRefund": state["_creatorBetCents"] / 100 if draw else 0, "opponentRefund": state["_opponentBetCents"] / 100 if draw else 0, "serverSeed": state["_seed"], "finishedAt": self.clock().isoformat()})
        await self.save_pvp(connection, state)

    async def advance_blackjack_pvp(self, connection):
        now = time.time()
        async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE game = 'blackjack' AND status = 'playing' AND ((json_extract(data,'$.creatorDone') = 0 AND json_extract(data,'$.creatorDeadline') <= ?) OR (json_extract(data,'$.opponentDone') = 0 AND json_extract(data,'$.opponentDeadline') <= ?))", (now, now)) as cursor:
            states = [json.loads(row[0]) for row in await cursor.fetchall()]
        for state in states:
            for role in ("creator", "opponent"):
                if not state[role + "Done"] and state[role + "Deadline"] <= now:
                    state[role + "Done"] = True
                    state[role + "TimedOut"] = True
                    state[role + "Version"] += 1
            await self.save_pvp(connection, state)
            await self.finish_blackjack_pvp(connection, state)

    async def handle_blackjack_pvp_state(self, request):
        try:
            user = self.validate_user(request)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    await self.advance_blackjack_pvp(connection)
                    async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ? AND game = 'blackjack'", (request.query.get("roomId", ""),)) as cursor:
                        row = await cursor.fetchone()
                    if row is None:
                        raise GameError("Комната не найдена.", 404)
                    state = json.loads(row[0])
                    response = await self.pvp_response(connection, state, user.id)
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)

    async def handle_blackjack_pvp_move(self, request, payload, user, key, signature):
        try:
            action = request.path.split("/")[-1]
            if not isinstance(payload.get("roomId"), str) or not re.fullmatch(r"P[A-F0-9]{16}", payload["roomId"]):
                raise GameError("Некорректный идентификатор комнаты.")
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    replay = await self.load_receipt(connection, user.id, key, signature)
                    if replay:
                        await connection.commit()
                        return self.response(replay)
                    await self.advance_blackjack_pvp(connection)
                    async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ? AND game = 'blackjack'", (payload.get("roomId", ""),)) as cursor:
                        row = await cursor.fetchone()
                    if row is None:
                        raise GameError("Комната не найдена.", 404)
                    state = json.loads(row[0])
                    role = "creator" if state["creatorId"] == user.id else "opponent" if state.get("opponentId") == user.id else None
                    if role is None:
                        raise GameError("Нет доступа к чужой руке.", 403)
                    if state["status"] != "playing" or state[role + "Done"]:
                        raise GameError("Рука уже завершена.", 409)
                    if isinstance(payload.get("version"), bool) or payload.get("version") != state[role + "Version"]:
                        raise GameError("Состояние руки изменилось. Обновите игру.", 409)
                    cards = state[role + "Cards"]
                    if action == "double":
                        if len(cards) != 2 or state[role + "Doubled"]:
                            raise GameError("Удвоение недоступно.")
                        await self.debit(connection, user.id, state["_betCents"])
                        state["_" + role + "BetCents"] += state["_betCents"]
                        state[role + "Doubled"] = True
                    if action in {"hit", "double"}:
                        if state["_cursor"] >= len(state["_deck"]):
                            raise GameError("В колоде закончились карты.", 409)
                        cards.append(state["_deck"][state["_cursor"]])
                        state["_cursor"] += 1
                        total = hand_total(cards)
                        state[role + "Result"] = total
                        state[role + "Busted"] = total > 21
                        state[role + "Done"] = total >= 21 or action == "double"
                    else:
                        state[role + "Done"] = True
                    state[role + "Version"] += 1
                    state[role + "Deadline"] = time.time() + BLACKJACK_TURN_SECONDS
                    await self.save_pvp(connection, state)
                    await self.finish_blackjack_pvp(connection, state)
                    response = await self.pvp_response(connection, state, user.id)
                    await self.save_receipt(connection, user.id, key, signature, response)
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)
'''

# ==================== checks_backend.py ====================
_SOURCES['checks_backend'] = r'''import asyncio
import hashlib
import hmac
import json
import logging
import re
import secrets
import time
from datetime import datetime, timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent

from games_backend import GameError, integer, money_cents, serialize


CHECK_LIMITS = {"minAmount": 0.1, "maxAmount": 1000000, "minActivations": 2, "maxActivations": 100}


class ChecksMixin:
    def register_checks(self, application):
        for section in ("overview", "my", "detail", "settings", "history"):
            application.router.add_get("/api/checks/" + section, self.handle_checks_read)
        for action in ("start", "answer", "replay"):
            application.router.add_post("/api/checks/captcha/" + action, self.handle_check_captcha)
        for action in ("create", "activate", "cancel", "edit_settings", "notifications"):
            application.router.add_post("/api/checks/" + action, self.handle_checks_write)

    async def initialize_checks(self):
        async with self.database_lock:
            connection = self.database()
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_checks(code TEXT PRIMARY KEY,creator_id INTEGER NOT NULL,amount_cents INTEGER NOT NULL,activations INTEGER NOT NULL,remaining INTEGER NOT NULL,type TEXT NOT NULL,target_username TEXT NOT NULL DEFAULT '',status TEXT NOT NULL DEFAULT 'active',created_at TEXT NOT NULL,expires_at INTEGER NOT NULL,settings TEXT NOT NULL)")
            await connection.execute("CREATE INDEX IF NOT EXISTS idx_webapp_checks_creator ON webapp_checks(creator_id,created_at)")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_check_claims(code TEXT NOT NULL,user_id INTEGER NOT NULL,amount_cents INTEGER NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(code,user_id))")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_check_attempts(user_id INTEGER PRIMARY KEY,started_at INTEGER NOT NULL,attempts INTEGER NOT NULL)")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_check_captchas(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL,code TEXT NOT NULL,task TEXT NOT NULL,expires_at INTEGER NOT NULL,solved INTEGER NOT NULL DEFAULT 0,attempts INTEGER NOT NULL DEFAULT 0,replays INTEGER NOT NULL DEFAULT 2)")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_check_wagers(code TEXT NOT NULL,user_id INTEGER NOT NULL,turnover_start INTEGER NOT NULL,games_start INTEGER NOT NULL,amount_cents INTEGER NOT NULL,games INTEGER NOT NULL,PRIMARY KEY(code,user_id))")
            await connection.commit()
        self.checks_expiry_task = asyncio.create_task(self.checks_expiry_loop())

    async def checks_expiry_loop(self):
        while True:
            await asyncio.sleep(30)
            try:
                async with self.database_lock:
                    connection = self.database()
                    try:
                        await connection.execute("BEGIN IMMEDIATE")
                        await self.expire_checks(connection)
                        await connection.execute("DELETE FROM webapp_check_captchas WHERE expires_at < ?", (int(time.time()),))
                        await connection.commit()
                    except BaseException:
                        await connection.rollback()
                        raise
            except Exception:
                logging.error("Check expiry transaction failed; retrying next cycle")

    def check_password(self, password, salt=None):
        if not isinstance(password, str) or len(password) > 64:
            raise GameError("Пароль должен содержать не более 64 символов.")
        if not password:
            return ""
        salt = salt or secrets.token_hex(16)
        return salt + ":" + hashlib.scrypt(password.encode(), salt=salt.encode(), n=16384, r=8, p=1).hex()

    def check_settings(self, payload, previous=None):
        settings = dict(previous or {"premiumOnly": False, "verifiedOnly": False, "referralOnly": False, "passwordHash": ""})
        for field in ("premiumOnly", "verifiedOnly", "referralOnly"):
            if field in payload:
                if not isinstance(payload[field], bool):
                    raise GameError("Некорректная настройка чека.")
                settings[field] = payload[field]
        if payload.get("removePassword") is True:
            settings["passwordHash"] = ""
        if payload.get("removeWager") is True:
            settings.pop("wagerAmount", None)
            settings.pop("wagerGames", None)
        for kind in ("Deposit", "Turnover", "Withdraw"):
            if payload.get("removeReq" + kind) is True:
                settings.pop("req" + kind, None)
        if "password" in payload:
            settings["passwordHash"] = self.check_password(payload["password"] or "")
        if "captchaLevel" in payload:
            settings["captchaLevel"] = integer(payload["captchaLevel"], 0, 2)
        else:
            settings.setdefault("captchaLevel", 0)
        if "wagerAmount" in payload or "wagerGames" in payload:
            amount, games = payload.get("wagerAmount"), payload.get("wagerGames")
            if not amount and not games:
                settings.pop("wagerAmount", None)
                settings.pop("wagerGames", None)
            else:
                settings["wagerAmount"] = money_cents(amount, 1, 100000000)
                settings["wagerGames"] = integer(games, 1, 1000000)
        for kind in ("Deposit", "Turnover", "Withdraw"):
            amount_key, period_key = "req" + kind + "Amount", "req" + kind + "Period"
            if amount_key in payload:
                if payload[amount_key] in (None, 0, ""):
                    settings.pop("req" + kind, None)
                else:
                    period = payload.get(period_key, "all")
                    if not isinstance(period, str) or period not in {"day", "week", "month", "3months", "6months", "all"}:
                        raise GameError("Неизвестный период условия чека.")
                    settings["req" + kind] = {"amount": money_cents(payload[amount_key], 1, 100000000) / 100, "period": period}
        return settings

    async def check_row(self, connection, code):
        if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{24,64}", code):
            raise GameError("Чек не найден.", 404)
        async with connection.execute("SELECT code,creator_id,amount_cents,activations,remaining,type,target_username,status,created_at,expires_at,settings FROM webapp_checks WHERE code = ?", (code,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            raise GameError("Чек не найден.", 404)
        result = dict(zip(("code", "creator_id", "amount_cents", "activations", "remaining", "type", "target_username", "status", "created_at", "expires_at", "settings"), row))
        result["settings"] = json.loads(result["settings"])
        return result

    async def expire_checks(self, connection):
        async with connection.execute("SELECT code,creator_id,amount_cents,remaining FROM webapp_checks WHERE status = 'active' AND expires_at <= ?", (int(time.time()),)) as cursor:
            expired = await cursor.fetchall()
        for code, creator, amount, remaining in expired:
            await connection.execute("UPDATE webapp_checks SET status = 'expired',remaining = 0 WHERE code = ? AND status = 'active'", (code,))
            await self.wallet_credit(connection, creator, amount * remaining, "check_refund", "check-expiry:" + code)

    async def check_detail(self, connection, check, user_id):
        settings = check["settings"]
        async with connection.execute("SELECT 1 FROM webapp_check_claims WHERE code = ? AND user_id = ?", (check["code"], user_id)) as cursor:
            claimed = await cursor.fetchone() is not None
        bot_username = getattr(self, "wallet_runtime", {}).get("BOT_USERNAME", "mjrstarsbot")
        detail = {"ok": True, "code": check["code"], "checkCode": check["code"], "checkType": check["type"], "amount": check["amount_cents"] / 100, "maxActivations": check["activations"], "activationsLeft": check["remaining"], "isMulti": check["type"] == "multi", "targetUsername": check["target_username"], "status": check["status"], "isCreator": user_id == check["creator_id"], "alreadyActivated": claimed, "createdAt": check["created_at"], "expiresAt": check["expires_at"], "expireHours": max(1, round((check["expires_at"] - datetime.fromisoformat(check["created_at"]).timestamp()) / 3600)), "timeLeftSeconds": max(0, check["expires_at"] - int(time.time())), "heldAmount": check["remaining"] * check["amount_cents"] / 100 if check["status"] == "active" else 0, "link": f"https://t.me/{bot_username}?startapp=check_{check['code']}", "hasPassword": bool(settings["passwordHash"]), "passwordRequired": bool(settings["passwordHash"]), "premiumOnly": settings["premiumOnly"], "verifiedOnly": settings["verifiedOnly"], "referralOnly": settings["referralOnly"], "captchaLevel": settings.get("captchaLevel", 0), "captchaFloor": 0, "hasWager": bool(settings.get("wagerAmount")), "wagerAmount": settings.get("wagerAmount", 0) / 100, "wagerGames": settings.get("wagerGames", 0), "reqPeriods": [["day", "За день"], ["week", "За неделю"], ["month", "За месяц"], ["3months", "За 3 месяца"], ["6months", "За полгода"], ["all", "За всё время"]], "wagerGamesText": "Все завершённые игры"}
        async with connection.execute("SELECT full_name FROM usernames WHERE user_id = ?", (check["creator_id"],)) as cursor:
            row = await cursor.fetchone()
        creator = await self.public_identity(connection, check["creator_id"], row[0] if row else "Игрок")
        detail.update({"creatorName": creator["name"], "creatorId": creator["id"], "canActivate": check["status"] == "active" and check["creator_id"] != user_id and not claimed, "blockedReason": "Вы уже активировали этот чек." if claimed else "Нельзя активировать собственный чек." if check["creator_id"] == user_id else "Чек недоступен."})
        for kind in ("Deposit", "Turnover", "Withdraw"):
            detail["req" + kind] = settings.get("req" + kind)
        return detail

    async def checks_overview(self, connection, user_id):
        async with connection.execute("SELECT COUNT(*),COALESCE(SUM(amount_cents*activations),0) FROM webapp_checks WHERE creator_id = ?", (user_id,)) as cursor:
            created, reserved = await cursor.fetchone()
        async with connection.execute("SELECT COUNT(*),COALESCE(SUM(amount_cents),0) FROM webapp_check_claims WHERE user_id = ?", (user_id,)) as cursor:
            activated, received = await cursor.fetchone()
        async with connection.execute("SELECT COALESCE(SUM(c.amount_cents),0) FROM webapp_check_claims c JOIN webapp_checks k ON k.code = c.code WHERE k.creator_id = ?", (user_id,)) as cursor:
            sent = (await cursor.fetchone())[0]
        async with connection.execute("SELECT check_notifications FROM webapp_preferences WHERE user_id = ?", (user_id,)) as cursor:
            pref = await cursor.fetchone()
        result = {"ok": True, "createdChecks": created, "activatedChecks": activated, "totalSent": sent / 100, "totalReceived": received / 100, "notificationsEnabled": bool(pref[0]) if pref else True, "limits": CHECK_LIMITS, "captcha": {"enabled": True, "floor": 0, "default": 0}, "advancedSettings": True}
        daily = []
        for offset in range(6, -1, -1):
            day = (self.clock() - timedelta(days=offset)).date().isoformat()
            async with connection.execute("SELECT COALESCE(SUM(CASE WHEN k.creator_id = ? THEN c.amount_cents ELSE 0 END),0),COALESCE(SUM(CASE WHEN c.user_id = ? THEN c.amount_cents ELSE 0 END),0) FROM webapp_check_claims c JOIN webapp_checks k ON k.code = c.code WHERE substr(c.created_at,1,10) = ?", (user_id, user_id, day)) as cursor:
                outgoing, incoming = await cursor.fetchone()
            daily.append({"sent": outgoing / 100, "received": incoming / 100})
        result.update({"daily": daily, "weekSent": sum(row["sent"] for row in daily), "weekReceived": sum(row["received"] for row in daily)})
        return result

    async def handle_checks_read(self, request):
        try:
            user = self.validate_user(request)
            section = request.path.split("/")[-1]
            page = self.wallet_page(request, zero=True)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    await self.expire_checks(connection)
                    if section == "overview":
                        result = await self.checks_overview(connection, user.id)
                    elif section in {"detail", "settings"}:
                        check = await self.check_row(connection, request.query.get("code", ""))
                        if section == "settings" and check["creator_id"] != user.id:
                            raise GameError("forbidden", 403)
                        result = await self.check_detail(connection, check, user.id)
                    elif section == "my":
                        async with connection.execute("SELECT code FROM webapp_checks WHERE creator_id = ? AND status = 'active' ORDER BY created_at DESC,code LIMIT 6 OFFSET ?", (user.id, page * 6)) as cursor:
                            codes = await cursor.fetchall()
                        async with connection.execute("SELECT COUNT(*) FROM webapp_checks WHERE creator_id = ? AND status = 'active'", (user.id,)) as cursor:
                            total = (await cursor.fetchone())[0]
                        rows = []
                        for code, in codes:
                            check = await self.check_row(connection, code)
                            rows.append({"check_code": code, "amount": check["amount_cents"] / 100, "check_type": check["type"], "is_multi": check["type"] == "multi", "target_username": check["target_username"]})
                        result = {"ok": True, "rows": rows, "page": page, "totalPages": max(1, (total + 5) // 6)}
                    else:
                        scope = request.query.get("scope", "all")
                        if scope not in {"all", "created", "activated"}:
                            raise GameError("Неизвестный фильтр.")
                        source = "SELECT 'created' AS type,amount_cents*activations AS amount,created_at,target_username,code AS check_code,creator_id AS user_id FROM webapp_checks UNION ALL SELECT 'activated',c.amount_cents,c.created_at,'',c.code,c.user_id FROM webapp_check_claims c"
                        condition, values = " WHERE user_id = ?", [user.id]
                        if scope != "all":
                            condition += " AND type = ?"
                            values.append(scope)
                        async with connection.execute("SELECT COUNT(*) FROM (" + source + ")" + condition, values) as cursor:
                            total = (await cursor.fetchone())[0]
                        async with connection.execute("SELECT type,amount,created_at,target_username,check_code FROM (" + source + ")" + condition + " ORDER BY created_at DESC,check_code LIMIT 10 OFFSET ?", values + [page * 10]) as cursor:
                            rows = [{"type": row[0], "amount": row[1] / 100, "time_readable": datetime.fromisoformat(row[2]).strftime("%d.%m.%Y %H:%M"), "target_username": row[3], "check_code": row[4]} for row in await cursor.fetchall()]
                        result = {"ok": True, "rows": rows, "page": page, "totalPages": max(1, (total + 9) // 10)}
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
            return self.response(result)
        except GameError as error:
            return self.failure(error)

    async def check_attempt(self, user_id):
        async with self.database_lock:
            connection = self.database()
            now = int(time.time())
            await connection.execute("INSERT INTO webapp_check_attempts(user_id,started_at,attempts) VALUES (?,?,1) ON CONFLICT(user_id) DO UPDATE SET started_at = CASE WHEN started_at < ? THEN excluded.started_at ELSE started_at END,attempts = CASE WHEN started_at < ? THEN 1 ELSE attempts + 1 END", (user_id, now, now - 60, now - 60))
            async with connection.execute("SELECT attempts FROM webapp_check_attempts WHERE user_id = ?", (user_id,)) as cursor:
                attempts = (await cursor.fetchone())[0]
            await connection.commit()
        if attempts > 10:
            raise GameError("Слишком много попыток. Подождите минуту.", 429)

    async def handle_checks_write(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            action = request.path.split("/")[-1]
            key, signature = self.request_identity(request, payload)
            if action == "activate":
                await self.check_attempt(user.id)
            notifications = []
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    await self.expire_checks(connection)
                    existing = await self.load_receipt(connection, user.id, key, signature)
                    if existing:
                        await connection.commit()
                        return self.response(existing)
                    if action == "notifications":
                        if not isinstance(payload.get("enabled"), bool):
                            raise GameError("Некорректная настройка.")
                        await connection.execute("INSERT INTO webapp_preferences(user_id,check_notifications) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET check_notifications = excluded.check_notifications", (user.id, int(payload["enabled"])))
                        result = {"ok": True, "enabled": payload["enabled"]}
                    elif action == "create":
                        check_type = payload.get("type", "normal")
                        if not isinstance(check_type, str) or check_type not in {"normal", "personal", "multi"}:
                            raise GameError("Неизвестный тип чека.")
                        amount = money_cents(payload.get("amount"), 10, 100000000)
                        activations = integer(payload.get("activations", 2), 2, 100) if check_type == "multi" else 1
                        hours = integer(payload.get("expireHours") or 48, 1, 720)
                        target = payload.get("targetUsername", "")
                        if check_type == "personal":
                            if not isinstance(target, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", target):
                                raise GameError("Укажите Telegram username получателя.")
                        else:
                            target = ""
                        settings = self.check_settings(payload)
                        code = secrets.token_urlsafe(24)
                        await self.ensure_check_wager(connection, user.id)
                        cursor = await connection.execute("UPDATE balances SET amount = ROUND(amount - ?,2) WHERE user_id = ? AND ROUND(amount*100) >= ?", (amount * activations / 100, user.id, amount * activations))
                        if cursor.rowcount != 1:
                            raise GameError("Недостаточно средств на балансе.")
                        await connection.execute("INSERT INTO webapp_checks(code,creator_id,amount_cents,activations,remaining,type,target_username,created_at,expires_at,settings) VALUES (?,?,?,?,?,?,?,?,?,?)", (code, user.id, amount, activations, activations, check_type, target, self.clock().isoformat(), int(time.time()) + hours * 3600, serialize(settings)))
                        result = await self.check_detail(connection, await self.check_row(connection, code), user.id)
                        result["balance"] = await self.balance(connection, user.id)
                        notifications.append((user.id, f"Создан чек MajorStars на {amount * activations / 100:g} Stars.\n{result['link']}"))
                    else:
                        check = await self.check_row(connection, payload.get("code", ""))
                        if check["status"] != "active":
                            raise GameError("Этот чек уже активирован, отменён или истёк.", 409)
                        if action in {"cancel", "edit_settings"} and check["creator_id"] != user.id:
                            raise GameError("Изменять чек может только создатель.", 403)
                        if action == "cancel":
                            refund = check["amount_cents"] * check["remaining"]
                            await connection.execute("UPDATE webapp_checks SET status = 'cancelled',remaining = 0 WHERE code = ?", (check["code"],))
                            await self.wallet_credit(connection, user.id, refund, "check_refund", "check-cancel:" + check["code"])
                            result = {"ok": True, "refundedAmount": refund / 100}
                        elif action == "edit_settings":
                            settings = self.check_settings(payload, check["settings"])
                            expires = check["expires_at"]
                            if "expireHours" in payload:
                                expires = int(datetime.fromisoformat(check["created_at"]).timestamp()) + integer(payload["expireHours"], 1, 720) * 3600
                                if expires <= time.time():
                                    raise GameError("Укажите срок, который ещё не истёк.")
                            await connection.execute("UPDATE webapp_checks SET settings = ?,expires_at = ? WHERE code = ?", (serialize(settings), expires, check["code"]))
                            result = {"ok": True}
                        else:
                            if user.id == check["creator_id"]:
                                raise GameError("Нельзя активировать собственный чек.")
                            async with connection.execute("SELECT 1 FROM webapp_check_claims WHERE code = ? AND user_id = ?", (check["code"], user.id)) as cursor:
                                if await cursor.fetchone():
                                    raise GameError("Вы уже активировали этот чек.", 409)
                            if check["target_username"] and (user.username or "").casefold() != check["target_username"].casefold():
                                raise GameError("Этот чек предназначен другому пользователю.", 403)
                            settings = check["settings"]
                            if settings["premiumOnly"] and not user.is_premium:
                                raise GameError("Чек доступен только пользователям Telegram Premium.", 403)
                            if settings["verifiedOnly"]:
                                async with connection.execute("SELECT created_at FROM balances WHERE user_id = ?", (user.id,)) as cursor:
                                    registration = await cursor.fetchone()
                                if registration and registration[0] and datetime.fromisoformat(registration[0]) < datetime.fromisoformat(check["created_at"]):
                                    raise GameError("Чек доступен только новым пользователям бота.", 403)
                            if settings["passwordHash"]:
                                password = payload.get("password", "")
                                salt = settings["passwordHash"].split(":")[0]
                                if not hmac.compare_digest(self.check_password(password, salt), settings["passwordHash"]):
                                    raise GameError("Неверный пароль чека.", 403)
                            level = settings.get("captchaLevel", 0)
                            if level:
                                async with connection.execute("SELECT solved FROM webapp_check_captchas WHERE token = ? AND user_id = ? AND code = ? AND expires_at > ?", (payload.get("captchaToken", ""), user.id, check["code"], int(time.time()))) as cursor:
                                    captcha = await cursor.fetchone()
                                if captcha is None or not captcha[0]:
                                    raise GameError("Сначала пройдите капчу чека.", 403)
                            await self.check_activation_requirements(connection, user.id, settings)
                            if settings.get("wagerAmount"):
                                turnover, games = await self.check_game_totals(connection, user.id)
                                await connection.execute("INSERT INTO webapp_check_wagers(code,user_id,turnover_start,games_start,amount_cents,games) VALUES (?,?,?,?,?,?)", (check["code"], user.id, turnover, games, settings["wagerAmount"], settings["wagerGames"]))
                            if settings["referralOnly"]:
                                async with connection.execute("SELECT referrer_id FROM referrals WHERE user_id = ? UNION ALL SELECT referrer_id FROM pending_referrals WHERE user_id = ?", (user.id, user.id)) as cursor:
                                    referrers = await cursor.fetchall()
                                if any(row[0] != check["creator_id"] for row in referrers):
                                    raise GameError("Чек доступен только рефералам создателя.", 403)
                                if not referrers:
                                    await connection.execute("INSERT INTO pending_referrals(user_id,referrer_id,created_at) VALUES (?,?,?)", (user.id, check["creator_id"], self.clock().isoformat()))
                            await connection.execute("INSERT INTO webapp_check_claims(code,user_id,amount_cents,created_at) VALUES (?,?,?,?)", (check["code"], user.id, check["amount_cents"], self.clock().isoformat()))
                            await connection.execute("UPDATE webapp_checks SET remaining = remaining - 1,status = CASE WHEN remaining = 1 THEN 'used' ELSE status END WHERE code = ? AND remaining > 0", (check["code"],))
                            await self.wallet_credit(connection, user.id, check["amount_cents"], "check", "check:" + check["code"] + ":" + str(user.id))
                            result = {"ok": True, "amount": check["amount_cents"] / 100, "creditedAmount": check["amount_cents"] / 100}
                            notifications.extend([(check["creator_id"], f"Ваш чек MajorStars активирован: {check['amount_cents'] / 100:g} Stars."), (user.id, f"Вы получили {check['amount_cents'] / 100:g} Stars по чеку MajorStars.")])
                        result["balance"] = await self.balance(connection, user.id)
                    await self.save_receipt(connection, user.id, key, signature, result)
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
            bot = getattr(self, "telegram_bot", None)
            if bot:
                for recipient, text in notifications:
                    async with self.database_lock:
                        async with self.database().execute("SELECT check_notifications FROM webapp_preferences WHERE user_id = ?", (recipient,)) as cursor:
                            pref = await cursor.fetchone()
                    if pref is None or pref[0]:
                        try:
                            await bot.send_message(recipient, text, parse_mode=None)
                        except Exception:
                            logging.warning("Check notification delivery failed for user %s", recipient)
            return self.response(result)
        except GameError as error:
            return self.failure(error)

    async def check_game_totals(self, connection, user_id):
        events, names = await self.leaderboard_events(connection)
        async with connection.execute("SELECT COALESCE(SUM(bet_cents),0),COUNT(*) FROM (" + events + ") WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

    async def ensure_check_wager(self, connection, user_id):
        async with connection.execute("SELECT turnover_start,games_start,amount_cents,games FROM webapp_check_wagers WHERE user_id = ?", (user_id,)) as cursor:
            wagers = await cursor.fetchall()
        if not wagers:
            return
        turnover, games = await self.check_game_totals(connection, user_id)
        if any(turnover - start < amount or games - count < required for start, count, amount, required in wagers):
            raise GameError("Сначала выполните отыгрыш полученных чеков: нужную сумму ставок и количество завершённых игр.", 403)

    async def check_activation_requirements(self, connection, user_id, settings):
        for kind in ("Deposit", "Turnover", "Withdraw"):
            requirement = settings.get("req" + kind)
            if not requirement:
                continue
            period = requirement["period"]
            days = {"day": 1, "week": 7, "month": 30, "3months": 90, "6months": 180}.get(period)
            since = (self.clock() - timedelta(days=days)).isoformat() if days else "0001-01-01"
            if kind == "Turnover":
                source, names = await self.leaderboard_events(connection)
                query = "SELECT COALESCE(SUM(bet_cents),0) FROM (" + source + ") WHERE user_id = ? AND julianday(created_at) >= julianday(?)"
                values = [user_id, since]
            elif kind == "Deposit":
                query = "SELECT COALESCE(SUM(cents),0) FROM (SELECT user_id,amount*100 AS cents,created_at FROM payments UNION ALL SELECT user_id,stars_cents,COALESCE(paid_at,created_at) FROM webapp_deposits WHERE provider != 'stars' AND status = 'paid') WHERE user_id = ? AND julianday(created_at) >= julianday(?)"
                values = [user_id, since]
            else:
                query = "SELECT COALESCE(SUM(cents),0) FROM (SELECT user_id,ROUND(amount*100) AS cents,created_at FROM withdrawals WHERE status = 'approved' UNION ALL SELECT user_id,quantity*100,created_at FROM webapp_star_withdrawals WHERE state = 'completed') WHERE user_id = ? AND julianday(created_at) >= julianday(?)"
                values = [user_id, since]
            async with connection.execute(query, values) as cursor:
                amount = (await cursor.fetchone())[0]
            if amount < round(requirement["amount"] * 100):
                label = {"Deposit": "депозитам", "Turnover": "обороту", "Withdraw": "выводам"}[kind]
                raise GameError(f"Не выполнено условие по {label}: требуется {requirement['amount']:g} Stars.", 403)

    def captcha_task(self, level, token, attempts=3, replays=2):
        sequence = list(range(6))
        secrets.SystemRandom().shuffle(sequence)
        return {"ok": True, "token": token, "chests": 6, "seq": sequence[:3 if level == 1 else 4], "level": level, "levelName": "Лёгкая" if level == 1 else "Сложная", "attempts": attempts, "replaysLeft": replays, "showMs": 600 if level == 1 else 400, "gapMs": 200, "swaps": [] if level == 1 else [[0, 3], [1, 5]], "swapMs": 640}

    async def handle_check_captcha(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            action = request.path.split("/")[-1]
            await self.check_attempt(user.id)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    check = await self.check_row(connection, payload.get("code", ""))
                    if check["status"] != "active" or check["expires_at"] <= time.time():
                        raise GameError("Чек недоступен.", 409)
                    level = check["settings"]["captchaLevel"]
                    if not level:
                        result = {"ok": True, "notNeeded": True}
                    elif action == "start":
                        token = secrets.token_urlsafe(32)
                        task = self.captcha_task(level, token)
                        await connection.execute("DELETE FROM webapp_check_captchas WHERE user_id = ? AND code = ?", (user.id, check["code"]))
                        await connection.execute("INSERT INTO webapp_check_captchas(token,user_id,code,task,expires_at) VALUES (?,?,?,?,?)", (token, user.id, check["code"], serialize(task), int(time.time()) + 300))
                        result = task
                    else:
                        async with connection.execute("SELECT task,expires_at,solved,attempts,replays FROM webapp_check_captchas WHERE token = ? AND user_id = ? AND code = ?", (payload.get("token", ""), user.id, check["code"])) as cursor:
                            row = await cursor.fetchone()
                        if not row or row[1] <= time.time():
                            result = {"ok": False, "expired": True}
                        elif row[3] >= 3:
                            result = {"ok": False, "failed": True, "wait": max(1, row[1] - int(time.time()))}
                        else:
                            task = json.loads(row[0])
                            if action == "replay":
                                if row[4] <= 0:
                                    raise GameError("Повторы закончились.")
                                task["replaysLeft"] = row[4] - 1
                                await connection.execute("UPDATE webapp_check_captchas SET replays = replays - 1 WHERE token = ?", (task["token"],))
                                result = task
                            elif row[2]:
                                result = {"ok": True, "solved": True}
                            elif payload.get("answer") == task["seq"]:
                                await connection.execute("UPDATE webapp_check_captchas SET solved = 1 WHERE token = ?", (task["token"],))
                                result = {"ok": True, "solved": True}
                            else:
                                attempts = row[3] + 1
                                task = self.captcha_task(level, task["token"], 3 - attempts, row[4])
                                await connection.execute("UPDATE webapp_check_captchas SET attempts = ?,task = ? WHERE token = ?", (attempts, serialize(task), task["token"]))
                                result = task if attempts < 3 else {"ok": True, "failed": True, "wait": max(1, row[1] - int(time.time()))}
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
            return self.response(result)
        except GameError as error:
            return self.failure(error)

    async def inline_check_results(self, user_id, query):
        bot_username = getattr(self, "wallet_runtime", {}).get("BOT_USERNAME", "mjrstarsbot")
        values = [user_id, int(time.time())]
        condition = "creator_id = ? AND status = 'active' AND expires_at > ?"
        if query.startswith("share_check_"):
            condition += " AND code = ?"
            values.append(query.removeprefix("share_check_"))
        elif query.strip():
            return []
        async with self.database_lock:
            async with self.database().execute("SELECT code,amount_cents,remaining,type FROM webapp_checks WHERE " + condition + " ORDER BY created_at DESC LIMIT 20", values) as cursor:
                checks = await cursor.fetchall()
        results = []
        for code, amount, remaining, check_type in checks:
            link = f"https://t.me/{bot_username}?startapp=check_{code}"
            title = f"Чек на {amount / 100:g} Stars"
            description = f"Осталось активаций: {remaining}" if check_type == "multi" else "Персональный чек" if check_type == "personal" else "Для любого пользователя"
            results.append(InlineQueryResultArticle(id=code, title=title, description=description, input_message_content=InputTextMessageContent(message_text=f"MajorStars · {title}\n{description}", parse_mode=None), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Активировать чек", url=link)]])))
        if not query.strip():
            link = f"https://t.me/{bot_username}?startapp=createcheck"
            results.append(InlineQueryResultArticle(id="open-check-creation", title="Создать новый чек", description="Открыть MajorStars и подтвердить создание чека", input_message_content=InputTextMessageContent(message_text="Создайте внутренний чек MajorStars в приложении.", parse_mode=None), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Создать чек", url=link)]])))
        return results
'''

# ==================== complete_games.py ====================
_SOURCES['complete_games'] = r'''import asyncio
import hashlib
import json
import re
import secrets
import time

from aiohttp import web

from games_backend import ProgressiveGamesBackend, GameError, GAME_PREFIXES, MIN_BET_CENTS, MAX_BET_CENTS, MULTIPLIER_SCALE, integer, money_cents, serialize
from account_backend import AccountMixin
from checks_backend import ChecksMixin
from payments_backend import PaymentsMixin
from star_withdrawals import StarWithdrawalsMixin
from ton_deposits import TonDepositsMixin
from fairness_backend import FairnessMixin
from doghouse_backend import DoghouseMixin
from support_backend import SupportMixin
from realtime_backend import RealtimeMixin
from pot_games import PotGamesMixin
from escape_pvp import EscapePvpMixin
from emoji_games import EmojiGamesMixin
from leaders_backend import LeadersMixin
from live_games import LiveGamesMixin
from pvp_games import PvpGamesMixin
from game_rules import CLAW_TOYS, BACCARAT_MULTIPLIERS, WHEEL_CATALOG, RED_NUMBERS, digest, prepare_cards, move_cards, prepare_blackjack, move_blackjack, prepare_coinflip, move_coinflip, baccarat_deal, unit, payout


CARD_GAMES = {"hilo", "redblack", "blackjack", "coinflip"}
INSTANT_GAMES = {"claw", "baccarat", "wheel", "escape"}
ESCAPE_LEVELS = [
    {"id": "lite", "name": "Lite", "chance": 0.65, "step": 0.1, "gapDeg": 80, "nMin": 11, "q": 0.20967579074919113, "minMult": 1.1, "maxMult": 6, "meanMult": 1.4769},
    {"id": "mid", "name": "Mid", "chance": 0.5, "step": 0.15, "gapDeg": 64, "nMin": 8, "q": 0.17240619184777034, "minMult": 1.2, "maxMult": 9, "meanMult": 1.92},
    {"id": "epic", "name": "Epic", "chance": 0.35, "step": 0.2, "gapDeg": 50, "nMin": 6, "q": 0.11461215543729122, "minMult": 1.2, "maxMult": 12, "meanMult": 2.7429},
]
GAME_PREFIXES.update({"hilo": "H", "redblack": "RB", "blackjack": "BJ", "coinflip": "CF", "claw": "A", "baccarat": "Q", "wheel": "W", "escape": "E", "crash": "C", "roulette": "R", "doghouse": "DH"})


class CompleteGamesBackend(TonDepositsMixin, FairnessMixin, StarWithdrawalsMixin, SupportMixin, RealtimeMixin, AccountMixin, ChecksMixin, PaymentsMixin, DoghouseMixin, PotGamesMixin, EscapePvpMixin, EmojiGamesMixin, LeadersMixin, PvpGamesMixin, LiveGamesMixin, ProgressiveGamesBackend):
    def register(self, application):
        super().register(application)
        self.register_live(application)
        self.register_pvp(application)
        self.register_leaders(application)
        self.register_emoji(application)
        self.register_escape_pvp(application)
        self.register_pots(application)
        application.router.add_route("*", "/api/doghouse/{path:.*}", self.handle_removed_doghouse)
        self.register_support(application)
        self.register_realtime(application)
        self.register_payments(application)
        self.register_account(application)
        self.register_checks(application)
        self.register_star_withdrawals(application)
        self.register_ton_deposits(application)
        self.register_fairness(application)
        for game in sorted(CARD_GAMES | INSTANT_GAMES):
            application.router.add_get(f"/api/{game}/state", self.handle_extended_state)
            application.router.add_get(f"/api/{game}/history", self.handle_history)
            application.router.add_get(f"/api/{game}/round", self.handle_extended_round)
        for game in sorted(CARD_GAMES):
            actions = ["start", "cashout", "guess"] if game != "blackjack" else ["start", "hit", "stand", "double", "split"]
            for action in actions:
                application.router.add_post(f"/api/{game}/{action}", self.handle_extended_action)
        for game, action in (("claw", "play"), ("baccarat", "play"), ("wheel", "spin"), ("escape", "start")):
            application.router.add_post(f"/api/{game}/{action}", self.handle_extended_action)
        application.router.add_get("/api/bet-limits", self.handle_limits)
        application.router.add_get("/api/bets/status", self.handle_bets_status)
        application.router.add_get("/api/outcomes/off", self.handle_outcomes)
        application.router.add_get("/api/games/off", self.handle_switches)
        application.router.add_get("/api/games/popular", self.handle_popular)
        application.router.add_get("/api/avatar/{user_id}", self.handle_avatar)
        application.router.add_get("/api/ping", self.handle_ping)
        application.router.add_get("/api/subscription/check", self.handle_subscription_check)
        application.on_shutdown.append(self.cleanup)

    async def initialize(self, application):
        await super().initialize(application)
        async with self.database_lock:
            connection = self.database()
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_commits(user_id INTEGER NOT NULL,game TEXT NOT NULL,round_id TEXT NOT NULL,seed TEXT NOT NULL,PRIMARY KEY(user_id,game))")
            await connection.commit()

        await self.initialize_payments()
        await self.initialize_lave(application)
        await self.initialize_account()
        await self.initialize_checks()
        await self.initialize_star_withdrawals()
        await self.initialize_ton_deposits()
        await self.initialize_pvp()
        await self.initialize_emoji()
        await self.initialize_escape_pvp()
        await self.initialize_support()
        await self.initialize_pots()
        await self.initialize_live()
        await self.initialize_fairness()

    async def handle_removed_doghouse(self, request):
        self.validate_user(request)
        return self.response({"ok": False, "error": "DogHouse удалён из доступных игр.", "code": "GAME_REMOVED"}, 410)

    async def cleanup(self, application):
        await self.cleanup_star_withdrawals()
        await self.cleanup_ton_deposits()
        await self.cleanup_realtime()
        if hasattr(self, "referral_notices_task"):
            self.referral_notices_task.cancel()
            await asyncio.gather(self.referral_notices_task, return_exceptions=True)
        if hasattr(self, "checks_expiry_task"):
            self.checks_expiry_task.cancel()
            await asyncio.gather(self.checks_expiry_task, return_exceptions=True)
        await self.cleanup_emoji()
        await self.cleanup_pvp()
        if hasattr(self, "live_task"):
            self.live_task.cancel()
            await asyncio.gather(self.live_task, return_exceptions=True)

    def public_state(self, game, state):
        def clean(value):
            if isinstance(value, dict):
                return {key: clean(item) for key, item in value.items() if not key.startswith("_")}
            if isinstance(value, list):
                return [clean(item) for item in value]
            return value
        result = clean(state)
        if game == "escape":
            result["elapsed"] = max(0, (time.time() * 1000 - state["startedAt"]) / 1000)
        if game == "coinflip":
            remaining = max(0, (state.get("_actAt", state.get("finishAt", 0)) - time.time() * 1000) / 1000)
            result.update({"flipping": remaining > 0, "finishIn": remaining, "elapsed": max(0, state.get("flipSec", 3) - remaining), "canCashout": state.get("active", False) and remaining == 0, "canGuess": state.get("active", False) and remaining == 0 and len(state["steps"]) < 15, "payout": state.get("winAmount", 0)})
            if remaining:
                result.pop("serverSeed", None)
            return {"ok": True, "active": state.get("active", False), "roundId": state["roundId"], "version": state.get("version", 0), "round": result}
        return result

    async def commit_for(self, connection, user_id, game):
        async with connection.execute("SELECT round_id, seed FROM webapp_commits WHERE user_id = ? AND game = ?", (user_id, game)) as cursor:
            row = await cursor.fetchone()
        if row:
            return row[0], row[1]
        round_id = GAME_PREFIXES[game] + secrets.token_hex(12).upper()
        seed = secrets.token_hex(32)
        await connection.execute("INSERT INTO webapp_commits(user_id,game,round_id,seed) VALUES (?,?,?,?)", (user_id, game, round_id, seed))
        return round_id, seed

    def commitment(self, pair):
        return {"roundId": pair[0], "seedHash": hashlib.sha256(pair[1].encode()).hexdigest()}

    async def handle_extended_state(self, request):
        try:
            user = self.validate_user(request)
            game = request.path.split("/")[2]
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    async with connection.execute("SELECT data FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game)) as cursor:
                        row = await cursor.fetchone()
                    if row and game == "escape":
                        resumed = json.loads(row[0])
                        if time.time() * 1000 >= resumed["_presentationUntil"]:
                            await connection.execute("DELETE FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game))
                            row = None
                    async with connection.execute("SELECT response FROM webapp_rounds WHERE game = ? AND user_id = ? ORDER BY id DESC LIMIT 24", (game, user.id)) as cursor:
                        recent = [json.loads(item[0]) for item in await cursor.fetchall()]
                    commit = self.commitment(await self.commit_for(connection, user.id, game))
                    response = self.public_state(game, json.loads(row[0])) if row else {"ok": True, "active": False}
                    response["balance"] = await self.balance(connection, user.id)
                    response["commit"] = commit
                    response["recent"] = recent
                    if game == "escape":
                        response["config"] = {"levels": ESCAPE_LEVELS, "rtp": 0.96, "tick": 0.5, "tFirst": 0.75, "nCap": 60}
                        if row:
                            response = {"ok": True, "active": True, "round": self.public_state(game, json.loads(row[0])), "balance": response["balance"], "commit": commit, "config": response["config"]}
                    if game == "coinflip" and not row and recent:
                        response.update({"round": recent[0], "next": commit})
                        if recent[0].get("finishAt", 0) > time.time() * 1000:
                            response["round"] = self.public_state(game, recent[0])["round"]
                            response["round"].pop("serverSeed", None)
                    if game == "coinflip":
                        response.update({"config": {"enabled": True, "stepMult": 1.95, "multiplier": 1.95, "maxSteps": 15, "flipSec": 3}, "recent": recent})
                    elif game == "claw":
                        response["toys"] = CLAW_TOYS
                    elif game == "baccarat":
                        response.update({"spots": [{"key": key, "label": {"player": "Игрок", "banker": "Банкир", "tie": "Ничья", "pp": "Пара игрока", "bp": "Пара банкира"}[key], "multiplier": value, "enabled": True} for key, value in BACCARAT_MULTIPLIERS.items()], "recent": recent})
                    elif game == "wheel":
                        response.update({"mults": {"straight": 36, "split": 18, "corner": 9, "column": 3, "dozen": 3, "even": 2}, "recent": recent, "commit": commit})
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)

    async def load_receipt(self, connection, user_id, request_id, digest):
        async with connection.execute("SELECT request_digest,response FROM webapp_requests WHERE user_id = ? AND request_id = ?", (user_id, request_id)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            async with connection.execute("SELECT request_digest,response FROM webapp_rounds WHERE user_id = ? AND request_id = ?", (user_id, request_id)) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        if row[0] != digest:
            raise GameError("Идентификатор использован для другого запроса.", 409)
        response = json.loads(row[1])
        response["balance"] = await self.balance(connection, user_id)
        if "newBalance" in response:
            response["newBalance"] = response["balance"]
        return response

    async def save_receipt(self, connection, user_id, request_id, digest, response):
        await connection.execute("INSERT INTO webapp_requests(user_id,request_id,request_digest,response) VALUES (?,?,?,?)", (user_id, request_id, digest, serialize(response)))

    def request_identity(self, request, payload):
        key = request.headers.get("Idempotency-Key") or payload.get("rid", "")
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", key):
            raise GameError("Необходим идентификатор запроса.")
        try:
            signature = hashlib.sha256(serialize({"path": request.path, "payload": payload}).encode()).hexdigest()
        except (ValueError, TypeError):
            raise GameError("Некорректные параметры.") from None
        return key, signature

    async def debit(self, connection, user_id, cents):
        if not 0 < cents <= MAX_BET_CENTS * 4:
            raise GameError("Недопустимая сумма ставки.")
        cursor = await connection.execute("UPDATE balances SET amount = ROUND(amount - ?,2) WHERE user_id = ? AND ROUND(amount * 100) >= ?", (cents / 100, user_id, cents))
        if cursor.rowcount != 1:
            raise GameError("Недостаточно средств на балансе.")

    async def credit(self, connection, user_id, cents):
        if not isinstance(cents, int) or cents < 0:
            raise RuntimeError("Invalid payout")
        await connection.execute("UPDATE balances SET amount = ROUND(amount + ?,2) WHERE user_id = ?", (cents / 100, user_id))

    async def record_round(self, connection, game, state, user_id, key, signature):
        result = self.public_state(game, state)
        detail = result.get("round", result)
        await connection.execute(
            "INSERT INTO webapp_rounds(public_id,game,user_id,username,bet_cents,payout_cents,request_id,request_digest,response,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (state["roundId"], game, user_id, state["username"], state.get("_totalBetCents", state["_betCents"]), state["_payoutCents"], key, signature, serialize(detail), self.clock().isoformat()),
        )

    def base_state(self, game, user, pair, bet_cents):
        return {"ok": True, "active": True, "roundId": pair[0], "seedHash": hashlib.sha256(pair[1].encode()).hexdigest(), "_seed": pair[1], "_betCents": bet_cents, "_multiplier": MULTIPLIER_SCALE, "userId": user.id, "username": " ".join(part for part in (user.first_name, user.last_name) if part), "bet": bet_cents / 100, "createdAt": self.clock().isoformat(), "version": 0, "multiplier": 1}

    def validate_version(self, payload, state):
        if payload.get("roundId") != state["roundId"] or payload.get("version") != state.get("version", 0):
            raise GameError("Состояние раунда изменилось. Обновите игру.", 409)

    async def handle_extended_action(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            game, action = request.path.split("/")[2:4]
            key, signature = self.request_identity(request, payload)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    replay = await self.load_receipt(connection, user.id, key, signature)
                    if replay:
                        await connection.commit()
                        return self.response(replay)
                    async with connection.execute("SELECT data FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game)) as cursor:
                        row = await cursor.fetchone()
                    if row and game == "escape" and time.time() * 1000 >= json.loads(row[0])["_presentationUntil"]:
                        await connection.execute("DELETE FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game))
                        row = None
                    if action in {"start", "play", "spin"}:
                        if row:
                            raise GameError("Сначала завершите активный раунд.", 409)
                        if game in {"baccarat", "wheel"}:
                            bets = self.validated_bets(game, payload)
                            bet_cents = sum(bets.values())
                        else:
                            bets = None
                            bet_cents = money_cents(payload.get("bet"))
                        pair = await self.commit_for(connection, user.id, game)
                        state = self.base_state(game, user, pair, bet_cents)
                        await self.debit(connection, user.id, bet_cents)
                        await connection.execute("DELETE FROM webapp_commits WHERE user_id = ? AND game = ?", (user.id, game))
                        finished, won = False, False
                        if game in {"hilo", "redblack"}:
                            prepare_cards(game, state, payload)
                        elif game == "blackjack":
                            prepare_blackjack(state)
                            finished = state.pop("_finished", False)
                            won = state.get("_payoutCents", 0) > 0
                        elif game == "coinflip":
                            prepare_coinflip(state)
                            finished, won = move_coinflip(state, payload, "guess")
                        else:
                            self.instant_result(game, state, payload, bets)
                            finished, won = True, state["_payoutCents"] > (state["_betCents"] if game == "baccarat" else 0)
                    else:
                        if not row:
                            raise GameError("Активный раунд не найден.", 409)
                        state = json.loads(row[0])
                        self.validate_version(payload, state)
                        if game in {"hilo", "redblack"}:
                            finished, won = move_cards(game, state, payload, action)
                        elif game == "blackjack":
                            finished, won = move_blackjack(state, payload, action)
                        else:
                            finished, won = move_coinflip(state, payload, action)
                        extra = state.pop("_extraBetCents", 0)
                        if extra:
                            if state.get("betAmount", 0) > MAX_BET_CENTS * 4 / 100:
                                raise GameError("Превышен предел общей ставки.")
                            await self.debit(connection, user.id, extra)
                    state["version"] += 1
                    if finished:
                        cents = state["_payoutCents"]
                        await self.credit(connection, user.id, cents)
                        state.update({"active": False, "win": won, "winAmount": cents / 100, "payout": cents / 100, "betAmount": state.get("betAmount", state["bet"]), "serverSeed": state["_seed"], "result": state.get("result", "win" if won else "lose")})
                        await self.record_round(connection, game, state, user.id, key, signature)
                        await connection.execute("DELETE FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game))
                        if game == "escape":
                            await connection.execute("INSERT INTO webapp_active_games(user_id,game,data) VALUES (?,?,?)", (user.id, game, serialize(state)))
                    else:
                        await connection.execute("INSERT INTO webapp_active_games(user_id,game,data) VALUES (?,?,?) ON CONFLICT(user_id,game) DO UPDATE SET data=excluded.data", (user.id, game, serialize(state)))
                    state["balanceAfterBet"] = round(await self.balance(connection, user.id) - (state.get("_payoutCents", 0) / 100 if finished else 0), 2)
                    next_commit = self.commitment(await self.commit_for(connection, user.id, game))
                    response = self.public_state(game, state)
                    response.update({"balance": await self.balance(connection, user.id), "nextCommit": next_commit, "next": next_commit})
                    await self.save_receipt(connection, user.id, key, signature, response)
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)

    def validated_bets(self, game, payload):
        if game == "baccarat":
            raw = payload.get("bets")
            if not isinstance(raw, dict) or not raw or len(raw) > 5:
                raise GameError("Поставьте на одно из полей.")
            if any(key not in BACCARAT_MULTIPLIERS for key in raw):
                raise GameError("Неизвестное поле ставки.")
            if raw.get("player") and raw.get("banker"):
                raise GameError("Нельзя одновременно ставить на Игрока и Банкира.")
            bets = {key: money_cents(value) for key, value in raw.items()}
        else:
            raw = payload.get("items")
            if not isinstance(raw, list) or not 1 <= len(raw) <= len(WHEEL_CATALOG):
                raise GameError("Поставьте на одно из полей.")
            bets = {}
            for item in raw:
                if not isinstance(item, dict) or item.get("key") not in WHEEL_CATALOG:
                    raise GameError("Неизвестная позиция рулетки.")
                key = item["key"]
                bets[key] = bets.get(key, 0) + money_cents(item.get("bet", item.get("amount")))
        if not MIN_BET_CENTS <= sum(bets.values()) <= MAX_BET_CENTS:
            raise GameError("Общая сумма ставок вне допустимого диапазона.")
        return bets

    def instant_result(self, game, state, payload, bets):
        seed, round_id = state["_seed"], state["roundId"]
        if game == "claw":
            toy = next((item for item in CLAW_TOYS if item["key"] == payload.get("toy")), None)
            if toy is None:
                raise GameError("Неизвестная игрушка.")
            roll = unit(seed, round_id) * 100
            state.update({"toy": toy["key"], "toyLabel": toy["label"], "chance": toy["chance"], "multiplier": toy["multiplier"], "roll": roll})
            state["_payoutCents"] = payout(state["_betCents"], toy["multiplier"]) if roll < toy["chance"] else 0
        elif game == "baccarat":
            deal = baccarat_deal(seed, round_id)
            state.update(deal)
            spots = {}
            for key, cents in bets.items():
                won = key == deal["winner"] or key == "pp" and deal["playerPair"] or key == "bp" and deal["bankerPair"]
                push = deal["winner"] == "tie" and key in {"player", "banker"}
                paid = payout(cents, BACCARAT_MULTIPLIERS[key]) if won else cents if push else 0
                spots[key] = {"bet": cents / 100, "multiplier": BACCARAT_MULTIPLIERS[key], "winAmount": paid / 100, "win": paid / 100, "result": "win" if won else "push" if push else "lose"}
            state["spots"] = spots
            state["bets"] = {key: cents / 100 for key, cents in bets.items()}
            state["mults"] = BACCARAT_MULTIPLIERS
            state["_payoutCents"] = sum(round(item["winAmount"] * 100) for item in spots.values())
            state["push"] = state["_payoutCents"] == state["_betCents"]
            state["result"] = "win" if state["_payoutCents"] > state["_betCents"] else "draw" if state["push"] else "lose"
            state["recent"] = [{"roundId": round_id, "winner": deal["winner"]}]
        elif game == "escape":
            import math
            level = next((entry for entry in ESCAPE_LEVELS if entry["id"] == payload.get("level")), None)
            if level is None:
                raise GameError("Неизвестная сложность.")
            prefix = round_id + ":" + level["id"] + ":"
            won = unit(seed, prefix + "win") < level["chance"]
            ticks = min(60, level["nMin"] + int(math.log(1 - unit(seed, prefix + "ticks")) / math.log(1 - level["q"])))
            low, high = (0, level["chance"]) if won else (level["chance"], 1)
            land = low + (high - low) * (0.06 + 0.88 * unit(seed, prefix + "land"))
            multiplier = round(ticks * level["step"], 2)
            started = int(time.time() * 1000)
            paid = payout(state["_betCents"], multiplier) if won else 0
            state.update({"kind": "solo", "level": level["id"], "params": level, "N": ticks, "landU": land, "mult": multiplier, "multiplier": multiplier, "pathSeed": digest(seed, round_id + ":path"), "win": won, "startedAt": started, "finishAt": started + int((1.75 + ticks * 0.5) * 1000), "_presentationUntil": started + int((1.75 + ticks * 0.5) * 1000), "_payoutCents": paid})
        else:
            number = int(unit(seed, round_id) * 37)
            items = []
            total = 0
            for key, cents in bets.items():
                entry = WHEEL_CATALOG[key]
                paid = cents * entry["multiplier"] if number in entry["nums"] else 0
                total += paid
                items.append({**entry, "bet": cents / 100, "amount": cents / 100, "winAmount": paid / 100, "mult": entry["multiplier"], "win": paid / 100})
            state.update({"number": number, "color": "green" if number == 0 else "red" if number in RED_NUMBERS else "black", "items": items, "bets": items, "totalBet": state["bet"], "totalWin": total / 100, "_payoutCents": total, "mode": "solo"})

    async def handle_history(self, request):
        response = await super().handle_history(request)
        if request.path.split("/")[2] == "coinflip" and response.status == 200:
            data = json.loads(response.body)
            for row in data.get("rows", []):
                detail = json.loads(row["meta"])
                if detail.get("finishAt", 0) > time.time() * 1000:
                    detail.pop("serverSeed", None)
                    row["meta"] = serialize(detail)
            return self.response(data)
        return response

    async def handle_extended_round(self, request):
        user = self.validate_user(request)
        game = request.path.split("/")[2]
        identifier = request.query.get("id", "")
        if game == "escape" and identifier.startswith("V"):
            return await self.handle_escape_pvp_round(request)
        async with self.database_lock:
            async with self.database().execute("SELECT response FROM webapp_rounds WHERE game = ? AND public_id = ?", (game, identifier)) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return self.failure(GameError("Раунд не найден.", 404))
        result = json.loads(row[0])
        if game == "coinflip" and result.get("finishAt", 0) > time.time() * 1000:
            result.pop("serverSeed", None)
        result.pop("balance", None)
        return self.response(result)

    async def handle_limits(self, request):
        self.validate_user(request)
        keys = ["dice", "slots", "foot", "basket", "bowl", "darts", "keno", "upgrade", "mines", "ladder", "hilo", "redblack", "blackjack", "coinflip", "claw", "baccarat", "wheel", "crash", "roulette", "escape", "portal", "race", "bomb", "sumo", "arena", "arenahub", "escape_pvp"]
        return self.response({"ok": True, "limits": {key: {"min": MIN_BET_CENTS / 100, "max": MAX_BET_CENTS / 100} for key in keys + ["pvp_" + game for game in ("dice", "slots", "football", "basketball", "bowling", "foot", "basket", "bowl", "darts", "blackjack")]}})

    async def handle_bets_status(self, request):
        self.validate_user(request)
        return self.response({"ok": True, "accepting": True, "accepted": True, "betsAccepted": True, "paused": False})

    async def handle_outcomes(self, request):
        self.validate_user(request)
        return self.response({"ok": True, "off": {}, "families": {}, "ver": 1})

    async def handle_switches(self, request):
        self.validate_user(request)
        off = ["doghouse"]
        if not getattr(self, "telegram_bot", None) or not getattr(self, "telegram_channel", None):
            off.extend(["dice", "slots", "bowl", "darts", "basket", "foot", "pvp", "pvp_dice", "pvp_bowling", "pvp_darts", "pvp_basketball", "pvp_football", "pvp_slots"])
        return self.response({"ok": True, "off": off, "order": [], "names": {}, "ver": 2})

    async def handle_popular(self, request):
        self.validate_user(request)
        async with self.database_lock:
            async with self.database().execute("SELECT game,COUNT(*) FROM webapp_rounds WHERE game != 'doghouse' GROUP BY game ORDER BY COUNT(*) DESC LIMIT 6") as cursor:
                rows = await cursor.fetchall()
        return self.response({"ok": True, "games": [row[0] for row in rows]})

    async def handle_subscription_check(self, request):
        user = self.validate_user(request)
        bot = getattr(self, "telegram_bot", None)
        channel = getattr(self, "telegram_channel", None)
        if not bot or not channel:
            return self.response({"ok": True, "required": False, "subscribed": False, "channels": []})
        try:
            member = await asyncio.wait_for(bot.get_chat_member(chat_id=channel, user_id=user.id), timeout=8)
            status = getattr(member.status, "value", member.status)
            subscribed = status in {"creator", "administrator", "member"} or (status == "restricted" and bool(getattr(member, "is_member", False)))
        except Exception:
            return self.response({"ok": False, "error": "Не удалось проверить подписку. Попробуйте позже."}, 503)
        url = "https://t.me/" + str(channel).lstrip("@") if str(channel).startswith("@") else ""
        return self.response({"ok": True, "required": True, "subscribed": subscribed, "channels": [{"name": "Игровой канал", "url": url, "subscribed": subscribed, "buttonText": "Открыть канал"}]})

    async def handle_avatar(self, request):
        self.validate_user(request)
        try:
            user_id = integer(request.match_info["user_id"], 1, 999999999999)
        except GameError as error:
            return self.failure(error)
        hue = user_id * 137 % 360
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96"><rect width="96" height="96" rx="48" fill="hsl({hue},45%,35%)"/><circle cx="48" cy="34" r="16" fill="white"/><path d="M18 82a30 30 0 0 1 60 0" fill="white"/></svg>'
        return web.Response(text=svg, content_type="image/svg+xml", headers={"Cache-Control": "private, max-age=3600"})

    async def handle_ping(self, request):
        self.validate_user(request)
        return self.response({"ok": True, "time": int(time.time() * 1000)})
'''

# ==================== doghouse_backend.py ====================
_SOURCES['doghouse_backend'] = r'''import asyncio
import hashlib
import json
import re
from pathlib import Path

from aiohttp import web

from doghouse_rules import DOGHOUSE_SYMBOLS, DOGHOUSE_WEIGHTS, DOGHOUSE_PAYTABLE, DOGHOUSE_LINES, doghouse_expectation, doghouse_spin
from games_backend import GameError, money_cents, serialize


class DoghouseMixin:
    def register_doghouse(self, application):
        application.router.add_get("/api/doghouse/page", self.handle_doghouse_page)
        application.router.add_get("/api/doghouse/state", self.handle_doghouse_state)
        application.router.add_get("/api/doghouse/history", self.handle_history)
        application.router.add_get("/api/doghouse/round", self.handle_doghouse_round)
        application.router.add_post("/api/doghouse/play", self.handle_doghouse_play)

    async def initialize_doghouse(self):
        await asyncio.to_thread(doghouse_expectation)

    def doghouse_config(self):
        return {"symbols": DOGHOUSE_SYMBOLS, "weights": DOGHOUSE_WEIGHTS, "paytable": DOGHOUSE_PAYTABLE, "paylines": DOGHOUSE_LINES, "normalizationNumerator": 9 * 100 ** 5, "normalizationDenominator": 200 * doghouse_expectation(), "rtp": 0.9, "minBet": 0.1, "maxBet": 1000000, "version": 1}

    async def handle_doghouse_page(self, request):
        self.validate_user(request)
        return web.Response(text=Path(__file__).with_name("doghouse.html").read_text(encoding="utf-8"), content_type="text/html", headers={"Cache-Control": "no-store"})

    async def handle_doghouse_state(self, request):
        try:
            user = self.validate_user(request)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    commitment = self.commitment(await self.commit_for(connection, user.id, "doghouse"))
                    response = {"ok": True, "commit": commitment, "balance": await self.balance(connection, user.id), "config": self.doghouse_config()}
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)

    async def handle_doghouse_play(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            key, signature = self.request_identity(request, payload)
            cents = money_cents(payload.get("bet"))
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    replay = await self.load_receipt(connection, user.id, key, signature)
                    if replay:
                        await connection.commit()
                        return self.response(replay)
                    identifier, seed = await self.commit_for(connection, user.id, "doghouse")
                    if payload.get("roundId") != identifier:
                        raise GameError("Коммит изменился. Обновите игру.", 409)
                    await self.debit(connection, user.id, cents)
                    result = doghouse_spin(seed, identifier, cents)
                    paid = result.pop("payoutCents")
                    await self.credit(connection, user.id, paid)
                    response = {"ok": True, "active": False, "roundId": identifier, "userId": user.id, "username": " ".join(part for part in (user.first_name, user.last_name) if part), "bet": cents / 100, "betCents": cents, "winAmount": paid / 100, "payoutCents": paid, "win": paid > cents, "result": "win" if paid > cents else "draw" if paid == cents else "lose", "multiplier": paid / cents, "seedHash": hashlib.sha256(seed.encode()).hexdigest(), "serverSeed": seed, "createdAt": self.clock().isoformat(), "config": self.doghouse_config(), **result, "balance": await self.balance(connection, user.id)}
                    await connection.execute("INSERT INTO webapp_rounds(public_id,game,user_id,username,bet_cents,payout_cents,request_id,request_digest,response,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (identifier, "doghouse", user.id, response["username"], cents, paid, key, signature, serialize(response), response["createdAt"]))
                    await connection.execute("DELETE FROM webapp_commits WHERE user_id = ? AND game = 'doghouse'", (user.id,))
                    response["commit"] = self.commitment(await self.commit_for(connection, user.id, "doghouse"))
                    await self.save_receipt(connection, user.id, key, signature, response)
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)

    async def handle_doghouse_round(self, request):
        self.validate_user(request)
        identifier = request.query.get("id", "")
        if not re.fullmatch(r"DH[A-F0-9]{24}", identifier):
            return self.failure(GameError("Некорректный UID раунда."))
        async with self.database_lock:
            async with self.database().execute("SELECT response FROM webapp_rounds WHERE public_id = ? AND game = 'doghouse'", (identifier,)) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return self.failure(GameError("Раунд не найден.", 404))
        result = json.loads(row[0])
        result.pop("balance", None)
        return self.response(result)
'''

# ==================== doghouse_rules.py ====================
_SOURCES['doghouse_rules'] = r'''from functools import lru_cache
from itertools import product

from game_rules import unit


DOGHOUSE_SYMBOLS = ["bone", "collar", "bowl", "pug", "husky", "rottweiler", "wild"]
DOGHOUSE_WEIGHTS = [25, 20, 18, 15, 10, 8, 4]
DOGHOUSE_PAYTABLE = {"bone": [3, 10, 40], "collar": [5, 15, 50], "bowl": [7, 20, 75], "pug": [10, 30, 100], "husky": [15, 45, 150], "rottweiler": [20, 60, 250], "wild": [30, 100, 500]}
DOGHOUSE_LINES = [[1, 1, 1, 1, 1], [0, 0, 0, 0, 0], [2, 2, 2, 2, 2], [0, 1, 2, 1, 0], [2, 1, 0, 1, 2], [0, 0, 1, 2, 2], [2, 2, 1, 0, 0], [1, 0, 0, 0, 1], [1, 2, 2, 2, 1], [0, 1, 1, 1, 0], [2, 1, 1, 1, 2], [1, 0, 1, 2, 1], [1, 2, 1, 0, 1], [0, 1, 0, 1, 0], [2, 1, 2, 1, 2], [0, 2, 0, 2, 0], [2, 0, 2, 0, 2], [0, 2, 2, 2, 0], [2, 0, 0, 0, 2], [1, 1, 0, 1, 1]]


def doghouse_line(symbols):
    best = 0
    result = None
    for target in DOGHOUSE_SYMBOLS:
        count = wilds = 0
        for symbol in symbols:
            if symbol != target and symbol != "wild":
                break
            count += 1
            wilds += symbol == "wild"
        if count >= 3:
            raw = DOGHOUSE_PAYTABLE[target][count - 3] * (2 ** wilds if target != "wild" else 1)
            if raw > best:
                best, result = raw, {"symbol": target, "count": count, "wilds": wilds}
    return best, result


@lru_cache(maxsize=1)
def doghouse_expectation():
    numerator = 0
    for indices in product(range(7), repeat=5):
        weight = 1
        for index in indices:
            weight *= DOGHOUSE_WEIGHTS[index]
        raw, detail = doghouse_line([DOGHOUSE_SYMBOLS[index] for index in indices])
        numerator += weight * raw
    return numerator


def doghouse_spin(seed, identifier, cents):
    grid = []
    for reel in range(5):
        column = []
        for row in range(3):
            target = int(unit(seed, f"{identifier}:reel:{reel}:row:{row}") * 100)
            cumulative = 0
            for symbol, weight in zip(DOGHOUSE_SYMBOLS, DOGHOUSE_WEIGHTS):
                cumulative += weight
                if target < cumulative:
                    column.append(symbol)
                    break
        grid.append(column)
    lines, total = [], 0
    for index, path in enumerate(DOGHOUSE_LINES):
        raw, detail = doghouse_line([grid[reel][row] for reel, row in enumerate(path)])
        if raw:
            lines.append({"line": index + 1, "path": path, "raw": raw, **detail})
            total += raw
    paid = cents * total * 9 * 100 ** 5 // (10 * 20 * doghouse_expectation())
    return {"grid": grid, "lines": lines, "rawTotal": total, "payoutCents": paid}
'''

# ==================== emoji_games.py ====================
_SOURCES['emoji_games'] = r'''import asyncio
import json
import logging
import re
import secrets

from emoji_rules import EMOJI_CATALOG, EMOJI_GAMES, EMOJI_FACES, LADDERS, emoji_rule
from games_backend import GameError, money_cents, serialize
from pvp_games import slot_reels


class EmojiGamesMixin:
    def register_emoji(self, application):
        for game in EMOJI_GAMES:
            application.router.add_post(f"/api/{game}/play", self.handle_emoji_play)
            application.router.add_get(f"/api/{game}/multipliers", self.handle_emoji_multipliers)
            application.router.add_get(f"/api/{game}/quote", self.handle_emoji_quote)
            application.router.add_get(f"/api/{game}/history", self.handle_history)
        application.router.add_get("/api/play/result", self.handle_emoji_result)

    async def initialize_emoji(self):
        self.emoji_tasks = {}
        async with self.database_lock:
            connection = self.database()
            try:
                await connection.execute("BEGIN IMMEDIATE")
                await connection.execute("CREATE TABLE IF NOT EXISTS webapp_emoji_jobs(user_id INTEGER NOT NULL,rid TEXT NOT NULL,game TEXT NOT NULL,status TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(user_id,rid))")
                async with connection.execute("SELECT data FROM webapp_emoji_jobs WHERE status = 'pending'") as cursor:
                    interrupted = [json.loads(row[0]) for row in await cursor.fetchall()]
                for state in interrupted:
                    await self.refund_emoji(connection, state, "Игра прервана перезапуском сервера. Ставка возвращена.")
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    async def cleanup_emoji(self):
        if self.emoji_tasks:
            await asyncio.gather(*list(self.emoji_tasks.values()), return_exceptions=True)

    def emoji_quote(self, game, outcome):
        count, settle, maximum = emoji_rule(game, outcome)
        return {"ok": True, "outcome": outcome, "throws": count, "multiplier": maximum / 100, "variable": outcome == "Лесенка" or outcome in LADDERS or outcome in {"Копилка", "Лаки 7"}}

    async def handle_emoji_quote(self, request):
        try:
            self.validate_user(request)
            return self.response(await asyncio.to_thread(self.emoji_quote, request.path.split("/")[2], request.query.get("outcome", "")))
        except GameError as error:
            return self.failure(error)

    def emoji_multipliers(self, game):
        outcomes = list(EMOJI_CATALOG[game])
        if game == "dice":
            outcomes.extend(["Лесенка низкий риск", "Лесенка высокий риск"])
        elif game == "slots":
            outcomes.extend(["Лесенка", "Копилка", "Лаки 7"])
        else:
            outcomes.append("Лесенка")
        multipliers = {outcome: emoji_rule(game, outcome)[2] / 100 for outcome in outcomes}
        response = {"ok": True, "multipliers": multipliers, "families": {}, "rtp": 0.9}
        if game == "dice":
            for outcome in LADDERS:
                if outcome.startswith("Лесенка "):
                    for face in range(1, 7):
                        multipliers[outcome + ":" + str(face)] = emoji_rule(game, outcome)[1]([face]) / 100
        elif game == "slots":
            paytables = {}
            symbols = ["Бар", "Виноград", "Лимон", "Семёрка"]
            for kind, outcome in (("ladder", "Лесенка"), ("piggy", "Копилка")):
                settle = emoji_rule(game, outcome)[1]
                table = {symbol: settle([1 + index * 21]) / (300 if kind == "piggy" else 100) for index, symbol in enumerate(symbols)}
                paytables[kind] = {"table": table, "max": multipliers[outcome]}
            settle = emoji_rule(game, "Лаки 7")[1]
            examples = {3: [64, 1], 4: [64, 4], 5: [64, 16], 6: [64, 64]}
            paytables["lucky"] = {"table": {str(count): settle(values) / 100 for count, values in examples.items()}, "max": multipliers["Лаки 7"]}
            paytables["count"] = {str(count): emoji_rule(game, "Кол-во:Бар:" + str(count))[2] / 100 for count in (1, 2)}
            response["paytables"] = paytables
        else:
            settle = emoji_rule(game, "Лесенка")[1]
            response["ladder"] = {"table": {str(face): settle([face]) / 100 for face in range(1, EMOJI_FACES[game] + 1)}}
            response["pick"] = {str(count): emoji_rule(game, "Выбор:" + ",".join(str(value) for value in range(1, count + 1)))[2] / 100 for count in range(1, EMOJI_FACES[game])}
        return response

    async def handle_emoji_multipliers(self, request):
        try:
            self.validate_user(request)
            return self.response(await asyncio.to_thread(self.emoji_multipliers, request.path.split("/")[2]))
        except GameError as error:
            return self.failure(error)

    async def save_emoji(self, connection, state):
        await connection.execute("UPDATE webapp_emoji_jobs SET status = ?,data = ? WHERE user_id = ? AND rid = ?", (state["status"], serialize(state), state["userId"], state["rid"]))
        await connection.execute("UPDATE webapp_requests SET response = ? WHERE user_id = ? AND request_id = ?", (serialize(state["response"]), state["userId"], state["_key"]))

    async def refund_emoji(self, connection, state, message):
        if state["status"] != "pending":
            return
        await self.credit(connection, state["userId"], state["_betCents"])
        state.update({"status": "cancelled", "response": {"ok": False, "refunded": True, "error": message, "roundId": state["roundId"], "balance": await self.balance(connection, state["userId"]), "newBalance": await self.balance(connection, state["userId"])}})
        await self.save_emoji(connection, state)

    async def settle_emoji(self, user_id, rid):
        try:
            async with self.database_lock:
                async with self.database().execute("SELECT data FROM webapp_emoji_jobs WHERE user_id = ? AND rid = ? AND status = 'pending'", (user_id, rid)) as cursor:
                    row = await cursor.fetchone()
            if row is None:
                return
            state = json.loads(row[0])
            count, settle, maximum = emoji_rule(state["game"], state["outcome"])
            async with self.pvp_telegram_lock:
                async with asyncio.timeout(90):
                    rolls = [await self.telegram_duel_roll(EMOJI_GAMES[state["game"]]) for _ in range(count)]
            values, links = [roll[0] for roll in rolls], [roll[1] for roll in rolls]
            multiplier = settle(values)
            paid = state["_betCents"] * multiplier // 100
            draw = multiplier == 100 and (state["outcome"] == "Дуэль" or state["outcome"].startswith("Дуэль - ")) and values[0] == values[1]
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    async with connection.execute("SELECT status FROM webapp_emoji_jobs WHERE user_id = ? AND rid = ?", (user_id, rid)) as cursor:
                        current = await cursor.fetchone()
                    if current is not None and current[0] == "pending":
                        await self.credit(connection, user_id, paid)
                        response = {"ok": True, "roundId": state["roundId"], "outcome": state["outcome"], "userId": user_id, "username": state["username"], "bet": state["_betCents"] / 100, "betAmount": state["_betCents"] / 100, "win": multiplier > 100, "isDraw": draw, "refund": paid / 100 if 0 < multiplier < 100 else 0, "winAmount": paid / 100, "multiplier": multiplier / 100, "mult": multiplier / 100, "result": "draw" if draw else "win" if multiplier > 100 else "lose", "values": values, "dice": values, "checkLink": links[0], "checkLinks": links, "details": " · ".join(map(str, values)), "createdAt": self.clock().isoformat(), "balance": await self.balance(connection, user_id), "newBalance": await self.balance(connection, user_id)}
                        if state["game"] == "slots":
                            response["reels"] = slot_reels(values[0]) if count == 1 else [slot_reels(value) for value in values]
                        state.update({"status": "done", "response": response})
                        await connection.execute("INSERT INTO webapp_rounds(public_id,game,user_id,username,bet_cents,payout_cents,request_id,request_digest,response,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (state["roundId"], state["game"], user_id, state["username"], state["_betCents"], paid, state["_key"], state["_signature"], serialize(response), response["createdAt"]))
                        await self.save_emoji(connection, state)
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
        except Exception:
            logging.exception("Telegram solo round failed for %s", rid)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    async with connection.execute("SELECT data FROM webapp_emoji_jobs WHERE user_id = ? AND rid = ? AND status = 'pending'", (user_id, rid)) as cursor:
                        row = await cursor.fetchone()
                    if row:
                        await self.refund_emoji(connection, json.loads(row[0]), "Не удалось завершить игру. Ставка возвращена.")
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
        finally:
            self.emoji_tasks.pop((user_id, rid), None)

    async def handle_emoji_play(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            game = request.path.split("/")[2]
            key, signature = self.request_identity(request, payload)
            rid = payload.get("rid", key)
            if not isinstance(rid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", rid):
                raise GameError("Некорректный идентификатор игры.")
            bet = money_cents(payload.get("bet"))
            outcome = payload.get("outcome")
            if not isinstance(outcome, str):
                raise GameError("Укажите исход игры.")
            await asyncio.to_thread(emoji_rule, game, outcome)
            if not getattr(self, "telegram_bot", None) or not getattr(self, "telegram_channel", None):
                raise GameError("Игровой канал Telegram недоступен.", 503)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    replay = await self.load_receipt(connection, user.id, key, signature)
                    if replay and not replay.get("pending"):
                        await connection.commit()
                        return self.response(replay)
                    async with connection.execute("SELECT data FROM webapp_emoji_jobs WHERE user_id = ? AND rid = ?", (user.id, rid)) as cursor:
                        row = await cursor.fetchone()
                    if row:
                        state = json.loads(row[0])
                        if state["_signature"] != signature:
                            raise GameError("Идентификатор игры уже использован.", 409)
                        if state["status"] != "pending":
                            await connection.commit()
                            return self.response(state["response"])
                        if (user.id, rid) not in self.emoji_tasks:
                            await self.refund_emoji(connection, state, "Игра прервана. Ставка возвращена.")
                    else:
                        async with connection.execute("SELECT 1 FROM webapp_emoji_jobs WHERE user_id = ? AND status = 'pending'", (user.id,)) as cursor:
                            if await cursor.fetchone():
                                raise GameError("Дождитесь предыдущей игры.", 409)
                        await self.debit(connection, user.id, bet)
                        state = {"rid": rid, "game": game, "outcome": outcome, "userId": user.id, "username": " ".join(part for part in (user.first_name, user.last_name) if part), "roundId": "T" + secrets.token_hex(12).upper(), "status": "pending", "_betCents": bet, "_key": key, "_signature": signature, "response": {"ok": True, "pending": True}}
                        await connection.execute("INSERT INTO webapp_emoji_jobs(user_id,rid,game,status,data) VALUES (?,?,?,?,?)", (user.id, rid, game, "pending", serialize(state)))
                        await self.save_receipt(connection, user.id, key, signature, state["response"])
                    await connection.commit()
                    if state["status"] == "pending" and (user.id, rid) not in self.emoji_tasks:
                        self.emoji_tasks[(user.id, rid)] = asyncio.create_task(self.settle_emoji(user.id, rid))
                except BaseException:
                    await connection.rollback()
                    raise
            task = self.emoji_tasks.get((user.id, rid))
            if task:
                await asyncio.shield(task)
            async with self.database_lock:
                async with self.database().execute("SELECT data FROM webapp_emoji_jobs WHERE user_id = ? AND rid = ?", (user.id, rid)) as cursor:
                    state = json.loads((await cursor.fetchone())[0])
            return self.response(state["response"])
        except GameError as error:
            return self.failure(error)

    async def handle_emoji_result(self, request):
        try:
            user = self.validate_user(request)
            rid = request.query.get("rid", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", rid):
                raise GameError("Некорректный идентификатор игры.")
            async with self.database_lock:
                async with self.database().execute("SELECT status,data FROM webapp_emoji_jobs WHERE user_id = ? AND rid = ?", (user.id, rid)) as cursor:
                    row = await cursor.fetchone()
            if row is None:
                raise GameError("Игра не найдена.", 404)
            return self.response({"ok": True, "state": row[0], "payload": json.loads(row[1])["response"] if row[0] == "done" else None})
        except GameError as error:
            return self.failure(error)
'''

# ==================== emoji_rules.py ====================
_SOURCES['emoji_rules'] = r'''import json
import math
import re
from collections import Counter
from functools import lru_cache
from itertools import product
from pathlib import Path

from games_backend import GameError
from pvp_games import slot_reels


EMOJI_CATALOG = json.loads(__bundled_resources__["emoji_catalog.json"])
EMOJI_GAMES = {"dice": "dice", "slots": "slots", "bowl": "bowling", "darts": "darts", "basket": "basketball", "foot": "football"}
EMOJI_FACES = {game: 64 if game == "slots" else 5 if game in {"basket", "foot"} else 6 for game in EMOJI_GAMES}
LADDERS = {"foot": [0, 30, 80, 120, 250], "basket": [0, 20, 40, 110, 310], "bowl": [0, 0, 0, 60, 150, 390], "darts": [0, 0, 0, 60, 150, 390], "Лесенка низкий риск": [0, 35, 85, 0, 145, 220], "Лесенка высокий риск": [0, 0, 0, 130, 160, 310]}
SLOT_TABLES = {"Лесенка": {"Семёрка": 2800, "Бар": 1800, "Лимон": 1200, "Виноград": 600}, "Копилка": {"Семёрка": 80, "Бар": 35, "Лимон": 10, "Виноград": 5}, "Лаки 7": {3: 400, 4: 800, 5: 2500, 6: 40000}}


def selection(text, allowed, empty=False):
    values = text.split(",") if text else []
    if (not values and not empty) or len(values) != len(set(values)) or any(value not in allowed for value in values):
        raise GameError("Некорректный выбор исходов.")
    return values


def comparison(left, operator, right):
    return left < right if operator in {"‹", "<"} else left > right if operator in {"›", ">"} else left == right


def dice_predicate(outcome):
    singles = {"Меньше": {1, 2, 3}, "Больше": {4, 5, 6}, "Чётное": {2, 4, 6}, "Нечётное": {1, 3, 5}, "Кроме шести": {1, 2, 3, 4, 5}, "Один": {1}, "Два": {2}, "Три": {3}, "Четыре": {4}, "Пять": {5}, "Шесть": {6}, "1-й сектор": {1, 2}, "2-й сектор": {3, 4}, "3-й сектор": {5, 6}}
    if outcome in singles:
        return 1, lambda values: values[0] in singles[outcome]
    fixed = {
        "Сумма чётное": lambda values: sum(values) % 2 == 0,
        "Сумма нечётное": lambda values: sum(values) % 2 == 1,
        "Двойной куб меньше": lambda values: max(values) <= 3,
        "Двойной куб больше": lambda values: min(values) >= 4,
        "Куб1>Куб2": lambda values: values[0] > values[1],
        "Куб2>Куб1": lambda values: values[1] > values[0],
        "Оба чётное": lambda values: all(value % 2 == 0 for value in values),
        "Оба нечётное": lambda values: all(value % 2 == 1 for value in values),
        "Шаг": lambda values: abs(values[0] - values[1]) == 1,
        "Меньше 7": lambda values: sum(values) < 7,
        "Точно 7": lambda values: sum(values) == 7,
        "Больше 7": lambda values: sum(values) > 7,
        "Умн. 1-18": lambda values: math.prod(values) <= 18,
        "Умн. 19-36": lambda values: math.prod(values) >= 19,
        "Три чётное": lambda values: all(value % 2 == 0 for value in values),
        "Три нечётное": lambda values: all(value % 2 == 1 for value in values),
        "Три меньше": lambda values: max(values) <= 3,
        "Три больше": lambda values: min(values) >= 4,
        "Уникальные": lambda values: len(set(values)) == 3,
        "67": lambda values: sum(values) in {6, 7},
        "Рост 3к": lambda values: values[0] < values[1] < values[2],
        "Спад 3к": lambda values: values[0] > values[1] > values[2],
        "Без 1 и 6": lambda values: all(value not in {1, 6} for value in values),
    }
    if outcome in fixed:
        return EMOJI_CATALOG["dice"][outcome], fixed[outcome]
    match = re.fullmatch(r"(?:Сумма ([23])к[: ]|Произведение )([‹=›])(\d{1,2}|1[0-9]{2})", outcome)
    if match:
        count = int(match[1] or 3)
        threshold = int(match[3])
        return count, lambda values: comparison(sum(values) if match[1] else math.prod(values), match[2], threshold)
    match = re.fullmatch(r"Больший куб:([123])", outcome)
    if match:
        index = int(match[1]) - 1
        return 3, lambda values: all(values[index] > value for position, value in enumerate(values) if position != index)
    match = re.fullmatch(r"Коридор 3к:(\d{1,2})-(\d{1,2})", outcome)
    if match and 3 <= int(match[1]) <= int(match[2]) <= 18:
        return 3, lambda values: int(match[1]) <= sum(values) <= int(match[2])
    match = re.fullmatch(r"Точный исход ([23])к:(.*)", outcome)
    if match:
        count = int(match[1])
        rows = [selection(row, [str(value) for value in range(1, 7)], True) for row in match[2].split("|")]
        if len(rows) != count or not any(rows):
            raise GameError("Некорректный точный исход.")
        return count, lambda values: all(not row or str(value) in row for row, value in zip(rows, values))
    match = re.fullmatch(r"(Дубль|Трипл|Хотя бы|Итог 2к):(.*)", outcome)
    if match:
        kind = match[1]
        allowed = [str(value) for value in range(2, 13)] if kind == "Итог 2к" else [str(value) for value in range(1, 7)]
        chosen = {int(value) for value in selection(match[2], allowed)}
        return 3 if kind == "Трипл" else 2, lambda values: sum(values) in chosen if kind == "Итог 2к" else any(value in chosen for value in values) if kind == "Хотя бы" else len(set(values)) == 1 and values[0] in chosen
    match = re.fullmatch(r"Комбинация:([1-6],[1-6],[1-6])", outcome)
    if match:
        chosen = sorted(int(value) for value in match[1].split(","))
        return 3, lambda values: sorted(values) == chosen
    match = re.fullmatch(r"Стрит:(asc|desc|any)\|(.*)", outcome)
    if match:
        chosen = selection(match[2], ["123", "234", "345", "456"], True) or ["123", "234", "345", "456"]
        return 3, lambda values: "".join(map(str, sorted(values))) in chosen and (match[1] == "any" or list(values) == sorted(values, reverse=match[1] == "desc"))
    raise GameError("Неизвестный исход костей.")


def throw_predicate(game, outcome):
    singles = {
        "bowl": {"Промах": {1}, "Сбито 1/6": {2}, "Сбито 3/6": {3}, "Сбито 4/6": {4}, "Сбито 5/6": {5}, "Страйк": {6}},
        "darts": {"Промах": {1}, "Сектор 1 🔴": {2}, "Сектор 1 ⚪️": {3}, "Сектор 2 🔴": {4}, "Сектор 2 ⚪️": {5}, "Центр": {6}, "Любой белый сектор": {3, 5}, "Сектор или Центр": {2, 4, 6}, "Любой сектор": {2, 3, 4, 5}},
        "basket": {"Отскок": {1}, "Близко": {2}, "Застрял": {3}, "Попал с краем": {4}, "Чистый гол": {5}, "Прокрут": {2, 4}, "Любой гол": {4, 5}, "Промах": {1, 2, 3}},
        "foot": {"Мимо ворот": {1}, "Удар об штангу": {2}, "Гол в центр": {3}, "Гол от штанги": {4}, "Девятка": {5}, "Гол в угол": {4, 5}, "Любой гол": {3, 4, 5}, "Штанга": {2, 4}, "Промах": {1, 2}},
    }[game]
    if outcome.startswith("Выбор:"):
        chosen = {int(value) for value in selection(outcome[6:], [str(value) for value in range(1, EMOJI_FACES[game] + 1)])}
        if len(chosen) >= EMOJI_FACES[game]:
            raise GameError("Выберите не все исходы.")
        return 1, lambda values: values[0] in chosen
    if outcome not in EMOJI_CATALOG[game]:
        raise GameError("Неизвестный исход игры.")
    count = EMOJI_CATALOG[game][outcome]
    if outcome in singles and count == 1:
        return 1, lambda values: values[0] in singles[outcome]
    goal = {4, 5} if game == "basket" else {3, 4, 5}
    if outcome in {"Гол-Промах", "Промах-Гол", "1 Гол и 1 Промах", "Только третий", "Камбэк"}:
        def ordered(values):
            goals = [value in goal for value in values]
            return goals == [True, False] if outcome == "Гол-Промах" else goals == [False, True] if outcome == "Промах-Гол" else sum(goals) == 1 if outcome == "1 Гол и 1 Промах" else goals == [False, False, True] if outcome == "Только третий" else not goals[0] and all(goals[1:])
        return count, ordered
    if outcome in {"Любой дубль", "Дубль x3", "Трипл", "Все разные", "Рост", "Спад"}:
        return count, lambda values: len(set(values)) == 1 if outcome == "Трипл" else len(set(values)) == len(values) if outcome == "Все разные" else list(values) == sorted(set(values)) if outcome == "Рост" else list(values) == sorted(set(values), reverse=True) if outcome == "Спад" else sorted(Counter(values).values()) == ([2] if count == 2 else [1, 2])
    if outcome in {"Шар1>Шар2", "Шар2>Шар1", "1-й дротик ближе", "2-й дротик ближе"}:
        index = 0 if outcome in {"Шар1>Шар2", "1-й дротик ближе"} else 1
        return 2, lambda values: values[index] > values[1 - index]
    if game == "bowl" and outcome.startswith("Сумма "):
        low, high = map(int, outcome[6:].split("-"))
        return 2, lambda values: low <= sum([0, 1, 3, 4, 5, 6][value - 1] for value in values) <= high
    if game == "darts" and outcome in {"Две рядом", "Светофор"}:
        return 2, lambda values: abs(values[0] - values[1]) == 1 if outcome == "Две рядом" else values[0] in {3, 5} and values[1] in {2, 4, 6} or values[1] in {3, 5} and values[0] in {2, 4, 6}
    if game == "foot" and outcome.startswith("Дуэль - "):
        index = 0 if "игрок" in outcome else 1
        if "штангу" in outcome:
            return 2, lambda values: values[index] in {2, 4} and values[1 - index] not in {2, 4}
        return 2, lambda values: -1 if values[0] == values[1] else int(values[index] > values[1 - index])
    normalized = re.sub(r"^(?:[123](?:×| )|[12]\+ )", "", re.sub(r" x[23]$", "", outcome))
    targets = dict(singles)
    targets.update({"Страйка": {6}, "Промаха": singles["Промах"], "Промахов": singles["Промах"], "страйка": {6}, "промаха": singles["Промах"], "промахов": singles["Промах"], "центра": {6}, "Центра": {6}, "Чистых гола": {5}, "Отскока": {1}, "Застряло": {3}, "Прокрут гола": {4}, "Гол": goal, "гол": goal, "гола": goal, "промах": singles["Промах"], "Сектор 1": {5}, "Сектор 2": {4}, "Сектор 3": {3}, "Сектор 4": {2}, "Белых сектора": {3, 5}, "Белый": {3, 5}, "Красных сектора": {2, 4}, "Красный": {2, 4, 6}, "Два сектора": {2, 3, 4, 5}, "Только сектор": {2, 3, 4, 5}})
    if outcome == "Есть Девятка":
        return count, lambda values: 5 in values
    if normalized.startswith("Без "):
        chosen = targets.get(normalized[4:])
        if chosen is not None:
            return count, lambda values: not any(value in chosen for value in values)
    exact = re.match(r"Ровно ([12]) (.*)", normalized)
    if exact:
        chosen = targets.get(exact[2])
        if chosen is not None:
            return count, lambda values: sum(value in chosen for value in values) == int(exact[1])
    chosen = targets.get(normalized)
    if chosen is not None:
        required = int(outcome[0]) if re.match(r"[12]\+ ", outcome) else count
        return count, lambda values: sum(value in chosen for value in values) >= required
    raise GameError("Неизвестный составной исход игры.")


def slots_predicate(outcome):
    symbols = ["Бар", "Виноград", "Лимон", "Семёрка"]
    match = re.fullmatch(r"Точный исход:(.*)", outcome)
    if match:
        rows = [selection(row, symbols, True) for row in match[1].split("|")]
        if len(rows) != 3 or not any(rows):
            raise GameError("Некорректный точный исход.")
        return 1, lambda values: all(not row or symbol in row for row, symbol in zip(rows, slot_reels(values[0])))
    match = re.fullmatch(r"Комбинация:(.*)", outcome)
    if match:
        chosen = match[1].split(",")
        if len(chosen) != 3 or any(symbol not in symbols for symbol in chosen):
            raise GameError("Некорректная комбинация.")
        return 1, lambda values: sorted(slot_reels(values[0])) == sorted(chosen)
    match = re.fullmatch(r"Кол-во:(.*):([12])", outcome)
    if match and match[1] in symbols:
        return 1, lambda values: slot_reels(values[0]).count(match[1]) == int(match[2])
    match = re.fullmatch(r"Дуэль:(.*):([<>=])", outcome)
    if match and match[1] in symbols:
        return 2, lambda values: comparison(slot_reels(values[0]).count(match[1]), match[2], slot_reels(values[1]).count(match[1]))
    if outcome not in EMOJI_CATALOG["slots"]:
        raise GameError("Неизвестный исход слотов.")
    count = EMOJI_CATALOG["slots"][outcome]
    def predicate(values):
        rows = [slot_reels(value) for value in values]
        flattened = [symbol for row in rows for symbol in row]
        counts = Counter(flattened)
        triples = sum(len(set(row)) == 1 for row in rows)
        if outcome.startswith(("3 ", "3+ ")):
            symbol = {"Семёрки": "Семёрка", "Лимона": "Лимон", "Винограда": "Виноград", "Бара": "Бар"}[outcome.split(" ", 1)[1]]
            return counts[symbol] >= 3
        if outcome == "Любая комбинация":
            return triples == 1
        if outcome == "1-2 Любые комбинации":
            return triples >= 1
        if outcome == "2 Любые комбинации":
            return triples == 2
        if outcome.startswith("Уникальные символы"):
            return all(len(set(row)) == 3 for row in rows)
        if outcome.startswith("Любые "):
            return max(counts.values()) >= int(outcome.split(" ")[1][0])
        if outcome.startswith(("1+ Комбо", "2+ Комбо")):
            return triples >= int(outcome[0])
        if outcome == "Без 7 x3":
            return "Семёрка" not in flattened
        if outcome == "7 в каждом x3":
            return all("Семёрка" in row for row in rows)
        raise GameError("Неизвестный составной исход слотов.")
    return count, predicate


@lru_cache(maxsize=512)
def emoji_rule(game, outcome):
    if game not in EMOJI_GAMES or not isinstance(outcome, str) or not 1 <= len(outcome) <= 240:
        raise GameError("Некорректный исход.")
    faces = EMOJI_FACES[game]
    if outcome in LADDERS and game == "dice" or outcome == "Лесенка" and game in {"bowl", "darts", "basket", "foot"}:
        original = LADDERS[outcome if game == "dice" else game]
        table = [value * 90 * faces // sum(original) for value in original]
        return 1, lambda values: table[values[0] - 1], max(table)
    if game == "slots" and outcome in SLOT_TABLES:
        original = SLOT_TABLES[outcome]
        count = 2 if outcome == "Лаки 7" else 1
        if outcome == "Копилка":
            table = {symbol: value * 90 * 4 // (3 * sum(original.values())) for symbol, value in original.items()}
            return 1, lambda values: sum(table[symbol] for symbol in slot_reels(values[0])), max(table.values()) * 3
        def raw(values):
            rows = [slot_reels(value) for value in values]
            flat = [symbol for row in rows for symbol in row]
            return original.get(flat.count("Семёрка"), 0) if count == 2 else sum(original[symbol] for symbol in flat) if outcome == "Копилка" else original[flat[0]] if len(set(flat)) == 1 else 0
        values = [(result, raw(result)) for result in product(range(1, 65), repeat=count)]
        total = sum(value for _, value in values)
        scaled = {result: value * 90 * 64 ** count // total for result, value in values}
        return count, lambda values: scaled[tuple(values)], max(scaled.values())
    if outcome == "Дуэль" and game != "slots":
        count, predicate = 2, lambda values: -1 if values[0] == values[1] else int(values[0] > values[1])
    else:
        count, predicate = dice_predicate(outcome) if game == "dice" else slots_predicate(outcome) if game == "slots" else throw_predicate(game, outcome)
    wins = draws = 0
    for values in product(range(1, faces + 1), repeat=count):
        result = predicate(values)
        wins += result == 1
        draws += result == -1
    if not wins:
        raise GameError("У выбранного исхода нет выигрышных комбинаций.")
    multiplier = (90 * faces ** count - 100 * draws) // wins
    if multiplier <= 0:
        raise GameError("Невозможная таблица выплат.")
    def settlement(values):
        result = predicate(values)
        return 100 if result == -1 else multiplier if result else 0
    return count, settlement, multiplier
'''

# ==================== escape_pvp.py ====================
_SOURCES['escape_pvp'] = r'''import hashlib
import json
import math
import re
import secrets
from time import time as duel_now

from game_rules import digest, unit
from games_backend import GameError, integer, money_cents, serialize


ESCAPE_DUEL_LEVELS = [{"id": "lite", "name": "Lite", "gapDeg": 80, "t1Min": 4, "t1Max": 7}, {"id": "mid", "name": "Mid", "gapDeg": 64, "t1Min": 5, "t1Max": 9}, {"id": "epic", "name": "Epic", "gapDeg": 50, "t1Min": 6, "t1Max": 11}]
ESCAPE_DUEL_CONFIG = {"levels": ESCAPE_DUEL_LEVELS, "commissionPercent": 1, "countdown": 3, "waitTtl": 600, "resultPad": 0.9, "minBet": 0.1, "maxBet": 1000000, "dlMin": 1.3, "dlMax": 3, "landPad": 0.08, "slack": 0.6, "slackLose": 0.3}


def escape_duel_outcome(seed, identifier, level):
    configuration = next(value for value in ESCAPE_DUEL_LEVELS if value["id"] == level)
    values = {key: unit(seed, identifier + ":" + level + ":pvp:" + key) for key in ("winner", "t1", "dl", "landw", "landl")}
    first = math.floor((configuration["t1Min"] + (configuration["t1Max"] - configuration["t1Min"]) * values["t1"]) * 20 + 0.5) / 20
    delay = math.floor((1.3 + 1.7 * values["dl"]) * 20 + 0.5) / 20
    return {"creatorWins": values["winner"] < 0.5, "t1": first, "dl": delay, "t2": math.floor((first + delay) * 20 + 0.5) / 20, "landWin": 0.5 * (0.08 + 0.84 * values["landw"]), "landLose": 0.5 + 0.5 * (0.08 + 0.84 * values["landl"])}


class EscapePvpMixin:
    def register_escape_pvp(self, application):
        for action in ("play", "join", "cancel"):
            application.router.add_post("/api/escape/pvp/" + action, self.handle_escape_pvp_action)
        for action in ("state", "history", "howto"):
            application.router.add_get("/api/escape/pvp/" + action, self.handle_escape_pvp_read)

    async def initialize_escape_pvp(self):
        async with self.database_lock:
            connection = self.database()
            try:
                await connection.execute("BEGIN IMMEDIATE")
                await connection.execute("CREATE TABLE IF NOT EXISTS webapp_escape_duels(id TEXT PRIMARY KEY,creator_id INTEGER NOT NULL,opponent_id INTEGER,status TEXT NOT NULL,data TEXT NOT NULL)")
                await connection.execute("CREATE INDEX IF NOT EXISTS idx_escape_duels_status ON webapp_escape_duels(status,creator_id)")
                await self.expire_escape_duels(connection)
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    async def save_escape_duel(self, connection, state):
        await connection.execute("UPDATE webapp_escape_duels SET status = ?,opponent_id = ?,data = ? WHERE id = ?", (state["status"], state.get("opponentId"), serialize(state), state["roomId"]))

    async def expire_escape_duels(self, connection):
        async with connection.execute("SELECT data FROM webapp_escape_duels WHERE status = 'waiting' AND json_extract(data,'$._expiresAt') <= ?", (duel_now(),)) as cursor:
            expired = [json.loads(row[0]) for row in await cursor.fetchall()]
        for state in expired:
            await self.credit(connection, state["creatorId"], state["_betCents"])
            state.update({"status": "expired", "refunded": True, "finishedAt": self.clock().isoformat()})
            await self.save_escape_duel(connection, state)

    def escape_duel_public(self, state, user_id):
        result = {key: value for key, value in state.items() if not key.startswith("_")}
        slot = 0 if state["creatorId"] == user_id else 1 if state.get("opponentId") == user_id else None
        live = state["status"] == "finished" and state["_presentationUntil"] > duel_now()
        result.update({"ok": True, "kind": "pvp", "id": state["roomId"], "bet": state["betAmount"], "pot": state["betAmount"] * 2, "prize": state["_betCents"] * 2 * 99 // 100 / 100, "commissionPercent": 1, "mySlot": slot, "mine": slot is not None, "iWon": slot is not None and slot == state.get("winnerSlot"), "status": "live" if live else state["status"], "creator": {"id": state["creatorId"], "name": state["creatorName"], "avatar": "/api/avatar/" + str(state["creatorId"]), "isMe": slot == 0}})
        result["commission"] = round(result["pot"] - result["prize"], 2)
        if state.get("opponentId"):
            result["opponent"] = {"id": state["opponentId"], "name": state["opponentName"], "avatar": "/api/avatar/" + str(state["opponentId"]), "isMe": slot == 1}
        if state["status"] == "finished":
            result["elapsed"] = duel_now() - state["_startedAt"] - 3
            if live:
                result.pop("serverSeed", None)
        result["timeText"] = state.get("finishedAt", state["createdAt"])
        return result

    async def escape_duel_response(self, connection, state, user_id):
        balance = await self.balance(connection, user_id)
        response = {"ok": True, "duel": self.escape_duel_public(state, user_id), "balance": balance, "balanceAfterBet": balance}
        if state["status"] == "finished" and state.get("winnerId") == user_id:
            response["balanceAfterBet"] = round(balance - state["winAmount"], 2)
        return response

    async def escape_user_busy(self, connection, user_id):
        async with connection.execute("SELECT 1 FROM webapp_escape_duels WHERE (creator_id = ? OR opponent_id = ?) AND (status = 'waiting' OR (status = 'finished' AND json_extract(data,'$._presentationUntil') > ?))", (user_id, user_id, duel_now())) as cursor:
            return await cursor.fetchone() is not None

    async def join_escape_duel(self, connection, state, user):
        if state["status"] != "waiting":
            raise GameError("Дуэль уже закрыта или началась.", 409)
        if state["creatorId"] == user.id:
            raise GameError("Нельзя играть против себя.")
        await self.debit(connection, user.id, state["_betCents"])
        outcome = escape_duel_outcome(state["_seed"], state["roomId"], state["level"])
        winner = state["creatorId"] if outcome["creatorWins"] else user.id
        paid = state["_betCents"] * 2 * 99 // 100
        await self.credit(connection, winner, paid)
        started = duel_now()
        params = {**outcome, "gapDeg": next(level["gapDeg"] for level in ESCAPE_DUEL_LEVELS if level["id"] == state["level"]), "countdown": 3, "slack": 0.6, "slackLose": 0.3, "finishAfter": outcome["t1"] + 1.2}
        state.update({"status": "finished", "opponentId": user.id, "opponentName": " ".join(part for part in (user.first_name, user.last_name) if part), "winnerId": winner, "winnerSlot": 0 if outcome["creatorWins"] else 1, "winAmount": paid / 100, "feeAmount": (2 * state["_betCents"] - paid) / 100, "isDraw": False, "serverSeed": state["_seed"], "pathSeed": digest(state["_seed"], state["roomId"] + ":pvp:path"), "params": params, "_startedAt": started, "_presentationUntil": started + 3 + params["finishAfter"], "finishedAt": self.clock().isoformat()})
        await self.save_escape_duel(connection, state)

    async def handle_escape_pvp_action(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            key, signature = self.request_identity(request, payload)
            action = request.path.split("/")[-1]
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    replay = await self.load_receipt(connection, user.id, key, signature)
                    if replay:
                        identifier = replay["duel"]["id"]
                        async with connection.execute("SELECT data FROM webapp_escape_duels WHERE id = ?", (identifier,)) as cursor:
                            state = json.loads((await cursor.fetchone())[0])
                        await connection.commit()
                        return self.response(await self.escape_duel_response(connection, state, user.id))
                    await self.expire_escape_duels(connection)
                    if action != "cancel" and await self.escape_user_busy(connection, user.id):
                        raise GameError("Дождитесь завершения своей дуэли.", 409)
                    if action == "play":
                        bet = money_cents(payload.get("bet"))
                        level = payload.get("level", "mid")
                        private = payload.get("private", False)
                        if not isinstance(level, str) or level not in {"lite", "mid", "epic"} or not isinstance(private, bool):
                            raise GameError("Некорректные настройки дуэли.")
                        async with connection.execute("SELECT data FROM webapp_escape_duels WHERE status = 'waiting' AND creator_id != ? AND json_extract(data,'$.private') = 0 AND json_extract(data,'$.level') = ? AND json_extract(data,'$._betCents') = ? ORDER BY rowid LIMIT 1", (user.id, level, bet)) as cursor:
                            row = await cursor.fetchone() if not private else None
                        if row:
                            state = json.loads(row[0])
                            await self.join_escape_duel(connection, state, user)
                        else:
                            await self.debit(connection, user.id, bet)
                            seed = secrets.token_hex(32)
                            identifier = "V" + secrets.token_hex(8).upper()
                            state = {"roomId": identifier, "creatorId": user.id, "creatorName": " ".join(part for part in (user.first_name, user.last_name) if part), "status": "waiting", "betAmount": bet / 100, "level": level, "private": private, "createdAt": self.clock().isoformat(), "seedHash": hashlib.sha256(seed.encode()).hexdigest(), "_seed": seed, "_betCents": bet, "_expiresAt": duel_now() + 600}
                            await connection.execute("INSERT INTO webapp_escape_duels(id,creator_id,status,data) VALUES (?,?,'waiting',?)", (identifier, user.id, serialize(state)))
                    else:
                        identifier = payload.get("id")
                        if not isinstance(identifier, str) or not re.fullmatch(r"V[A-F0-9]{16}", identifier):
                            raise GameError("Некорректный UID дуэли.")
                        async with connection.execute("SELECT data FROM webapp_escape_duels WHERE id = ?", (identifier,)) as cursor:
                            row = await cursor.fetchone()
                        if row is None:
                            raise GameError("Дуэль не найдена.", 404)
                        state = json.loads(row[0])
                        if action == "join":
                            await self.join_escape_duel(connection, state, user)
                        else:
                            if state["creatorId"] != user.id:
                                raise GameError("Нет доступа к чужой дуэли.", 403)
                            if state["status"] != "waiting":
                                raise GameError("Дуэль уже закрыта или началась.", 409)
                            await self.credit(connection, user.id, state["_betCents"])
                            state.update({"status": "cancelled", "refunded": True, "finishedAt": self.clock().isoformat()})
                            await self.save_escape_duel(connection, state)
                    response = await self.escape_duel_response(connection, state, user.id)
                    await self.save_receipt(connection, user.id, key, signature, response)
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)

    async def handle_escape_pvp_round(self, request):
        user = self.validate_user(request)
        async with self.database_lock:
            async with self.database().execute("SELECT data FROM webapp_escape_duels WHERE id = ?", (request.query.get("id", ""),)) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return self.failure(GameError("Дуэль не найдена.", 404))
        return self.response(self.escape_duel_public(json.loads(row[0]), user.id))

    async def handle_escape_pvp_read(self, request):
        try:
            user = self.validate_user(request)
            action = request.path.split("/")[-1]
            level = request.query.get("level", "")
            if level not in {"", "lite", "mid", "epic"}:
                raise GameError("Неизвестный уровень.")
            offset = integer(request.query.get("offset", "0"), 0, 1000000)
            scope = request.query.get("scope", "all")
            query = request.query.get("q", "").strip()
            if scope not in {"all", "mine"} or len(query) > 100:
                raise GameError("Некорректные параметры истории.")
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    await self.expire_escape_duels(connection)
                    if action == "howto":
                        async with connection.execute("SELECT DISTINCT creator_id,json_extract(data,'$.creatorName') FROM webapp_escape_duels ORDER BY rowid DESC LIMIT 2") as cursor:
                            records = await cursor.fetchall()
                        response = {"ok": True, "players": [{"name": name, "avatar": "/api/avatar/" + str(identifier)} for identifier, name in records]}
                    else:
                        conditions = ["status = 'finished'", "json_extract(data,'$._presentationUntil') <= ?"]
                        values = [duel_now()]
                        if scope == "mine":
                            conditions.append("(creator_id = ? OR opponent_id = ?)")
                            values.extend([user.id, user.id])
                        if level and action == "history":
                            conditions.append("json_extract(data,'$.level') = ?")
                            values.append(level)
                        if query:
                            conditions.append("(id = ? OR CAST(creator_id AS TEXT) = ? OR CAST(opponent_id AS TEXT) = ? OR substr(json_extract(data,'$.finishedAt'),1,10) = ?)")
                            values.extend([query] * 4)
                        async with connection.execute("SELECT data FROM webapp_escape_duels WHERE " + " AND ".join(conditions) + " ORDER BY rowid DESC LIMIT 20 OFFSET ?", values + [offset]) as cursor:
                            rows = [self.escape_duel_public(json.loads(row[0]), user.id) for row in await cursor.fetchall()]
                        response = {"ok": True, "rows": rows}
                        if action == "state":
                            async with connection.execute("SELECT data FROM webapp_escape_duels WHERE (creator_id = ? OR opponent_id = ?) AND (status = 'waiting' OR (status = 'finished' AND json_extract(data,'$._presentationUntil') > ?)) ORDER BY rowid DESC LIMIT 1", (user.id, user.id, duel_now())) as cursor:
                                row = await cursor.fetchone()
                            mine = json.loads(row[0]) if row else None
                            async with connection.execute("SELECT data FROM webapp_escape_duels WHERE status = 'waiting' AND json_extract(data,'$.private') = 0 ORDER BY rowid LIMIT 100") as cursor:
                                waiting = [json.loads(row[0]) for row in await cursor.fetchall()]
                            balance = await self.balance(connection, user.id)
                            response.update({"config": ESCAPE_DUEL_CONFIG, "lobby": [self.escape_duel_public(state, user.id) for state in waiting if not level or state["level"] == level], "counts": {value["id"]: sum(state["level"] == value["id"] for state in waiting) for value in ESCAPE_DUEL_LEVELS}, "chips": rows[:15], "mine": self.escape_duel_public(mine, user.id) if mine else None, "balance": balance, "balanceAfterBet": round(balance - mine["winAmount"], 2) if mine and mine["status"] == "finished" and mine["winnerId"] == user.id else balance})
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)
'''

# ==================== fairness_backend.py ====================
_SOURCES['fairness_backend'] = r'''"""Finished-round lookup plus explicit, scoped deterministic verification."""
import hashlib
import hmac
import json
import math
import re
import time

from games_backend import GameError, keno_draw, progressive_positions
from game_rules import unit, baccarat_deal


class FairnessMixin:
    def register_fairness(self, app):
        app.router.add_get('/api/fairness/check', self.handle_fairness_check)

    async def initialize_fairness(self):
        async with self.database_lock:
            db = self.database()
            await db.execute("CREATE INDEX IF NOT EXISTS idx_round_seed_hash ON webapp_rounds(json_extract(response,'$.seedHash'))")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_round_commit_hash ON webapp_rounds(json_extract(response,'$.commitHash'))")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_round_shared_id ON webapp_rounds(substr(public_id,1,instr(public_id,'_')-1))")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_live_seed_hash ON webapp_live_rounds(json_extract(data,'$.seedHash'))")
            await db.commit()

    def verify_round_outcome(self, game, seed, identifier, result):
        """Verify the random outcome, NOT betting/payout accounting or operator honesty."""
        if game == 'keno':
            expected = keno_draw(seed, identifier)
            return expected == result.get('drawn'), {'drawn': expected}
        if game == 'upgrade':
            expected = unit(seed, identifier) * 100
            return result.get('roll') == expected, {'roll': expected}
        if game == 'crash':
            expected = max(1, min(1000, math.floor(90 / (1 - unit(seed, identifier))) / 100))
            return result.get('crashPoint') == expected, {'crashPoint': expected}
        if game == 'roulette':
            roll = unit(seed, identifier)
            expected = 'red' if roll < 0.45 else 'black' if roll < 0.9 else 'green'
            return result.get('outcomeColor') == expected, {'outcomeColor': expected}
        if game in {'mines', 'ladder'}:
            count = result.get('minesCount' if game == 'mines' else 'stonesCount')
            if type(count) is not int or not 1 <= count <= (24 if game == 'mines' else 4):
                return False, {}
            expected = progressive_positions(game, count, seed, identifier)
            actual = result.get('minePositions' if game == 'mines' else 'stonePositions')
            return actual == expected, {'positions': expected}
        if game == 'wheel':
            expected = int(unit(seed, identifier) * 37)
            return result.get('number') == expected, {'number': expected}
        if game == 'baccarat':
            expected = baccarat_deal(seed, identifier)
            return all(result.get(key) == value for key, value in expected.items()), expected
        if game == 'claw':
            expected = unit(seed, identifier) * 100
            return result.get('roll') == expected, {'roll': expected}
        return None, None

    async def handle_fairness_check(self, request):
        try:
            self.validate_user(request)
            identifier = request.query.get('roundId', '').strip().upper()
            supplied_hash = request.query.get('hash', '').strip().lower()
            seed = request.query.get('seed', '').strip()
            game = request.query.get('game', '').strip()
            if sum(bool(value) for value in (identifier, supplied_hash, seed)) < 2:
                raise GameError('Укажите минимум два поля: UID раунда, хеш или раскрытый сид.')
            if identifier and not re.fullmatch(r'[A-Z0-9_]{2,96}', identifier):
                raise GameError('Некорректный UID раунда.')
            if supplied_hash and not re.fullmatch(r'[a-f0-9]{64}', supplied_hash):
                raise GameError('SHA-256 должен содержать 64 шестнадцатеричных символа.')
            if seed and not re.fullmatch(r'[a-fA-F0-9]{64}', seed):
                raise GameError('Некорректный раскрытый сид.')
            derived = hashlib.sha256(seed.encode()).hexdigest() if seed else ''
            if supplied_hash and derived and not hmac.compare_digest(supplied_hash, derived):
                raise GameError('Сид не соответствует указанному SHA-256.', 400, 'FAIRNESS_HASH_MISMATCH')
            digest = supplied_hash or derived
            async with self.database_lock:
                db = self.database()
                # Match shared live round IDs without exposing active state/seeds.
                where, args = ['game != \'doghouse\''], []
                if identifier:
                    where.append("(public_id=? OR substr(public_id,1,instr(public_id,'_')-1)=?)")
                    args.extend([identifier, identifier])
                else:
                    where.append("(json_extract(response,'$.seedHash')=? OR json_extract(response,'$.commitHash')=?)")
                    args.extend([digest, digest])
                if game:
                    where.append('game=?')
                    args.append(game)
                async with db.execute('SELECT game,response FROM webapp_rounds WHERE ' + ' AND '.join(where) + ' LIMIT 20', args) as cursor:
                    rows = await cursor.fetchall()
                if not rows:
                    predicate, values = ('id=?', [identifier]) if identifier else ("json_extract(data,'$.seedHash')=?", [digest])
                    if game:
                        predicate += ' AND game=?'
                        values.append(game)
                    async with db.execute('SELECT game,data FROM webapp_live_rounds WHERE finished=1 AND ' + predicate + ' LIMIT 20', values) as cursor:
                        rows = await cursor.fetchall()
            for source, encoded in rows:
                result = json.loads(encoded)
                disclosed = result.get('serverSeed')
                stored_hash = result.get('seedHash') or result.get('commitHash')
                if not isinstance(disclosed, str) or result.get('active') or result.get('finishAt', 0) > time.time() * 1000:
                    continue
                actual_hash = hashlib.sha256(disclosed.encode()).hexdigest()
                if not isinstance(stored_hash, str) or not hmac.compare_digest(stored_hash, actual_hash):
                    raise GameError('Хеш раскрытого сида не совпадает с записью раунда.', 409, 'FAIRNESS_STORED_HASH_MISMATCH')
                if digest and not hmac.compare_digest(actual_hash, digest) or seed and not hmac.compare_digest(seed, disclosed):
                    continue
                round_id = result.get('roundId') or result.get('id')
                if not isinstance(round_id, str):
                    continue
                verified, expected = self.verify_round_outcome(source, disclosed, round_id, result)
                message = 'Хеш сида совпал; случайный исход воспроизведён по алгоритму игры. Расчёт выплат этой проверкой не проверяется.' if verified is True else 'Хеш сида совпал, но исход НЕ совпал с алгоритмом. Обратитесь в поддержку.' if verified is False else 'Хеш сида совпал. Для этой игры воспроизведение исхода пока не реализовано — это НЕ полная проверка результата.'
                return self.response({'ok': True, 'found': True, 'source': source, 'roundId': round_id, 'commitmentVerified': True, 'outcomeVerified': verified, 'scope': 'random_outcome' if verified is not None else 'commitment_only', 'expected': expected, 'message': message})
            return self.response({'ok': True, 'found': False})
        except GameError as error:
            return self.failure(error)
'''

# ==================== game_rules.py ====================
_SOURCES['game_rules'] = r'''import hashlib
import hmac
import math
import time
from decimal import Decimal, ROUND_HALF_UP

from games_backend import GameError, integer, money_cents, MULTIPLIER_SCALE


RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]
SUITS = ["S", "H", "D", "C"]
CLAW_TOYS = [
    {"key": "cherry", "label": "Вишенка", "multiplier": 2, "chance": 48, "enabled": True},
    {"key": "duck", "label": "Уточка", "multiplier": 5, "chance": 19.2, "enabled": True},
    {"key": "dog", "label": "Собачка", "multiplier": 10, "chance": 9.6, "enabled": True},
    {"key": "pepe", "label": "Пепе", "multiplier": 30, "chance": 3.2, "enabled": True},
]
BACCARAT_MULTIPLIERS = {"player": 2, "banker": 1.95, "tie": 9, "pp": 12, "bp": 12}
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def digest(seed, label):
    return hmac.new(seed.encode(), label.encode(), hashlib.sha256).hexdigest()


def unit(seed, label):
    return int(digest(seed, label)[:13], 16) / 16 ** 13


def rounded_multiplier(value):
    return int(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP) * MULTIPLIER_SCALE)


def payout(cents, multiplier):
    return int((Decimal(cents) * Decimal(str(multiplier))).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def card_at(seed, round_id, index):
    hashed = digest(seed, f"{round_id}:{index}")
    return {"rank": RANKS[int(hashed[:8], 16) % 13], "suit": SUITS[int(hashed[8:16], 16) % 4]}


def deck_for(seed, round_id):
    return [{"rank": RANKS[index % 13], "suit": SUITS[index // 13]} for index in sorted(range(52), key=lambda index: int(digest(seed, f"{round_id}:{index}")[:13], 16))]


def hand_total(cards):
    total = sum(11 if card["rank"] == "A" else 10 if card["rank"] in {"J", "Q", "K"} else int(card["rank"]) for card in cards)
    aces = sum(card["rank"] == "A" for card in cards)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def prepare_cards(game, state, payload):
    state.update({"cards": [card_at(state["_seed"], state["roundId"], 0)], "step": 0, "choices": [], "choiceMultipliers": {}, "_multiplier": MULTIPLIER_SCALE})
    update_card_choices(game, state)


def update_card_choices(game, state):
    if game == "hilo":
        rank = RANKS.index(state["cards"][-1]["rank"])
        counts = {"lower": rank, "same": 1, "higher": 12 - rank}
        state["choiceMultipliers"] = {key: round(0.9 * 13 / value, 4) if value else None for key, value in counts.items()}
    else:
        state["choiceMultipliers"] = {"color": 1.8, "suit": 3.6}
    state["canCashout"] = state["step"] > 0
    state["multiplier"] = state["_multiplier"] / MULTIPLIER_SCALE
    state["cashoutAmount"] = payout(state["_betCents"], state["multiplier"]) / 100


def move_cards(game, state, payload, action):
    if action == "cashout":
        if not state["step"]:
            raise GameError("Сначала угадайте карту.")
        state["_payoutCents"] = payout(state["_betCents"], state["multiplier"])
        return True, True
    if state["step"] >= 15:
        raise GameError("Достигнут предел серии.")
    next_card = card_at(state["_seed"], state["roundId"], state["step"] + 1)
    if game == "hilo":
        choice = payload.get("choice")
        if not isinstance(choice, str) or choice not in {"lower", "same", "higher"}:
            raise GameError("Неизвестный выбор карты.")
        coefficient = state["choiceMultipliers"].get(choice)
        if coefficient is None:
            raise GameError("Этот исход невозможен.")
        previous = RANKS.index(state["cards"][-1]["rank"])
        current = RANKS.index(next_card["rank"])
        actual = "higher" if current > previous else "lower" if current < previous else "same"
        won = choice == actual
        state["choices"].append(choice)
    else:
        kind, value = payload.get("choiceType"), payload.get("choiceValue")
        if not isinstance(kind, str) or not isinstance(value, str) or kind not in {"color", "suit"} or (kind == "color" and value not in {"red", "black"}) or (kind == "suit" and value not in SUITS):
            raise GameError("Неизвестный цвет или масть.")
        coefficient = state["choiceMultipliers"][kind]
        actual = "red" if next_card["suit"] in {"H", "D"} else "black"
        won = value == (actual if kind == "color" else next_card["suit"])
        state["choices"].append({"choiceType": kind, "choiceValue": value, "win": won})
    state["cards"].append(next_card)
    state["step"] += 1
    if not won:
        state["busted"] = True
        state["_payoutCents"] = 0
        return True, False
    state["_multiplier"] = rounded_multiplier(state["_multiplier"] / MULTIPLIER_SCALE * coefficient)
    update_card_choices(game, state)
    if state["step"] == 15:
        state["_payoutCents"] = payout(state["_betCents"], state["multiplier"])
        return True, True
    return False, True


def prepare_blackjack(state):
    state["_deck"] = deck_for(state["_seed"], state["roundId"])
    state["_cursor"] = 4
    deck = state["_deck"]
    state["_dealer"] = [deck[1], deck[3]]
    state["hands"] = [{"cards": [deck[0], deck[2]], "bet": state["bet"], "_betCents": state["_betCents"], "done": False}]
    state["activeHand"] = 0
    state["split"] = False
    update_blackjack(state)
    if hand_total(state["hands"][0]["cards"]) == 21 or hand_total(state["_dealer"]) == 21:
        finish_blackjack(state)
        state["_finished"] = True


def draw_blackjack(state):
    if state["_cursor"] >= len(state["_deck"]):
        raise GameError("В колоде закончились карты.", 409)
    card = state["_deck"][state["_cursor"]]
    state["_cursor"] += 1
    return card


def update_blackjack(state):
    hand = state["hands"][state["activeHand"]]
    state["playerCards"] = hand["cards"]
    state["playerTotal"] = hand_total(hand["cards"])
    state["dealerCards"] = state["_dealer"][:1]
    state["dealerTotal"] = hand_total(state["dealerCards"])
    state["canDouble"] = len(hand["cards"]) == 2 and not hand["done"]
    state["canSplit"] = len(state["hands"]) == 1 and len(hand["cards"]) == 2 and hand["cards"][0]["rank"] == hand["cards"][1]["rank"]
    state["doubled"] = bool(hand.get("doubled"))
    state["betAmount"] = sum(hand["_betCents"] for hand in state["hands"]) / 100
    for hand in state["hands"]:
        hand["total"] = hand_total(hand["cards"])


def finish_blackjack(state):
    while any(hand_total(hand["cards"]) <= 21 for hand in state["hands"]) and hand_total(state["_dealer"]) < 17:
        state["_dealer"].append(draw_blackjack(state))
    dealer_total = hand_total(state["_dealer"])
    dealer_natural = len(state["_dealer"]) == 2 and dealer_total == 21
    total_payout = 0
    for hand in state["hands"]:
        total = hand_total(hand["cards"])
        natural = not state["split"] and len(hand["cards"]) == 2 and total == 21
        if total > 21 or dealer_natural and not natural:
            result, paid = "lose", 0
        elif natural and not dealer_natural:
            result, paid = "win", payout(hand["_betCents"], 2.5)
        elif dealer_total > 21 or total > dealer_total:
            result, paid = "win", hand["_betCents"] * 2
        elif total == dealer_total:
            result, paid = "push", hand["_betCents"]
        else:
            result, paid = "lose", 0
        hand.update({"total": total, "result": result, "winAmount": paid / 100, "done": True})
        total_payout += paid
    update_blackjack(state)
    state.update({"dealerCards": state["_dealer"], "dealerTotal": dealer_total, "canSplit": False, "canDouble": False, "_payoutCents": total_payout})
    wager = sum(hand["_betCents"] for hand in state["hands"])
    state["result"] = "win" if total_payout > wager else "push" if total_payout == wager else "lose"
    state["_totalBetCents"] = wager


def move_blackjack(state, payload, action):
    hand = state["hands"][state["activeHand"]]
    if action == "split":
        if not state["canSplit"]:
            raise GameError("Разделение недоступно.")
        state["_extraBetCents"] = hand["_betCents"]
        left, right = hand["cards"]
        state["hands"] = [{"cards": [card, draw_blackjack(state)], "bet": hand["bet"], "_betCents": hand["_betCents"], "done": card["rank"] == "A"} for card in (left, right)]
        state["split"] = True
    elif action in {"hit", "double"}:
        if action == "double":
            if not state["canDouble"]:
                raise GameError("Удвоение недоступно.")
            state["_extraBetCents"] = hand["_betCents"]
            hand["_betCents"] *= 2
            hand["bet"] *= 2
            hand["doubled"] = True
        hand["cards"].append(draw_blackjack(state))
        hand["done"] = action == "double" or hand_total(hand["cards"]) >= 21
    elif action == "stand":
        hand["done"] = True
    else:
        raise GameError("Неизвестное действие.")
    for index, candidate in enumerate(state["hands"]):
        if not candidate["done"]:
            state["activeHand"] = index
            update_blackjack(state)
            return False, False
    finish_blackjack(state)
    return True, state["_payoutCents"] > 0


def prepare_coinflip(state):
    state.update({"steps": [], "stepMult": 1.95, "maxSteps": 15, "flipSec": 3, "startedAt": int(time.time() * 1000), "status": "active", "nextMultiplier": 1.95})


def move_coinflip(state, payload, action):
    if time.time() * 1000 < state.get("_actAt", 0):
        raise GameError("Дождитесь завершения броска.", 409)
    if action == "cashout":
        if not state["steps"] or not state["steps"][-1]["win"]:
            raise GameError("Выигрыш недоступен.")
        state["_payoutCents"] = payout(state["_betCents"], state["multiplier"])
        state["status"] = "won"
        return True, True
    pick = payload.get("pick")
    if not isinstance(pick, str) or pick not in {"heads", "tails"}:
        raise GameError("Выберите сторону монеты.")
    step = len(state["steps"]) + 1
    if step > 15:
        raise GameError("Предел серии достигнут.")
    side = "heads" if unit(state["_seed"], state["roundId"] + f":coin:{step}") < 0.5 else "tails"
    won = side == pick
    if won:
        state["_multiplier"] = rounded_multiplier(state["_multiplier"] / MULTIPLIER_SCALE * 1.95)
    state["multiplier"] = state["_multiplier"] / MULTIPLIER_SCALE
    state["steps"].append({"n": step, "pick": pick, "side": side, "win": won, "mult": 1.95, "total": state["multiplier"]})
    state["_actAt"] = int(time.time() * 1000) + 3000
    state["finishAt"] = state["_actAt"]
    state["cashoutAmount"] = payout(state["_betCents"], state["multiplier"]) / 100
    state["nextMultiplier"] = rounded_multiplier(state["multiplier"] * 1.95) / MULTIPLIER_SCALE
    state["canGuess"] = won and step < 15
    state["canCashout"] = won
    if not won or step == 15:
        state["status"] = "won" if won else "lost"
        state["_payoutCents"] = payout(state["_betCents"], state["multiplier"]) if won else 0
        return True, won
    return False, True


def baccarat_deal(seed, round_id):
    pool = [suit + rank for _ in range(8) for suit in ["C", "D", "H", "S"] for rank in ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]]
    index = 0
    sequence = []
    def draw(side, third=False):
        nonlocal index
        pick = int(digest(seed, f"{round_id}:{index}")[:13], 16) % len(pool)
        index += 1
        code = pool.pop(pick)
        sequence.append({"side": side, "code": code, "third": third})
        return code
    def points(code):
        rank = code[1:]
        return 1 if rank == "A" else 0 if rank in {"10", "J", "Q", "K"} else int(rank)
    def total(cards):
        return sum(points(card) for card in cards) % 10
    player, banker = [], []
    for _ in range(2):
        player.append(draw("P"))
        banker.append(draw("B"))
    natural = total(player) >= 8 or total(banker) >= 8
    if not natural:
        third = None
        if total(player) <= 5:
            player.append(draw("P", True))
            third = points(player[-1])
        banker_total = total(banker)
        take = banker_total <= 5 if third is None else banker_total <= 2 or banker_total == 3 and third != 8 or banker_total == 4 and 2 <= third <= 7 or banker_total == 5 and 4 <= third <= 7 or banker_total == 6 and third in {6, 7}
        if take:
            banker.append(draw("B", True))
    p_total, b_total = total(player), total(banker)
    return {"player": player, "banker": banker, "playerCards": player, "bankerCards": banker, "playerTotal": p_total, "bankerTotal": b_total, "sequence": sequence, "deal": sequence, "natural": natural, "winner": "player" if p_total > b_total else "banker" if b_total > p_total else "tie", "playerPair": player[0][1:] == player[1][1:], "bankerPair": banker[0][1:] == banker[1][1:]}


def wheel_catalog():
    catalog = {}
    def put(key, kind, numbers):
        catalog[key] = {"key": key, "kind": kind, "nums": numbers, "multiplier": {"straight": 36, "split": 18, "corner": 9, "column": 3, "dozen": 3, "even": 2}[kind]}
    for number in range(37):
        put(f"n:{number}", "straight", [number])
    for number in range(1, 37):
        if number % 3:
            put(f"s:{number}-{number + 1}", "split", [number, number + 1])
        if number + 3 <= 36:
            put(f"s:{number}-{number + 3}", "split", [number, number + 3])
    for number in range(1, 4):
        put(f"s:0-{number}", "split", [0, number])
    for number in range(1, 33):
        if number % 3:
            put(f"c:{number}-{number + 1}-{number + 3}-{number + 4}", "corner", [number, number + 1, number + 3, number + 4])
    for index in range(1, 4):
        put(f"col{index}", "column", list(range(index, 37, 3)))
        put(f"doz{index}", "dozen", list(range((index - 1) * 12 + 1, index * 12 + 1)))
    for key, numbers in {"low": range(1, 19), "high": range(19, 37), "even": range(2, 37, 2), "odd": range(1, 37, 2), "red": sorted(RED_NUMBERS), "black": sorted(set(range(1, 37)) - RED_NUMBERS)}.items():
        put(key, "even", list(numbers))
    return catalog


WHEEL_CATALOG = wheel_catalog()
'''

# ==================== games_backend.py ====================
_SOURCES['games_backend'] = r'''import hashlib
import hmac
import json
import math
import re
import secrets
import time
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from fractions import Fraction
from functools import lru_cache

from aiohttp import web


MIN_BET_CENTS = 10
MAX_BET_CENTS = 100000000
AUTO_MAX_ROUNDS = 100
AUTO_DELAY_MS = 450
MULTIPLIER_SCALE = 100000000
GAME_PREFIXES = {"keno": "K", "upgrade": "U", "mines": "M", "ladder": "L"}


class GameError(Exception):
    def __init__(self, message, status=400, code=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def integer(value, minimum, maximum):
    if isinstance(value, bool):
        raise GameError("Некорректное целое число.")
    if isinstance(value, str):
        if not re.fullmatch(r"[0-9]{1,10}", value):
            raise GameError("Некорректное целое число.")
        value = int(value)
    if not isinstance(value, int) or not minimum <= value <= maximum:
        raise GameError("Число вне допустимого диапазона.")
    return value


def money_cents(value, minimum=MIN_BET_CENTS, maximum=MAX_BET_CENTS):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise GameError("Некорректная сумма ставки.")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < Decimal(minimum) / 100 or amount > Decimal(maximum) / 100:
            raise GameError("Сумма ставки вне допустимого диапазона.")
        cents = amount * 100
        if cents != cents.to_integral_value():
            raise GameError("У суммы может быть не больше двух знаков после запятой.")
        return int(cents)
    except InvalidOperation:
        raise GameError("Некорректная сумма ставки.") from None


@lru_cache(maxsize=30)
def keno_paytable(risk, picks_count):
    if risk not in {"low", "medium", "high"}:
        raise GameError("Неизвестный уровень риска.")
    integer(picks_count, 1, 10)
    threshold = {"low": 1, "medium": (picks_count + 1) // 2, "high": min(picks_count, 6)}[risk]
    probabilities = tuple(
        Fraction(math.comb(picks_count, hits) * math.comb(40 - picks_count, 10 - hits), math.comb(40, 10))
        for hits in range(picks_count + 1)
    )
    weights = tuple(math.comb(hits, threshold) if hits >= threshold else 0 for hits in range(picks_count + 1))
    expectation = sum((probability * weight for probability, weight in zip(probabilities, weights)), Fraction(0))
    return tuple(
        (Fraction(9, 10) * weight / expectation * MULTIPLIER_SCALE).__floor__()
        for weight in weights
    )


def keno_draw(server_seed, round_id):
    return [
        index + 1
        for index in sorted(
            range(40),
            key=lambda index: int(hmac.new(server_seed.encode(), f"{round_id}:{index}".encode(), hashlib.sha256).hexdigest()[:13], 16),
        )[:10]
    ]


def serialize(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class GamesBackend:
    def __init__(self, database, database_lock, authenticate, clock):
        self.database = database
        self.database_lock = database_lock
        self.authenticate = authenticate
        self.clock = clock

    def register(self, application):
        application.router.add_get("/api/keno/paytable", self.handle_paytable)
        for game in ("keno", "upgrade"):
            application.router.add_post(f"/api/{game}/play", self.handle_play)
            application.router.add_get(f"/api/{game}/history", self.handle_history)
            application.router.add_get(f"/api/{game}/round", self.handle_round)
            application.router.add_get(f"/api/{game}/auto/config", self.handle_auto_config)
            application.router.add_post(f"/api/{game}/auto/start", self.handle_auto_start)
            application.router.add_post(f"/api/{game}/auto/finish", self.handle_auto_finish)
        application.router.add_get("/api/pvp/commission", self.handle_commission)

    async def initialize(self, application):
        async with self.database_lock:
            connection = self.database()
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS webapp_rounds ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, public_id TEXT NOT NULL UNIQUE, "
                "game TEXT NOT NULL, user_id INTEGER NOT NULL, username TEXT NOT NULL, "
                "bet_cents INTEGER NOT NULL, payout_cents INTEGER NOT NULL, "
                "request_id TEXT NOT NULL, request_digest TEXT NOT NULL, "
                "response TEXT NOT NULL, created_at TEXT NOT NULL, "
                "UNIQUE(user_id, request_id))"
            )
            await connection.execute("CREATE INDEX IF NOT EXISTS idx_webapp_rounds_game_date ON webapp_rounds(game, id DESC)")
            await connection.execute("CREATE INDEX IF NOT EXISTS idx_webapp_rounds_user_date ON webapp_rounds(user_id, game, id DESC)")
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS webapp_auto_sessions ("
                "id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, game TEXT NOT NULL, "
                "params TEXT NOT NULL, rounds INTEGER NOT NULL DEFAULT 0, "
                "staked_cents INTEGER NOT NULL DEFAULT 0, paid_cents INTEGER NOT NULL DEFAULT 0, "
                "last_at INTEGER NOT NULL DEFAULT 0, closed INTEGER NOT NULL DEFAULT 0, "
                "created_at INTEGER NOT NULL)"
            )
            await connection.execute("CREATE INDEX IF NOT EXISTS idx_webapp_auto_user ON webapp_auto_sessions(user_id, game, closed)")
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS webapp_requests ("
                "user_id INTEGER NOT NULL, request_id TEXT NOT NULL, request_digest TEXT NOT NULL, "
                "response TEXT NOT NULL, PRIMARY KEY(user_id, request_id))"
            )
            await connection.commit()

    def response(self, data, status=200):
        return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})

    def failure(self, error):
        payload = {"ok": False, "error": error.message}
        if error.code:
            payload["autoCode"] = error.code
        return self.response(payload, error.status)

    async def payload(self, request):
        try:
            data = await request.json()
        except (ValueError, TypeError, UnicodeDecodeError):
            raise GameError("Некорректный JSON.") from None
        if not isinstance(data, dict):
            raise GameError("Ожидается JSON-объект.")
        return data

    def validate_user(self, request, payload=None):
        user = self.authenticate(request)
        if payload is not None and "uid" in payload:
            if isinstance(payload["uid"], bool) or str(payload["uid"]) != str(user.id):
                raise GameError("Нет доступа к чужому аккаунту.", 403)
        return user

    async def balance(self, connection, user_id):
        async with connection.execute("SELECT amount FROM balances WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        return float(row[0]) if row else 0.0

    def auto_config(self):
        return {"ok": True, "enabled": True, "maxRounds": AUTO_MAX_ROUNDS, "minDelayMs": AUTO_DELAY_MS, "maxBet": MAX_BET_CENTS / 100}

    async def handle_paytable(self, request):
        self.validate_user(request)
        try:
            risk = request.query.get("risk", "medium")
            count = integer(request.query.get("picksCount", "0"), 1, 10)
            table = keno_paytable(risk, count)
            return self.response({"ok": True, "risk": risk, "picksCount": count, "table": {str(index): value / MULTIPLIER_SCALE for index, value in enumerate(table)}})
        except GameError as error:
            return self.failure(error)

    async def handle_auto_config(self, request):
        self.validate_user(request)
        return self.response(self.auto_config())

    async def handle_commission(self, request):
        self.validate_user(request)
        return self.response({"ok": True, "percent": 1})

    def auto_params(self, params):
        if not isinstance(params, dict):
            raise GameError("Некорректные настройки авто-игры.")
        result = {"rounds": integer(params.get("rounds", AUTO_MAX_ROUNDS), 0, AUTO_MAX_ROUNDS)}
        for name in ("profit", "loss", "bigWin", "cap"):
            result[name] = money_cents(params.get(name, 0), 0)
        if not isinstance(params.get("stopWin", False), bool):
            raise GameError("Некорректное условие остановки.")
        result["stopWin"] = params.get("stopWin", False)
        return result

    async def handle_auto_start(self, request):
        try:
            payload = await self.payload(request)
            game = request.path.split("/")[2]
            user = self.validate_user(request, payload)
            params = self.auto_params(payload.get("params"))
            session_id = secrets.token_hex(16)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    await connection.execute("UPDATE webapp_auto_sessions SET closed = 1 WHERE user_id = ? AND game = ? AND closed = 0", (user.id, game))
                    await connection.execute(
                        "INSERT INTO webapp_auto_sessions(id,user_id,game,params,created_at) VALUES (?,?,?,?,?)",
                        (session_id, user.id, game, serialize(params), int(time.time() * 1000)),
                    )
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
            return self.response({**self.auto_config(), "sid": session_id})
        except GameError as error:
            return self.failure(error)

    async def handle_auto_finish(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            game = request.path.split("/")[2]
            session_id = payload.get("sid")
            if not isinstance(session_id, str) or not re.fullmatch(r"[a-f0-9]{32}", session_id):
                raise GameError("Некорректная авто-сессия.")
            async with self.database_lock:
                connection = self.database()
                await connection.execute("UPDATE webapp_auto_sessions SET closed = 1 WHERE id = ? AND user_id = ? AND game = ?", (session_id, user.id, game))
                await connection.commit()
            return self.response({"ok": True})
        except GameError as error:
            return self.failure(error)

    async def validate_auto(self, connection, session_id, user_id, game, bet_cents, now):
        if not isinstance(session_id, str) or not re.fullmatch(r"[a-f0-9]{32}", session_id):
            raise GameError("Некорректная авто-сессия.", code="other")
        async with connection.execute(
            "SELECT params, rounds, staked_cents, paid_cents, last_at, closed, created_at "
            "FROM webapp_auto_sessions WHERE id = ? AND user_id = ? AND game = ?", (session_id, user_id, game)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None or row[5] or now - row[6] > 86400000:
            raise GameError("Авто-сессия завершена или не найдена.", code="other")
        params = json.loads(row[0])
        if row[1] >= (params["rounds"] or AUTO_MAX_ROUNDS):
            raise GameError("Лимит раундов исчерпан.", code="cap")
        if now - row[4] < AUTO_DELAY_MS:
            raise GameError("Подождите перед следующим раундом.", 429, "fast" if game in {"mines", "ladder"} else "wait")
        if params["cap"] and bet_cents > params["cap"]:
            raise GameError("Превышен потолок ставки авто-игры.", code="cap")
        net = row[3] - row[2]
        if (params["profit"] and net >= params["profit"]) or (params["loss"] and -net >= params["loss"]):
            raise GameError("Достигнуто условие остановки авто-игры.", code="cap")
        return params

    async def handle_play(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            bet_cents = money_cents(payload.get("bet"))
            game = request.path.split("/")[2]
            if game == "keno":
                picks = payload.get("picks")
                if not isinstance(picks, list) or not 1 <= len(picks) <= 10:
                    raise GameError("Выберите от 1 до 10 чисел.")
                picks = [integer(value, 1, 40) for value in picks]
                if len(set(picks)) != len(picks):
                    raise GameError("Выбранные числа не должны повторяться.")
                picks = sorted(picks)
                risk = payload.get("risk", "medium")
                if not isinstance(risk, str):
                    raise GameError("Неизвестный уровень риска.")
                table = keno_paytable(risk, len(picks))
                options = {"picks": picks, "risk": risk}
            elif game == "upgrade":
                chance_value = money_cents(payload.get("chance"), 200, 8000)
                options = {"chance": chance_value / 100}
            else:
                key = "minesCount" if game == "mines" else "stonesCount"
                path_key = "cells" if game == "mines" else "columns"
                count = integer(payload.get(key), 1, 24 if game == "mines" else 4)
                path = payload.get(path_key)
                maximum = 25 - count if game == "mines" else 6
                if not isinstance(path, list) or not 1 <= len(path) <= maximum:
                    raise GameError("Некорректная длина пути авто-игры.")
                path = [integer(value, 0, 24 if game == "mines" else 4) for value in path]
                if game == "mines" and len(set(path)) != len(path):
                    raise GameError("Клетки пути не должны повторяться.")
                if not payload.get("autoSid"):
                    raise GameError("Необходима авто-сессия.", code="session")
                options = {key: count, "path": path}
            request_id = request.headers.get("Idempotency-Key", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", request_id):
                raise GameError("Отсутствует корректный идентификатор запроса.")
            session_id = payload.get("autoSid")
            if session_id is not None and not isinstance(session_id, str):
                raise GameError("Некорректная авто-сессия.")
            digest = hashlib.sha256(serialize({"game": game, "bet": bet_cents, "options": options, "session": session_id}).encode()).hexdigest()
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    async with connection.execute("SELECT request_digest, response FROM webapp_rounds WHERE user_id = ? AND request_id = ?", (user.id, request_id)) as cursor:
                        previous = await cursor.fetchone()
                    if previous is None:
                        async with connection.execute("SELECT request_digest, response FROM webapp_requests WHERE user_id = ? AND request_id = ?", (user.id, request_id)) as cursor:
                            previous = await cursor.fetchone()
                    if previous:
                        if previous[0] != digest:
                            raise GameError("Идентификатор уже использован для другой ставки.", 409)
                        response = json.loads(previous[1])
                        response["balance"] = await self.balance(connection, user.id)
                        await connection.commit()
                        return self.response(response)
                    now = int(time.time() * 1000)
                    params = await self.validate_auto(connection, session_id, user.id, game, bet_cents, now) if session_id else None
                    if game in {"mines", "ladder"}:
                        async with connection.execute("SELECT 1 FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game)) as cursor:
                            if await cursor.fetchone():
                                raise GameError("Сначала завершите ручной раунд.", 409)
                    async with connection.execute("SELECT created_at FROM webapp_rounds WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user.id,)) as cursor:
                        last = await cursor.fetchone()
                    if last and (self.clock() - datetime.fromisoformat(last[0])).total_seconds() < 0.2:
                        raise GameError("Подождите перед следующей ставкой.", 429, "wait")
                    cursor = await connection.execute(
                        "UPDATE balances SET amount = ROUND(amount - ?, 2) WHERE user_id = ? AND ROUND(amount * 100) >= ?",
                        (bet_cents / 100, user.id, bet_cents),
                    )
                    if cursor.rowcount != 1:
                        raise GameError("Недостаточно средств на балансе.", code="balance")
                    round_id = GAME_PREFIXES[game] + secrets.token_hex(12).upper()
                    seed = secrets.token_hex(32)
                    if game == "keno":
                        drawn = keno_draw(seed, round_id)
                        hits = len(set(picks).intersection(drawn))
                        multiplier = table[hits]
                        result = {**options, "drawn": drawn, "hits": hits}
                        payout_cents = bet_cents * multiplier // MULTIPLIER_SCALE
                    elif game == "upgrade":
                        roll = int(hmac.new(seed.encode(), round_id.encode(), hashlib.sha256).hexdigest()[:13], 16) / 16 ** 13 * 100
                        coefficient = (Decimal(9400) / chance_value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
                        multiplier = int(coefficient * MULTIPLIER_SCALE)
                        payout_cents = bet_cents * multiplier // MULTIPLIER_SCALE if 0.0946 <= roll <= options["chance"] else 0
                        result = {**options, "roll": roll}
                    else:
                        state = self.progressive_start(game, {**options, "bet": bet_cents / 100}, user, seed, round_id)
                        used = []
                        for level, cell in enumerate(path):
                            move = {"roundId": round_id, "cellIndex": cell, "column": cell, "level": level}
                            finished, won = self.progressive_move(game, "reveal" if game == "mines" else "pick", move, state)
                            used.append(cell)
                            if finished:
                                break
                        multiplier = state["_multiplier"]
                        payout_cents = bet_cents * multiplier // MULTIPLIER_SCALE if won else 0
                        state.update({"active": False, "canCashout": False, "path": used})
                        state["minePositions" if game == "mines" else "stonePositions"] = state["_positions"]
                        result = self.public_progressive_state(state)
                    await connection.execute("UPDATE balances SET amount = ROUND(amount + ?, 2) WHERE user_id = ?", (payout_cents / 100, user.id))
                    created_at = self.clock().isoformat()
                    response = {
                        "ok": True, "active": False, "roundId": round_id,
                        "seedHash": hashlib.sha256(seed.encode()).hexdigest(), "serverSeed": seed,
                        "userId": user.id, "username": " ".join(part for part in (user.first_name, user.last_name) if part),
                        "bet": bet_cents / 100, **result,
                        "multiplier": multiplier / MULTIPLIER_SCALE, "winAmount": payout_cents / 100,
                        "win": payout_cents > 0, "result": "win" if payout_cents > 0 else "lose",
                        "balance": await self.balance(connection, user.id), "createdAt": created_at, "auto": bool(session_id),
                    }
                    await connection.execute(
                        "INSERT INTO webapp_rounds(public_id,game,user_id,username,bet_cents,payout_cents,request_id,request_digest,response,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (round_id, game, user.id, response["username"], bet_cents, payout_cents, request_id, digest, serialize(response), created_at),
                    )
                    if session_id:
                        closed = bool(params["stopWin"] and payout_cents > 0 or params["bigWin"] and payout_cents >= params["bigWin"])
                        await connection.execute(
                            "UPDATE webapp_auto_sessions SET rounds = rounds + 1, staked_cents = staked_cents + ?, paid_cents = paid_cents + ?, last_at = ?, closed = ? WHERE id = ? AND user_id = ?",
                            (bet_cents, payout_cents, now, int(closed), session_id, user.id),
                        )
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)

    async def handle_history(self, request):
        try:
            user = self.validate_user(request)
            offset = integer(request.query.get("offset", "0"), 0, 1000000)
            scope = request.query.get("scope", "all")
            if scope not in {"all", "mine"}:
                raise GameError("Неизвестный фильтр истории.")
            query = request.query.get("q", "").strip()
            if len(query) > 100:
                raise GameError("Слишком длинный поисковый запрос.")
            conditions = ["game = ?"]
            values = [request.path.split("/")[2]]
            if scope == "mine":
                conditions.append("user_id = ?")
                values.append(user.id)
            if query:
                conditions.append("(public_id = ? OR CAST(user_id AS TEXT) = ? OR substr(created_at, 1, 10) = ?)")
                values.extend([query, query, query])
            values.append(offset)
            async with self.database_lock:
                async with self.database().execute(
                    "SELECT id,user_id,username,bet_cents,payout_cents,response,created_at FROM webapp_rounds WHERE " + " AND ".join(conditions) + " ORDER BY id DESC LIMIT 20 OFFSET ?", values
                ) as cursor:
                    records = await cursor.fetchall()
            rows = []
            for record in records:
                detail = json.loads(record[5])
                detail.pop("balance", None)
                rows.append({"id": record[0], "user_id": record[1], "username": record[2], "bet": record[3] / 100, "win_amount": record[4] / 100, "result": detail["result"], "meta": serialize(detail), "created_at": record[6]})
            return self.response({"ok": True, "rows": rows})
        except GameError as error:
            return self.failure(error)

    async def handle_round(self, request):
        self.validate_user(request)
        round_id = request.query.get("id", "")
        game = request.path.split("/")[2]
        if not re.fullmatch(GAME_PREFIXES[game] + r"[A-F0-9]{24}", round_id):
            return self.failure(GameError("Раунд не найден.", 404))
        async with self.database_lock:
            async with self.database().execute("SELECT response FROM webapp_rounds WHERE public_id = ? AND game = ?", (round_id, game)) as cursor:
                record = await cursor.fetchone()
        if record is None:
            return self.failure(GameError("Раунд не найден.", 404))
        response = json.loads(record[0])
        response.pop("balance", None)
        return self.response(response)


@lru_cache(maxsize=28)
def progressive_table(game, count):
    if game == "mines":
        integer(count, 1, 24)
        return {str(step): (Fraction(9, 10) * Fraction(math.comb(25, step), math.comb(25 - count, step)) * MULTIPLIER_SCALE).__floor__() for step in range(1, 26 - count)}
    integer(count, 1, 4)
    return {str(step): (Fraction(9, 10) * Fraction(5, 5 - count) ** step * MULTIPLIER_SCALE).__floor__() for step in range(1, 7)}


def progressive_positions(game, count, seed, round_id):
    if game == "mines":
        return sorted(range(25), key=lambda index: int(hmac.new(seed.encode(), f"{round_id}:{index}".encode(), hashlib.sha256).hexdigest()[:13], 16))[:count]
    positions = []
    for level in range(6):
        columns = sorted(range(5), key=lambda column: int(hmac.new(seed.encode(), f"{round_id}:{level}:{column}".encode(), hashlib.sha256).hexdigest()[:13], 16))[:count]
        positions.extend([[level, column] for column in columns])
    return positions


class ProgressiveGamesBackend(GamesBackend):
    def register(self, application):
        super().register(application)
        for game, choice in (("mines", "reveal"), ("ladder", "pick")):
            application.router.add_get(f"/api/{game}/coefs", self.handle_coefs)
            application.router.add_get(f"/api/{game}/state", self.handle_progressive_state)
            application.router.add_get(f"/api/{game}/history", self.handle_history)
            application.router.add_get(f"/api/{game}/round", self.handle_round)
            application.router.add_get(f"/api/{game}/auto/config", self.handle_auto_config)
            application.router.add_post(f"/api/{game}/auto/start", self.handle_auto_start)
            application.router.add_post(f"/api/{game}/auto/finish", self.handle_auto_finish)
            application.router.add_post(f"/api/{game}/auto/round", self.handle_play)
            for action in ("start", choice, "cashout"):
                application.router.add_post(f"/api/{game}/{action}", self.handle_progressive_action)

    async def initialize(self, application):
        await super().initialize(application)
        async with self.database_lock:
            connection = self.database()
            await connection.execute(
                "CREATE TABLE IF NOT EXISTS webapp_active_games ("
                "user_id INTEGER NOT NULL, game TEXT NOT NULL, data TEXT NOT NULL, "
                "PRIMARY KEY(user_id, game))"
            )
            await connection.commit()

    async def handle_coefs(self, request):
        try:
            self.validate_user(request)
            game = request.path.split("/")[2]
            key = "minesCount" if game == "mines" else "stonesCount"
            count = integer(request.query.get(key, "0"), 1, 24 if game == "mines" else 4)
            table = progressive_table(game, count)
            return self.response({"ok": True, key: count, "table": {step: coefficient / MULTIPLIER_SCALE for step, coefficient in table.items()}})
        except GameError as error:
            return self.failure(error)

    def public_progressive_state(self, state):
        return {key: value for key, value in state.items() if not key.startswith("_")}

    async def handle_progressive_state(self, request):
        try:
            user = self.validate_user(request)
            game = request.path.split("/")[2]
            async with self.database_lock:
                connection = self.database()
                async with connection.execute("SELECT data FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game)) as cursor:
                    row = await cursor.fetchone()
                balance = await self.balance(connection, user.id)
            response = self.public_progressive_state(json.loads(row[0])) if row else {"ok": True, "active": False}
            response["balance"] = balance
            return self.response(response)
        except GameError as error:
            return self.failure(error)

    def progressive_start(self, game, payload, user, seed=None, round_id=None):
        bet_cents = money_cents(payload.get("bet"))
        key = "minesCount" if game == "mines" else "stonesCount"
        count = integer(payload.get(key), 1, 24 if game == "mines" else 4)
        seed = seed or secrets.token_hex(32)
        round_id = round_id or GAME_PREFIXES[game] + secrets.token_hex(12).upper()
        table = progressive_table(game, count)
        state = {
            "ok": True, "active": True, "roundId": round_id,
            "seedHash": hashlib.sha256(seed.encode()).hexdigest(),
            "_seed": seed, "_positions": progressive_positions(game, count, seed, round_id),
            "_betCents": bet_cents, "_table": table, "_multiplier": MULTIPLIER_SCALE,
            "userId": user.id, "username": " ".join(part for part in (user.first_name, user.last_name) if part),
            "createdAt": self.clock().isoformat(), "bet": bet_cents / 100,
            "multiplier": 1, "table": {step: value / MULTIPLIER_SCALE for step, value in table.items()},
            "canCashout": False, "cashoutAmount": 0, key: count,
        }
        if game == "mines":
            state.update({"cellsOpened": 0, "revealed": [], "hitIndex": None, "maxSteps": 25 - count})
        else:
            state.update({"level": 0, "picks": [], "revealedStones": [], "hitPosition": None, "maxLevels": 6})
        return state

    def progressive_move(self, game, action, payload, state):
        if payload.get("roundId") != state["roundId"]:
            raise GameError("Раунд изменился. Обновите состояние игры.", 409)
        if action == "cashout":
            if not state["canCashout"]:
                raise GameError("Сначала сделайте успешный ход.")
            return True, True
        if game == "mines":
            cell = integer(payload.get("cellIndex"), 0, 24)
            if cell in state["revealed"]:
                raise GameError("Эта клетка уже открыта.", 409)
            if cell in state["_positions"]:
                state["hitIndex"] = cell
                return True, False
            state["revealed"].append(cell)
            state["cellsOpened"] += 1
            step = state["cellsOpened"]
            maximum = state["maxSteps"]
        else:
            level = integer(payload.get("level"), 0, 5)
            if level != state["level"]:
                raise GameError("Уровень уже изменился. Обновите состояние игры.", 409)
            column = integer(payload.get("column"), 0, 4)
            state["picks"].append(column)
            if [level, column] in state["_positions"]:
                state["hitPosition"] = [level, column]
                return True, False
            state["level"] += 1
            state["revealedStones"] = [position for position in state["_positions"] if position[0] < state["level"]]
            step = state["level"]
            maximum = state["maxLevels"]
        state["_multiplier"] = state["_table"][str(step)]
        state["multiplier"] = state["_multiplier"] / MULTIPLIER_SCALE
        state["cashoutAmount"] = state["_betCents"] * state["_multiplier"] // MULTIPLIER_SCALE / 100
        state["canCashout"] = True
        return step == maximum, True

    async def handle_progressive_action(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            game, action = request.path.split("/")[2:4]
            request_id = request.headers.get("Idempotency-Key", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", request_id):
                raise GameError("Отсутствует корректный идентификатор запроса.")
            try:
                digest = hashlib.sha256(serialize({"game": game, "action": action, "payload": payload}).encode()).hexdigest()
            except ValueError:
                raise GameError("Некорректный JSON.") from None
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    async with connection.execute("SELECT request_digest,response FROM webapp_requests WHERE user_id = ? AND request_id = ?", (user.id, request_id)) as cursor:
                        previous = await cursor.fetchone()
                    if previous is None:
                        async with connection.execute("SELECT request_digest,response FROM webapp_rounds WHERE user_id = ? AND request_id = ?", (user.id, request_id)) as cursor:
                            previous = await cursor.fetchone()
                    if previous:
                        if previous[0] != digest:
                            raise GameError("Идентификатор уже использован для другого действия.", 409)
                        response = json.loads(previous[1])
                        response["balance"] = await self.balance(connection, user.id)
                        await connection.commit()
                        return self.response(response)
                    async with connection.execute("SELECT data FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game)) as cursor:
                        row = await cursor.fetchone()
                    if action == "start":
                        if row:
                            raise GameError("Сначала завершите текущий раунд.", 409)
                        state = self.progressive_start(game, payload, user)
                        cursor = await connection.execute(
                            "UPDATE balances SET amount = ROUND(amount - ?, 2) WHERE user_id = ? AND ROUND(amount * 100) >= ?",
                            (state["bet"], user.id, state["_betCents"]),
                        )
                        if cursor.rowcount != 1:
                            raise GameError("Недостаточно средств на балансе.")
                        finished, won = False, False
                    else:
                        if not row:
                            raise GameError("Активный раунд не найден.", 409)
                        state = json.loads(row[0])
                        finished, won = self.progressive_move(game, action, payload, state)
                    if finished:
                        payout_cents = state["_betCents"] * state["_multiplier"] // MULTIPLIER_SCALE if won else 0
                        await connection.execute("UPDATE balances SET amount = ROUND(amount + ?, 2) WHERE user_id = ?", (payout_cents / 100, user.id))
                        state.update({"active": False, "canCashout": False, "win": won, "winAmount": payout_cents / 100, "result": "win" if won else "lose", "serverSeed": state["_seed"]})
                        state["minePositions" if game == "mines" else "stonePositions"] = state["_positions"]
                        response = self.public_progressive_state(state)
                        await connection.execute(
                            "INSERT INTO webapp_rounds(public_id,game,user_id,username,bet_cents,payout_cents,request_id,request_digest,response,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (state["roundId"], game, user.id, state["username"], state["_betCents"], payout_cents, request_id, digest, serialize(response), self.clock().isoformat()),
                        )
                        await connection.execute("DELETE FROM webapp_active_games WHERE user_id = ? AND game = ?", (user.id, game))
                    else:
                        await connection.execute(
                            "INSERT INTO webapp_active_games(user_id,game,data) VALUES (?,?,?) ON CONFLICT(user_id,game) DO UPDATE SET data = excluded.data",
                            (user.id, game, serialize(state)),
                        )
                        response = self.public_progressive_state(state)
                    response["balance"] = await self.balance(connection, user.id)
                    await connection.execute(
                        "INSERT INTO webapp_requests(user_id,request_id,request_digest,response) VALUES (?,?,?,?)",
                        (user.id, request_id, digest, serialize(response)),
                    )
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)
'''

# ==================== leaders_backend.py ====================
_SOURCES['leaders_backend'] = r'''from datetime import date, datetime, time, timedelta

from games_backend import GameError, integer


BOT_GAME_TABLES = ("mines_history", "football_history", "basketball_history", "slot_history", "dice_history")


class LeadersMixin:
    def register_leaders(self, application):
        application.router.add_get("/api/leaders", self.handle_leaders)

    def leader_period(self, query):
        period = query.get("period", "all")
        now = self.clock()
        today = now.date()
        if period == "all":
            return None, None
        if period == "today":
            first, last = today, today
        elif period == "yesterday":
            first = last = today - timedelta(days=1)
        elif period == "week":
            first, last = today - timedelta(days=today.weekday()), today
        elif period == "month":
            first, last = today.replace(day=1), today
        elif period == "custom":
            try:
                raw_first, raw_last = query.get("from", ""), query.get("to", "")
                first, last = date.fromisoformat(raw_first), date.fromisoformat(raw_last)
                if first.isoformat() != raw_first or last.isoformat() != raw_last or first > last:
                    raise ValueError
            except (ValueError, TypeError):
                raise GameError("Укажите корректный период YYYY-MM-DD.") from None
        else:
            raise GameError("Неизвестный период рейтинга.")
        try:
            return datetime.combine(first, time.min, now.tzinfo).isoformat(), datetime.combine(last + timedelta(days=1), time.min, now.tzinfo).isoformat()
        except (OverflowError, ValueError):
            raise GameError("Период вне допустимого диапазона дат.") from None

    async def leaderboard_events(self, connection):
        async with connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cursor:
            tables = {row[0] for row in await cursor.fetchall()}
        sources = ["SELECT user_id,username,bet_cents,payout_cents AS paid_cents,created_at FROM webapp_rounds"]
        for table in BOT_GAME_TABLES:
            if table in tables:
                sources.append(f"SELECT user_id,'' AS username,CAST(ROUND(bet*100) AS INTEGER) AS bet_cents,CAST(ROUND(win_amount*100) AS INTEGER) AS paid_cents,created_at FROM {table}")
        if "crash_games" in tables:
            sources.append("SELECT user_id,'' AS username,CAST(ROUND(bet*100) AS INTEGER) AS bet_cents,CASE WHEN won = 1 THEN CAST(ROUND(bet*multiplier*100) AS INTEGER) ELSE 0 END AS paid_cents,created_at FROM crash_games")
        for table in ("webapp_pvp_rooms", "webapp_escape_duels"):
            if table not in tables:
                continue
            for role in ("creator", "opponent"):
                sources.append(f"SELECT {role}_id AS user_id,json_extract(data,'$.{role}Name') AS username,COALESCE(json_extract(data,'$._{role}BetCents'),json_extract(data,'$._betCents')) AS bet_cents,CASE WHEN json_extract(data,'$.isDraw') = 1 THEN COALESCE(json_extract(data,'$._{role}BetCents'),json_extract(data,'$._betCents')) WHEN json_extract(data,'$.winnerId') = {role}_id THEN CAST(ROUND(json_extract(data,'$.winAmount')*100) AS INTEGER) ELSE 0 END AS paid_cents,json_extract(data,'$.finishedAt') AS created_at FROM {table} WHERE status = 'finished'")
        names = "SELECT user_id,full_name AS name FROM usernames" if "usernames" in tables else "SELECT NULL AS user_id,NULL AS name WHERE 0"
        return " UNION ALL ".join(sources), names

    async def handle_leaders(self, request):
        try:
            user = self.validate_user(request)
            category = request.query.get("category", "turnover")
            if category not in {"turnover", "wins", "losses", "balance"}:
                raise GameError("Неизвестная категория рейтинга.")
            metric = request.query.get("metric", "count" if category == "wins" else "sum")
            if metric not in {"count", "sum"}:
                raise GameError("Неизвестная метрика рейтинга.")
            limit = integer(request.query.get("limit", "20"), 1, 100)
            first, end = self.leader_period(request.query)
            async with self.database_lock:
                connection = self.database()
                events, names = await self.leaderboard_events(connection)
                filters, values = "", []
                if first is not None and category != "balance":
                    filters = " WHERE julianday(created_at) >= julianday(?) AND julianday(created_at) < julianday(?)"
                    values = [first, end]
                monetary = category not in {"wins", "losses"} or metric == "sum"
                if category == "balance":
                    scores = "SELECT user_id,CAST(ROUND(amount*100) AS INTEGER) AS score FROM balances WHERE amount > 0"
                else:
                    if category == "turnover":
                        expression = "SUM(bet_cents)"
                    elif category == "wins":
                        expression = "SUM(CASE WHEN paid_cents > bet_cents THEN " + ("paid_cents-bet_cents" if metric == "sum" else "1") + " ELSE 0 END)"
                    else:
                        expression = "SUM(CASE WHEN paid_cents < bet_cents THEN " + ("bet_cents-paid_cents" if metric == "sum" else "1") + " ELSE 0 END)"
                    scores = "SELECT user_id," + expression + " AS score FROM events" + filters + " GROUP BY user_id HAVING score > 0"
                scores = "SELECT * FROM (" + scores + ") WHERE user_id NOT IN (SELECT user_id FROM webapp_privacy WHERE hidden = 1)"
                sql = "WITH events AS (" + events + "),names AS (" + names + "),scores AS (" + scores + "),ranked AS (SELECT user_id,score,ROW_NUMBER() OVER(ORDER BY score DESC,user_id ASC) AS place FROM scores) SELECT r.user_id,COALESCE(NULLIF((SELECT n.name FROM names n WHERE n.user_id=r.user_id),''),NULLIF((SELECT e.username FROM events e WHERE e.user_id=r.user_id AND e.username != '' ORDER BY e.created_at DESC LIMIT 1),''),CAST(r.user_id AS TEXT)),r.score,r.place FROM ranked r WHERE r.place <= ? OR r.user_id = ? ORDER BY r.place"
                async with connection.execute(sql, values + [limit, user.id]) as cursor:
                    records = await cursor.fetchall()
            rows, my_rank, my_score = [], None, 0
            for user_id, name, score, place in records:
                score = score / 100 if monetary else int(score)
                if place <= limit:
                    rows.append({"id": user_id, "user_id": user_id, "username": name, "score": score, "rank": place})
                if user_id == user.id:
                    my_rank, my_score = place, score
            return self.response({"ok": True, "rows": rows, "myRank": my_rank, "myScore": my_score, "category": category, "metric": metric, "period": request.query.get("period", "all")})
        except GameError as error:
            return self.failure(error)
'''

# ==================== live_games.py ====================
_SOURCES['live_games'] = r'''import asyncio
import hashlib
import json
import logging
import math
import secrets
import time
from decimal import Decimal, InvalidOperation

from pot_rules import POT_GAMES
from games_backend import GameError, money_cents, serialize
from game_rules import unit, payout


ROULETTE_OUTCOMES = [{"color": "red", "mult": 1.8, "weight": 0.45}, {"color": "black", "mult": 1.8, "weight": 0.45}, {"color": "green", "mult": 3.5, "weight": 0.1}]


class LiveGamesMixin:
    def register_live(self, application):
        for game in ("crash", "roulette"):
            application.router.add_get(f"/api/{game}/state", self.handle_live_state)
            application.router.add_get(f"/api/{game}/round", self.handle_live_round)
            application.router.add_get(f"/api/{game}/history", self.handle_history)
            application.router.add_post(f"/api/{game}/bet", self.handle_live_action)
        application.router.add_post("/api/crash/cashout", self.handle_live_action)

    async def initialize_live(self):
        async with self.database_lock:
            connection = self.database()
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_live_rounds(id TEXT PRIMARY KEY,game TEXT NOT NULL,data TEXT NOT NULL,finished INTEGER NOT NULL DEFAULT 0)")
            await connection.execute("CREATE INDEX IF NOT EXISTS idx_webapp_live_current ON webapp_live_rounds(game,finished)")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_live_bets(round_id TEXT NOT NULL,user_id INTEGER NOT NULL,data TEXT NOT NULL,PRIMARY KEY(round_id,user_id))")
            await connection.execute("CREATE TABLE IF NOT EXISTS webapp_live_queue(user_id INTEGER NOT NULL,game TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(user_id,game))")
            await connection.commit()
        self.live_task = asyncio.create_task(self.live_loop())

    async def live_loop(self):
        while True:
            # Do not start another transaction after a requested shutdown, even
            # if an awaited helper completed concurrently with cancellation.
            task = asyncio.current_task()
            if getattr(task, "cancelling", lambda: False)():
                return
            try:
                async with self.database_lock:
                    connection = self.database()
                    try:
                        await connection.execute("BEGIN IMMEDIATE")
                        await self.advance_blackjack_pvp(connection)
                        await self.expire_escape_duels(connection)
                        for pot_game in POT_GAMES:
                            for room in (1, 2):
                                await self.advance_pot(connection, pot_game, room)
                        for game in ("crash", "roulette"):
                            await self.advance_live(connection, game)
                        await connection.commit()
                    except BaseException:
                        await connection.rollback()
                        raise
            except asyncio.CancelledError:
                raise
            except Exception:
                logging.exception("Live game processing failed")
            await asyncio.sleep(0.2)

    async def live_bets(self, connection, round_id):
        async with connection.execute("SELECT user_id,data FROM webapp_live_bets WHERE round_id = ? ORDER BY rowid", (round_id,)) as cursor:
            return {row[0]: json.loads(row[1]) for row in await cursor.fetchall()}

    async def update_live_bet(self, connection, round_id, user_id, bet):
        await connection.execute("UPDATE webapp_live_bets SET data = ? WHERE round_id = ? AND user_id = ?", (serialize(bet), round_id, user_id))

    async def advance_live(self, connection, game):
        now = int(time.time() * 1000)
        async with connection.execute("SELECT data FROM webapp_live_rounds WHERE game = ? AND finished = 0", (game,)) as cursor:
            row = await cursor.fetchone()
        stored_data = row[0] if row else None
        state = json.loads(stored_data) if row else None
        if state is not None and state.get("_nextAt", now + 1) <= now:
            await connection.execute("UPDATE webapp_live_rounds SET finished = 1 WHERE id = ?", (state["roundId"],))
            state = None
        if state is None:
            seed = secrets.token_hex(32)
            round_id = ("C" if game == "crash" else "R") + secrets.token_hex(12).upper()
            state = {"ok": True, "roundId": round_id, "_seed": seed, "seedHash": hashlib.sha256(seed.encode()).hexdigest(), "status": "waiting", "waitingStartedAt": now, "waitSeconds": 10 if game == "crash" else 15, "growth": 0.1, "spinSeconds": 6, "createdAt": self.clock().isoformat()}
            if game == "crash":
                state["_crashPoint"] = max(1, min(1000, math.floor(90 / (1 - unit(seed, round_id))) / 100))
            else:
                roll = unit(seed, round_id)
                selected = ROULETTE_OUTCOMES[0] if roll < 0.45 else ROULETTE_OUTCOMES[1] if roll < 0.9 else ROULETTE_OUTCOMES[2]
                state.update({"_outcomeColor": selected["color"], "_outcomeMult": selected["mult"], "outcomes": ROULETTE_OUTCOMES})
            stored_data = serialize(state)
            await connection.execute("INSERT INTO webapp_live_rounds(id,game,data) VALUES (?,?,?)", (round_id, game, stored_data))
        if state["status"] == "waiting":
            async with connection.execute("SELECT user_id,data FROM webapp_live_queue WHERE game = ?", (game,)) as cursor:
                queued = await cursor.fetchall()
            for identifier, data in queued:
                await connection.execute("INSERT INTO webapp_live_bets(round_id,user_id,data) VALUES (?,?,?)", (state["roundId"], identifier, data))
            if queued:
                await connection.execute("DELETE FROM webapp_live_queue WHERE game = ?", (game,))
        bets = await self.live_bets(connection, state["roundId"])
        start = state["waitingStartedAt"] + state["waitSeconds"] * 1000
        if state["status"] == "waiting" and now >= start:
            if not bets and game != "crash":
                state["waitingStartedAt"] = now
            elif game == "crash":
                state.update({"status": "flying", "flyingStartedAt": start})
            else:
                state.update({"status": "spinning", "spinningStartedAt": start, "outcomeColor": state["_outcomeColor"], "outcomeMult": state["_outcomeMult"]})
        finished = False
        if game == "crash" and state["status"] == "flying":
            current = math.exp(min(20, (now - state["flyingStartedAt"]) / 1000 * state["growth"]))
            crash = state["_crashPoint"]
            for user_id, bet in bets.items():
                auto = bet.get("autoCashout")
                if not bet["settled"] and auto and auto <= crash and current >= auto:
                    await self.settle_live_bet(connection, game, state, user_id, bet, auto)
            if current >= crash:
                state.update({"status": "crashed", "crashPoint": crash, "serverSeed": state["_seed"], "_nextAt": now + 4000})
                for user_id, bet in bets.items():
                    if not bet["settled"]:
                        await self.settle_live_bet(connection, game, state, user_id, bet, 0)
                finished = True
        elif game == "roulette" and state["status"] == "spinning" and now >= state["spinningStartedAt"] + state["spinSeconds"] * 1000:
            state.update({"status": "resolved", "serverSeed": state["_seed"], "_nextAt": now + 4000})
            for user_id, bet in bets.items():
                if not bet["settled"]:
                    await self.settle_live_bet(connection, game, state, user_id, bet, 0)
            finished = True
        if finished:
            for user_id, bet in bets.items():
                detail = {key: value for key, value in state.items() if not key.startswith("_")}
                detail.update({"userId": user_id, "username": bet["username"], "bet": bet["bet"], "betAmount": bet["bet"], "winAmount": bet["winAmount"], "result": "win" if bet["winAmount"] > 0 else "lose", "cashoutMult": bet.get("cashoutMult", 0), "multiplier": bet.get("cashoutMult", 0), "items": bet.get("items", []), "active": False})
                await connection.execute("INSERT INTO webapp_rounds(public_id,game,user_id,username,bet_cents,payout_cents,request_id,request_digest,response,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (state["roundId"] + "_" + str(user_id), game, user_id, bet["username"], bet["_betCents"], bet["_paidCents"], "settle_" + state["roundId"], state["seedHash"], serialize(detail), self.clock().isoformat()))
        encoded = serialize(state)
        if encoded != stored_data:
            await connection.execute("UPDATE webapp_live_rounds SET data = ? WHERE id = ?", (encoded, state["roundId"]))
        return state

    async def settle_live_bet(self, connection, game, state, user_id, bet, multiplier):
        if bet["settled"]:
            return
        if game == "roulette":
            paid = 0
            for item in bet["items"]:
                item_paid = payout(item["_betCents"], state["_outcomeMult"]) if item["color"] == state["_outcomeColor"] else 0
                item["winAmount"] = item_paid / 100
                paid += item_paid
        else:
            paid = payout(bet["_betCents"], multiplier)
            bet.update({"cashoutMult": multiplier, "cashedOut": multiplier > 0})
        bet.update({"settled": True, "winAmount": paid / 100, "_paidCents": paid})
        await self.credit(connection, user_id, paid)
        await self.update_live_bet(connection, state["roundId"], user_id, bet)

    async def live_public(self, connection, game, state, user_id):
        response = {key: value for key, value in state.items() if not key.startswith("_")}
        bets = await self.live_bets(connection, state["roundId"])
        players = []
        for identifier, item in bets.items():
            public = {key: value for key, value in item.items() if not key.startswith("_")}
            public["id"] = identifier
            public["userId"] = identifier
            public["items"] = [{key: value for key, value in entry.items() if not key.startswith("_")} for entry in item.get("items", [])]
            players.append(public)
        async with connection.execute("SELECT data FROM webapp_live_rounds WHERE game = ? AND id != ? AND json_extract(data,'$.serverSeed') IS NOT NULL ORDER BY rowid DESC LIMIT 20", (game, state["roundId"])) as cursor:
            history = [{key: value for key, value in json.loads(row[0]).items() if not key.startswith("_")} for row in await cursor.fetchall()]
        own = next((player for player in players if player["id"] == user_id), None)
        response.update({"balance": await self.balance(connection, user_id), "players": players, "history": history})
        if game == "crash":
            async with connection.execute("SELECT data FROM webapp_live_queue WHERE game = ? AND user_id = ?", (game, user_id)) as cursor:
                queued = await cursor.fetchone()
            response.update({"myBet": own, "myQueued": {key: value for key, value in json.loads(queued[0]).items() if not key.startswith("_")} if queued else None})
        else:
            response.update({"myBets": own["items"] if own else [], "myQueued": [], "bets": [{"id": player["id"], "username": player["username"], **item} for player in players for item in player["items"]]})
        return response

    async def handle_live_state(self, request):
        user = self.validate_user(request)
        game = request.path.split("/")[2]
        async with self.database_lock:
            connection = self.database()
            try:
                await connection.execute("BEGIN IMMEDIATE")
                state = await self.advance_live(connection, game)
                response = await self.live_public(connection, game, state, user.id)
                await connection.commit()
                return self.response(response)
            except BaseException:
                await connection.rollback()
                raise

    async def handle_live_action(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            game, action = request.path.split("/")[2:4]
            key, signature = self.request_identity(request, payload)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    replay = await self.load_receipt(connection, user.id, key, signature)
                    if replay:
                        await connection.commit()
                        return self.response(replay)
                    state = await self.advance_live(connection, game)
                    bets = await self.live_bets(connection, state["roundId"])
                    if payload.get("roundId") != state["roundId"]:
                        raise GameError("Раунд изменился. Обновите игру.", 409)
                    if action == "cashout":
                        bet = bets.get(user.id)
                        if game != "crash" or state["status"] != "flying" or not bet or bet["settled"]:
                            raise GameError("Вывод в этом раунде недоступен.", 409)
                        multiplier = math.floor(math.exp((time.time() * 1000 - state["flyingStartedAt"]) / 1000 * state["growth"]) * 100) / 100
                        if multiplier >= state["_crashPoint"]:
                            raise GameError("Раунд уже завершён.", 409)
                        await self.settle_live_bet(connection, game, state, user.id, bet, multiplier)
                    else:
                        if state["status"] != "waiting":
                            raise GameError("Дождитесь следующего раунда.", 409)
                        if game == "crash":
                            async with connection.execute("SELECT 1 FROM webapp_live_queue WHERE game = ? AND user_id = ?", (game, user.id)) as cursor:
                                queued = await cursor.fetchone()
                            if user.id in bets or queued:
                                raise GameError("Ставка уже принята.", 409)
                            cents = money_cents(payload.get("bet"))
                            auto = payload.get("autoCashout")
                            if auto is not None:
                                try:
                                    auto = Decimal(str(auto))
                                    if not auto.is_finite() or not Decimal("1.01") <= auto <= 1000 or auto * 100 != (auto * 100).to_integral_value():
                                        raise ValueError
                                except (InvalidOperation, ValueError):
                                    raise GameError("Автовывод должен быть от x1.01 до x1000 с точностью 0.01.") from None
                                auto = float(auto)
                            bet = {"bet": cents / 100, "_betCents": cents, "autoCashout": auto, "cashedOut": False, "settled": False, "winAmount": 0}
                        else:
                            items = payload.get("items")
                            if not isinstance(items, list) or not 1 <= len(items) <= 3:
                                raise GameError("Выберите цвет ставки.")
                            existing = bets.get(user.id)
                            previous = existing["items"] if existing else []
                            taken = {item["color"] for item in previous}
                            valid = []
                            for item in items:
                                if not isinstance(item, dict) or not isinstance(item.get("color"), str) or item["color"] not in {"red", "black", "green"} or item["color"] in taken:
                                    raise GameError("Неизвестный или повторяющийся цвет ставки.")
                                cents = money_cents(item.get("bet"))
                                valid.append({"color": item["color"], "bet": cents / 100, "_betCents": cents, "winAmount": 0})
                                taken.add(item["color"])
                            cents = sum(item["_betCents"] for item in valid)
                            bet = {"bet": (cents + (existing["_betCents"] if existing else 0)) / 100, "_betCents": cents + (existing["_betCents"] if existing else 0), "items": previous + valid, "settled": False, "winAmount": 0}
                        await self.debit(connection, user.id, cents)
                        bet["username"] = " ".join(part for part in (user.first_name, user.last_name) if part)
                        await connection.execute("INSERT INTO webapp_live_bets(round_id,user_id,data) VALUES (?,?,?) ON CONFLICT(round_id,user_id) DO UPDATE SET data=excluded.data", (state["roundId"], user.id, serialize(bet)))
                    response = await self.live_public(connection, game, state, user.id)
                    await self.save_receipt(connection, user.id, key, signature, response)
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)

    async def handle_live_round(self, request):
        user = self.validate_user(request)
        game = request.path.split("/")[2]
        async with self.database_lock:
            connection = self.database()
            async with connection.execute("SELECT data FROM webapp_live_rounds WHERE game = ? AND id = ?", (game, request.query.get("id", ""))) as cursor:
                row = await cursor.fetchone()
            if row is None or "serverSeed" not in json.loads(row[0]):
                return self.failure(GameError("Завершённый раунд не найден.", 404))
            return self.response(await self.live_public(connection, game, json.loads(row[0]), user.id))
'''

# ==================== main.py ====================
_SOURCES['main'] = r'''import asyncio
import faulthandler
import hashlib
import time
import hmac
import logging
import math
import os
import re
import secrets
import sqlite3
import string
import sys
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from html import escape as html_escape
from types import SimpleNamespace
from pathlib import Path

import aiosqlite
from complete_games import CompleteGamesBackend
from games_backend import GameError
from privacy_rules import PRIVACY_CACHE, TELEGRAM_NAMES, player_identity
from aiohttp import web
from static_assets import static_response

from aiogram import BaseMiddleware, Bot, Dispatcher, Router, F
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineKeyboardButton,
    LabeledPrice,
    PreCheckoutQuery,
    CopyTextButton,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.utils.web_app import safe_parse_webapp_init_data
from contextvars import ContextVar

BOT_TOKEN = __server_config__['BOT_TOKEN']
CHANNEL_ID = __server_config__['CHANNEL_ID']
CHANNEL_URL = __server_config__['CHANNEL_URL']
CHAT_URL = __server_config__['CHAT_URL']

DB_PATH = "bot.db"
BACKUP_PATH = "bot_backup.db"
BACKUP_INTERVAL_SECONDS = 6 * 3600
TOPUP_MAX = 10000
MINES_STALE_SECONDS = 6 * 3600
DB_LOCK_TIMEOUT = 30

HASH_ALPHABET = string.ascii_lowercase + string.digits

WEBHOOK_HOST = __server_config__['WEBHOOK_HOST']
WEBHOOK_PATH = __server_config__['WEBHOOK_PATH']
WEBHOOK_SECRET = __server_config__['WEBHOOK_SECRET']
WEBAPP_HOST = __server_config__['WEBAPP_HOST']
WEBAPP_PORT = __server_config__['WEBAPP_PORT']

HOUSE_EDGE = 0.90
MAX_MULTIPLIER = 10.0
MIN_BET = 0.5

ALL_IN_ALIASES = {"все", "всё", "вб", "банк"}
HALF_ALIASES = {"пол", "половина", "половину", "хаф"}

ADMIN_ID = __server_config__['ADMIN_ID']

MSK = timezone(timedelta(hours=3))
BONUS_COOLDOWN = timedelta(hours=12)
BONUS_BIO_TEXT = "@mjrstars"
BONUS_BASE_MIN = 1.0
BONUS_BASE_MAX = 3.0
BONUS_STREAK_BASE = 0.1
BONUS_STREAK_STEP = 0.05

# Telegram language preference is stored per account. The outgoing API middleware
# localizes messages and keyboard labels, including delayed game results.
TELEGRAM_LANGUAGE_CACHE: dict[int, str] = {}
CURRENT_TELEGRAM_USER: ContextVar[int | None] = ContextVar("telegram_locale_user", default=None)
CURRENT_TELEGRAM_LANGUAGE: ContextVar[str] = ContextVar("telegram_locale_language", default="ru")

RU_EN_PHRASES = {
    "Заработать на чате": "Earn with your chat",
    "Профиль | Бонусы": "Profile | Bonuses",
    "Топ | Реф. программа": "Top | Referral program",
    "Хочу своё казино": "I want my own casino",
    "Добавить в чат": "Add to chat",
    "Заработок на чате": "Earn with your chat",
    "Пополнить | Вывести": "Deposit | Withdraw",
    "Пополнить": "Deposit",
    "Вывести": "Withdraw",
    "Вывести всё": "Withdraw all",
    "Транзакции": "Transactions",
    "Все операции": "All operations",
    "Пополнения": "Deposits",
    "Выводы": "Withdrawals",
    "Назад": "Back",
    "Настройки": "Settings",
    "Русский": "Russian",
    "Анонимность": "Anonymous",
    "Анонимно": "Anonymous",
    "Имя Telegram": "Telegram name",
    "Telegram-имя": "Telegram name",
    "Никнейм": "Nickname",
    "Добавить никнейм": "Add nickname",
    "Изменить никнейм": "Change nickname",
    "Отображаемое имя в топе": "Leaderboard display name",
    "Ваш профиль": "Your profile",
    "Профиль:": "Profile:",
    "Дата регистрации:": "Registration date:",
    "Регистрация:": "Registration:",
    "Баланс:": "Balance:",
    "Оборот:": "Turnover:",
    "Выданные бонусы:": "Bonuses received:",
    "Пополнено:": "Deposits:",
    "Выведено:": "Withdrawals:",
    "Имя:": "Name:",
    "ID:": "ID:",
    "Страница": "Page",
    "Страница не найдена.": "Page not found.",
    "Операций пока нет.": "No transactions yet.",
    "Нет операций для выбранного фильтра.": "No transactions for this filter.",
    "Введите сумму цифрами или нажмите «Вывести всё». Для отмены напишите «отмена».": "Enter an amount or tap “Withdraw all”. To cancel, send “cancel”.",
    "Псевдоним должен содержать от 3 до 20 букв, цифр или знаков подчёркивания.": "A nickname must be 3–20 letters, digits, or underscores.",
    "Отправьте новый псевдоним одним сообщением. Для отмены нажмите «Назад».": "Send your new nickname in one message. Tap “Back” to cancel.",
    "Псевдоним сохранён.": "Nickname saved.",
    "Сначала добавьте никнейм.": "Add a nickname first.",
    "Выберите отображаемое имя для рейтинга.": "Choose a display name for the leaderboard.",
    "Показывать в рейтинге как «Аноним».": "Show as “Anonymous” in the leaderboard.",
    "В чате участники автоматически связываются с его владельцем. Вы получаете 50% чистых проигрышей по ставкам, сделанным именно в этом чате.": "Chat members are automatically linked to the chat owner. Earn 50% of net losses on bets placed in this chat.",
    "Добавьте бота в чат администратором, чтобы автоматическое подключение участников работало.": "Add the bot to your chat as an administrator to link members automatically.",
    "Канал обновлений": "Updates channel",
    "Мы обновили MajorStars! Теперь в боте есть профиль, настройки и подробная история операций.": "MajorStars has been updated! The bot now includes a profile, settings, and a detailed transaction history.",
    "«Большие победы начинаются с одного шага».": "“Big wins begin with a single step.”",
    "Установить язык: Русский": "Set language: Russian",
    "Установить язык: English": "Set language: English",
    "Новый псевдоним:": "New nickname:",
    "Укажите сумму.": "Enter an amount.",
    "Недостаточно средств!": "Insufficient funds!",
    "Недостаточно средств": "Insufficient funds",
    "Ошибка результата. Ставка возвращена.": "Invalid result. Your bet has been refunded.",
    "Не удалось отправить игру. Ставка возвращена.": "Could not start the game. Your bet has been refunded.",
    "Игра уже завершена.": "The game is already over.",
    "Это не ваша игра!": "This is not your game!",
    "Откройте хотя бы одну клетку!": "Open at least one cell!",
    "Эта клетка уже открыта!": "This cell is already open!",
    "Вы не подписаны на обязательные каналы!": "You are not subscribed to the required channels!",
    "вы <b>выиграли</b>": "you <b>won</b>",
    "вы <b>проиграли</b>": "you <b>lost</b>",
    "правильное использование команды": "Correct command usage",
    "Ваш баланс:": "Your balance:",
    "Баланс после вывода:": "Balance after withdrawal:",
    "Минимальная ставка": "Minimum bet",
    "минимальная сумма вывода —": "minimum withdrawal amount is",
    "минимальный баланс для вывода —": "minimum balance for withdrawal is",
    "Ваш профиль:": "Your profile:",
    "Дата регистрации": "Registration date",
    "Самый большой выигрыш": "Largest win",
    "Самая большая ставка за игру": "Largest bet",
    "Сыграно игр": "Games played",
    "Реферальная система": "Referral program",
    "Пополнение": "Deposit",
    "Вывод": "Withdrawal",
    "Выберите": "Choose",
    "введите": "enter",
    "Ставка:": "Bet:",
    "Мин:": "Mines:",
    "Потенциальный выигрыш:": "Potential payout:",
    "Могли выиграть:": "Possible win:",
    "Вы выиграли": "You won",
    "вы проиграли": "you lost",
    "вы забрали выигрыш!": "you collected your winnings!",
    "вы добрались до конца!": "you reached the end!",
    "Ваша заявка добавлена в обработку!": "Your request has been queued for processing!",
    "Ракета упала на": "The rocket crashed at",
    "Новая заявка на вывод": "New withdrawal request",
    "Пополнение баланса": "Balance deposit",
    "Подписка": "Subscription",
    "На вашем балансе:": "Your balance:",
    "Ваш реферальный баланс:": "Your referral balance:",
}

# Word-level fallback covers generated game quotes and variable messages. Common
# full sentences above are translated first so the English stays natural.
RU_EN_WORDS = {
    "не": "not", "в": "in", "и": "and", "но": "but", "тебя": "you", "тебе": "you",
    "твою": "your", "твоей": "your", "твой": "your", "твой": "your", "твоё": "your",
    "твоего": "your", "твои": "your", "твоим": "your", "это": "this", "за": "for",
    "на": "on", "а": "and", "с": "with", "по": "for", "от": "from", "ты": "you",
    "вы": "you", "ваш": "your", "ваша": "your", "вас": "you", "вам": "you", "ваши": "your",
    "сегодня": "today", "против": "against", "пользу": "favor", "значит": "so", "удачу": "luck",
    "удача": "luck", "удачной": "good", "игры": "games", "игра": "game", "игру": "game",
    "игре": "game", "игрок": "player", "игрока": "player", "игроки": "players", "игр": "games",
    "ставка": "bet", "ставки": "bets", "ставку": "bet", "ставкой": "bet", "ставке": "bet",
    "баланс": "balance", "баланса": "balance", "балансе": "balance", "балансу": "balance",
    "сумма": "amount", "сумму": "amount", "суммы": "amount", "суммой": "amount", "число": "number",
    "числа": "numbers", "чисел": "numbers", "числу": "number", "игра": "game", "игре": "game",
    "больше": "higher", "меньше": "lower", "бонус": "bonus", "бонусы": "bonuses", "игра": "game",
    "мимо": "miss", "классик": "classic", "классика": "classic", "число": "number", "аут": "out",
    "цель": "target", "целью": "target", "результат": "result", "результата": "result", "результате": "result",
    "попал": "hit", "попадание": "hit", "попала": "hit", "попало": "hit", "попали": "hit",
    "выиграли": "won", "выиграл": "won", "выиграла": "won", "выигрыш": "win", "выигрыша": "win",
    "выиграть": "win", "выигрышные": "winning", "выигрышное": "winning", "проиграли": "lost",
    "проиграл": "lost", "проиграла": "lost", "проигрыш": "loss", "победа": "victory", "поражение": "defeat",
    "уже": "already", "недостаточно": "not enough", "средств": "funds", "средства": "funds",
    "минимальная": "minimum", "минимальный": "minimum", "минимальное": "minimum", "минимальное": "minimum",
    "максимальный": "maximum", "максимальная": "maximum", "минимум": "minimum", "максимум": "maximum",
    "сумма": "amount", "вывод": "withdrawal", "вывода": "withdrawal", "вывести": "withdraw", "выводы": "withdrawals",
    "пополнение": "deposit", "пополнения": "deposits", "пополнить": "deposit", "пополнений": "deposits",
    "выводом": "withdrawal", "депозит": "deposit", "депозита": "deposit", "депозитов": "deposits",
    "игра": "game", "завершена": "over", "окончена": "over", "закончена": "over", "ошибка": "error",
    "некорректный": "invalid", "правильное": "correct", "использование": "usage", "команды": "commands",
    "команда": "command", "команду": "command", "команде": "command", "команд": "commands",
    "введите": "enter", "введи": "enter", "нажмите": "tap", "выберите": "choose", "выбери": "choose",
    "получить": "get", "получил": "received", "получили": "received", "успешно": "successfully",
    "успешный": "successful", "успешная": "successful", "возвращена": "refunded", "возврат": "refund",
    "вернули": "refunded", "вернуть": "refund", "отправить": "send", "отправлено": "sent", "удалось": "could",
    "не": "not", "временно": "temporarily", "недоступен": "unavailable", "канал": "channel", "каналы": "channels",
    "подписаны": "subscribed", "подписан": "subscribed", "подписаны": "subscribed", "ссылка": "link",
    "реферальная": "referral", "реферальный": "referral", "реферальном": "referral", "рефералов": "referrals",
    "рефералы": "referrals", "реферал": "referral", "рефералов": "referrals", "приглашений": "invites",
    "приглашении": "inviting", "приглашения": "invites", "заработок": "earnings", "заработано": "earned",
    "заработать": "earn", "заработал": "earned", "награда": "reward", "друга": "friend", "друзей": "friends",
    "знакомых": "acquaintances", "пользователь": "user", "пользователя": "user", "пользователю": "user",
    "пользователи": "users", "профиль": "profile", "профиле": "profile", "настройки": "settings",
    "регистрация": "registration", "дата": "date", "неизвестна": "unknown", "получатель": "recipient",
    "имя": "name", "псевдоним": "nickname", "новый": "new", "новая": "new", "сохранён": "saved",
    "сохранена": "saved", "описание": "bio", "текст": "text", "сообщение": "message", "сообщения": "messages",
    "игрок": "player", "игры": "games", "начните": "start", "начните": "start", "начать": "start",
    "сначала": "first", "можно": "can", "должен": "must", "нужно": "need", "нужен": "needed",
    "подождите": "wait", "попробуйте": "try", "снова": "again", "осталось": "remaining", "ждать": "wait",
    "очереди": "queue", "очередь": "queue", "минуты": "minutes", "минут": "minutes", "часа": "hours",
    "часов": "hours", "день": "day", "дня": "days", "дней": "days", "сумму": "amount",
    "клетка": "cell", "клетку": "cell", "клетки": "cells", "открыта": "open", "откройте": "open",
    "одну": "one", "хотя": "at least", "мине": "mine", "мина": "mine", "мины": "mines", "мин": "mines",
    "проиграли": "lost", "игракено": "Keno", "играрулетка": "Roulette", "доступные": "available",
    "баскетбол": "basketball", "футбол": "football", "боулинг": "bowling", "дартс": "darts", "слоты": "slots",
    "краш": "crash", "мины": "mines", "куб": "dice", "кубы": "dice", "кубик": "die", "играть": "play",
    "играйте": "play", "красное": "red", "красный": "red", "белое": "white", "белый": "white",
    "чёт": "even", "чет": "even", "нечет": "odd", "нечёт": "odd", "числа": "numbers", "диапазон": "range",
    "диапазоны": "ranges", "минимальная": "minimum", "множитель": "multiplier", "мяч": "ball", "гол": "goal",
    "ворот": "goal", "ворота": "goal", "штанга": "post", "перелёт": "over", "девятка": "top corner",
    "нижний": "low", "право": "right", "вправо": "right", "центр": "center", "прямо": "straight",
    "отскок": "bounce", "застрянет": "gets stuck", "застрял": "got stuck", "почти": "almost", "бросок": "shot",
    "кегли": "pins", "кеглей": "pins", "кегля": "pin", "страйк": "strike", "тройка": "three", "четвёрка": "four",
    "пятёрка": "five", "шестёрка": "six", "двойка": "two", "единица": "one", "один": "one", "одно": "one",
    "одна": "one", "два": "two", "две": "two", "три": "three", "четыре": "four", "пять": "five", "шесть": "six",
    "первое": "first", "второе": "second", "третье": "third", "четвёртое": "fourth", "пятое": "fifth", "шестое": "sixth",
    "барабаны": "reels", "остановились": "stopped", "крутил": "spun", "шар": "ball", "сектор": "sector",
    "цвет": "color", "красный": "red", "белый": "white", "белое": "white", "черный": "black", "чёрный": "black",
    "выбрала": "chose", "фортуну": "fortune", "удаче": "luck", "удача": "luck", "везения": "luck", "везение": "luck",
    "мяч": "ball", "щит": "backboard", "щита": "backboard", "кольцо": "hoop", "кольца": "hoop", "кольцом": "hoop",
    "попал": "hit", "попала": "hit", "попало": "hit", "забить": "score", "забил": "scored", "забили": "scored",
    "удар": "shot", "ударом": "shot", "низкий": "low", "низом": "low", "верхний": "upper", "угол": "corner",
    "деньгам": "money", "деньги": "money", "денег": "money", "минус": "loss", "плюсе": "ahead", "сгорела": "was lost",
    "сгорело": "was lost", "сгорел": "was lost", "кассы": "cash desk", "результат": "result", "раз": "time", "бывает": "happens",
    "просто": "just", "чуть": "a little", "и": "and", "тоже": "too", "значит": "means", "почти": "almost", "зато": "but",
    "без": "without", "красиво": "beautifully", "больно": "painful", "игры": "games", "классика": "classic", "жанра": "style",
    "надёжно": "reliably", "надежно": "reliably", "учебнику": "textbook", "стандартный": "standard", "плану": "plan",
    "стороне": "side", "принесла": "brought", "принёс": "brought", "сыграло": "played", "сыграл": "played", "сыграли": "played",
    "принёс": "brought", "зашло": "hit", "зашла": "hit", "хватило": "was enough", "твой": "your", "твоей": "your",
    "сантиметры": "centimeters", "отделили": "separated", "идеальный": "perfect", "удар": "shot", "цель": "target",
    "штанги": "post", "вратаря": "goalkeeper", "дерево": "wood", "спасло": "saved", "спасла": "saved", "помог": "helped",
    "помогла": "helped", "помешала": "got in the way", "рикoшет": "ricochet", "рикoшет": "ricochet", "рикошет": "ricochet",
    "вмешалась": "intervened", "случай": "case", "редкий": "rare", "судьба": "fate", "завис": "got stuck", "застрял": "got stuck",
    "грани": "edge", "залетел": "went in", "центр": "center", "центру": "center", "вправо": "right", "правее": "to the right",
    "ушёл": "went", "ушел": "went", "неберущийся": "unstoppable", "точнее": "more accurately", "прямолинейно": "directly",
    "эффективно": "effectively", "вернее": "safer", "прогадал": "misjudged", "земле": "ground", "вверх": "up", "выше": "above",
    "ниже": "below", "настроение": "mood", "признак": "sign", "мастерства": "skill", "стабильность": "consistency",
    "подвела": "let down", "изменила": "failed", "соперника": "opponent", "соперник": "opponent", "разочарование": "disappointment",
    "попытка": "attempt", "засчитана": "counts", "трибуны": "stands", "орбите": "orbit", "мусорке": "trash", "пропасть": "abyss",
    "яблочко": "bullseye", "мишени": "target", "стену": "wall", "проволоки": "wire", "проволока": "wire", "срикошетил": "ricocheted",
    "крутить": "spin", "чётное": "even", "четное": "even", "нечётное": "odd", "нечетное": "odd", "малое": "small", "большое": "large",
    "игра": "game", "много": "many", "пара": "pair", "набор": "set", "полный": "full", "половины": "half", "всего": "total",
    "остановился": "stopped", "неважно": "doesn't matter", "снесена": "knocked down", "снесены": "knocked down",
    "формат": "format", "целое": "whole", "платёжный": "payment", "следующий": "next", "предыдущей": "previous",
    "операции": "transactions", "ошибке": "error", "удалось": "possible", "отдельная": "separate", "отдельно": "separately",
    "принято": "accepted", "принятый": "accepted", "подтверждены": "confirmed", "проверены": "checked", "проверенных": "checked",
    "обработано": "processed", "обработан": "processed", "обнаружены": "found", "тест": "test", "иконки": "icons", "кнопка": "button",
    "кнопок": "buttons", "контекстам": "contexts", "отправляю": "sending", "отправками": "between sends", "пауза": "pause",
    "виден": "visible", "сообщении": "message", "проверка": "check", "проверьте": "check", "проверить": "check", "при": "on",
    "у": "at", "вас": "you", "профиле": "profile", "отсутствует": "missing", "нужное": "required", "подождите": "wait",
    "если": "if", "установили": "set", "снова": "again", "серию": "streak", "забираете": "claim", "размере": "amount",
    "встали": "joined", "очередь": "queue", "получен": "received", "получена": "received", "заявка": "request", "заявку": "request",
    "сервис": "service", "подключён": "connected", "учитывается": "counted", "основной": "main", "данном": "this", "боте": "bot",
    "можешь": "can", "поднять": "earn", "звезды": "Stars", "звёзды": "Stars", "свой": "your", "аккаунт": "account",
    "автоматическая": "automatic", "повторная": "duplicate", "доставка": "delivery", "исходного": "original", "сообщения": "message",
    "защищена": "protected", "двойного": "duplicate", "начисления": "credits", "начисление": "credit", "выполняются": "processed",
    "анимацию": "animation", "клиенте": "client", "менялись": "changed", "гарантирует": "guarantees", "среди": "among",
    "начислен": "credited", "готов": "ready", "позже": "later", "итог": "result", "пополнен": "credited", "администратору": "administrator",
    "установи": "set", "данный": "this", "нужен": "needed", "быть": "be", "самому": "yourself", "себе": "yourself",
    "получатель": "recipient", "обязательные": "required", "каналы": "channels", "бот": "bot", "запущен": "started", "использовано": "used",
    "другого": "another", "отправьте": "send", "новую": "new", "команду": "command", "того": "that", "сервис": "service",
    "временно": "temporarily", "недоступен": "unavailable", "перевод": "transfer", "переводить": "transfer", "переводы": "transfers",
    "комиссия": "fee", "комиссии": "fees", "комиссией": "fee", "процентов": "percent", "процентах": "percent", "бесплатно": "free",
    "попробуйте": "try", "добавить": "add", "добавлена": "added", "добавлен": "added", "добавлена": "added", "обработка": "processing",
    "время": "time", "суммой": "amount", "получили": "received", "выданные": "issued", "бонусы": "bonuses", "оборот": "turnover",
    "пополнений": "deposits", "выводов": "withdrawals", "дата": "date", "регистрации": "registration", "аноним": "anonymous",
    "никнейм": "nickname", "имя": "name", "имени": "name", "русский": "Russian", "английский": "English", "пока": "for now",
    "скоро": "soon", "подписку": "subscription", "проверить": "check", "последний": "last", "последняя": "last", "номер": "number",
    "идентификатор": "ID", "попробуйте": "try", "всегда": "always", "правильно": "correctly", "первый": "first", "первого": "first",
    "следующего": "next", "следующая": "next", "выберите": "select", "выбрали": "selected", "текущий": "current", "текущая": "current",
    "текущую": "current", "остаток": "remaining", "сумме": "amount", "сумма": "amount", "внесли": "deposited", "неделя": "week",
    "неделю": "week", "недели": "weeks", "доступен": "available", "доступно": "available", "сохранены": "saved", "сохраните": "save",
    "открыть": "open", "проверил": "checked", "проверь": "check", "отказ": "rejected", "отклонено": "rejected", "отклонена": "rejected",
    "одобрено": "approved", "одобрена": "approved", "одобрить": "approve", "отклонить": "reject", "отменён": "cancelled", "отмена": "cancel",
    "наличии": "available", "введите": "enter", "цифрами": "using digits", "нажмите": "tap", "напишите": "send", "сумму": "amount",
    "платёж": "payment", "счёт": "invoice", "инвойс": "invoice", "покупка": "purchase", "пополните": "deposit", "балансе": "balance",
    "главное": "the key", "значит": "means", "бывает": "happens", "просто": "just", "игра": "game", "пользователь": "user",
    "про": "about", "наш": "our", "нашем": "our", "нашей": "our", "чате": "chat", "беседе": "chat", "канал": "channel",
    "владельца": "owner", "владельцем": "owner", "участник": "member", "участники": "members", "сообщение": "message",
    "связаны": "linked", "автоматически": "automatically", "проигрышей": "losses", "чистых": "net", "проигрыш": "loss",
    "проигрыши": "losses", "каждого": "each", "именно": "exactly", "сделанным": "placed", "добавьте": "add", "администратором": "as administrator",
    "работало": "works", "участников": "members", "приглашённый": "invited", "приглашенные": "invited", "собственных": "own", "своё": "own",
    "казино": "casino", "познакомиться": "meet", "исходный": "original", "попытка": "attempt", "закрыто": "closed", "открыто": "open",
    "когда": "when", "где": "where", "разницу": "difference", "мог": "could", "получить": "get", "подписаны": "subscribed",
}


RU_EN_PHRASES.update({
    "Привет,": "Hello,",
    "Канал обновлений:": "Updates channel:",
    "Мы обновили MajorStars!": "MajorStars has been updated!",
    "Теперь в боте удобнее следить за профилем, балансом и операциями.": "The bot now makes it easier to track your profile, balance, and transactions.",
    "Добавьте бота администратором. Участники, вступившие в чат, автоматически связываются с его владельцем. Владелец получает 50% чистых проигрышей по ставкам, сделанным именно в этом чате.": "Add the bot as an administrator. New chat members are automatically linked to the chat owner. The owner receives 50% of net losses on bets placed in that chat.",
    "Отображаемое имя в топе:": "Leaderboard display name:",
    "По умолчанию используется имя Telegram. Режим «Анонимность» показывает в рейтинге имя «Аноним».": "Your Telegram name is used by default. Anonymous mode shows your leaderboard name as “Anonymous”.",
    "Выберите раздел MajorStars:": "Choose a MajorStars section:",
    "Отправьте новый псевдоним одним сообщением. Для отмены нажмите «Назад».": "Send your new nickname in one message. Tap “Back” to cancel.",
    "Псевдоним должен содержать от 3 до 20 букв, цифр или знаков подчёркивания.": "A nickname must contain 3–20 letters, digits, or underscores.",
    "Барабаны остановились там, где нужно.": "The reels stopped where they should.",
    "Три в ряд — и это твой день.": "Three in a row — this is your day.",
    "Слоты улыбнулись именно тебе.": "The slots smiled on you.",
    "Крутил не зря.": "That spin was worth it.",
    "Фортуна выбрала тебя.": "Fortune chose you.",
    "Барабаны остановились, но не там.": "The reels stopped, but not in the right place.",
    "Удача — дама капризная.": "Luck can be fickle.",
    "Не в этот раз.": "Not this time.",
    "Слоты — игра терпеливых.": "Slots reward the patient.",
    "Крути ещё, повезёт.": "Spin again; your luck may turn.",
    "Барабаны остановились, но не там.": "The reels stopped, but not in the right place.",
    "Мяч улетел на трибуны.": "The ball flew into the stands.",
    "Гол есть гол.": "A goal is a goal.",
    "Штанга. Ещё чуть-чуть и был бы гол.": "The post! Just a little closer and it would have been a goal.",
    "Звон штанги — музыка для ушей.": "The post's clang is music to the ears.",
    "Просто и со вкусом.": "Simple and tasteful.",
    "Мяч в сетке.": "The ball is in the net.",
    "Чётко и по делу.": "Clean and effective.",
    "Правее — оно и вернее.": "A little to the right can be just right.",
    "Вправо, но в точку.": "To the right and right on target.",
    "Перелёт. Мяч улетел за ворота.": "Too high. The ball sailed over the goal.",
    "Низом пошёл.": "A low shot.",
    "Мяч прошёл по земле.": "The ball rolled along the ground.",
    "Мимо. И это стоило тебе ставки.": "A miss, and it cost you your bet.",
    "Гол был, но не в твою сторону.": "There was a goal, but not in your favor.",
    "Мяч в сетке, а ставка сгорела.": "The ball is in the net, but your bet is gone.",
    "Гол есть гол, но не для тебя.": "A goal is a goal, just not for you.",
    "Мяч в сетке, ставка в мусорке.": "The ball is in the net; your bet is in the trash.",
    "Чётко и по делу — против тебя.": "Clean and effective — against you.",
    "Без выкрутасов, зато с твоим минусом.": "No tricks, just a loss for you.",
    "Вправо, и не в твою сторону.": "To the right, but not in your favor.",
    "Право — не всегда стратегия.": "Going right is not always a strategy.",
    "Перелёт. Мяч улетел, деньги тоже.": "Too high. The ball flew away, and so did the money.",
    "Мяч на орбите, а ты на дне.": "The ball is in orbit, and you're down in the dumps.",
    "Низом пошёл, и мимо тебя.": "A low shot, and you missed out.",
    "Низкий удар — низкий результат для тебя.": "A low shot means a low return for you.",
    "Скромно, но обидно.": "Small, but painful.",
    "Чистое попадание.": "A clean hit.",
    "Как по учебнику.": "Textbook perfect.",
})

RU_EN_WORDS.update({
    "выпала": "came up", "выпал": "came up", "выпало": "came up", "выпали": "came up",
    "промах": "miss", "засчитано": "counts", "нет": "no", "нету": "none", "ждал": "waited",
    "пришло": "came", "то": "that", "как": "as", "всё": "all", "все": "all", "ноль": "zero",
    "улетел": "flew away", "для": "for", "выкрутасов": "tricks", "или": "or", "банк": "bank",
    "дротик": "dart", "забирай": "collect", "дать": "give", "ещё": "more", "реф": "referral",
    "только": "only", "учили": "taught", "до": "to", "там": "there", "есть": "is", "стоило": "cost",
    "стратегия": "strategy", "скромно": "modestly", "повторить": "play again", "половина": "half", "половину": "half",
    "этот": "this", "этого": "this", "его": "its", "был": "was", "сетке": "net", "чистое": "clean",
    "оказался": "turned out", "выгодным": "profitable", "иногда": "sometimes", "зашёл": "worked", "зашел": "worked",
    "никуда": "nowhere", "обошёлся": "cost", "обошелся": "cost", "дорого": "dearly", "к": "to", "зарегистрирован": "registered",
    "эмодзи": "emoji", "чат": "chat", "чате": "chat", "чата": "chat", "чаты": "chats", "чату": "chat",
    "ровно": "exactly", "бота": "bot", "чётко": "precisely", "четко": "precisely", "делу": "matter", "пошёл": "went",
    "пошел": "went", "прошёл": "passed", "прошел": "passed", "сторону": "side", "обидно": "painful", "успех": "success",
    "между": "between", "такое": "such", "году": "year", "нестандартный": "unusual", "сможешь": "you can", "точно": "exactly",
    "забрал": "collected", "приносит": "brings", "жёлоб": "gutter", "желоб": "gutter", "сыграла": "played", "хороший": "good",
    "принесло": "brought", "раздел": "section", "запустите": "start", "личном": "private", "ботом": "bot", "включая": "including",
    "чтобы": "so that", "обработана": "processed", "приложение": "app", "запрос": "request", "найден": "found", "он": "it",
    "будет": "will be", "количество": "number", "ответом": "response", "нельзя": "cannot", "ракета": "rocket", "упала": "crashed",
    "например": "for example", "ряд": "row", "улыбнулись": "smiled", "зря": "in vain", "фортуна": "fortune", "дама": "lady",
    "капризная": "fickle", "терпеливых": "patient", "крути": "spin", "повезёт": "may be lucky", "повезет": "may be lucky",
    "хочешь": "want", "открывает": "unlocks", "переводах": "transfers", "никакой": "no", "чистый": "clean", "обычные": "regular",
    "почувствуй": "feel", "должны": "should", "доходить": "arrive", "полностью": "fully", "забудь": "forget", "о": "about",
    "переводит": "transfers", "мы": "we", "обновили": "updated", "теперь": "now", "удобнее": "easier", "следить": "track",
    "профилем": "profile", "балансом": "balance", "операциями": "transactions", "вступившие": "who joined", "связываются": "are linked",
    "владелец": "owner", "получает": "receives", "ставкам": "bets", "этом": "this", "бы": "would", "звон": "clang",
    "музыка": "music", "ушей": "ears", "со": "with", "вкусом": "taste", "оно": "it", "точку": "spot", "минусом": "loss",
    "дне": "bottom", "дамках": "on top", "щитом": "backboard", "зачли": "counted", "уплыли": "drifted away", "ключевое": "key",
    "слово": "word", "считается": "counts", "повторного": "duplicate", "идёт": "is running", "идет": "is running", "подорвались": "hit a mine",
    "тут": "here", "своих": "your", "обычного": "regular", "также": "also", "будете": "will", "получать": "receive", "ваших": "your",
    "статистика": "statistics", "заработка": "earnings", "чатах": "chats", "каждом": "each", "грязный": "dirty", "десять": "ten",
    "шара": "ball", "чистая": "clean", "дорожка": "lane", "одним": "one", "выигрышная": "winning", "случился": "happened",
    "устояли": "held", "получился": "turned out", "оба": "both", "крупно": "big", "выигрышный": "winning", "единицу": "one",
    "двойку": "two", "тройку": "three", "четвёрку": "four", "четверку": "four", "пятёрку": "five", "пятерку": "five",
    "шестёрку": "six", "шестерку": "six", "совершили": "made", "составила": "was", "перевел": "transferred", "перевёл": "transferred",
    "привет": "hello", "умолчанию": "default", "используется": "is used", "режим": "mode", "показывает": "shows", "рейтинге": "leaderboard",
    "доступна": "available", "учёт": "account", "невалидные": "invalid", "никакие": "no", "друг": "friend", "после": "after",
    "реферальные": "referral", "добро": "welcome", "пожаловать": "welcome", "диагностическая": "diagnostic", "администратора": "administrator",
    "ввод": "entry", "заморожен": "frozen", "через": "through", "доступа": "access", "чужому": "someone else's", "аккаунту": "account",
    "связан": "linked", "несколькими": "multiple", "записями": "records", "уточните": "please clarify", "выполнено": "completed",
    "подтверждён": "confirmed", "подтвержден": "confirmed", "историю": "history", "отправки": "sending", "новой": "new", "вашей": "your",
    "ссылке": "link", "уникальных": "unique", "одному": "one", "принятого": "accepted", "отметка": "note", "ближайшее": "soon",
    "сняли": "withdrew", "пополнили": "deposited", "максимальное": "maximum", "произошла": "occurred", "ботам": "bots", "перевода": "transfer",
    "вход": "entry", "устарел": "expired", "недействителен": "invalid", "перезапустите": "restart", "зарегистрироваться": "register",
    "снять": "withdraw", "скопировать": "copy", "забрать": "collect", "топ": "top", "программа": "program", "отклонил": "rejected",
    "другая": "another", "владельцу": "owner", "привлечения": "attraction", "потерь": "losses", "чистых": "net", "чистый": "net",
    "регистрация": "registration", "бонусом": "bonus", "бонусы": "bonuses", "бонуса": "bonus", "выводами": "withdrawals",
})

RU_EN_PHRASES.update({
    "Заработок с приглашений заморожен": "Referral earnings are frozen.",
    "На реферальном балансе меньше ": "Your referral balance is below ",
    "Запустите /addep в личном чате с ботом.": "Run /addep in a private chat with the bot.",
    "Формат: /addep @username 50. Сумма — целое число от 1 до 1 000 000 Stars.": "Format: /addep @username 50. The amount must be a whole number from 1 to 1,000,000 Stars.",
    "Результат начисления не подтверждён. Проверьте историю до отправки новой команды. Автоматическая повторная доставка исходного сообщения защищена от двойного начисления.": "The credit result is unconfirmed. Check the history before sending another command. Automatic redelivery of the original message is protected against duplicate credits.",
    "Тест иконки. Никакие операции не выполняются.": "Icon test. No transactions are performed.",
    "Это диагностическая кнопка администратора.": "This diagnostic button is for administrators only.",
    "Ваша заявка на вывод ": "Your withdrawal request for ",
    " одобрена! В ближайшее время вывод будет обработан.": " has been approved! Your withdrawal will be processed soon.",
    " отклонена. Сумма возвращена на баланс.": " was rejected. The amount has been returned to your balance.",
    "Минимальная ставка ": "Minimum bet: ",
    ", диапазон должен быть больше 1.00": ", the multiplier must be greater than 1.00",
    ", максимальный множитель ": ", maximum multiplier: ",
    "минимальное количество мин — ": "minimum number of mines: ",
    "максимальное количество мин — ": "maximum number of mines: ",
    ", вы успешно получили бонус в размере ": ", you received a bonus of ",
    "для того чтобы получить бонус, установи данный текст в описание": "To claim the bonus, add this text to your bio",
    "у вас в профиле отсутствует нужное описание": "your profile is missing the required bio text",
    "Подождите 1-2 минуты если установили описание и попробуйте снова": "Wait 1–2 minutes if you just updated your bio, then try again",
    "вы уже в очереди, осталось ждать ": "you are already in the queue; time remaining: ",
    "вы успешно встали в очередь, осталось ждать 12:00:00.": "you have joined the queue; please wait 12 hours.",
    "бонус уже получен.": "you have already claimed this bonus.",
    "Ваша реферальная ссылка:": "Your referral link:",
    "Заработок с приглашений:": "Referral earnings:",
    "Текущий реферальный баланс:": "Current referral balance:",
    "Заработано с рефералов:": "Earned from referrals:",
    "Статистика заработка:": "Earnings breakdown:",
    "Заработано с приглашений:": "Earned from referrals:",
    "Заработано с пополнений:": "Earned from deposits:",
    "Заработано в чатах:": "Earned in chats:",
    " Тут ты сможешь заработать Telegram Stars на приглашении своих друзей и знакомых. ": " Earn Telegram Stars by inviting your friends and contacts. ",
    "За обычного друга награда — ": "Reward for a standard referral: ",
    ", награда за друга с Telegram Premium — ": ", reward for a Telegram Premium referral: ",
    ". Также вы будете получать 10% от пополнения ваших рефералов.": ". You also earn 10% of your referrals' deposits.",
    " Статистика заработка:\n": " Earnings breakdown:\n",
    " Stars.\nСумма учитывается как депозит, включая реферальные начисления.": " Stars.\nThis amount counts as a deposit, including referral credits.",
    "Баланс после начисления:": "Balance after credit:",
    " Stars\\nБаланс после начисления: ": " Stars\\nBalance after credit: ",
    "Пользователь не найден. Он должен быть зарегистрирован в боте.": "User not found. They must be registered with the bot.",
    "нельзя переводить самому себе.": "You cannot transfer money to yourself.",
    "минимальная сумма перевода — ": "Minimum transfer amount: ",
    "получатель не зарегистрирован в боте.": "The recipient is not registered with the bot.",
    "не удалось отправить заявку. Сумма возвращена.": "Could not submit the request. The amount has been refunded.",
    "не удалось отправить игру. Ставка возвращена.": "Could not start the game. Your bet has been refunded.",
    "вы не подписаны на обязательные каналы!": "you are not subscribed to the required channels!",
    "вы всё ещё не подписаны!": "you are still not subscribed!",
    "Ты не зарегистрирован!": "You are not registered!",
    " Stars. Баланс: ": " Stars. Balance: ",
    "Баланс пополнен на ": "Balance topped up by ",
    "на основной баланс!": "to your main balance!",
    "Для вывода введите сумму чтобы вывести Telegram Stars": "Enter the amount of Telegram Stars you want to withdraw",
    "введите сумму": "enter an amount",
    "выберите или введите": "choose or enter",
    "Введите сумму цифрами": "Enter an amount using digits",
    "Платёжный сервис просит подождать.": "The payment provider asked you to wait.",
    "Осталось ждать ": "Time remaining: ",
    "Сумма возвращена на баланс.": "The amount has been returned to your balance.",
    "Создать новый чек": "Create a new check",
    "Открыть MajorStars и подтвердить создание чека": "Open MajorStars to confirm check creation",
    "Создайте внутренний чек MajorStars в приложении.": "Create a MajorStars internal check in the app.",
    "Создать чек": "Create check",
    "добро пожаловать в ": "welcome to ",
    " В данном боте ты сможешь поднять и вывести звезды на свой Telegram аккаунт!": " In this bot, you can earn and withdraw Telegram Stars to your account!",
    "Удачной игры в Major!": "Enjoy playing Major!",
    "Классика подвела.": "The classic let you down.",
    "Классика жанра.": "A classic.",
    "Классика жанра — чистая дорожка.": "A classic move: a clean lane.",
    "Классика жанра — и это твой день.": "A classic move — and it's your day.",
    "Просто, надёжно, но не в твою пользу.": "Simple and reliable, but not in your favor.",
    "Просто, надёжно, в цель.": "Simple, reliable, and right on target.",
    "Просто, надёжно, в твою пользу.": "Simple and reliable — in your favor.",
    "Стандартный бросок — нестандартный проигрыш.": "A standard throw, an unexpected loss.",
    "Стандартный бросок — стандартный успех.": "A standard throw, a standard win.",
    "Как учили, но учили не тебя.": "Just like they taught — but not you.",
    "Как по учебнику, но учили не тебя.": "Textbook technique — just not yours.",
    "Без выкрутасов, зато в минус.": "No tricks — but you're still down.",
    "Без выкрутасов, зато зашло.": "No tricks — just a win.",
    "Стабильность изменила.": "Consistency let you down.",
    "Стабильность — признак мастерства.": "Consistency is a sign of skill.",
    "Всё по плану.": "Everything went to plan.",
    "Всё по плану, но плану соперника.": "Everything went to plan — your opponent's plan.",
    "Не попал, и ты тоже.": "You missed — and so did your bet.",
    "Промах обошёлся дорого.": "That miss was costly.",
    "Мимо кольца, мимо кассы.": "Missed the hoop, lost the bet.",
    "Промах — просто промах.": "A miss is just a miss.",
    "Не попал. Бывает.": "You missed. It happens.",
    "Мяч улетел, ставка сгорела.": "The ball flew off, and your bet was lost.",
    "Отскок от щита — и мимо.": "It bounced off the backboard and missed.",
    "Щит не помог.": "The backboard couldn't save it.",
    "Рикошет сыграл против тебя.": "The ricochet worked against you.",
    "Отскок — не попадание.": "A bounce isn't a basket.",
    "Щит сегодня не на твоей стороне.": "The backboard wasn't on your side today.",
    "Мяч от щита и в аут.": "Off the backboard and out.",
    "Везения не хватило.": "Luck wasn't on your side.",
    "Отскок принёс только разочарование.": "That bounce brought nothing but disappointment.",
    "Мяч застрял, а ставка сгорела.": "The ball got stuck, and your bet was lost.",
    "Застрял — и не в твою пользу.": "It got stuck — not in your favor.",
    "Редкий случай, но против тебя.": "A rare outcome, but not in your favor.",
    "Мяч завис, деньги уплыли.": "The ball got stuck; your money drifted away.",
    "Такое бывает раз в году, и не в твой день.": "It happens once a year — and today isn't your day.",
    "Застрял. И это не твой день.": "It got stuck. Not your day.",
    "Судьба вмешалась против тебя.": "Fate intervened against you.",
    "Мяч застрял, ты проиграл.": "The ball got stuck; you lost.",
    "Почти попал. Ключевое слово — почти.": "Almost hit it. The key word is almost.",
    "Чуть-чуть не хватило.": "You were just short.",
    "Почти — не считается.": "Almost doesn't count.",
    "На грани, но не в твою пользу.": "It was close, but not in your favor.",
    "Сантиметры сыграли против тебя.": "A few centimeters made the difference — against you.",
    "Почти попал, но проиграл.": "Almost hit it, but still lost.",
    "Чуть не залетел — и чуть не выиграл.": "It nearly went in — and you nearly won.",
    "Почти — и это поражение.": "So close, but still a loss.",
    "Мимо, но ставка зашла.": "It missed, but your bet won.",
    "Не попал, зато заработал.": "You missed, but still earned a payout.",
    "Мяч улетел в аут, а ты в плюсе.": "The ball went out, but you're ahead.",
    "Промах оказался выгодным.": "That miss turned out to be profitable.",
    "Мимо кольца, но в цель по деньгам.": "Missed the hoop, hit the jackpot.",
    "Иногда промах — это стратегия.": "Sometimes a miss is the right strategy.",
    "Не попал — и правильно.": "You missed — and that was the right move.",
    "Мяч мимо, ты в дамках.": "The ball missed, but you're on top.",
    "Отскок от щита — и в кольцо.": "Off the backboard and into the hoop.",
    "Щит помог, мяч зашёл.": "The backboard helped — it went in.",
    "Рикошет сыграл за тебя.": "The ricochet worked in your favor.",
    "Отскок — тоже попадание.": "A bounce still counts.",
    "Щит сегодня на твоей стороне.": "The backboard is on your side today.",
    "Мяч от щита и в цель.": "Off the backboard and on target.",
    "Не без везения, но зашло.": "A little luck — and it went in.",
    "Отскок принёс результат.": "That bounce paid off.",
    "Мяч застрял между кольцом и щитом.": "The ball got stuck between the rim and the backboard.",
    "Застрял — и это засчитано.": "It got stuck — and it counts.",
    "Редкий случай, но в твою пользу.": "A rare outcome — in your favor.",
    "Мяч завис, ставка зашла.": "The ball got stuck, but your bet won.",
    "Такое бывает раз в году.": "It happens once a year.",
    "Застрял. И это твой день.": "It got stuck. It's your day.",
    "Судьба вмешалась в твою пользу.": "Fate intervened in your favor.",
    "Мяч застрял, ты выиграл.": "The ball got stuck — and you won.",
    "Страйк был нужен, но не случился.": "You needed a strike, but it didn't happen.",
    "Все кегли устояли.": "All the pins stayed up.",
    "Идеальный бросок не получился.": "That wasn't a perfect throw.",
    "Страйк прошёл мимо.": "The strike never came.",
    "Шар ушёл в жёлоб, деньги в никуда.": "The ball went into the gutter, and your money went with it.",
    "Мимо кеглей, мимо кассы.": "Missed the pins, lost the bet.",
    "Одна кегля, а ставка сгорела.": "One pin — and your bet was gone.",
    "Всего одна, но не в твою пользу.": "Just one — and not in your favor.",
    "Скромно и обидно.": "A small result, and a painful one.",
    "Одна кегля сыграла против тебя.": "One pin worked against you.",
    "Минимум, но и его не хватило.": "The bare minimum still wasn't enough.",
    "Одна — значит мимо кассы.": "One pin means a losing bet.",
    "Три кегли, а ставка сгорела.": "Three pins — and your bet was gone.",
    "Три сыграли против тебя.": "Three worked against you.",
    "Не много, и не в твою пользу.": "Not many — and not in your favor.",
    "Три кегли — и ноль результата.": "Three pins, and nothing to show for it.",
    "Тройка не принесла удачу.": "Three wasn't lucky.",
    "Три — значит мимо кассы.": "Three means no payout.",
    "Четыре кегли — и ноль результата.": "Four pins, and nothing to show for it.",
    "Четвёрка не принесла удачу.": "Four pins didn't bring you luck.",
    "Пять кеглей — и ноль результата.": "Five pins, and nothing to show for it.",
    "Пятёрка не принесла удачу.": "Five pins didn't bring you luck.",
    "Шесть кеглей — и ноль результата.": "Six pins, and nothing to show for it.",
    "Шестёрка не принесла удачу.": "Six pins didn't bring you luck.",
    "Страйк. Все десять с первого шара.": "Strike! All ten pins on the first ball.",
    "Страйк, и это твой день.": "A strike — it's your day.",
    "Все кегли снесены одним ударом.": "All the pins fell with one throw.",
    "Как по учебнику — страйк.": "Textbook-perfect strike.",
    "Шар ушёл в жёлоб, а ты в плюсе.": "The ball went into the gutter, but you're ahead.",
    "Одна кегля — и этого хватило.": "One pin was all it took.",
    "Всего одна, но в твою пользу.": "Just one — and in your favor.",
    "Скромно, зато зашло.": "A small win, but a win.",
    "Одна кегля сыграла за тебя.": "One pin worked in your favor.",
    "Минимум, но результат есть.": "The minimum — but it counts.",
    "Одна — значит выигрышная.": "One pin, and it's a winning bet.",
    "Три кегли — и это засчитано.": "Three pins — it counts.",
    "Три сыграли за тебя.": "Three worked in your favor.",
    "Не много, но в твою пользу.": "Not many, but in your favor.",
    "Три кегли — уже результат.": "Three pins — that's a result.",
    "Тройка принесла удачу.": "Three pins brought you luck.",
    "Три — значит выигрышные.": "Three means a winning result.",
    "Четыре кегли — и это засчитано.": "Four pins — it counts.",
    "Четыре сыграли за тебя.": "Four pins worked in your favor.",
    "Пять кеглей — и это засчитано.": "Five pins — it counts.",
    "Пять сыграли за тебя.": "Five pins worked in your favor.",
    "Шесть кеглей — и это засчитано.": "Six pins — it counts.",
    "Шесть сыграли за тебя.": "Six pins worked in your favor.",
    "Проверьте баланс и историю до повторной попытки.": "Check your balance and history before trying again.",
    "Чат участники автоматически связываются": "Chat members are automatically linked",
})


RU_EN_PHRASES.update({
    "Куб остановился не там.": "The die landed on the wrong number.",
    "Куб остановился там, где нужно.": "The die landed exactly where you needed it.",
    "Классик сыграл против тебя.": "The classic result went against you.",
    "Классик сыграл за тебя.": "The classic result went your way.",
    "Чёт не выпал.": "No even number came up.",
    "Чётное число сыграло против тебя.": "The even number worked against you.",
    "Чёт — но не в твою пользу.": "Even — but not in your favor.",
    "Ждал чёт, а пришло не то.": "You called even, but got something else.",
    "Чёт сегодня не на твоей стороне.": "Even isn't on your side today.",
    "Чётное — и мимо кассы.": "Even came up, but your bet missed.",
    "Нечёт не выпал.": "No odd number came up.",
    "Нечётное число сыграло против тебя.": "The odd number worked against you.",
    "Нечёт — но не в твою пользу.": "Odd — but not in your favor.",
    "Ждал нечёт, а пришло не то.": "You called odd, but got something else.",
    "Нечёт сегодня не на твоей стороне.": "Odd isn't on your side today.",
    "Нечётное — и мимо кассы.": "Odd came up, but your bet missed.",
    "Чёт выпал, и это твой день.": "Even came up — it's your day.",
    "Чётное число сыграло за тебя.": "The even number worked in your favor.",
    "Чёт — значит выигрышное.": "Even means a winning result.",
    "Двойка, четвёрка или шестёрка — неважно, зашло.": "Two, four, or six — it doesn't matter; your bet won.",
    "Чёт сегодня на твоей стороне.": "Even is on your side today.",
    "Чётное — и ставка зашла.": "Even came up, and your bet won.",
    "Нечёт выпал, и это твой день.": "Odd came up — it's your day.",
    "Нечётное число сыграло за тебя.": "The odd number worked in your favor.",
    "Нечёт — значит выигрышное.": "Odd means a winning result.",
    "Единица, тройка или пятёрка — неважно, зашло.": "One, three, or five — it doesn't matter; your bet won.",
    "Нечёт сегодня на твоей стороне.": "Odd is on your side today.",
    "Нечётное — и ставка зашла.": "Odd came up, and your bet won.",
    "Два числа, а ставка сгорела.": "Two numbers came up, but your bet was lost.",
    "Два сыграли против тебя.": "The two worked against you.",
    "Пара чисел — и ноль результата.": "A pair of numbers, and no payout.",
    "Два — значит мимо кассы.": "Two means no payout.",
    "Двойка чисел не принесла удачу.": "The pair didn't bring you luck.",
    "Два числа, но не твои.": "Two numbers — but not the ones you needed.",
    "Три числа, а ставка сгорела.": "Three numbers came up, but your bet was lost.",
    "Полный набор — и ноль результата.": "A full set, and no payout.",
    "Тройка чисел не принесла удачу.": "Three numbers didn't bring you luck.",
    "Три числа, но не твои.": "Three numbers — but not the ones you needed.",
    "Меньше не выпало.": "No low number came up.",
    "Малое число сыграло против тебя.": "The low number worked against you.",
    "Меньше — но не в твою пользу.": "Low — but not in your favor.",
    "Ждал меньше, а пришло не то.": "You called low, but got something else.",
    "Меньше сегодня не на твоей стороне.": "Low isn't on your side today.",
    "Малое число — и мимо кассы.": "A low number, but no payout.",
    "Больше не выпало.": "No high number came up.",
    "Большое число сыграло против тебя.": "The high number worked against you.",
    "Больше — но не в твою пользу.": "High — but not in your favor.",
    "Ждал больше, а пришло не то.": "You called high, but got something else.",
    "Больше сегодня не на твоей стороне.": "High isn't on your side today.",
    "Большое число — и мимо кассы.": "A high number, but no payout.",
    "Единица не выпала.": "The one didn't come up.",
    "Один сыграл против тебя.": "The one worked against you.",
    "Первое число — но не в твою пользу.": "The first number — but not in your favor.",
    "Единица не принесла удачу.": "One wasn't lucky.",
    "Один сегодня не на твоей стороне.": "One isn't on your side today.",
    "Ждал единицу, а пришло не то.": "You called one, but got something else.",
    "Одно число, а ставка сгорела.": "One number came up, but your bet was lost.",
    "Ровно одно, но не в твою пользу.": "Exactly one — but not in your favor.",
    "Одно число сыграло против тебя.": "The number one worked against you.",
    "Минимум, и его не хватило.": "The minimum still wasn't enough.",
    "Одно — значит мимо кассы.": "One means no payout.",
    "Одно число, но не твоё.": "One number — but not the one you needed.",
    "Двойка не выпала.": "The two didn't come up.",
    "Два сыграло против тебя.": "The two worked against you.",
    "Второе число — но не в твою пользу.": "The second number — but not in your favor.",
    "Двойка не принесла удачу.": "Two wasn't lucky.",
    "Два сегодня не на твоей стороне.": "Two isn't on your side today.",
    "Ждал двойку, а пришло не то.": "You called two, but got something else.",
    "Тройка не выпала.": "The three didn't come up.",
    "Три сыграло против тебя.": "The three worked against you.",
    "Третье число — но не в твою пользу.": "The third number — but not in your favor.",
    "Три сегодня не на твоей стороне.": "Three isn't on your side today.",
    "Ждал тройку, а пришло не то.": "You called three, but got something else.",
    "Четвёрка не выпала.": "The four didn't come up.",
    "Четыре сыграло против тебя.": "The four worked against you.",
    "Четвёртое число — но не в твою пользу.": "The fourth number — but not in your favor.",
    "Четыре сегодня не на твоей стороне.": "Four isn't on your side today.",
    "Ждал четвёрку, а пришло не то.": "You called four, but got something else.",
    "Пятёрка не выпала.": "The five didn't come up.",
    "Пять сыграло против тебя.": "The five worked against you.",
    "Пятое число — но не в твою пользу.": "The fifth number — but not in your favor.",
    "Пять сегодня не на твоей стороне.": "Five isn't on your side today.",
    "Ждал пятёрку, а пришло не то.": "You called five, but got something else.",
    "Шестёрка не выпала.": "The six didn't come up.",
    "Шесть сыграло против тебя.": "The six worked against you.",
    "Шестое число — но не в твою пользу.": "The sixth number — but not in your favor.",
    "Шесть сегодня не на твоей стороне.": "Six isn't on your side today.",
    "Ждал шестёрку, а пришло не то.": "You called six, but got something else.",
    "Единица выпала, и это твой день.": "The one came up — it's your day.",
    "Один — значит выигрышный.": "One means a winning result.",
    "Первое число сыграло за тебя.": "The first number worked in your favor.",
    "Единица принесла удачу.": "One brought you luck.",
    "Один сегодня на твоей стороне.": "One is on your side today.",
    "Выпала единица — забирай своё.": "The one came up — collect your winnings.",
    "Одно число — и этого хватило.": "One number was all it took.",
    "Одно число сыграло за тебя.": "The number one worked in your favor.",
    "Одно — значит выигрышное.": "One means a winning result.",
    "Одно число, зато твоё.": "One number — and it's yours.",
    "Двойка выпала, и это твой день.": "The two came up — it's your day.",
    "Два — значит выигрышное.": "Two means a winning result.",
    "Второе число сыграло за тебя.": "The second number worked in your favor.",
    "Двойка принесла удачу.": "Two brought you luck.",
    "Два сегодня на твоей стороне.": "Two is on your side today.",
    "Выпала двойка — забирай своё.": "The two came up — collect your winnings.",
    "Тройка выпала, и это твой день.": "The three came up — it's your day.",
    "Три — значит выигрышное.": "Three means a winning result.",
    "Третье число сыграло за тебя.": "The third number worked in your favor.",
    "Три сегодня на твоей стороне.": "Three is on your side today.",
    "Выпала тройка — забирай своё.": "The three came up — collect your winnings.",
    "Четвёрка выпала, и это твой день.": "The four came up — it's your day.",
    "Четыре — значит выигрышное.": "Four means a winning result.",
    "Четвёртое число сыграло за тебя.": "The fourth number worked in your favor.",
    "Четыре сегодня на твоей стороне.": "Four is on your side today.",
    "Выпала четвёрка — забирай своё.": "The four came up — collect your winnings.",
    "Пятёрка выпала, и это твой день.": "The five came up — it's your day.",
    "Пять — значит выигрышное.": "Five means a winning result.",
    "Пятое число сыграло за тебя.": "The fifth number worked in your favor.",
    "Пять сегодня на твоей стороне.": "Five is on your side today.",
    "Выпала пятёрка — забирай своё.": "The five came up — collect your winnings.",
    "Шестёрка выпала, и это твой день.": "The six came up — it's your day.",
    "Шесть — значит выигрышное.": "Six means a winning result.",
    "Шестое число сыграло за тебя.": "The sixth number worked in your favor.",
    "Шесть сегодня на твоей стороне.": "Six is on your side today.",
    "Выпала шестёрка — забирай своё.": "The six came up — collect your winnings.",
    "Сегодня не твой день.": "It's not your day today.",
    "Сегодня удача на твоей стороне.": "Luck is on your side today.",
    "Сегодня удача на твоей стороне.": "Luck is on your side today.",
    "Три в ряд — и это твой день.": "Three in a row — it's your day.",
    "Слоты улыбнулись именно тебе.": "The slots smiled on you.",
    "Крутил не зря.": "That spin was worth it.",
    "Фортуна выбрала тебя.": "Fortune chose you.",
    "Барабаны остановились, но не там.": "The reels stopped — just not where you wanted.",
    "Удача — дама капризная.": "Luck can be fickle.",
    "Не в этот раз.": "Not this time.",
    "Слоты — игра терпеливых.": "Slots reward the patient.",
    "Крути ещё, повезёт.": "Spin again — your luck may turn.",
    "Барабаны остановились там, где нужно.": "The reels stopped exactly where you wanted.",
})


RU_EN_PHRASES.update({
    # Exact English versions for every built-in game result line.
    "Классик сегодня против тебя.": "The classic result went against you today.",
    "По вашей ссылке зашёл новый пользователь: ": "A new user joined using your referral link: ",
    "Произошла ошибка, попробуйте ещё раз.": "Something went wrong. Please try again.",
    "Произошла ошибка, попробуйте ещё раз": "Something went wrong. Please try again",
    "нельзя переводить самому себе": "You cannot transfer money to yourself",
    "Нельзя переводить самому себе.": "You cannot transfer money to yourself.",
    "Мяч в аут, деньги в никуда.": "The ball went out, and your bet went with it.",
    "Почти попал — и этого хватило.": "It nearly went in — and that was enough.",
    "Чуть-чуть, но в твою пользу.": "It was close, but it went your way.",
    "Почти — тоже результат.": "Almost counts.",
    "На грани, но зашло.": "A close call, but it paid off.",
    "Сантиметры сыграли за тебя.": "A few centimeters made the difference — in your favor.",
    "Почти попал, но выиграл.": "It nearly went in, but you still won.",
    "Чуть не залетел, но зачли.": "It nearly went in, but it counted.",
    "Почти — и это победа.": "So close — and still a win.",
    "Четыре кегли, а ставка сгорела.": "Four pins fell, but your bet was lost.",
    "Четыре сыграли против тебя.": "Four pins worked against you.",
    "Половина снесена, но не в твою пользу.": "Half the pins fell, but not in your favor.",
    "Четыре — значит мимо кассы.": "Four pins, but no payout.",
    "Пять кеглей, а ставка сгорела.": "Five pins fell, but your bet was lost.",
    "Пять сыграли против тебя.": "Five pins worked against you.",
    "Больше половины, но не в твою пользу.": "More than half the pins fell, but it still went against you.",
    "Пять — значит мимо кассы.": "Five pins, but no payout.",
    "Шесть кеглей, а ставка сгорела.": "Six pins fell, but your bet was lost.",
    "Шесть сыграли против тебя.": "Six pins worked against you.",
    "Хороший бросок, но не в твою пользу.": "A good throw, but not in your favor.",
    "Шесть — значит мимо кассы.": "Six pins, but no payout.",
    "Идеальный бросок.": "A perfect throw.",
    "Мимо кеглей, но в цель по деньгам.": "Missed the pins, but hit the payout.",
    "Половина снесена, но в твою пользу.": "Half the pins fell — and it worked in your favor.",
    "Четыре кегли — уже результат.": "Four pins — that's a result.",
    "Четвёрка принесла удачу.": "Four pins brought you luck.",
    "Четыре — значит выигрышные.": "Four pins mean a winning result.",
    "Больше половины, и в твою пользу.": "More than half the pins fell, and it went your way.",
    "Пять кеглей — уже результат.": "Five pins — that's a result.",
    "Пятёрка принесла удачу.": "Five pins brought you luck.",
    "Пять — значит выигрышные.": "Five pins mean a winning result.",
    "Хороший бросок, и в твою пользу.": "A good throw — and it went your way.",
    "Шесть кеглей — уже результат.": "Six pins — that's a result.",
    "Шестёрка принесла удачу.": "Six pins brought you luck.",
    "Шесть — значит выигрышные.": "Six pins mean a winning result.",
    "Как по учебнику — зашло.": "A textbook roll — and your bet paid off.",
    "Без выкрутасов, зато выигрыш.": "No tricks, just a win.",
    "Два числа — и это засчитано.": "Two numbers — that's a hit.",
    "Два сыграли за тебя.": "Both numbers worked in your favor.",
    "Пара чисел — уже результат.": "A pair of numbers — that's a result.",
    "Два — значит выигрышные.": "Two means a winning result.",
    "Двойка чисел принесла удачу.": "The pair brought you luck.",
    "Два числа, и оба твои.": "Two numbers, both in your favor.",
    "Три числа — максимум, и это твоё.": "Three numbers — the maximum, and you got them.",
    "Полный набор — уже результат.": "A full set — that's a result.",
    "Тройка чисел принесла удачу.": "Three numbers brought you luck.",
    "Три числа, и все твои.": "Three numbers, all in your favor.",
    "Меньше — и это засчитано.": "Low — and it counts.",
    "Малое число сыграло за тебя.": "The low number worked in your favor.",
    "Меньше — значит выигрышное.": "Low means a winning result.",
    "Скромно, но в твою пользу.": "A modest result, but in your favor.",
    "Меньше сегодня на твоей стороне.": "Low is on your side today.",
    "Малое число принесло удачу.": "A low number brought you luck.",
    "Больше — и это засчитано.": "High — and it counts.",
    "Большое число сыграло за тебя.": "The high number worked in your favor.",
    "Больше — значит выигрышное.": "High means a winning result.",
    "Крупно, и в твою пользу.": "A high roll — and it went your way.",
    "Больше сегодня на твоей стороне.": "High is on your side today.",
    "Большое число принесло удачу.": "A high number brought you luck.",
    "Ровно одно, но в твою пользу.": "Exactly one — but in your favor.",
    "Дротик точно в цель, но не в твою пользу.": "The dart hit the mark, but not in your favor.",
    "Прямо в яблочко — и мимо тебя.": "Right in the bullseye — but your bet still missed.",
    "Чистое попадание, грязный проигрыш.": "A clean hit, but a costly loss.",
    "Дротик улетел в стену, деньги в никуда.": "The dart hit the wall, and your money went with it.",
    "Мимо мишени, мимо кассы.": "Missed the target, lost the bet.",
    "Отскок от проволоки — и мимо.": "It bounced off the wire and missed.",
    "Дротик срикошетил и ушёл.": "The dart ricocheted away.",
    "Отскок сыграл против тебя.": "The bounce worked against you.",
    "Проволока помешала, а не помогла.": "The wire got in the way instead of helping.",
    "Рикошет принёс только разочарование.": "The ricochet brought nothing but disappointment.",
    "Красное — но не в твою пользу.": "Red — but not in your favor.",
    "Красный сектор сыграл против тебя.": "The red segment worked against you.",
    "Попал в красное, а ставка сгорела.": "You hit red, but your bet was lost.",
    "Красное сегодня не на твоей стороне.": "Red isn't on your side today.",
    "Красный цвет не всегда к удаче.": "Red doesn't always bring luck.",
    "Красное — значит мимо кассы.": "Red, but no payout.",
    "Белое — но не в твою пользу.": "White — but not in your favor.",
    "Белый сектор сыграл против тебя.": "The white segment worked against you.",
    "Попал в белое, а ставка сгорела.": "You hit white, but your bet was lost.",
    "Белое сегодня не на твоей стороне.": "White isn't on your side today.",
    "Белый цвет не всегда к удаче.": "White doesn't always bring luck.",
    "Белое — значит мимо кассы.": "White, but no payout.",
    "Дротик точно в цель.": "The dart hit the mark.",
    "Прямо в яблочко.": "Right in the bullseye.",
    "Дротик улетел в стену, а ты в плюсе.": "The dart hit the wall, but your bet still paid off.",
    "Мимо мишени, но в цель по деньгам.": "Missed the target, but hit the payout.",
    "Отскок от проволоки — и в цель.": "It bounced off the wire and hit the mark.",
    "Дротик срикошетил, но зашёл.": "The dart ricocheted — and still scored.",
    "Отскок сыграл за тебя.": "The bounce worked in your favor.",
    "Не без везения, но засчитано.": "A little luck — and it counts.",
    "Проволока помогла, а не помешала.": "The wire helped instead of getting in the way.",
    "Рикошет принёс результат.": "The ricochet paid off.",
    "Красное — и это засчитано.": "Red — and it counts.",
    "Красный сектор сыграл за тебя.": "The red segment worked in your favor.",
    "Попал в красное, забрал своё.": "You hit red — collect your winnings.",
    "Красное сегодня на твоей стороне.": "Red is on your side today.",
    "Красный цвет приносит удачу.": "Red brings good luck.",
    "Красное — значит выигрышное.": "Red means a winning result.",
    "Белое — и это засчитано.": "White — and it counts.",
    "Белый сектор сыграл за тебя.": "The white segment worked in your favor.",
    "Попал в белое, забрал своё.": "You hit white — collect your winnings.",
    "Белое сегодня на твоей стороне.": "White is on your side today.",
    "Белый цвет приносит удачу.": "White brings good luck.",
    "Белое — значит выигрышное.": "White means a winning result.",
    "Мимо ворот, мимо денег.": "Wide of the goal — and there goes your bet.",
    "Штанга спасла вратаря, но не тебя.": "The post saved the keeper, but not your bet.",
    "Сантиметры отделили от выигрыша.": "You were just centimeters away from a win.",
    "Дерево сыграло против тебя.": "The woodwork worked against you.",
    "Девятка. Красиво и больно.": "Top corner. A beautiful shot, a painful result.",
    "Идеальный удар — не в твою пользу.": "A perfect strike — but not for your bet.",
    "Верхний угол, а ставка в пропасть.": "Top corner — but your bet went down the drain.",
    "Прямо по центру, а мимо тебя.": "Straight down the middle — but not your way.",
    "Центр — тоже результат, но не твой.": "Down the middle — but not the result you wanted.",
    "Главное — забить, а забили не тебе.": "A goal is all that matters — and they scored against you.",
    "Гол. Но не в твою пользу.": "A goal — just not for you.",
    "Забили. Не ты.": "They scored. You didn't.",
    "Прямо в цель, но не в твою.": "On target — but not your pick.",
    "Ушёл вправо, а ты — в минус.": "It went right, and your balance went down.",
    "Выше ворот — ниже твоё настроение.": "Over the bar — and your mood went down.",
    "Мимо ворот, но попытка засчитана.": "Off target, but your pick still won.",
    "Не попал, бывает.": "He missed. It happens.",
    "Дерево спасло вратаря.": "The woodwork saved the keeper.",
    "Девятка. Идеальный удар.": "Top corner. A perfect strike.",
    "Верхний угол, неберущийся мяч.": "Top corner — an unstoppable shot.",
    "Точнее не бывает.": "It couldn't be more accurate.",
    "Прямо по центру.": "Straight down the middle.",
    "Главное — забить.": "All that matters is scoring.",
    "Гол.": "Goal!",
    "Забил.": "Scored!",
    "Прямо в цель.": "Right on target.",
    "Прямолинейно, но эффективно.": "Straightforward, but effective.",
    "Ушёл вправо и не прогадал.": "It went right — and that was the right call.",
    "Выше ворот.": "Over the bar.",
    "Мяч на орбите.": "The ball is in orbit.",
    "Низкий удар.": "A low shot.",
})

_I18N_PROTECTED_RE = re.compile(r'(<a\b[^>]*>.*?</a>|<tg-emoji\b[^>]*>.*?</tg-emoji>|<[^>]+>)', re.IGNORECASE | re.DOTALL)
_RUSSIAN_WORD_RE = re.compile(r"[А-Яа-яЁё]+")


def translate_telegram_text(text: str, language: str = "en") -> str:
    if not isinstance(text, str) or language != "en":
        return text

    def translate_span(span: str) -> str:
        for russian, english in sorted(RU_EN_PHRASES.items(), key=lambda item: len(item[0]), reverse=True):
            span = span.replace(russian, english)
        def translate_word(match):
            word = match.group(0)
            translated = RU_EN_WORDS.get(word.lower())
            if translated is None:
                return word
            if word.isupper():
                return translated.upper()
            if word[:1].isupper():
                return translated[:1].upper() + translated[1:]
            return translated
        return _RUSSIAN_WORD_RE.sub(translate_word, span)

    parts = _I18N_PROTECTED_RE.split(text)
    return "".join(part if part.startswith("<") else translate_span(part) for part in parts)


def user_language_from_update(update) -> int | None:
    for name in ("message", "edited_message", "channel_post", "callback_query", "inline_query", "pre_checkout_query", "chat_member", "my_chat_member"):
        event = getattr(update, name, None)
        user = getattr(event, "from_user", None) if event is not None else None
        if user is not None and type(getattr(user, "id", None)) is int:
            return user.id
    return None


class TelegramLocaleContextMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = user_language_from_update(event)
        user_token = CURRENT_TELEGRAM_USER.set(user_id)
        lang_token = CURRENT_TELEGRAM_LANGUAGE.set(await get_telegram_language(user_id) if user_id else "ru")
        try:
            return await handler(event, data)
        finally:
            CURRENT_TELEGRAM_LANGUAGE.reset(lang_token)
            CURRENT_TELEGRAM_USER.reset(user_token)


def _telegram_method_locale_user(method) -> int | None:
    chat_id = getattr(method, "chat_id", None)
    if type(chat_id) is int and chat_id > 0:
        return chat_id
    return CURRENT_TELEGRAM_USER.get()


def _localized_inline_result(result, language):
    updates = {}
    for field in ("title", "description", "caption"):
        value = getattr(result, field, None)
        if isinstance(value, str):
            updates[field] = translate_telegram_text(value, language)
    content = getattr(result, "input_message_content", None)
    message_text = getattr(content, "message_text", None) if content is not None else None
    if isinstance(message_text, str):
        updates["input_message_content"] = content.model_copy(update={"message_text": translate_telegram_text(message_text, language)})
    markup = getattr(result, "reply_markup", None)
    if markup is not None:
        updates["reply_markup"] = _localized_markup(markup, language)
    return result.model_copy(update=updates) if updates else result


def _localized_markup(markup, language):
    rows = getattr(markup, "inline_keyboard", None)
    if rows is not None:
        return markup.model_copy(update={"inline_keyboard": [[button.model_copy(update={"text": translate_telegram_text(button.text, language)}) for button in row] for row in rows]})
    rows = getattr(markup, "keyboard", None)
    if rows is not None:
        return markup.model_copy(update={"keyboard": [[button.model_copy(update={"text": translate_telegram_text(button.text, language)}) for button in row] for row in rows]})
    return markup


class TelegramLocaleRequestMiddleware(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        user_id = _telegram_method_locale_user(method)
        if user_id is None:
            language = CURRENT_TELEGRAM_LANGUAGE.get()
        elif user_id == CURRENT_TELEGRAM_USER.get():
            language = CURRENT_TELEGRAM_LANGUAGE.get()
        else:
            language = await get_telegram_language(user_id)
        if language != "en":
            return await make_request(bot, method)
        updates = {}
        for field in ("text", "caption", "question", "explanation", "title", "description", "error_message"):
            value = getattr(method, field, None)
            if isinstance(value, str):
                updates[field] = translate_telegram_text(value, language)
        markup = getattr(method, "reply_markup", None)
        if markup is not None:
            updates["reply_markup"] = _localized_markup(markup, language)
        prices = getattr(method, "prices", None)
        if prices:
            updates["prices"] = [price.model_copy(update={"label": translate_telegram_text(price.label, language)}) for price in prices]
        media = getattr(method, "media", None)
        if media:
            updates["media"] = [item.model_copy(update={"caption": translate_telegram_text(item.caption, language)}) if getattr(item, "caption", None) else item for item in media]
        options = getattr(method, "options", None)
        if options:
            updates["options"] = [option.model_copy(update={"text": translate_telegram_text(option.text, language)}) if hasattr(option, "model_copy") and isinstance(getattr(option, "text", None), str) else translate_telegram_text(option, language) if isinstance(option, str) else option for option in options]
        results = getattr(method, "results", None)
        if results:
            updates["results"] = [_localized_inline_result(result, language) for result in results]
        if not updates:
            return await make_request(bot, method)
        return await make_request(bot, method.model_copy(update=updates))


REF_SIGNUP_BASE = 2.5
REF_SIGNUP_PREMIUM = 5.0
REF_DEPOSIT_PERCENT = 0.10
REF_BASE_LIMIT = 2
REF_LIMIT_PER_DEPOSIT = 2
REF_MIN_WITHDRAW = 10
BOT_USERNAME = __server_config__['BOT_USERNAME']

WITHDRAW_MIN_BALANCE = 50
WITHDRAW_MIN_DEPOSIT = 50
WITHDRAW_DEPOSIT_DAYS = 7

MINES_GRID = 5
MINES_TOTAL = MINES_GRID * MINES_GRID
MINES_MIN = 3
MINES_MAX = 10
MINES_DEFAULT = 3
MINES_MAX_MULTIPLIER = 100.0

MINES_BASE_TABLE = [
    0.85, 0.97, 1.12, 1.30, 1.51, 1.76, 2.05, 2.39, 2.78, 3.24,
    3.78, 4.40, 5.13, 5.97, 6.96, 8.11, 9.45, 11.01, 12.82, 14.94,
    17.40, 20.27,
]

FOOTBALL_DICE_EMOJI = "⚽️"
FOOTBALL_WAIT_SECONDS = 2.8
FOOTBALL_MIN_BET = 0.5

FOOTBALL_RANGES = {
    "мимо": 2.2,
    "штанга": 3.2,
    "перелёт": 4.0,
    "нижний": 1.2,
    "право": 1.3,
    "гол": 1.4,
    "прямо": 1.6,
    "центр": 2.4,
    "классик": 1.2,
    "девятка": 4.0,
}

FOOTBALL_VALUE_MAP = {
    1: ["перелёт", "мимо"],
    2: ["штанга", "мимо", "девятка"],
    3: ["нижний", "центр"],
    4: ["гол", "прямо"],
    5: ["классик", "право"],
}

FOOTBALL_QUOTES_WIN = {
    "мимо": ["Мимо ворот, но попытка засчитана.", "Мяч улетел на трибуны.", "Не попал, бывает."],
    "классик": ["Классика жанра.", "Просто, надёжно, в цель.", "Гол есть гол."],
    "штанга": ["Штанга. Ещё чуть-чуть и был бы гол.", "Дерево спасло вратаря.", "Звон штанги — музыка для ушей."],
    "девятка": ["Девятка. Идеальный удар.", "Верхний угол, неберущийся мяч.", "Точнее не бывает."],
    "центр": ["Прямо по центру.", "Просто и со вкусом.", "Главное — забить."],
    "гол": ["Гол.", "Мяч в сетке.", "Забил."],
    "прямо": ["Прямо в цель.", "Чётко и по делу.", "Прямолинейно, но эффективно."],
    "право": ["Правее — оно и вернее.", "Ушёл вправо и не прогадал.", "Вправо, но в точку."],
    "перелёт": ["Перелёт. Мяч улетел за ворота.", "Выше ворот.", "Мяч на орбите."],
    "нижний": ["Низом пошёл.", "Низкий удар.", "Мяч прошёл по земле."],
}

FOOTBALL_QUOTES_LOSE = {
    "мимо": ["Мимо. И это стоило тебе ставки.", "Не попал. Бывает.", "Мимо ворот, мимо денег."],
    "классик": ["Гол был, но не в твою сторону.", "Мяч в сетке, а ставка сгорела.", "Гол есть гол, но не для тебя."],
    "штанга": ["Штанга спасла вратаря, но не тебя.", "Сантиметры отделили от выигрыша.", "Дерево сыграло против тебя."],
    "девятка": ["Девятка. Красиво и больно.", "Идеальный удар — не в твою пользу.", "Верхний угол, а ставка в пропасть."],
    "центр": ["Прямо по центру, а мимо тебя.", "Центр — тоже результат, но не твой.", "Главное — забить, а забили не тебе."],
    "гол": ["Гол. Но не в твою пользу.", "Мяч в сетке, ставка в мусорке.", "Забили. Не ты."],
    "прямо": ["Прямо в цель, но не в твою.", "Чётко и по делу — против тебя.", "Без выкрутасов, зато с твоим минусом."],
    "право": ["Вправо, и не в твою сторону.", "Ушёл вправо, а ты — в минус.", "Право — не всегда стратегия."],
    "перелёт": ["Перелёт. Мяч улетел, деньги тоже.", "Выше ворот — ниже твоё настроение.", "Мяч на орбите, а ты на дне."],
    "нижний": ["Низом пошёл, и мимо тебя.", "Низкий удар — низкий результат для тебя.", "Скромно, но обидно."],
}

BASKETBALL_DICE_EMOJI = "🏀"
BASKETBALL_WAIT_SECONDS = 2.8
BASKETBALL_MIN_BET = 0.5

BASKETBALL_RANGES = {
    "классик": 1.4,
    "мимо": 1.35,
    "отскок": 4.0,
    "застрянет": 4.0,
    "почти": 4.0,
}

BASKETBALL_VALUE_MAP = {
    1: ["мимо"],
    2: ["отскок", "почти"],
    3: ["застрянет", "почти"],
    4: ["классик"],
    5: ["классик"],
}

BASKETBALL_QUOTES_WIN = {
    "классик": [
        "Классика жанра.", "Просто, надёжно, в цель.", "Чистое попадание.",
        "Как по учебнику.", "Стандартный бросок — стандартный успех.",
        "Без выкрутасов, зато зашло.", "Стабильность — признак мастерства.", "Всё по плану.",
    ],
    "мимо": [
        "Мимо, но ставка зашла.", "Не попал, зато заработал.",
        "Мяч улетел в аут, а ты в плюсе.", "Промах оказался выгодным.",
        "Мимо кольца, но в цель по деньгам.", "Иногда промах — это стратегия.",
        "Не попал — и правильно.", "Мяч мимо, ты в дамках.",
    ],
    "отскок": [
        "Отскок от щита — и в кольцо.", "Щит помог, мяч зашёл.",
        "Рикошет сыграл за тебя.", "Отскок — тоже попадание.",
        "Щит сегодня на твоей стороне.", "Мяч от щита и в цель.",
        "Не без везения, но зашло.", "Отскок принёс результат.",
    ],
    "застрянет": [
        "Мяч застрял между кольцом и щитом.", "Застрял — и это засчитано.",
        "Редкий случай, но в твою пользу.", "Мяч завис, ставка зашла.",
        "Такое бывает раз в году.", "Застрял. И это твой день.",
        "Судьба вмешалась в твою пользу.", "Мяч застрял, ты выиграл.",
    ],
    "почти": [
        "Почти попал — и этого хватило.", "Чуть-чуть, но в твою пользу.",
        "Почти — тоже результат.", "На грани, но зашло.",
        "Сантиметры сыграли за тебя.", "Почти попал, но выиграл.",
        "Чуть не залетел, но зачли.", "Почти — и это победа.",
    ],
}

BASKETBALL_QUOTES_LOSE = {
    "классик": [
        "Классика подвела.", "Просто, надёжно, но не в твою пользу.",
        "Стандартный бросок — нестандартный проигрыш.", "Как учили, но учили не тебя.",
        "Без выкрутасов, зато в минус.", "Классик сегодня против тебя.",
        "Стабильность изменила.", "Всё по плану, но плану соперника.",
    ],
    "мимо": [
        "Мимо. И это стоило тебе ставки.", "Не попал, и ты тоже.",
        "Мяч в аут, деньги в никуда.", "Промах обошёлся дорого.",
        "Мимо кольца, мимо кассы.", "Промах — просто промах.",
        "Не попал. Бывает.", "Мяч улетел, ставка сгорела.",
    ],
    "отскок": [
        "Отскок от щита — и мимо.", "Щит не помог.",
        "Рикошет сыграл против тебя.", "Отскок — не попадание.",
        "Щит сегодня не на твоей стороне.", "Мяч от щита и в аут.",
        "Везения не хватило.", "Отскок принёс только разочарование.",
    ],
    "застрянет": [
        "Мяч застрял, а ставка сгорела.", "Застрял — и не в твою пользу.",
        "Редкий случай, но против тебя.", "Мяч завис, деньги уплыли.",
        "Такое бывает раз в году, и не в твой день.", "Застрял. И это не твой день.",
        "Судьба вмешалась против тебя.", "Мяч застрял, ты проиграл.",
    ],
    "почти": [
        "Почти попал. Ключевое слово — почти.", "Чуть-чуть не хватило.",
        "Почти — не считается.", "На грани, но не в твою пользу.",
        "Сантиметры сыграли против тебя.", "Почти попал, но проиграл.",
        "Чуть не залетел — и чуть не выиграл.", "Почти — и это поражение.",
    ],
}

SLOT_DICE_EMOJI = "🎰"
SLOT_WAIT_SECONDS = 2.8
SLOT_MIN_BET = 0.5
SLOT_WIN_VALUE = 64
SLOT_MULTIPLIER = 40.0

SLOT_QUOTES_WIN = [
    "Барабаны остановились там, где нужно.",
    "Сегодня удача на твоей стороне.",
    "Три в ряд — и это твой день.",
    "Слоты улыбнулись именно тебе.",
    "Крутил не зря.",
    "Фортуна выбрала тебя.",
]

SLOT_QUOTES_LOSE = [
    "Барабаны остановились, но не там.",
    "Удача — дама капризная.",
    "Не в этот раз.",
    "Слоты — игра терпеливых.",
    "Сегодня не твой день.",
    "Крути ещё, повезёт.",
]

CANCEL_WORDS = {"/cancel", "отмена", "/отмена", "cancel"}

GAME_TRIGGER_PREFIXES = (
    "/start", "/balance", "/crash", "/краш", "/mines", "/мины",
    "/bonus", "/бонус", "/ref", "/реф", "/set", "/пополнить",
    "/profile", "/профиль", "/проф",
    "/game", "/games", "/игры", "/игра", "/играть",
    "/football", "/фут", "/футбол", "/фб",
    "/basketball", "/баскет", "/бс", "/бк",
    "/slot", "/slots", "/слоты", "/слот", "/автомат",
    "/darts", "/дартс", "/дс",
    "/bowling", "/боулинг", "/боул",
    "/cube", "/cubs", "/куб",
    "/send", "/дать", "/нк", "/перевод", "/передать", "/пер",
)

MINES_GAMES: dict = {}
MINES_NEXT_ID: int = 1
FOOTBALL_LAST_GAMES: dict = {}
BASKETBALL_LAST_GAMES: dict = {}
SLOT_LAST_GAMES: dict = {}

_db_conn: aiosqlite.Connection | None = None


class TimedLock:
    """asyncio.Lock that raises (and logs) instead of hanging forever."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        if not self._lock.locked():
            await self._lock.acquire()
            return self
        try:
            await asyncio.wait_for(self._lock.acquire(), timeout=DB_LOCK_TIMEOUT)
        except asyncio.TimeoutError:
            logging.error("DB lock wait exceeded %ss - possible deadlock/hang", DB_LOCK_TIMEOUT)
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self._lock.release()


_db_lock = TimedLock()

BACKGROUND_TASKS: set = set()
START_TIME = time.time()
HEARTBEAT: float = time.time()
DB_FAILS = 0
WATCHDOG_EXIT = os.getenv("WATCHDOG_EXIT", "1") == "1"
WATCHDOG_LOOP_DUMP_SECONDS = 60
WATCHDOG_LOOP_EXIT_SECONDS = 150
WATCHDOG_DB_FAILS_EXIT = 3
LAST_UPDATE_AT: float = 0.0
LOOP_LAG: float = 0.0
HAS_RETURNING = sqlite3.sqlite_version_info >= (3, 35, 0)
REGISTERED_CACHE: set = set()
NOTIFIED_CACHE: set = set()
SUBSCRIBED_UNTIL: dict = {}
SUBSCRIBED_TTL = 120
PENDING_BETS: dict = {}
_bet_seq = 0


def spawn(coro) -> "asyncio.Task":
    task = asyncio.get_running_loop().create_task(coro)
    BACKGROUND_TASKS.add(task)
    task.add_done_callback(BACKGROUND_TASKS.discard)
    return task


def register_bet(user_id: int, bet: float) -> int:
    global _bet_seq
    _bet_seq += 1
    PENDING_BETS[_bet_seq] = (user_id, bet)
    return _bet_seq


def pop_bet(bet_id: int) -> bool:
    """True if the bet was still pending (caller now owns settlement)."""
    return PENDING_BETS.pop(bet_id, None) is not None


async def refund_pending_bets() -> None:
    for bet_id in list(PENDING_BETS):
        item = PENDING_BETS.pop(bet_id, None)
        if item is None:
            continue
        user_id, bet = item
        try:
            await add_balance(user_id, bet)
            logging.info("refunded pending bet: user=%s bet=%s", user_id, bet)
        except Exception:
            logging.exception("refund of pending bet failed: user=%s bet=%s", user_id, bet)


def bet_task_done(task: "asyncio.Task", bet_id: int) -> None:
    if task.cancelled():
        exc = None
    else:
        exc = task.exception()
        if exc is not None:
            logging.error("game task failed", exc_info=exc)
    if (task.cancelled() or exc is not None) and bet_id in PENDING_BETS:
        item = PENDING_BETS.pop(bet_id, None)
        if item is not None:
            spawn(add_balance(item[0], item[1]))
_backup_task: asyncio.Task | None = None
_maint_task: asyncio.Task | None = None


class WithdrawStates(StatesGroup):
    waiting_amount = State()


class TelegramProfileStates(StatesGroup):
    waiting_nickname = State()


router = Router()


def db() -> aiosqlite.Connection:
    if _db_conn is None:
        raise RuntimeError("DB is not initialized")
    return _db_conn


async def get_telegram_language(user_id: int | None) -> str:
    if type(user_id) is not int or user_id <= 0:
        return "ru"
    cached = TELEGRAM_LANGUAGE_CACHE.get(user_id)
    if cached in {"ru", "en"}:
        return cached
    try:
        async with _db_lock:
            async with db().execute("SELECT language FROM telegram_user_settings WHERE user_id = ?", (user_id,)) as cursor:
                row = await cursor.fetchone()
        language = row[0] if row and row[0] in {"ru", "en"} else "ru"
    except Exception:
        language = "ru"
    TELEGRAM_LANGUAGE_CACHE[user_id] = language
    return language


async def set_telegram_language(user_id: int, language: str) -> None:
    if type(user_id) is not int or user_id <= 0 or language not in {"ru", "en"}:
        raise ValueError("Invalid Telegram language preference")
    async with _db_lock:
        conn = db()
        await conn.execute("INSERT INTO telegram_user_settings(user_id,language) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET language = excluded.language", (user_id, language))
        await conn.commit()
    TELEGRAM_LANGUAGE_CACHE[user_id] = language


async def db_init() -> None:
    global _db_conn
    _db_conn = await aiosqlite.connect(DB_PATH)
    await _db_conn.execute("PRAGMA journal_mode=WAL")
    await _db_conn.execute("PRAGMA synchronous=NORMAL")
    await _db_conn.execute("PRAGMA busy_timeout=5000")
    await _db_conn.execute("PRAGMA cache_size=-32768")
    await _db_conn.execute("PRAGMA temp_store=MEMORY")
    await _db_conn.execute("PRAGMA mmap_size=268435456")
    await _db_conn.execute("PRAGMA wal_autocheckpoint=1000")
    await _db_conn.execute("PRAGMA foreign_keys=ON")
    await _db_conn.commit()


async def db_close() -> None:
    global _db_conn
    if _db_conn is not None:
        await _db_conn.close()
        _db_conn = None


async def refund_open_mines() -> None:
    for gid in list(MINES_GAMES):
        game = MINES_GAMES.pop(gid, None)
        if not game or game.get("game_over"):
            continue
        game["game_over"] = True
        try:
            await add_balance(game["owner_id"], game["bet"])
        except Exception:
            logging.exception("mines refund failed: game=%s", gid)


def _die(reason: str) -> None:
    logging.critical("WATCHDOG: %s - exiting so the host restarts the bot", reason)
    logging.critical("pending bets at exit (refund manually if needed): %s", dict(PENDING_BETS))
    try:
        sys.stdout.flush()
    except Exception:
        pass
    os._exit(1)


def _thread_watchdog() -> None:
    """Runs in its own thread, so it still works when the event loop is frozen."""
    dumped = False
    while True:
        time.sleep(10)
        stale = time.time() - HEARTBEAT
        if stale < WATCHDOG_LOOP_DUMP_SECONDS:
            dumped = False
            continue
        if not dumped:
            dumped = True
            logging.critical("EVENT LOOP FROZEN for %.0fs, thread dump follows", stale)
            try:
                faulthandler.dump_traceback(file=sys.stdout, all_threads=True)
                sys.stdout.flush()
            except Exception:
                pass
        if WATCHDOG_EXIT and stale > WATCHDOG_LOOP_EXIT_SECONDS:
            _die(f"event loop frozen for {stale:.0f}s")


def dump_task_stacks() -> None:
    current = asyncio.current_task()
    for i, t in enumerate(asyncio.all_tasks()):
        if t is current or i >= 30:
            continue
        try:
            t.print_stack(limit=4, file=sys.stdout)
        except Exception:
            pass


async def maintenance_loop() -> None:
    """Event-loop lag watchdog, heartbeat and cleanup of abandoned mines games."""
    interval = 5
    last = time.monotonic()
    ticks = 0
    while True:
        await asyncio.sleep(interval)
        now = time.monotonic()
        global LOOP_LAG
        lag = max(0.0, now - last - interval)
        LOOP_LAG = lag
        last = now
        if lag > 2:
            logging.warning("Event loop lag: %.1fs", lag)

        global HEARTBEAT, DB_FAILS
        HEARTBEAT = time.time()

        ticks += 1
        if ticks % 6 == 0:
            try:
                await asyncio.wait_for(db_ping(), timeout=10)
                DB_FAILS = 0
            except BaseException as e:
                if isinstance(e, asyncio.CancelledError):
                    raise
                DB_FAILS += 1
                logging.critical(
                    "DB WATCHDOG: ping failed (%d/%d): %r",
                    DB_FAILS, WATCHDOG_DB_FAILS_EXIT, e,
                )
                dump_task_stacks()
                if WATCHDOG_EXIT and DB_FAILS >= WATCHDOG_DB_FAILS_EXIT:
                    _die("database unresponsive")

        if ticks % 60 == 0:
            logging.info(
                "alive: tasks=%d pending_bets=%d mines=%d",
                len(asyncio.all_tasks()), len(PENDING_BETS), len(MINES_GAMES),
            )

        for gid, game in list(MINES_GAMES.items()):
            if now - game.get("created_at", now) <= MINES_STALE_SECONDS:
                continue
            MINES_GAMES.pop(gid, None)
            if game.get("game_over"):
                continue
            game["game_over"] = True
            try:
                await add_balance(game["owner_id"], game["bet"])
                logging.info("stale mines game refunded: game=%s", gid)
            except Exception:
                logging.exception("stale mines refund failed: game=%s", gid)


def loop_exception_handler(loop, context) -> None:
    logging.error(
        "Unhandled loop exception: %s", context.get("message"),
        exc_info=context.get("exception"),
    )


def _backup_sync() -> None:
    tmp = BACKUP_PATH + ".tmp"
    try:
        os.remove(tmp)
    except FileNotFoundError:
        pass
    src = sqlite3.connect(DB_PATH, timeout=30)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    os.replace(tmp, BACKUP_PATH)


async def backup_loop() -> None:
    while True:
        await asyncio.sleep(BACKUP_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(_backup_sync)
            logging.info("DB backup done: %s", BACKUP_PATH)
        except Exception:
            logging.exception("DB backup failed")


@lru_cache(maxsize=64)
def _mines_table_cached(mines_count: int) -> tuple:
    return tuple(_mines_table_build(mines_count))


def mines_table_for(mines_count: int) -> tuple:
    return _mines_table_cached(mines_count)


def _mines_table_build(mines_count: int) -> list[float]:
    base_safe = MINES_TOTAL - MINES_MIN
    safe = MINES_TOTAL - mines_count
    if safe <= 0:
        return []

    scale = (base_safe / safe) ** 0.5

    result = []
    for value in MINES_BASE_TABLE[:safe]:
        scaled = value * scale
        result.append(min(round(scaled, 2), MINES_MAX_MULTIPLIER))
    return result


def mines_multiplier(opened: int, mines_count: int) -> float:
    if opened <= 0:
        return 1.0
    table = mines_table_for(mines_count)
    if not table:
        return 1.0
    if opened > len(table):
        return table[-1]
    return table[opened - 1]


def generate_payload() -> str:
    return "".join(secrets.choice(HASH_ALPHABET) for _ in range(8))


def parse_number(token: str) -> float | None:
    normalized = token.replace(",", ".")
    if normalized.startswith("."):
        normalized = "0" + normalized
    try:
        value = float(normalized)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return value


def parse_int(token: str) -> int | None:
    try:
        value = int(token)
    except ValueError:
        return None
    return value


def now_msk() -> datetime:
    return datetime.now(MSK)


def format_delta(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    if total < 0:
        total = 0
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_registration_date(iso_str: str | None) -> str:
    if not iso_str:
        return "дата неизвестна"
    try:
        dt = datetime.fromisoformat(iso_str)
    except ValueError:
        return "дата неизвестна"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=MSK)
    else:
        dt = dt.astimezone(MSK)
    return dt.strftime("%d.%m.%Y %H:%M:%S")


async def init_db() -> None:
    async with _db_lock:
        conn = db()

        await conn.execute(
            "CREATE TABLE IF NOT EXISTS balances ("
            "user_id INTEGER PRIMARY KEY, "
            "amount REAL NOT NULL DEFAULT 0, "
            "created_at TEXT"
            ")"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS notified ("
            "user_id INTEGER PRIMARY KEY"
            ")"
        )
        await conn.execute("CREATE TABLE IF NOT EXISTS webapp_wallet_events(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,kind TEXT NOT NULL,amount_cents INTEGER NOT NULL,source TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL)")
        await conn.execute("CREATE TABLE IF NOT EXISTS webapp_ref_events(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,referral_id INTEGER NOT NULL,kind TEXT NOT NULL,amount_cents INTEGER NOT NULL,source TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL)")
        await conn.execute("CREATE TABLE IF NOT EXISTS telegram_user_settings(user_id INTEGER PRIMARY KEY,language TEXT NOT NULL DEFAULT 'ru' CHECK(language IN ('ru','en')))")
        await conn.execute("CREATE TABLE IF NOT EXISTS telegram_group_owners(chat_id INTEGER PRIMARY KEY,owner_id INTEGER NOT NULL,chat_title TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL)")
        await conn.execute("CREATE TABLE IF NOT EXISTS telegram_group_referrals(chat_id INTEGER NOT NULL,user_id INTEGER NOT NULL,referrer_id INTEGER NOT NULL,joined_at TEXT NOT NULL,PRIMARY KEY(chat_id,user_id))")
        await conn.execute("CREATE TABLE IF NOT EXISTS telegram_group_loss_rewards(source TEXT PRIMARY KEY,chat_id INTEGER NOT NULL,user_id INTEGER NOT NULL,owner_id INTEGER NOT NULL,loss_cents INTEGER NOT NULL,share_cents INTEGER NOT NULL,created_at TEXT NOT NULL)")
        await conn.execute("CREATE TABLE IF NOT EXISTS webapp_privacy(user_id INTEGER PRIMARY KEY,mode TEXT NOT NULL DEFAULT 'username',nickname TEXT NOT NULL DEFAULT '',hidden INTEGER NOT NULL DEFAULT 0,clickable INTEGER NOT NULL DEFAULT 1,game_uid TEXT NOT NULL UNIQUE)")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS bonus ("
            "user_id INTEGER PRIMARY KEY, "
            "queued_at TEXT, "
            "streak INTEGER NOT NULL DEFAULT 0, "
            "last_claim TEXT"
            ")"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS referrals ("
            "user_id INTEGER PRIMARY KEY, "
            "referrer_id INTEGER NOT NULL, "
            "joined_at TEXT NOT NULL, "
            "is_premium INTEGER NOT NULL DEFAULT 0, "
            "signup_bonus_paid INTEGER NOT NULL DEFAULT 0, "
            "deposited INTEGER NOT NULL DEFAULT 0"
            ")"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS pending_referrals ("
            "user_id INTEGER PRIMARY KEY, "
            "referrer_id INTEGER NOT NULL, "
            "created_at TEXT NOT NULL"
            ")"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS ref_balance ("
            "user_id INTEGER PRIMARY KEY, "
            "signup_earned REAL NOT NULL DEFAULT 0, "
            "deposit_earned REAL NOT NULL DEFAULT 0, "
            "group_earned REAL NOT NULL DEFAULT 0, "
            "frozen INTEGER NOT NULL DEFAULT 0"
            ")"
        )
        async with conn.execute("PRAGMA table_info(ref_balance)") as cursor:
            referral_balance_columns = {row[1] for row in await cursor.fetchall()}
        if "group_earned" not in referral_balance_columns:
            await conn.execute("ALTER TABLE ref_balance ADD COLUMN group_earned REAL NOT NULL DEFAULT 0")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS payments ("
            "charge_id TEXT PRIMARY KEY, "
            "user_id INTEGER NOT NULL, "
            "amount INTEGER NOT NULL, "
            "created_at TEXT NOT NULL"
            ")"
        )
        await conn.execute("CREATE TABLE IF NOT EXISTS webapp_admin_deposits(source TEXT PRIMARY KEY,admin_id INTEGER NOT NULL,chat_id INTEGER NOT NULL,message_id INTEGER NOT NULL,user_id INTEGER NOT NULL,username TEXT NOT NULL,amount INTEGER NOT NULL,balance_after REAL NOT NULL,created_at TEXT NOT NULL,UNIQUE(chat_id,message_id))")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS nonce_counter ("
            "user_id INTEGER PRIMARY KEY, "
            "counter INTEGER NOT NULL DEFAULT 0"
            ")"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS crash_games ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id INTEGER NOT NULL, "
            "server_seed TEXT NOT NULL, "
            "client_seed TEXT NOT NULL, "
            "nonce INTEGER NOT NULL, "
            "crash_point REAL NOT NULL, "
            "raw_crash_point REAL NOT NULL, "
            "bet REAL NOT NULL, "
            "multiplier REAL NOT NULL, "
            "won INTEGER NOT NULL, "
            "created_at TEXT NOT NULL"
            ")"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS mines_history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id INTEGER NOT NULL, "
            "bet REAL NOT NULL, "
            "mines_count INTEGER NOT NULL, "
            "opened INTEGER NOT NULL, "
            "multiplier REAL NOT NULL, "
            "win_amount REAL NOT NULL, "
            "won INTEGER NOT NULL, "
            "created_at TEXT NOT NULL"
            ")"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS football_history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id INTEGER NOT NULL, "
            "bet REAL NOT NULL, "
            "player_range TEXT NOT NULL, "
            "landed_range TEXT NOT NULL, "
            "multiplier REAL NOT NULL, "
            "win_amount REAL NOT NULL, "
            "won INTEGER NOT NULL, "
            "created_at TEXT NOT NULL"
            ")"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS basketball_history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id INTEGER NOT NULL, "
            "bet REAL NOT NULL, "
            "player_range TEXT NOT NULL, "
            "landed_range TEXT NOT NULL, "
            "multiplier REAL NOT NULL, "
            "win_amount REAL NOT NULL, "
            "won INTEGER NOT NULL, "
            "created_at TEXT NOT NULL"
            ")"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS slot_history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id INTEGER NOT NULL, "
            "bet REAL NOT NULL, "
            "dice_value INTEGER NOT NULL, "
            "multiplier REAL NOT NULL, "
            "win_amount REAL NOT NULL, "
            "won INTEGER NOT NULL, "
            "created_at TEXT NOT NULL"
            ")"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS withdrawals ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "user_id INTEGER NOT NULL, "
            "amount REAL NOT NULL, "
            "status TEXT NOT NULL DEFAULT 'pending', "
            "admin_message_id INTEGER, "
            "created_at TEXT NOT NULL"
            ")"
        )

        async with conn.execute("PRAGMA table_info(balances)") as cursor:
            rows = await cursor.fetchall()
            columns = {row[1] for row in rows}
        if "created_at" not in columns:
            await conn.execute("ALTER TABLE balances ADD COLUMN created_at TEXT")

        async with conn.execute("SELECT user_id,language FROM telegram_user_settings") as cursor:
            TELEGRAM_LANGUAGE_CACHE.clear()
            TELEGRAM_LANGUAGE_CACHE.update({row[0]: row[1] for row in await cursor.fetchall() if row[1] in {"ru", "en"}})

        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_payments_user_created "
            "ON payments (user_id, created_at)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_referrals_referrer "
            "ON referrals (referrer_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_referrals_referrer_deposited "
            "ON referrals (referrer_id, deposited)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_crash_games_user "
            "ON crash_games (user_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mines_history_user "
            "ON mines_history (user_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_football_history_user "
            "ON football_history (user_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_basketball_history_user "
            "ON basketball_history (user_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_slot_history_user "
            "ON slot_history (user_id)"
        )

        await conn.commit()


async def get_balance(user_id: int) -> float:
    async with _db_lock:
        async with db().execute(
            "SELECT amount FROM balances WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0.0


async def add_balance(user_id: int, amount: float) -> float:
    async with _db_lock:
        conn = db()
        try:
            if HAS_RETURNING:
                async with conn.execute(
                    "INSERT INTO balances (user_id, amount, created_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET amount = ROUND(amount + ?, 2) "
                    "RETURNING amount",
                    (user_id, amount, now_msk().isoformat(), amount),
                ) as cursor:
                    rows = await cursor.fetchall()
                await conn.commit()
                REGISTERED_CACHE.add(user_id)
                return float(rows[0][0]) if rows else amount

            await conn.execute(
                "INSERT INTO balances (user_id, amount, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET amount = ROUND(amount + ?, 2)",
                (user_id, amount, now_msk().isoformat(), amount),
            )
            await conn.commit()
            async with conn.execute(
                "SELECT amount FROM balances WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
            REGISTERED_CACHE.add(user_id)
            return float(row[0]) if row else amount
        except BaseException:
            await conn.rollback()
            raise


async def try_withdraw(user_id: int, amount: float) -> bool:
    async with _db_lock:
        conn = db()
        cursor = await conn.execute(
            "UPDATE balances SET amount = ROUND(amount - ?, 2) "
            "WHERE user_id = ? AND amount + 1e-9 >= ?",
            (amount, user_id, amount),
        )
        await conn.commit()
        return cursor.rowcount == 1


async def set_balance(user_id: int, amount: float) -> None:
    async with _db_lock:
        conn = db()
        await conn.execute(
            "INSERT INTO balances (user_id, amount, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET amount = ?",
            (user_id, amount, now_msk().isoformat(), amount),
        )
        await conn.commit()


async def is_registered(user_id: int) -> bool:
    if user_id in REGISTERED_CACHE:
        return True
    async with _db_lock:
        async with db().execute(
            "SELECT 1 FROM balances WHERE user_id = ?", (user_id,)
        ) as cursor:
            found = await cursor.fetchone() is not None
    if found:
        REGISTERED_CACHE.add(user_id)
    return found


async def mark_notified(user_id: int) -> None:
    async with _db_lock:
        conn = db()
        await conn.execute(
            "INSERT OR IGNORE INTO notified (user_id) VALUES (?)", (user_id,)
        )
        await conn.commit()
    NOTIFIED_CACHE.add(user_id)


async def was_notified(user_id: int) -> bool:
    if user_id in NOTIFIED_CACHE:
        return True
    async with _db_lock:
        async with db().execute(
            "SELECT 1 FROM notified WHERE user_id = ?", (user_id,)
        ) as cursor:
            found = await cursor.fetchone() is not None
    if found:
        NOTIFIED_CACHE.add(user_id)
    return found


async def register_payment(charge_id: str, user_id: int, amount: int) -> bool:
    async with _db_lock:
        conn = db()
        cursor = await conn.execute(
            "INSERT OR IGNORE INTO payments (charge_id, user_id, amount, created_at) "
            "VALUES (?, ?, ?, ?)",
            (charge_id, user_id, amount, now_msk().isoformat()),
        )
        await conn.commit()
        return cursor.rowcount == 1


async def get_weekly_deposit(user_id: int) -> float:
    since = (now_msk() - timedelta(days=WITHDRAW_DEPOSIT_DAYS)).isoformat()
    async with _db_lock:
        async with db().execute(
            "SELECT COALESCE(SUM(amount), 0) FROM payments "
            "WHERE user_id = ? AND created_at >= ?",
            (user_id, since),
        ) as cursor:
            row = await cursor.fetchone()
            total = float(row[0]) if row else 0.0
        if _wallet_backend is not None:
            async with db().execute("SELECT COALESCE(SUM(stars_cents),0) FROM webapp_deposits WHERE user_id = ? AND provider != 'stars' AND status = 'paid' AND COALESCE(paid_at,created_at) >= ?", (user_id, since)) as cursor:
                total += (await cursor.fetchone())[0] / 100
        return total


async def create_withdrawal(user_id: int, amount: float) -> int:
    async with _db_lock:
        conn = db()
        cursor = await conn.execute(
            "INSERT INTO withdrawals (user_id, amount, status, created_at) "
            "VALUES (?, ?, 'pending', ?)",
            (user_id, amount, now_msk().isoformat()),
        )
        await conn.commit()
        return cursor.lastrowid


async def create_withdrawal_atomic(user_id: int, amount: float) -> tuple[bool, float, int | None]:
    async with _db_lock:
        conn = db()
        try:
            if _wallet_backend is not None:
                try:
                    await _wallet_backend.ensure_check_wager(conn, user_id)
                except GameError:
                    await conn.rollback()
                    return False, await _wallet_backend.balance(conn, user_id), None
            cursor = await conn.execute(
                "UPDATE balances SET amount = ROUND(amount - ?, 2) "
                "WHERE user_id = ? AND amount + 1e-9 >= ?",
                (amount, user_id, amount),
            )
            if cursor.rowcount != 1:
                await conn.rollback()
                return False, 0.0, None

            async with conn.execute(
                "SELECT amount FROM balances WHERE user_id = ?", (user_id,)
            ) as balance_cursor:
                row = await balance_cursor.fetchone()
                new_balance = row[0] if row else 0.0

            insert_cursor = await conn.execute(
                "INSERT INTO withdrawals (user_id, amount, status, created_at) "
                "VALUES (?, ?, 'pending', ?)",
                (user_id, amount, now_msk().isoformat()),
            )
            await conn.commit()
            return True, new_balance, insert_cursor.lastrowid
        except BaseException:
            await conn.rollback()
            raise


async def claim_withdrawal(withdrawal_id: int, new_status: str) -> dict | None:
    """Atomically move a pending withdrawal to new_status.

    Returns the withdrawal, or None if it was not pending anymore.
    Refunds the user in the same transaction for rejected/failed.
    """
    async with _db_lock:
        conn = db()
        try:
            cursor = await conn.execute(
                "UPDATE withdrawals SET status = ? WHERE id = ? AND status = 'pending'",
                (new_status, withdrawal_id),
            )
            if cursor.rowcount != 1:
                await conn.rollback()
                return None
            async with conn.execute(
                "SELECT id, user_id, amount, status, admin_message_id "
                "FROM withdrawals WHERE id = ?",
                (withdrawal_id,),
            ) as c:
                row = await c.fetchone()
            if row is None:
                await conn.rollback()
                return None
            w = {
                "id": row[0], "user_id": row[1], "amount": row[2],
                "status": row[3], "admin_message_id": row[4],
            }
            if new_status in ("rejected", "failed"):
                await conn.execute(
                    "INSERT INTO balances (user_id, amount, created_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET amount = ROUND(amount + ?, 2)",
                    (w["user_id"], w["amount"], now_msk().isoformat(), w["amount"]),
                )
            await conn.commit()
            return w
        except BaseException:
            await conn.rollback()
            raise


async def admin_deposit_atomic(admin_id: int, chat_id: int, message_id: int, username: str, amount: int) -> dict:
    """Admin-issued deposit; all financial records commit or roll back together."""
    if ADMIN_ID <= 0 or admin_id != ADMIN_ID:
        raise GameError("Команда доступна только администратору.", 403)
    if (not isinstance(username, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{2,31}", username)
            or type(amount) is not int or not 1 <= amount <= 1000000
            or type(chat_id) is not int or type(message_id) is not int or message_id <= 0):
        raise GameError("Формат: /addep @username 50. Сумма — целое число от 1 до 1 000 000 Stars.")
    if _wallet_backend is None:
        raise GameError("Платёжный учёт ещё не готов. Попробуйте позже.", 503)
    username = username.lower()
    source = f"admin-deposit:{chat_id}:{message_id}"
    async with _db_lock:
        conn = db()
        try:
            await conn.execute("BEGIN IMMEDIATE")
            async with conn.execute("SELECT admin_id,user_id,username,amount,balance_after FROM webapp_admin_deposits WHERE source=?", (source,)) as cursor:
                replay = await cursor.fetchone()
            if replay:
                if replay[0] != admin_id or replay[2] != username or replay[3] != amount:
                    raise GameError("Это сообщение уже использовано для другого начисления. Отправьте новую команду.", 409)
                await conn.rollback()
                return {"user_id": replay[1], "amount": amount, "balance": replay[4], "new": False}
            async with conn.execute("SELECT user_id FROM usernames WHERE username = ? COLLATE NOCASE LIMIT 2", (username,)) as cursor:
                users = await cursor.fetchall()
            if not users:
                raise GameError("Пользователь не найден. Он должен сначала открыть бота; username должен быть сохранён в приложении.", 404)
            if len(users) != 1:
                raise GameError("Username связан с несколькими записями. Уточните пользователя — начисление не выполнено.", 409)
            user_id = int(users[0][0])
            stamp = now_msk().isoformat()
            await conn.execute("INSERT INTO payments(charge_id,user_id,amount,created_at) VALUES (?,?,?,?)", (source, user_id, amount, stamp))
            await _wallet_backend.wallet_credit(conn, user_id, amount * 100, "deposit", source)
            await _wallet_backend.referral_credit(conn, user_id, amount * 100, source)
            async with conn.execute("SELECT amount FROM balances WHERE user_id=?", (user_id,)) as cursor:
                balance = float((await cursor.fetchone())[0])
            await conn.execute("INSERT INTO webapp_admin_deposits(source,admin_id,chat_id,message_id,user_id,username,amount,balance_after,created_at) VALUES (?,?,?,?,?,?,?,?,?)", (source, admin_id, chat_id, message_id, user_id, username, amount, balance, stamp))
            await conn.commit()
            return {"user_id": user_id, "amount": amount, "balance": balance, "new": True}
        except BaseException:
            await conn.rollback()
            raise


@router.message(Command("addep", ignore_case=True))
async def cmd_addep(message: Message) -> None:
    if message.from_user is None or ADMIN_ID <= 0 or message.from_user.id != ADMIN_ID:
        return
    if message.chat.type != ChatType.PRIVATE:
        await message.answer("Запустите /addep в личном чате с ботом.", parse_mode=None)
        return
    parts = (message.text or "").split()
    if (len(parts) != 3 or not re.fullmatch(r"/[Aa][Dd][Dd][Ee][Pp](?:@[A-Za-z0-9_]+)?", parts[0])
            or not re.fullmatch(r"@[A-Za-z][A-Za-z0-9_]{2,31}", parts[1])
            or not re.fullmatch(r"[0-9]{1,7}", parts[2])):
        await message.answer("Формат: /addep @username 50. Сумма — целое число от 1 до 1 000 000 Stars.", parse_mode=None)
        return
    try:
        result = await admin_deposit_atomic(message.from_user.id, message.chat.id, message.message_id, parts[1][1:], int(parts[2]))
    except GameError as error:
        await message.answer(error.message, parse_mode=None)
        return
    except Exception as error:
        logging.error("Admin deposit failed: %s", type(error).__name__)
        await message.answer("Результат начисления не подтверждён. Проверьте историю до отправки новой команды. Автоматическая повторная доставка исходного сообщения защищена от двойного начисления.", parse_mode=None)
        return
    title = "Депозит начислен" if result["new"] else "Это сообщение уже обработано; повторного начисления нет"
    await message.answer(f"{title}: @{parts[1][1:]} (ID {result['user_id']})\n+{result['amount']} Stars\nБаланс после начисления: {result['balance']:g} Stars.\nСумма учитывается как депозит, включая реферальные начисления.", parse_mode=None)


async def credit_payment(charge_id: str, user_id: int, amount: int) -> float | None:
    """Register payment and credit balance in one transaction.

    Returns new balance, or None if the payment was already processed.
    """
    async with _db_lock:
        conn = db()
        try:
            cursor = await conn.execute(
                "INSERT OR IGNORE INTO payments (charge_id, user_id, amount, created_at) "
                "VALUES (?, ?, ?, ?)",
                (charge_id, user_id, amount, now_msk().isoformat()),
            )
            if cursor.rowcount != 1:
                await conn.rollback()
                return None
            await conn.execute(
                "INSERT INTO balances (user_id, amount, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET amount = ROUND(amount + ?, 2)",
                (user_id, float(amount), now_msk().isoformat(), float(amount)),
            )
            async with conn.execute(
                "SELECT amount FROM balances WHERE user_id = ?", (user_id,)
            ) as c:
                row = await c.fetchone()
            if _wallet_backend is not None:
                await _wallet_backend.referral_credit(conn, user_id, amount * 100, "telegram:" + charge_id)
            await conn.commit()
            return float(row[0]) if row else float(amount)
        except BaseException:
            await conn.rollback()
            raise


async def claim_bonus(user_id: int, streak: int, total: float) -> bool:
    """Atomically consume the bonus queue and pay the bonus (no double claim)."""
    now_iso = now_msk().isoformat()
    async with _db_lock:
        conn = db()
        try:
            cursor = await conn.execute(
                "UPDATE bonus SET queued_at = NULL, streak = ?, last_claim = ? "
                "WHERE user_id = ? AND queued_at IS NOT NULL AND julianday(queued_at) <= julianday(?)",
                (streak, now_iso, user_id, (now_msk() - BONUS_COOLDOWN).isoformat()),
            )
            if cursor.rowcount != 1:
                await conn.rollback()
                return False
            await conn.execute(
                "INSERT INTO balances (user_id, amount, created_at) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET amount = ROUND(amount + ?, 2)",
                (user_id, total, now_iso, total),
            )
            await conn.execute("INSERT INTO webapp_wallet_events(user_id,kind,amount_cents,source,created_at) VALUES (?,'bonus',?,?,?)", (user_id, round(total * 100), "bonus:" + str(user_id) + ":" + now_iso, now_iso))
            await conn.commit()
            return True
        except BaseException:
            await conn.rollback()
            raise


async def set_withdrawal_admin_message(withdrawal_id: int, admin_message_id: int) -> None:
    async with _db_lock:
        conn = db()
        await conn.execute(
            "UPDATE withdrawals SET admin_message_id = ? WHERE id = ?",
            (admin_message_id, withdrawal_id),
        )
        await conn.commit()


async def get_withdrawal(withdrawal_id: int) -> dict | None:
    async with _db_lock:
        async with db().execute(
            "SELECT id, user_id, amount, status, admin_message_id FROM withdrawals WHERE id = ?",
            (withdrawal_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "user_id": row[1],
                "amount": row[2],
                "status": row[3],
                "admin_message_id": row[4],
            }


async def set_withdrawal_status(withdrawal_id: int, status: str) -> None:
    async with _db_lock:
        conn = db()
        await conn.execute(
            "UPDATE withdrawals SET status = ? WHERE id = ?",
            (status, withdrawal_id),
        )
        await conn.commit()


async def next_nonce(user_id: int) -> int:
    async with _db_lock:
        conn = db()
        try:
            if HAS_RETURNING:
                async with conn.execute(
                    "INSERT INTO nonce_counter (user_id, counter) VALUES (?, 1) "
                    "ON CONFLICT(user_id) DO UPDATE SET counter = counter + 1 "
                    "RETURNING counter",
                    (user_id,),
                ) as cursor:
                    rows = await cursor.fetchall()
                await conn.commit()
                return (rows[0][0] - 1) if rows else 0

            await conn.execute(
                "INSERT INTO nonce_counter (user_id, counter) VALUES (?, 1) "
                "ON CONFLICT(user_id) DO UPDATE SET counter = counter + 1",
                (user_id,),
            )
            await conn.commit()
            async with conn.execute(
                "SELECT counter FROM nonce_counter WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
            return (row[0] - 1) if row else 0
        except BaseException:
            await conn.rollback()
            raise


async def get_ref_data(user_id: int) -> dict:
    async with _db_lock:
        async with db().execute(
            "SELECT signup_earned, deposit_earned, group_earned, frozen FROM ref_balance WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return {"signup_earned": 0.0, "deposit_earned": 0.0, "group_earned": 0.0, "frozen": 0}
            return {
                "signup_earned": row[0],
                "deposit_earned": row[1],
                "group_earned": row[2],
                "frozen": row[3],
            }


async def set_ref_frozen(user_id: int, frozen: int) -> None:
    async with _db_lock:
        conn = db()
        await conn.execute(
            "INSERT INTO ref_balance (user_id, frozen) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET frozen = ?",
            (user_id, frozen, frozen),
        )
        await conn.commit()


async def count_referrals(user_id: int) -> int:
    async with _db_lock:
        conn = db()
        async with conn.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            confirmed = row[0] if row else 0
        async with conn.execute(
            "SELECT COUNT(*) FROM pending_referrals WHERE referrer_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            pending = row[0] if row else 0
        return confirmed + pending


async def count_referrals_deposited(user_id: int) -> int:
    async with _db_lock:
        async with db().execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND deposited = 1",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def is_ref_frozen(user_id: int) -> bool:
    total = await count_referrals(user_id)
    deposited = await count_referrals_deposited(user_id)
    limit = REF_BASE_LIMIT + REF_LIMIT_PER_DEPOSIT * deposited
    return total > limit


async def update_ref_frozen(user_id: int) -> None:
    frozen = 1 if await is_ref_frozen(user_id) else 0
    await set_ref_frozen(user_id, frozen)


async def get_referral(referral_id: int) -> dict | None:
    async with _db_lock:
        async with db().execute(
            "SELECT user_id, referrer_id, is_premium, signup_bonus_paid FROM referrals WHERE user_id = ?",
            (referral_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return {
                "user_id": row[0],
                "referrer_id": row[1],
                "is_premium": row[2],
                "signup_bonus_paid": row[3],
            }


async def add_referral(referral_id: int, referrer_id: int, is_premium: bool) -> None:
    now_iso = now_msk().isoformat()
    async with _db_lock:
        conn = db()
        await conn.execute(
            "INSERT OR IGNORE INTO referrals (user_id, referrer_id, joined_at, is_premium) "
            "VALUES (?, ?, ?, ?)",
            (referral_id, referrer_id, now_iso, int(is_premium)),
        )
        await conn.commit()


async def save_pending_referral(user_id: int, referrer_id: int) -> None:
    if user_id == referrer_id:
        return
    async with _db_lock:
        conn = db()
        await conn.execute(
            "INSERT INTO pending_referrals (user_id, referrer_id, created_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "referrer_id = excluded.referrer_id, "
            "created_at = excluded.created_at",
            (user_id, referrer_id, now_msk().isoformat()),
        )
        await conn.commit()


async def get_pending_referral(user_id: int) -> int | None:
    async with _db_lock:
        async with db().execute(
            "SELECT referrer_id FROM pending_referrals WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None


async def delete_pending_referral(user_id: int) -> None:
    async with _db_lock:
        conn = db()
        await conn.execute(
            "DELETE FROM pending_referrals WHERE user_id = ?",
            (user_id,),
        )
        await conn.commit()


async def process_referral_signup(referral_id: int, is_premium: bool) -> bool:
    ref = await get_referral(referral_id)
    if ref is None:
        return False

    referrer_id = ref["referrer_id"]
    bonus = REF_SIGNUP_PREMIUM if is_premium else REF_SIGNUP_BASE

    async with _db_lock:
        conn = db()
        try:
            cursor = await conn.execute(
                "UPDATE referrals SET signup_bonus_paid = 1 "
                "WHERE user_id = ? AND signup_bonus_paid = 0",
                (referral_id,),
            )
            if cursor.rowcount != 1:
                await conn.rollback()
                return False

            await conn.execute(
                "INSERT INTO ref_balance (user_id, signup_earned) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET signup_earned = signup_earned + ?",
                (referrer_id, bonus, bonus),
            )
            await conn.execute("INSERT OR IGNORE INTO webapp_ref_events(user_id,referral_id,kind,amount_cents,source,created_at) VALUES (?,?,'signup',?,?,?)", (referrer_id, referral_id, round(bonus * 100), "signup:" + str(referral_id), now_msk().isoformat()))
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise

    await update_ref_frozen(referrer_id)
    return True


async def process_referral_deposit(referral_id: int, deposit_amount: float) -> None:
    ref = await get_referral(referral_id)
    if ref is None:
        return

    referrer_id = ref["referrer_id"]
    earn = round(deposit_amount * REF_DEPOSIT_PERCENT, 2)
    if earn <= 0:
        return

    async with _db_lock:
        conn = db()
        try:
            await conn.execute(
                "UPDATE referrals SET deposited = 1 WHERE user_id = ?",
                (referral_id,),
            )
            await conn.execute(
                "INSERT INTO ref_balance (user_id, deposit_earned) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET deposit_earned = deposit_earned + ?",
                (referrer_id, earn, earn),
            )
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise

    await update_ref_frozen(referrer_id)


async def try_pay_referral_signup(user_id: int, user, bot: Bot) -> bool:
    ref = await get_referral(user_id)
    if ref is None or ref["signup_bonus_paid"]:
        return False

    paid = await process_referral_signup(user_id, bool(user.is_premium))
    if not paid:
        return False

    if _wallet_backend is not None:
        async with _db_lock:
            async with db().execute("SELECT ref_notifications FROM webapp_preferences WHERE user_id = ?", (ref["referrer_id"],)) as cursor:
                preference = await cursor.fetchone()
        if preference is not None and not preference[0]:
            return True
    try:
        await bot.send_message(
            ref["referrer_id"],
            '<tg-emoji emoji-id="5814662914442797254">👥</tg-emoji>'
            f'<b>По вашей ссылке зашёл новый пользователь: {user_link(user)}</b>',
        )
    except Exception:
        logging.exception("Failed to notify referrer %s", ref["referrer_id"])

    return True


def amount_to_stars_cents(value) -> int:
    try:
        amount = Decimal(str(value))
    except Exception:
        return 0
    if not amount.is_finite():
        return 0
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


async def refresh_telegram_group_owner(bot: Bot, chat_id: int, chat_title: str = "") -> int | None:
    if type(chat_id) is not int or chat_id >= 0:
        return None
    try:
        administrators = await bot.get_chat_administrators(chat_id=chat_id)
    except Exception:
        # Membership updates can race Telegram permissions while the bot is added.
        return None
    owner = next((item.user for item in administrators if item.status == ChatMemberStatus.CREATOR), None)
    if owner is None or type(owner.id) is not int:
        return None
    async with _db_lock:
        conn = db()
        await conn.execute(
            "INSERT INTO telegram_group_owners(chat_id,owner_id,chat_title,updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET owner_id=excluded.owner_id,chat_title=excluded.chat_title,updated_at=excluded.updated_at",
            (chat_id, owner.id, (chat_title or "")[:255], now_msk().isoformat()),
        )
        await conn.commit()
    return owner.id


async def record_telegram_group_members(bot: Bot, chat_id: int, chat_title: str, members) -> None:
    owner_id = await refresh_telegram_group_owner(bot, chat_id, chat_title)
    if owner_id is None:
        return
    stamp = now_msk().isoformat()
    async with _db_lock:
        conn = db()
        for member in members:
            if member is None or getattr(member, "is_bot", False) or type(getattr(member, "id", None)) is not int:
                continue
            await conn.execute(
                "INSERT OR IGNORE INTO telegram_group_referrals(chat_id,user_id,referrer_id,joined_at) VALUES (?,?,?,?)",
                (chat_id, member.id, owner_id, stamp),
            )
            display_name = " ".join(part for part in (getattr(member, "first_name", ""), getattr(member, "last_name", "")) if part)
            await conn.execute(
                "INSERT INTO usernames(user_id,username,full_name,updated_at) VALUES (?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,full_name=excluded.full_name,updated_at=excluded.updated_at "
                "WHERE usernames.username IS NOT excluded.username OR usernames.full_name != excluded.full_name",
                (member.id, getattr(member, "username", None), display_name, stamp),
            )
            TELEGRAM_NAMES[member.id] = getattr(member, "username", None)
        await conn.commit()


async def credit_telegram_group_loss(connection, chat_id: int | None, user_id: int, bet, payout, source: str, created_at: str | None = None) -> int:
    """Credit half of a settled net loss to the chat's referral balance once."""
    if type(chat_id) is not int or chat_id >= 0 or not isinstance(source, str) or not source:
        return 0
    loss_cents = max(0, amount_to_stars_cents(bet) - amount_to_stars_cents(payout))
    if loss_cents <= 0:
        return 0
    # Half-up at the smallest supported wallet unit (0.01 Stars).
    share_cents = (loss_cents + 1) // 2
    async with connection.execute("SELECT owner_id FROM telegram_group_owners WHERE chat_id = ?", (chat_id,)) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return 0
    owner_id = int(row[0])
    stamp = created_at or now_msk().isoformat()
    await connection.execute("SAVEPOINT telegram_group_loss_reward")
    try:
        cursor = await connection.execute(
            "INSERT OR IGNORE INTO telegram_group_loss_rewards(source,chat_id,user_id,owner_id,loss_cents,share_cents,created_at) VALUES (?,?,?,?,?,?,?)",
            (source, chat_id, user_id, owner_id, loss_cents, share_cents, stamp),
        )
        if cursor.rowcount != 1:
            await connection.execute("RELEASE SAVEPOINT telegram_group_loss_reward")
            return 0
        await connection.execute(
            "INSERT INTO ref_balance(user_id,group_earned) VALUES (?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET group_earned=ROUND(group_earned+excluded.group_earned,2)",
            (owner_id, share_cents / 100),
        )
        await connection.execute(
            "INSERT INTO webapp_ref_events(user_id,referral_id,kind,amount_cents,source,created_at) VALUES (?,?,'group_loss',?,?,?)",
            (owner_id, user_id, share_cents, source, stamp),
        )
        await connection.execute("RELEASE SAVEPOINT telegram_group_loss_reward")
        return share_cents
    except BaseException:
        await connection.execute("ROLLBACK TO SAVEPOINT telegram_group_loss_reward")
        await connection.execute("RELEASE SAVEPOINT telegram_group_loss_reward")
        raise


async def save_crash_game(
    user_id: int,
    server_seed: str,
    client_seed: str,
    nonce: int,
    crash_point: float,
    raw_crash_point: float,
    bet: float,
    multiplier: float,
    won: bool,
    chat_id: int | None = None,
    idempotency_key: str | None = None,
) -> None:
    async with _db_lock:
        conn = db()
        stamp = now_msk().isoformat()
        try:
            cursor = await conn.execute(
                "INSERT INTO crash_games ("
                "user_id, server_seed, client_seed, nonce, crash_point, "
                "raw_crash_point, bet, multiplier, won, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, server_seed, client_seed, nonce, crash_point, raw_crash_point, bet, multiplier, int(won), stamp),
            )
            payout = round(bet * multiplier, 2) if won else 0.0
            await credit_telegram_group_loss(conn, chat_id, user_id, bet, payout, f"bot:crash:{idempotency_key}" if idempotency_key else f"bot:crash:{cursor.lastrowid}", stamp)
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


async def save_mines_game(
    user_id: int,
    bet: float,
    mines_count: int,
    opened: int,
    multiplier: float,
    win_amount: float,
    won: bool,
    chat_id: int | None = None,
    idempotency_key: str | None = None,
) -> None:
    async with _db_lock:
        conn = db()
        stamp = now_msk().isoformat()
        try:
            cursor = await conn.execute(
                "INSERT INTO mines_history (user_id, bet, mines_count, opened, multiplier, win_amount, won, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, bet, mines_count, opened, multiplier, win_amount, int(won), stamp),
            )
            await credit_telegram_group_loss(conn, chat_id, user_id, bet, win_amount, f"bot:mines:{idempotency_key}" if idempotency_key else f"bot:mines:{cursor.lastrowid}", stamp)
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


async def save_football_game(
    user_id: int,
    bet: float,
    player_range: str,
    landed_range: str,
    multiplier: float,
    win_amount: float,
    won: bool,
    chat_id: int | None = None,
    idempotency_key: str | None = None,
) -> None:
    async with _db_lock:
        conn = db()
        stamp = now_msk().isoformat()
        try:
            cursor = await conn.execute(
                "INSERT INTO football_history (user_id, bet, player_range, landed_range, multiplier, win_amount, won, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, bet, player_range, landed_range, multiplier, win_amount, int(won), stamp),
            )
            await credit_telegram_group_loss(conn, chat_id, user_id, bet, win_amount, f"bot:football:{idempotency_key}" if idempotency_key else f"bot:football:{cursor.lastrowid}", stamp)
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


async def save_basketball_game(
    user_id: int,
    bet: float,
    player_range: str,
    landed_range: str,
    multiplier: float,
    win_amount: float,
    won: bool,
    chat_id: int | None = None,
    idempotency_key: str | None = None,
) -> None:
    async with _db_lock:
        conn = db()
        stamp = now_msk().isoformat()
        try:
            cursor = await conn.execute(
                "INSERT INTO basketball_history (user_id, bet, player_range, landed_range, multiplier, win_amount, won, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, bet, player_range, landed_range, multiplier, win_amount, int(won), stamp),
            )
            await credit_telegram_group_loss(conn, chat_id, user_id, bet, win_amount, f"bot:basketball:{idempotency_key}" if idempotency_key else f"bot:basketball:{cursor.lastrowid}", stamp)
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


async def save_slot_game(
    user_id: int,
    bet: float,
    dice_value: int,
    multiplier: float,
    win_amount: float,
    won: bool,
    chat_id: int | None = None,
    idempotency_key: str | None = None,
) -> None:
    async with _db_lock:
        conn = db()
        stamp = now_msk().isoformat()
        try:
            cursor = await conn.execute(
                "INSERT INTO slot_history (user_id, bet, dice_value, multiplier, win_amount, won, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, bet, dice_value, multiplier, win_amount, int(won), stamp),
            )
            await credit_telegram_group_loss(conn, chat_id, user_id, bet, win_amount, f"bot:slot:{idempotency_key}" if idempotency_key else f"bot:slot:{cursor.lastrowid}", stamp)
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


async def get_profile_stats(user_id: int) -> dict:
    async with _db_lock:
        conn = db()

        async with conn.execute(
            "SELECT created_at FROM balances WHERE user_id = ?", (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
            created_at = row[0] if row else None

        async with conn.execute(
            "SELECT "
            "COALESCE(MAX(CASE WHEN won = 1 THEN bet * multiplier ELSE 0 END), 0), "
            "COALESCE(MAX(bet), 0), "
            "COUNT(*) "
            "FROM crash_games WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            crash_max_win = float(row[0]) if row else 0.0
            crash_max_bet = float(row[1]) if row else 0.0
            crash_games = int(row[2]) if row else 0

        async with conn.execute(
            "SELECT "
            "COALESCE(MAX(win_amount), 0), "
            "COALESCE(MAX(bet), 0), "
            "COUNT(*) "
            "FROM mines_history WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            mines_max_win = float(row[0]) if row else 0.0
            mines_max_bet = float(row[1]) if row else 0.0
            mines_games = int(row[2]) if row else 0

        async with conn.execute(
            "SELECT "
            "COALESCE(MAX(win_amount), 0), "
            "COALESCE(MAX(bet), 0), "
            "COUNT(*) "
            "FROM football_history WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            football_max_win = float(row[0]) if row else 0.0
            football_max_bet = float(row[1]) if row else 0.0
            football_games = int(row[2]) if row else 0

        async with conn.execute(
            "SELECT "
            "COALESCE(MAX(win_amount), 0), "
            "COALESCE(MAX(bet), 0), "
            "COUNT(*) "
            "FROM basketball_history WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            basketball_max_win = float(row[0]) if row else 0.0
            basketball_max_bet = float(row[1]) if row else 0.0
            basketball_games = int(row[2]) if row else 0

        async with conn.execute(
            "SELECT "
            "COALESCE(MAX(win_amount), 0), "
            "COALESCE(MAX(bet), 0), "
            "COUNT(*) "
            "FROM slot_history WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            slot_max_win = float(row[0]) if row else 0.0
            slot_max_bet = float(row[1]) if row else 0.0
            slot_games = int(row[2]) if row else 0

        return {
            "created_at": created_at,
            "max_win": max(
                crash_max_win, mines_max_win,
                football_max_win, basketball_max_win, slot_max_win,
            ),
            "max_bet": max(
                crash_max_bet, mines_max_bet,
                football_max_bet, basketball_max_bet, slot_max_bet,
            ),
            "games": (
                crash_games + mines_games
                + football_games + basketball_games + slot_games
            ),
        }


async def get_bonus_data(user_id: int) -> dict | None:
    async with _db_lock:
        async with db().execute(
            "SELECT user_id, queued_at, streak, last_claim FROM bonus WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return {
                "user_id": row[0],
                "queued_at": row[1],
                "streak": row[2],
                "last_claim": row[3],
            }


async def set_bonus_queued(user_id: int) -> None:
    now_iso = now_msk().isoformat()
    async with _db_lock:
        conn = db()
        await conn.execute(
            "INSERT INTO bonus (user_id, queued_at, streak, last_claim) "
            "VALUES (?, ?, 0, NULL) "
            "ON CONFLICT(user_id) DO UPDATE SET queued_at = ?",
            (user_id, now_iso, now_iso),
        )
        await conn.commit()


async def clear_bonus_queue(user_id: int) -> None:
    async with _db_lock:
        conn = db()
        await conn.execute(
            "UPDATE bonus SET queued_at = NULL WHERE user_id = ?", (user_id,)
        )
        await conn.commit()


async def update_bonus_streak(user_id: int, streak: int) -> None:
    now_iso = now_msk().isoformat()
    async with _db_lock:
        conn = db()
        await conn.execute(
            "UPDATE bonus SET streak = ?, last_claim = ? WHERE user_id = ?",
            (streak, now_iso, user_id),
        )
        await conn.commit()


def compute_streak(data: dict | None) -> int:
    if data is None or data["last_claim"] is None:
        return 1

    last = datetime.fromisoformat(data["last_claim"])
    now = now_msk()
    diff = now.date() - last.date()

    if diff.days == 0:
        return data["streak"]
    if diff.days == 1:
        return data["streak"] + 1
    return 1


def streak_bonus(streak: int) -> float:
    return round(BONUS_STREAK_BASE + (streak - 1) * BONUS_STREAK_STEP, 2)


def base_bonus() -> float:
    steps = int((BONUS_BASE_MAX - BONUS_BASE_MIN) * 10) + 1
    raw = BONUS_BASE_MIN + secrets.randbelow(steps) / 10
    return round(raw, 2)


async def is_subscribed(bot: Bot, user_id: int) -> bool:
    until = SUBSCRIBED_UNTIL.get(user_id)
    if until is not None and until > time.monotonic():
        return True
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        ok = member.status not in (
            ChatMemberStatus.LEFT,
            ChatMemberStatus.KICKED,
        )
        if ok:
            if len(SUBSCRIBED_UNTIL) > 50000:
                SUBSCRIBED_UNTIL.clear()
            SUBSCRIBED_UNTIL[user_id] = time.monotonic() + SUBSCRIBED_TTL
        return ok
    except Exception:
        logging.exception("get_chat_member failed for user %s", user_id)
        return False


def user_link(user) -> str:
    name, clickable = player_identity(user.id, user.full_name)
    return f'<a href="tg://user?id={user.id}">{html_escape(name)}</a>' if clickable else html_escape(name)


def check_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Канал",
                    url=CHANNEL_URL,
                    icon_custom_emoji_id="5271604874419647061",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="Проверить",
                    callback_data="check_sub",
                    icon_custom_emoji_id="5416081784641168838",
                    style="success",
                ),
            ]
        ]
    )


def balance_markup_private() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пополнить",
                    callback_data="balance_topup",
                    icon_custom_emoji_id="4988289890769699938",
                    style="success",
                ),
                InlineKeyboardButton(
                    text="Вывод",
                    callback_data="balance_withdraw",
                    icon_custom_emoji_id="4983748881977181112",
                    style="success",
                ),
            ]
        ]
    )


def balance_markup_group(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пополнить",
                    url=f"https://t.me/{bot_username}?start=toreplenish",
                    icon_custom_emoji_id="4988289890769699938",
                    style="success",
                ),
                InlineKeyboardButton(
                    text="Вывод",
                    url=f"https://t.me/{bot_username}?start=withdraw",
                    icon_custom_emoji_id="4983748881977181112",
                    style="success",
                ),
            ]
        ]
    )


def register_markup(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Зарегистрироваться",
                    url=f"https://t.me/{bot_username}?start=start",
                    icon_custom_emoji_id="5953810354365538566",
                    style="success",
                ),
            ]
        ]
    )


def get_bonus_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Получить Бонус",
                    callback_data="get_bonus",
                    icon_custom_emoji_id="5193085063998224234",
                    style="success",
                ),
            ]
        ]
    )


def ref_markup(user_id: int) -> InlineKeyboardMarkup:
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Снять",
                    callback_data="ref_withdraw",
                    icon_custom_emoji_id="4983748881977181112",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="Скопировать",
                    copy_text=CopyTextButton(text=ref_link),
                    icon_custom_emoji_id="5375129357373165375",
                    style="primary",
                ),
            ]
        ]
    )


async def answer_referral(message: Message, text: str, reply_markup: InlineKeyboardMarkup):
    """A rejected custom-emoji document must not disable the referral command."""
    try:
        return await message.answer(text, reply_markup=reply_markup)
    except TelegramBadRequest as error:
        if not re.search(r"\bDOCUMENT_INVALID\b", error.message):
            raise
        # Telegram rejected this send, so one plain-emoji retry cannot duplicate
        # an accepted message. Do not retry timeouts or unrelated API failures.
        plain_text = re.sub(r"</?tg-emoji\b[^>]*>", "", text, flags=re.IGNORECASE)
        plain_markup = reply_markup.model_copy(update={"inline_keyboard": [
            [button.model_copy(update={"icon_custom_emoji_id": None}) for button in row]
            for row in reply_markup.inline_keyboard
        ]})
        logging.warning("Referral message: DOCUMENT_INVALID; retrying without custom emoji")
        return await message.answer(plain_text, reply_markup=plain_markup)


def topup_markup() -> InlineKeyboardMarkup:
    amounts = ["5", "10", "15", "25", "50", "100", "250", "500", "1000", "2000", "10000"]
    rows = [amounts[i:i + 3] for i in range(0, len(amounts), 3)]
    keyboard = [
        [
            InlineKeyboardButton(
                text=amt,
                callback_data=f"topup_{amt}",
                icon_custom_emoji_id="5954135079662916434",
            )
            for amt in row
        ]
        for row in rows
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def hash_markup(server_seed: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="hash",
                    copy_text=CopyTextButton(text=server_seed),
                    icon_custom_emoji_id="5429405838345265327",
                    style="primary",
                ),
            ]
        ]
    )


def withdraw_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Вывести всё",
                    callback_data="withdraw_all",
                    icon_custom_emoji_id="5053473385355412667",
                    style="success",
                ),
            ]
        ]
    )


def withdraw_admin_markup(withdrawal_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Одобрить",
                    callback_data=f"withdraw_approve_{withdrawal_id}",
                    style="success",
                ),
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"withdraw_reject_{withdrawal_id}",
                    style="danger",
                ),
            ]
        ]
    )


def football_markup_disabled(amount: float, range_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{round(amount, 2)}⭐️/{range_name}",
                    callback_data="football_noop",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Пополнить",
                    url=f"https://t.me/{BOT_USERNAME}?start=toreplenish",
                    icon_custom_emoji_id="5443127283898405358",
                    style="success",
                ),
            ],
        ]
    )


def football_markup_replay() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Повторить",
                    callback_data="football_replay",
                    icon_custom_emoji_id="5264727218734524899",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="Ва-банк",
                    callback_data="football_vabank",
                    icon_custom_emoji_id="5424972470023104089",
                    style="danger",
                ),
            ]
        ]
    )


def basketball_markup_disabled(amount: float, range_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{round(amount, 2)}⭐️/{range_name}",
                    callback_data="basketball_noop",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Пополнить",
                    url=f"https://t.me/{BOT_USERNAME}?start=toreplenish",
                    icon_custom_emoji_id="5443127283898405358",
                    style="success",
                ),
            ],
        ]
    )


def basketball_markup_replay() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Повторить",
                    callback_data="basketball_replay",
                    icon_custom_emoji_id="5264727218734524899",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="Ва-банк",
                    callback_data="basketball_vabank",
                    icon_custom_emoji_id="5424972470023104089",
                    style="danger",
                ),
            ]
        ]
    )


def slot_markup_disabled(amount: float) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{round(amount, 2)}⭐️",
                    callback_data="slot_noop",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Пополнить",
                    url=f"https://t.me/{BOT_USERNAME}?start=toreplenish",
                    icon_custom_emoji_id="5443127283898405358",
                    style="success",
                ),
            ],
        ]
    )


def slot_markup_replay() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Повторить",
                    callback_data="slot_replay",
                    icon_custom_emoji_id="5264727218734524899",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="Ва-банк",
                    callback_data="slot_vabank",
                    icon_custom_emoji_id="5424972470023104089",
                    style="danger",
                ),
            ]
        ]
    )


def soon_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Channel",
                    url=CHANNEL_URL,
                    icon_custom_emoji_id="5008457489528652800",
                    style="primary",
                ),
            ]
        ]
    )


def soon_text() -> str:
    return (
        '<tg-emoji emoji-id="5051114649445991756">🔠</tg-emoji>'
        '<tg-emoji emoji-id="5050987303665665245">🔠</tg-emoji>'
        '<tg-emoji emoji-id="5053271642151584876">🔠</tg-emoji>'
        '<tg-emoji emoji-id="5051108567772300271">🔠</tg-emoji>'
        '<tg-emoji emoji-id="5053572629164721435">🔠</tg-emoji>'
        '<tg-emoji emoji-id="5019824691708167395">⭐️</tg-emoji>\n\n'
        '<b><tg-emoji emoji-id="5210956306952758910">👀</tg-emoji> Soon! Follow the news in the channel</b>'
    )


def game_usage_text(user, command_line: str) -> str:
    return (
        '<i><tg-emoji emoji-id="5008457489528652800">🤠</tg-emoji>'
        f'{user_link(user)}, правильное использование команды:\n\n '
        '<tg-emoji emoji-id="5949468670710258892">🚀</tg-emoji>'
        f'<code> {command_line}</code>\n '
        '<tg-emoji emoji-id="5055840333242303386">🤑</tg-emoji>'
        '<b>Удачной игры в Major!</b></i>'
    )


def crash_usage_text(user) -> str:
    return game_usage_text(user, "/crash [ставка] [диапазон]")


def mines_usage_text(user) -> str:
    return game_usage_text(user, "/mines [ставка] [мины]")


def football_usage_text(user) -> str:
    return (
        '<i><tg-emoji emoji-id="5008457489528652800">🤠</tg-emoji>'
        f'{user_link(user)}, правильное использование команды:\n\n '
        '<tg-emoji emoji-id="5949468670710258892">🚀</tg-emoji>'
        '<code> /football [ставка] [диапазон]</code>\n '
        '<tg-emoji emoji-id="5055840333242303386">🤑</tg-emoji>'
        '<b>Удачной игры в Major!</b>\n\n '
        'Диапазоны: мимо, штанга, перелёт, нижний, право, гол, прямо, центр, классик, девятка</i>'
    )


def basketball_usage_text(user) -> str:
    return (
        '<i><tg-emoji emoji-id="5008457489528652800">🤠</tg-emoji>'
        f'{user_link(user)}, правильное использование команды:\n\n '
        '<tg-emoji emoji-id="5949468670710258892">🚀</tg-emoji>'
        '<code> /basketball [ставка] [диапазон]</code>\n '
        '<tg-emoji emoji-id="5055840333242303386">🤑</tg-emoji>'
        '<b>Удачной игры в Major!</b>\n\n '
        'Диапазоны: классик, мимо, отскок, застрянет, почти</i>'
    )


def slot_usage_text(user) -> str:
    return (
        '<i><tg-emoji emoji-id="5008457489528652800">🤠</tg-emoji>'
        f'{user_link(user)}, правильное использование команды:\n\n '
        '<tg-emoji emoji-id="5949468670710258892">🚀</tg-emoji>'
        '<code> /slot [ставка]</code>\n '
        '<tg-emoji emoji-id="5055840333242303386">🤑</tg-emoji>'
        '<b>Удачной игры в Major!</b></i>'
    )


def generate_server_seed() -> str:
    return secrets.token_hex(32)


def server_seed_hash(server_seed: str) -> str:
    return hashlib.sha256(server_seed.encode()).hexdigest()


def crash_point_from_seeds(server_seed: str, client_seed: str, nonce: int) -> tuple[float, float]:
    message = f"{client_seed}:{nonce}".encode()
    h = hmac.new(server_seed.encode(), message, hashlib.sha256).hexdigest()
    h_int = int(h[:13], 16)
    e = 2 ** 52
    h_float = h_int / e

    raw = math.floor((100.0 * HOUSE_EDGE) / (1.0 - h_float)) / 100.0
    raw = max(1.00, raw)

    capped = min(raw, MAX_MULTIPLIER)

    return round(capped, 2), round(raw, 2)


def mines_from_seeds(server_seed: str, client_seed: str, nonce: int, mines_count: int) -> list[int]:
    seed_bytes = f"{server_seed}:{client_seed}:{nonce}:mines".encode()
    positions = list(range(MINES_TOTAL))
    result = []

    for i in range(mines_count):
        h = hmac.new(seed_bytes, str(i).encode(), hashlib.sha256).hexdigest()
        idx = int(h[:13], 16) % len(positions)
        result.append(positions.pop(idx))

    return sorted(result)


def mines_grid_markup(game: dict, game_over: bool = False, won: bool = False) -> InlineKeyboardMarkup:
    revealed = game.get("revealed", set())
    mine_positions = set(game.get("mine_positions", []))
    exploded_mine = game.get("exploded_mine")
    game_id = game["id"]

    keyboard_rows = []
    for row in range(MINES_GRID):
        row_buttons = []
        for col in range(MINES_GRID):
            idx = row * MINES_GRID + col
            if game_over and idx in mine_positions:
                if idx == exploded_mine:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"mines_noop_{game_id}",
                            icon_custom_emoji_id="5276032951342088188",
                            style="danger",
                        )
                    )
                else:
                    row_buttons.append(
                        InlineKeyboardButton(
                            text=" ",
                            callback_data=f"mines_noop_{game_id}",
                            icon_custom_emoji_id="5469654973308476699",
                            style="danger",
                        )
                    )
            elif idx in revealed:
                row_buttons.append(
                    InlineKeyboardButton(
                        text="💎",
                        callback_data=f"mines_noop_{game_id}",
                        style="success",
                    )
                )
            elif game_over or won:
                row_buttons.append(
                    InlineKeyboardButton(
                        text=" ",
                        callback_data=f"mines_noop_{game_id}",
                        icon_custom_emoji_id="5436113877181941026",
                    )
                )
            else:
                row_buttons.append(
                    InlineKeyboardButton(
                        text=" ",
                        callback_data=f"mines_cell_{game_id}_{idx}",
                        icon_custom_emoji_id="5436113877181941026",
                    )
                )
        keyboard_rows.append(row_buttons)

    if game_over or won:
        keyboard_rows.append([
            InlineKeyboardButton(
                text="hash",
                copy_text=CopyTextButton(text=game["server_seed"]),
                icon_custom_emoji_id="5429405838345265327",
                style="primary",
            )
        ])
    elif len(revealed) > 0:
        keyboard_rows.append([
            InlineKeyboardButton(
                text="Забрать выигрыш",
                callback_data=f"mines_cashout_{game_id}",
                style="success",
                icon_custom_emoji_id="5427009714745517609",
            )
        ])
    else:
        keyboard_rows.append([
            InlineKeyboardButton(
                text="hash",
                copy_text=CopyTextButton(text=game["server_seed"]),
                icon_custom_emoji_id="5429405838345265327",
                style="primary",
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


def mines_start_text(user, bet: float, mines_count: int, next_mult: float) -> str:
    safe_total = MINES_TOTAL - mines_count
    next_line = ""
    if safe_total > 0:
        next_line = (
            '<blockquote>Следующий множитель: '
            '<tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>'
            f'{next_mult}</blockquote>'
        )
    return (
        f'<i>{user_link(user)}, начните игру!'
        '<tg-emoji emoji-id="5012808218385058363">🎮</tg-emoji></i>\n\n'
        '<tg-emoji emoji-id="4988289890769699938">⭐️</tg-emoji>'
        f'<b>Ставка:</b> {round(bet, 2)}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>\n'
        '<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji>'
        f'<b>Мин:</b> {mines_count}\n\n'
        f'{next_line}'
    )


def mines_playing_text(user, bet: float, mines_count: int, opened: int, current_mult: float, next_mult: float | None) -> str:
    potential = round(bet * current_mult, 2)
    next_line = ""
    if next_mult is not None:
        next_line = (
            '<blockquote>Следующий множитель: '
            '<tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>'
            f'{next_mult}</blockquote>'
        )
    return (
        f'<i>{user_link(user)}, игра идёт!'
        '<tg-emoji emoji-id="5309815458990433715">🎮</tg-emoji></i>\n\n'
        '<tg-emoji emoji-id="4988289890769699938">⭐️</tg-emoji>'
        f'<b>Ставка:</b> {round(bet, 2)}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>\n'
        '<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji>'
        f'<b>Мин:</b> {mines_count}\n'
        '<tg-emoji emoji-id="5431577498364158238">📊</tg-emoji>'
        '<b> Потенциальный выигрыш:</b> '
        '<tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>'
        f'{current_mult} / {potential}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>\n\n'
        f'{next_line}'
    )


def mines_lose_text(user, bet: float, mines_count: int, could_mult: float) -> str:
    could = round(bet * could_mult, 2)
    return (
        f'<i>{user_link(user)}, игра окончена, вы подорвались на мине!'
        '<tg-emoji emoji-id="5276032951342088188">💥</tg-emoji></i>\n\n'
        '<tg-emoji emoji-id="4988289890769699938">⭐️</tg-emoji>'
        f'<b>Ставка:</b> {round(bet, 2)}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>\n'
        '<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji>'
        f'<b>Мин:</b> {mines_count}\n'
        '<blockquote>'
        '<tg-emoji emoji-id="5431577498364158238">📊</tg-emoji>'
        '<b> Могли выиграть:</b> '
        '<tg-emoji emoji-id="5836936408681421518">❌</tg-emoji>'
        f'{could_mult} / {could}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
        '</blockquote>'
    )


def mines_win_text(user, bet: float, mines_count: int, multiplier: float) -> str:
    win = round(bet * multiplier, 2)
    return (
        f'<i>{user_link(user)}, вы добрались до конца!'
        '<tg-emoji emoji-id="5006240624978953230">🌟</tg-emoji></i>\n\n'
        '<tg-emoji emoji-id="4988289890769699938">⭐️</tg-emoji>'
        f'<b>Ставка:</b> {round(bet, 2)}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>\n'
        '<blockquote>'
        '<tg-emoji emoji-id="5028746137645876535">📈</tg-emoji>'
        f' Вы выиграли {win}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
        '</blockquote>\n'
        '<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji>'
        f'<b>Мин:</b> {mines_count}'
    )


def mines_cashout_text(user, bet: float, mines_count: int, multiplier: float) -> str:
    win = round(bet * multiplier, 2)
    return (
        f'<i>{user_link(user)}, вы забрали выигрыш!'
        '<tg-emoji emoji-id="5006240624978953230">🌟</tg-emoji></i>\n\n'
        '<tg-emoji emoji-id="4988289890769699938">⭐️</tg-emoji>'
        f'<b>Ставка:</b> {round(bet, 2)}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>\n'
        '<blockquote>'
        '<tg-emoji emoji-id="5028746137645876535">📈</tg-emoji>'
        f' Вы выиграли {win}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
        '</blockquote>\n'
        '<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji>'
        f'<b>Мин:</b> {mines_count}'
    )


def football_range_from_value(value: int, player_range: str) -> tuple[bool, str] | None:
    ranges = FOOTBALL_VALUE_MAP.get(value)
    if not ranges:
        return None
    won = player_range in ranges
    landed = player_range if won else secrets.choice(ranges)
    return won, landed


def basketball_range_from_value(value: int, player_range: str) -> tuple[bool, str] | None:
    ranges = BASKETBALL_VALUE_MAP.get(value)
    if not ranges:
        return None
    won = player_range in ranges
    landed = player_range if won else secrets.choice(ranges)
    return won, landed


def basketball_multiplier(player_range: str, dice_value: int) -> float:
    if player_range == "классик" and dice_value == 5:
        return 3.0
    return BASKETBALL_RANGES.get(player_range, 1.0)


async def start_animation(message: Message) -> None:
    emoji_msg = await message.answer(
        '<tg-emoji emoji-id="5019726470101075726">🧸</tg-emoji>'
    )
    await asyncio.sleep(2.5)
    await emoji_msg.delete()
    await message.answer(
        '<i><tg-emoji emoji-id="5053473385355412667">⭐️</tg-emoji>'
        f'{user_link(message.from_user)}, '
        '<b>добро пожаловать в '
        '<tg-emoji emoji-id="5019824691708167395">⭐️</tg-emoji>'
        '<tg-emoji emoji-id="5051114649445991756">🔠</tg-emoji>'
        '<tg-emoji emoji-id="5050987303665665245">🔠</tg-emoji>'
        '<tg-emoji emoji-id="5053271642151584876">🔠</tg-emoji>'
        '<tg-emoji emoji-id="5051108567772300271">🔠</tg-emoji>'
        '<tg-emoji emoji-id="5053572629164721435">🔠</tg-emoji></b>\n\n'
        '<tg-emoji emoji-id="4988174149991007503">🥳</tg-emoji>'
        '<i> В данном боте ты сможешь поднять и вывести звезды на свой Telegram аккаунт!</i>\n\n'
        '<tg-emoji emoji-id="5055840333242303386">🤑</tg-emoji>'
        '<b>Удачной игры в Major!</b></i>'
    )


async def crash_game(message: Message, bet: float, multiplier: float, bet_id: int) -> bool:
    client_seed = str(message.from_user.id)
    nonce = await next_nonce(message.from_user.id)

    server_seed = generate_server_seed()

    crash_point, raw_crash_point = crash_point_from_seeds(
        server_seed, client_seed, nonce
    )

    emoji_msg = await message.answer(
        '<tg-emoji emoji-id="5949468670710258892">🚀</tg-emoji>'
    )
    await asyncio.sleep(1.7)
    try:
        await emoji_msg.delete()
    except Exception:
        logging.exception("crash emoji delete failed")

    if not pop_bet(bet_id):
        return True

    won = crash_point >= multiplier
    win_amount = round(bet * multiplier, 2) if won else 0.0

    try:
        if won:
            await add_balance(message.from_user.id, win_amount)
        await save_crash_game(
            message.from_user.id, server_seed, client_seed, nonce,
            crash_point, raw_crash_point,
            bet, multiplier, won, chat_id=message.chat.id,
            idempotency_key=f"{message.chat.id}:{message.message_id}",
        )
    except Exception:
        logging.critical(
            "crash settlement failed: user=%s bet=%s win=%s (check balance manually)",
            message.from_user.id, bet, win_amount, exc_info=True,
        )

    try:
        if won:
            await message.answer(
                '<i><tg-emoji emoji-id="5949468670710258892">🚀</tg-emoji>'
                f'{user_link(message.from_user)}, ракета упала на x{crash_point}\n'
                '<tg-emoji emoji-id="5028746137645876535">📈</tg-emoji>'
                f' вы выиграли {win_amount}'
                '<tg-emoji emoji-id="5951810621887484519">⭐️</tg-emoji></i>',
                reply_markup=hash_markup(server_seed),
            )
        else:
            await message.answer(
                '<i><tg-emoji emoji-id="5949468670710258892">🚀</tg-emoji>'
                f'{user_link(message.from_user)}, ракета упала на x{crash_point}\n'
                '<tg-emoji emoji-id="5028325978175177540">📉</tg-emoji>'
                f' вы проиграли {bet}'
                '<tg-emoji emoji-id="5951810621887484519">⭐️</tg-emoji></i>',
                reply_markup=hash_markup(server_seed),
            )
    except Exception:
        logging.exception("crash result send failed")
    return True


def crash_task_done(task: asyncio.Task, user_id: int, bet: float, bet_id: int) -> None:
    if task.cancelled():
        if pop_bet(bet_id):
            spawn(add_balance(user_id, bet))
        return

    exc = task.exception()
    if exc is not None:
        logging.error("crash_game failed", exc_info=exc)
        if pop_bet(bet_id):
            spawn(add_balance(user_id, bet))


def answer_bg(call, *args, **kwargs) -> None:
    """call.answer() without yielding to the event loop (keeps checks atomic)."""
    async def _run() -> None:
        try:
            await call.answer(*args, **kwargs)
        except Exception:
            pass
    spawn(_run())


def generic_task_done(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logging.exception("background task failed", exc_info=exc)


async def process_bonus(user_id: int, user, bot: Bot, send) -> None:
    try:
        chat = await bot.get_chat(user_id)
    except Exception:
        chat = None

    bio = chat.bio if chat else None

    data = await get_bonus_data(user_id)

    if not bio or BONUS_BIO_TEXT not in bio:
        if data is not None and data["queued_at"] is not None:
            await clear_bonus_queue(user_id)

        if data is None:
            await send(
                '<i><tg-emoji emoji-id="5951762148886582569">⭐️</tg-emoji>'
                f'{user_link(user)}, для того чтобы получить бонус, установи данный текст в описание\n'
                '<blockquote>@mjrstars</blockquote></i>',
                reply_markup=get_bonus_button(),
            )
            return

        await send(
            '<i><tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'{user_link(user)}, у вас в профиле отсутствует нужное описание!\n\n'
            'Подождите 1-2 минуты если установили описание и попробуйте снова'
            '<tg-emoji emoji-id="5386367538735104399">⌛</tg-emoji></i>'
        )
        return

    if data and data["queued_at"] is not None:
        queued_at = datetime.fromisoformat(data["queued_at"])
        elapsed = now_msk() - queued_at
        remaining = BONUS_COOLDOWN - elapsed

        if remaining > timedelta(0):
            await send(
                '<tg-emoji emoji-id="5386367538735104399">⌛</tg-emoji>'
                f'<i>{user_link(user)}, вы уже в очереди, осталось ждать '
                f'{format_delta(remaining)}.</i>'
            )
            return

        streak = compute_streak(data)
        s_bonus = streak_bonus(streak)
        b_bonus = base_bonus()
        total = round(s_bonus + b_bonus, 2)

        if not await claim_bonus(user_id, streak, total):
            await send(
                '<tg-emoji emoji-id="5386367538735104399">⌛</tg-emoji>'
                f'<i>{user_link(user)}, бонус уже получен.</i>'
            )
            return

        await send(
            '<tg-emoji emoji-id="5924870095925942277">⭐️</tg-emoji>'
            f'<i>{user_link(user)}, вы успешно получили бонус в размере {total}'
            '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></i>\n\n'
            '<blockquote>'
            '<tg-emoji emoji-id="5053473385355412667">⭐️</tg-emoji>'
            f'<i> Вы забираете бонус уже {streak} день!</i>'
            '</blockquote>\n'
            '<blockquote>'
            f'<i>Бонус за серию: +{s_bonus}'
            '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>\n'
            f'Основной бонус: +{b_bonus}'
            '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></i>'
            '</blockquote>'
        )
        return

    await set_bonus_queued(user_id)
    await send(
        '<tg-emoji emoji-id="5397782960512444700">📌</tg-emoji>'
        f'<i>{user_link(user)}, вы успешно встали в очередь, осталось ждать 12:00:00.</i>'
    )


async def show_withdraw_menu(user_id: int, user, send) -> bool:
    if _wallet_backend is not None:
        wager_error = None
        async with _db_lock:
            try:
                await _wallet_backend.ensure_check_wager(db(), user_id)
            except GameError as error:
                wager_error = error.message
        if wager_error:
            await send(html_escape(wager_error))
            return False
    balance = await get_balance(user_id)

    if balance < WITHDRAW_MIN_BALANCE:
        await send(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(user)}, минимальный баланс для вывода — {WITHDRAW_MIN_BALANCE}'
            '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>\n\n'
            '<blockquote>'
            '<tg-emoji emoji-id="4965219701572503640">💰</tg-emoji>'
            f' На вашем балансе: <code>{round(balance, 2)}</code>'
            '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
            '</blockquote></i>'
        )
        return False

    weekly = await get_weekly_deposit(user_id)

    if weekly < WITHDRAW_MIN_DEPOSIT:
        await send(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(user)}, минимальный депозит для вывода — '
            f'<b>≥{WITHDRAW_MIN_DEPOSIT}'
            '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></b>\n\n'
            '<blockquote>'
            '<tg-emoji emoji-id="5443127283898405358">📥</tg-emoji>'
            f' За текущую неделю вы внесли депозит в размере: '
            f'<code>{round(weekly, 2)}'
            '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></code>'
            '</blockquote></i>'
        )
        return False

    await send(
        '<tg-emoji emoji-id="5443127283898405358">📥</tg-emoji>'
        '<b>Вывод</b>\n\n'
        '<i><tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
        ' Для вывода введите сумму чтобы вывести Telegram Stars</i>\n\n'
        '<blockquote>'
        '<tg-emoji emoji-id="4965219701572503640">💰</tg-emoji>'
        f' Ваш баланс: <b>{round(balance, 2)}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></b>'
        '</blockquote>',
        reply_markup=withdraw_menu_markup(),
    )
    return True


async def create_withdraw_request(user_id: int, user, amount: float, bot: Bot, send) -> None:
    amount = round(amount, 2)
    if amount < WITHDRAW_MIN_BALANCE:
        await send(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(user)}, минимальная сумма вывода — {WITHDRAW_MIN_BALANCE}'
            '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></i>'
        )
        return

    ok, new_balance, withdrawal_id = await create_withdrawal_atomic(user_id, amount)

    if not ok or withdrawal_id is None:
        await send(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(user)}, недостаточно средств!</i>'
        )
        return

    old_balance = round(new_balance + amount, 2)

    admin_text = (
        '<tg-emoji emoji-id="5443127283898405358">📥</tg-emoji>'
        '<b> Новая заявка на вывод</b>\n\n'
        f'👤 {user_link(user)}\n'
        f'💰 Сумма: <b>{round(amount, 2)}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></b>\n'
        f'📊 Баланс после вывода: <b>{round(new_balance, 2)}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></b>'
    )

    try:
        admin_msg = await bot.send_message(
            ADMIN_ID,
            admin_text,
            reply_markup=withdraw_admin_markup(withdrawal_id),
        )
        await set_withdrawal_admin_message(withdrawal_id, admin_msg.message_id)
    except Exception:
        logging.exception("Failed to send withdrawal request to admin")
        await claim_withdrawal(withdrawal_id, "failed")
        await send(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(user)}, не удалось отправить заявку. Сумма возвращена.</i>'
        )
        return

    await send(
        '<tg-emoji emoji-id="4963511421280192936">💫</tg-emoji>'
        '<i> Ваша заявка добавлена в обработку!</i>\n\n'
        '<blockquote>'
        '<tg-emoji emoji-id="5028325978175177540">📉</tg-emoji>'
        f' Ваш баланс: <s>{old_balance}</s> {round(new_balance, 2)}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
        '</blockquote>'
    )


@router.callback_query(F.data == "balance_withdraw")
async def on_withdraw(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await call.answer()

    async def send(text: str, reply_markup=None) -> None:
        await call.message.answer(text, reply_markup=reply_markup)

    ok = await show_withdraw_menu(call.from_user.id, call.from_user, send)
    if ok:
        await state.set_state(WithdrawStates.waiting_amount)
    else:
        await state.clear()


@router.callback_query(F.data == "withdraw_all")
async def on_withdraw_all(call: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    await call.answer()

    async def send(text: str, reply_markup=None) -> None:
        await call.message.answer(text, reply_markup=reply_markup)

    balance = await get_balance(call.from_user.id)
    await create_withdraw_request(call.from_user.id, call.from_user, balance, bot, send)
    await state.clear()


def referral_text(user_id: int, ref_data: dict, active: bool) -> str:
    active_icon = (
        '<tg-emoji emoji-id="5832229652805985405">✅</tg-emoji>'
        if active
        else '<tg-emoji emoji-id="5273914604752216432">❌</tg-emoji>'
    )

    group_earned = ref_data.get("group_earned", 0.0)
    balance = ref_data["signup_earned"] + ref_data["deposit_earned"] + group_earned
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"

    return (
        '<tg-emoji emoji-id="5814662914442797254">👥</tg-emoji>'
        '<b> Реферальная система</b> '
        '<blockquote expandable>'
        '<tg-emoji emoji-id="5055840333242303386">🤑</tg-emoji>'
        ' Тут ты сможешь заработать Telegram Stars на приглашении своих друзей и знакомых. '
        'За обычного друга награда — 2.5'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
        ', награда за друга с Telegram Premium — 5'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
        '. Также вы будете получать 10% от пополнения ваших рефералов.\n\n '
        '<tg-emoji emoji-id="5271604874419647061">🔗</tg-emoji>'
        f'<i> Ваша реферальная ссылка:</i><code> {ref_link}</code>\n'
        '</blockquote>'
        '<blockquote>'
        f' Заработок с приглашений: {active_icon}\n'
        '</blockquote>'
        '<tg-emoji emoji-id="4965219701572503640">💰</tg-emoji>'
        f'<i> Текущий реферальный баланс:</i> {round(balance, 2)}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>\n'
        '<blockquote expandable>'
        '<tg-emoji emoji-id="4994896443824145756">⭐️</tg-emoji>'
        f' Заработано с рефералов: {round(balance, 2)}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>\n'
        '<tg-emoji emoji-id="5431577498364158238">📊</tg-emoji>'
        ' Статистика заработка:\n'
        '<tg-emoji emoji-id="5308004189677330658">👤</tg-emoji>'
        f' Заработано с приглашений: {round(ref_data["signup_earned"], 2)}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>\n'
        '<tg-emoji emoji-id="5443127283898405358">📥</tg-emoji>'
        f' Заработано с пополнений: {round(ref_data["deposit_earned"], 2)}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>\n'
        '<tg-emoji emoji-id="5472270097290634771">💬</tg-emoji>'
        f' Заработано в чатах: {round(group_earned, 2)}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
        '</blockquote>'
    )


@router.message(Command("ref", "реф", ignore_case=True))
@router.message(F.text.regexp(r"(?i)^/?(?:ref|реф)\s*$"))
async def cmd_ref(message: Message, state: FSMContext) -> None:
    logging.info("Processing referral command for user %s", message.from_user.id)
    await state.clear()

    user_id = message.from_user.id
    ref_data = await get_ref_data(user_id)

    active = not await is_ref_frozen(user_id)

    await answer_referral(
        message,
        referral_text(user_id, ref_data, active),
        reply_markup=ref_markup(user_id),
    )


CHECKR_RUNNING = set()
CHECKR_PAUSE_SECONDS = 1.1


def referral_emoji_probes(user_id: int):
    """Derive probes from the actual referral text and keyboard, not a second ID list."""
    probes = []
    seen = set()
    for active in (True, False):
        text = referral_text(user_id, {"signup_earned": 0, "deposit_earned": 0}, active)
        for emoji_id, fallback in re.findall(r'<tg-emoji\s+emoji-id="([0-9]+)">(.*?)</tg-emoji>', text, flags=re.DOTALL):
            key = ("text", emoji_id)
            if key not in seen:
                seen.add(key)
                probes.append(("text", emoji_id, fallback))
    for row in ref_markup(user_id).inline_keyboard:
        for button in row:
            emoji_id = button.icon_custom_emoji_id
            key = ("button", emoji_id)
            if emoji_id and key not in seen:
                seen.add(key)
                probes.append(("button", emoji_id, button.text))
    return probes


@router.message(Command("checkr", ignore_case=True))
async def cmd_checkr(message: Message) -> None:
    if message.from_user is None or message.from_user.id != ADMIN_ID:
        return
    if message.chat.type != ChatType.PRIVATE:
        await message.answer("Запустите /checkr в личном чате с ботом.", parse_mode=None)
        return
    if ADMIN_ID in CHECKR_RUNNING:
        # Do not introduce extra messages/rate-limit pressure into an active run.
        return
    CHECKR_RUNNING.add(ADMIN_ID)
    next_send = 0.0

    async def send(text, reply_markup=None):
        nonlocal next_send
        for attempt in range(3):
            await asyncio.sleep(max(0, next_send - time.monotonic()))
            next_send = time.monotonic() + CHECKR_PAUSE_SECONDS
            try:
                return await message.answer(text, reply_markup=reply_markup, parse_mode=ParseMode.HTML)
            except TelegramRetryAfter as error:
                if attempt == 2:
                    raise
                # A 429 is a definite rejection, not a network-ambiguous send.
                next_send = time.monotonic() + max(CHECKR_PAUSE_SECONDS, error.retry_after + 0.2)

    try:
        probes = referral_emoji_probes(message.from_user.id)
        total = len(probes)
        await send(f"Проверка /ref: {total} уникальных эмодзи по контекстам. Отправляю по одному, включая иконки кнопок. ID принятого эмодзи виден в сообщении; при ошибке будет отдельная отметка. Пауза между отправками — 1,1 с.")
        invalid = []
        unconfirmed = []
        accepted = 0
        for index, (kind, emoji_id, label) in enumerate(probes, 1):
            context = "текст" if kind == "text" else "кнопка"
            prefix = f"<b>{index}/{total} · {context}</b>\nID: <code>{emoji_id}</code>"
            markup = None
            if kind == "text":
                text = prefix + f'\n<tg-emoji emoji-id="{emoji_id}">{html_escape(label)}</tg-emoji>'
            else:
                text = prefix
                markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
                    text="Проверка: " + label,
                    callback_data="checkr_probe",
                    icon_custom_emoji_id=emoji_id,
                )]])
            try:
                # Deliberately bypass answer_referral: its Unicode fallback would
                # hide the very invalid document that this command diagnoses.
                await send(text, reply_markup=markup)
                accepted += 1
            except TelegramBadRequest as error:
                if re.search(r"\bDOCUMENT_INVALID\b", error.message):
                    invalid.append(f"{context}: <code>{emoji_id}</code>")
                    await send(prefix + "\n❌ DOCUMENT_INVALID — Telegram отклонил этот эмодзи.")
                else:
                    unconfirmed.append(f"{context}: <code>{emoji_id}</code>")
                    await send(prefix + "\n⚠️ Другая ошибка Telegram, не DOCUMENT_INVALID: " + html_escape(error.message[:180]))
            except (TelegramNetworkError, asyncio.TimeoutError):
                # A timeout does not prove an invalid ID and must not resend it.
                unconfirmed.extend(f"{'текст' if item[0] == 'text' else 'кнопка'}: <code>{item[1]}</code>" for item in probes[index - 1:])
                break
        summary = f"<b>Итог /checkr</b>\nПринято Telegram: {accepted}/{total}."
        summary += "\n\nНевалидные (DOCUMENT_INVALID):\n" + ("\n".join(invalid) if invalid else "Не обнаружены среди проверенных.")
        if unconfirmed:
            summary += "\n\nНе подтверждены / не проверены:\n" + "\n".join(unconfirmed)
        summary += "\n\nПринято Telegram не гарантирует анимацию на каждом клиенте. Начисления и настройки не менялись."
        await send(summary)
    finally:
        CHECKR_RUNNING.discard(ADMIN_ID)


@router.callback_query(F.data == "checkr_probe")
async def on_checkr_probe(call: CallbackQuery) -> None:
    if call.from_user.id != ADMIN_ID:
        await call.answer("Это диагностическая кнопка администратора.")
        return
    await call.answer("Тест иконки. Никакие операции не выполняются.")


@router.message(WithdrawStates.waiting_amount, F.text)
async def on_withdraw_amount(message: Message, state: FSMContext, bot: Bot) -> None:
    text = (message.text or "").strip()
    lower = text.lower()

    if lower in CANCEL_WORDS:
        await state.clear()
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            '<i> Ввод суммы отменён.</i>'
        )
        return

    triggers = {
        "б", "баланс", "crash", "краш", "mines", "мины",
        "бонус", "bonus", "реф", "ref", "профиль", "проф",
        "игра", "игры", "играть", "game", "games",
        "фут", "футбол", "фб", "football",
        "бс", "бк", "баскет", "basketball",
        "слот", "слоты", "автомат", "slot", "slots",
        "дартс", "дс", "darts",
        "боулинг", "боул", "bowling",
        "куб", "кубы", "кубик", "cubs", "cube",
        "дать", "нк", "send", "перевод", "передать", "пер",
    }

    if any(lower.startswith(p) for p in GAME_TRIGGER_PREFIXES) or lower in triggers:
        await state.clear()
        await message.answer(soon_text(), reply_markup=soon_markup())
        return

    amount = parse_number(text)

    if amount is None or amount <= 0:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            '<i> Введите сумму цифрами или нажмите «Вывести всё». '
            'Для отмены напишите «отмена».</i>'
        )
        return

    async def send(text: str, reply_markup=None) -> None:
        await message.answer(text, reply_markup=reply_markup)

    await create_withdraw_request(message.from_user.id, message.from_user, amount, bot, send)
    await state.clear()


@router.callback_query(F.data.startswith("withdraw_approve_"))
async def on_withdraw_approve(call: CallbackQuery, bot: Bot) -> None:
    if call.from_user.id != ADMIN_ID:
        await call.answer()
        return

    parts = call.data.split("_")
    if len(parts) != 3:
        await call.answer()
        return

    try:
        withdrawal_id = int(parts[2])
    except ValueError:
        await call.answer()
        return

    withdrawal = await claim_withdrawal(withdrawal_id, "approved")
    if withdrawal is None:
        await call.answer("Заявка уже обработана.", show_alert=True)
        return

    try:
        await call.message.edit_text(
            (call.message.html_text or "") + "\n\n✅ <b>Одобрено</b>",
        )
    except Exception:
        logging.exception("Failed to edit admin message")

    try:
        await bot.send_message(
            withdrawal["user_id"],
            '<tg-emoji emoji-id="5832229652805985405">✅</tg-emoji>'
            f'<i> Ваша заявка на вывод <b>{round(withdrawal["amount"], 2)}'
            '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></b> одобрена! '
            'В ближайшее время вывод будет обработан.</i>'
        )
    except Exception:
        logging.exception("Failed to notify user about approval")

    await call.answer("Одобрено")


@router.callback_query(F.data.startswith("withdraw_reject_"))
async def on_withdraw_reject(call: CallbackQuery, bot: Bot) -> None:
    if call.from_user.id != ADMIN_ID:
        await call.answer()
        return

    parts = call.data.split("_")
    if len(parts) != 3:
        await call.answer()
        return

    try:
        withdrawal_id = int(parts[2])
    except ValueError:
        await call.answer()
        return

    withdrawal = await claim_withdrawal(withdrawal_id, "rejected")
    if withdrawal is None:
        await call.answer("Заявка уже обработана.", show_alert=True)
        return

    try:
        await call.message.edit_text(
            (call.message.html_text or "") + "\n\n❌ <b>Отклонено</b>",
        )
    except Exception:
        logging.exception("Failed to edit admin message")

    try:
        await bot.send_message(
            withdrawal["user_id"],
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i> Ваша заявка на вывод <b>{round(withdrawal["amount"], 2)}'
            '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></b> отклонена. '
            'Сумма возвращена на баланс.</i>'
        )
    except Exception:
        logging.exception("Failed to notify user about rejection")

    await call.answer("Отклонено")


@router.message(
    F.text.regexp(r"(?i)^/?бонус$") | F.text.regexp(r"(?i)^/?bonus$"),
    F.chat.type == ChatType.PRIVATE,
)
async def cmd_bonus_private(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        '<tg-emoji emoji-id="5471930335312747865">💬</tg-emoji>'
        f'<i>{user_link(message.from_user)}, бонус доступен только в нашей беседе!</i>',
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="наш чат",
                        url=CHAT_URL,
                        icon_custom_emoji_id="5793933761594789855",
                    ),
                ]
            ]
        ),
    )


@router.message(
    F.text.regexp(r"(?i)^/?бонус$") | F.text.regexp(r"(?i)^/?bonus$"),
    F.chat.type != ChatType.PRIVATE,
)
async def cmd_bonus_group(message: Message, bot: Bot) -> None:
    async def send(text: str, reply_markup=None) -> None:
        await message.answer(text, reply_markup=reply_markup)

    await process_bonus(message.from_user.id, message.from_user, bot, send)


@router.callback_query(F.data == "get_bonus")
async def on_get_bonus(call: CallbackQuery, bot: Bot) -> None:
    await call.answer()

    async def send(text: str, reply_markup=None) -> None:
        await call.message.answer(text, reply_markup=reply_markup)

    await process_bonus(call.from_user.id, call.from_user, bot, send)


@router.message(
    F.text.regexp(r"(?i)^/?profile$")
    | F.text.regexp(r"(?i)^/?профиль$")
    | F.text.regexp(r"(?i)^/?проф$")
)
async def cmd_profile(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    await save_username(user.id, user.username, " ".join(part for part in (user.first_name, user.last_name) if part))
    await telegram_settings_data(user.id, user)
    stats = await telegram_profile_overview(user.id)
    language = await get_telegram_language(user.id)
    await message.answer(
        translate_telegram_text(telegram_profile_text(user, stats), language),
        reply_markup=telegram_profile_markup(language),
    )


@router.message(
    F.text.regexp(r"(?i)^/?game$")
    | F.text.regexp(r"(?i)^/?games$")
    | F.text.regexp(r"(?i)^/?игры$")
    | F.text.regexp(r"(?i)^/?игра$")
    | F.text.regexp(r"(?i)^/?играть$")
)
async def cmd_games(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        '<tg-emoji emoji-id="5361741454685256344">🎮</tg-emoji>'
        '<b> Доступные игры </b>\n\n'
        '<blockquote>'
        '<tg-emoji emoji-id="5469654973308476699">💣</tg-emoji>'
        ' Мины: /mines'
        '</blockquote>\n'
        '<blockquote>'
        '<tg-emoji emoji-id="5949468670710258892">🚀</tg-emoji>'
        ' Краш: /crash'
        '</blockquote>\n'
        '<blockquote>'
        '<tg-emoji emoji-id="5373101763442255191">⚽️</tg-emoji>'
        ' Футбол: /football'
        '</blockquote>\n'
        '<blockquote>'
        '<tg-emoji emoji-id="5467370261160432890">🏀</tg-emoji>'
        ' Баскетбол: /basketball'
        '</blockquote>\n'
        '<blockquote>'
        '<tg-emoji emoji-id="5915833712368424979">🎰</tg-emoji>'
        ' Слоты: /slot'
        '</blockquote>\n'
        '<blockquote>'
        '<tg-emoji emoji-id="5467748029303922613">🎯</tg-emoji>'
        ' Дартс: /darts'
        '</blockquote>\n'
        '<blockquote>'
        '<tg-emoji emoji-id="5467689819612162812">🎳</tg-emoji>'
        ' Боулинг: /bowling'
        '</blockquote>\n'
        '<blockquote>'
        '<tg-emoji emoji-id="5321230889357713132">🎲</tg-emoji>'
        ' Кубик: /cube'
        '</blockquote>'
    )


@router.message(
    F.text.regexp(r"(?i)^/?football(\s|$)")
    | F.text.regexp(r"(?i)^/?фут(\s|$)")
    | F.text.regexp(r"(?i)^/?футбол(\s|$)")
    | F.text.regexp(r"(?i)^/?фб(\s|$)")
)
async def cmd_football(message: Message, state: FSMContext) -> None:
    await state.clear()

    text = message.text.strip()
    if text.startswith("/"):
        text = text[1:]

    parts = text.split()

    if len(parts) < 2:
        await message.answer(football_usage_text(message.from_user))
        return

    balance = await get_balance(message.from_user.id)

    bet_token = parts[1].lower()
    is_alias = False

    if bet_token in ALL_IN_ALIASES:
        bet = round(balance, 2)
        is_alias = True
    elif bet_token in HALF_ALIASES:
        bet = round(balance / 2, 2)
        is_alias = True
    else:
        parsed_bet = parse_number(bet_token)
        if parsed_bet is None:
            await message.answer(football_usage_text(message.from_user))
            return
        bet = parsed_bet

    if len(parts) >= 3:
        range_token = " ".join(parts[2:]).lower()
        if range_token not in FOOTBALL_RANGES:
            await message.answer(football_usage_text(message.from_user))
            return
        player_range = range_token
    else:
        player_range = "классик"

    if bet < FOOTBALL_MIN_BET:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(message.from_user)}, минимальная ставка {FOOTBALL_MIN_BET}'
            '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></i>'
        )
        return

    if is_alias:
        bet = round(min(bet, balance), 2)

    ok = await try_withdraw(message.from_user.id, bet)
    if not ok:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(message.from_user)}, недостаточно средств!</i>'
        )
        return

    await football_start_game(
        message,
        bet,
        player_range,
        message.from_user.id,
        message.from_user,
    )


async def football_start_game(
    message: Message,
    bet: float,
    player_range: str,
    user_id: int,
    user,
) -> None:
    try:
        control_msg = await message.answer_dice(
            emoji=FOOTBALL_DICE_EMOJI,
            reply_markup=football_markup_disabled(bet, player_range),
        )
    except Exception:
        logging.exception("dice send failed")
        await add_balance(user_id, bet)
        try:
            await message.answer("Не удалось отправить игру. Ставка возвращена.")
        except Exception:
            pass
        return
    bet_id = register_bet(user_id, bet)

    async def finish() -> None:
        await asyncio.sleep(FOOTBALL_WAIT_SECONDS)

        dice_value = control_msg.dice.value
        if not pop_bet(bet_id):
            return
        result = football_range_from_value(dice_value, player_range)

        if result is None:
            await add_balance(user_id, bet)
            await message.answer("Ошибка результата. Ставка возвращена.")
            return

        won, landed = result

        balance_after_withdraw = await get_balance(user_id)
        balance_before = round(balance_after_withdraw + bet, 2)

        if won:
            multiplier = FOOTBALL_RANGES[player_range]
            total_return = round(bet * multiplier, 2)
            net_win = round(total_return - bet, 2)
            new_balance = await add_balance(user_id, total_return)

            await save_football_game(
                user_id, bet, player_range, landed,
                multiplier, total_return, True, chat_id=message.chat.id,
                idempotency_key=f"{message.chat.id}:{message.message_id}",
            )

            quote = secrets.choice(FOOTBALL_QUOTES_WIN[player_range])

            text_out = (
                '<tg-emoji emoji-id="5449683594425410231">🔼</tg-emoji>'
                f' <i>{user_link(user)}, вы <b>выиграли</b>: +{net_win}'
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
                f' [<b> x{multiplier} </b>]</i>\n'
                '<blockquote>'
                f'<s>{balance_before}'
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></s> '
                '<tg-emoji emoji-id="5028746137645876535">📈</tg-emoji>'
                f'<b>{round(new_balance, 2)}</b>'
                '</blockquote>\n\n'
                '<blockquote>'
                '<tg-emoji emoji-id="5240369183593615679">💬</tg-emoji>'
                f' {quote}'
                '</blockquote>'
            )
        else:
            new_balance = balance_after_withdraw

            await save_football_game(
                user_id, bet, player_range, landed,
                0.0, 0.0, False, chat_id=message.chat.id,
                idempotency_key=f"{message.chat.id}:{message.message_id}",
            )

            quote = secrets.choice(FOOTBALL_QUOTES_LOSE[player_range])

            text_out = (
                '<tg-emoji emoji-id="5447183459602669338">🔽</tg-emoji>'
                f' <i>{user_link(user)}, вы <b>проиграли</b>: -{round(bet, 2)}'
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></i>\n'
                '<blockquote>'
                f'<s>{balance_before}'
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></s> '
                '<tg-emoji emoji-id="5028325978175177540">📉</tg-emoji>'
                f'<b>{round(new_balance, 2)}</b>'
                '</blockquote>\n\n'
                '<blockquote>'
                '<tg-emoji emoji-id="5240369183593615679">💬</tg-emoji>'
                f' {quote}'
                '</blockquote>'
            )

        try:
            await message.answer(text_out, reply_markup=football_markup_replay())
        except Exception:
            logging.exception("football result send failed")

        FOOTBALL_LAST_GAMES[user_id] = {
            "bet": bet,
            "range": player_range,
        }

    task = spawn(finish())
    task.add_done_callback(lambda t, b=bet_id: bet_task_done(t, b))


@router.callback_query(F.data == "football_noop")
async def football_noop(call: CallbackQuery) -> None:
    await call.answer()


@router.callback_query(F.data == "football_replay")
async def football_replay(call: CallbackQuery) -> None:
    data = FOOTBALL_LAST_GAMES.get(call.from_user.id)
    if not data:
        await call.answer("Нет предыдущей игры", show_alert=True)
        return

    bet = data["bet"]
    player_range = data["range"]

    ok = await try_withdraw(call.from_user.id, bet)
    if not ok:
        await call.answer("Недостаточно средств", show_alert=True)
        return

    await call.answer()

    await football_start_game(
        call.message,
        bet,
        player_range,
        call.from_user.id,
        call.from_user,
    )


@router.callback_query(F.data == "football_vabank")
async def football_vabank(call: CallbackQuery) -> None:
    data = FOOTBALL_LAST_GAMES.get(call.from_user.id)
    if not data:
        await call.answer("Нет предыдущей игры", show_alert=True)
        return

    player_range = data["range"]
    balance = await get_balance(call.from_user.id)

    if balance < FOOTBALL_MIN_BET:
        await call.answer("Недостаточно средств", show_alert=True)
        return

    balance = round(balance, 2)
    ok = await try_withdraw(call.from_user.id, balance)
    if not ok:
        await call.answer("Недостаточно средств", show_alert=True)
        return

    await call.answer()

    await football_start_game(
        call.message,
        balance,
        player_range,
        call.from_user.id,
        call.from_user,
    )


@router.message(F.text.regexp(r"(?i)^/chd$"))
async def cmd_chd(message: Message) -> None:
    if message.from_user.id != ADMIN_ID:
        return

    dice_msg = await message.answer_dice(emoji=FOOTBALL_DICE_EMOJI)

    async def report() -> None:
        await asyncio.sleep(FOOTBALL_WAIT_SECONDS)
        await message.answer(f"Value: <b>{dice_msg.dice.value}</b>")

    task = spawn(report())
    task.add_done_callback(generic_task_done)


@router.message(
    F.text.regexp(r"(?i)^/?basketball(\s|$)")
    | F.text.regexp(r"(?i)^/?баскет(\s|$)")
    | F.text.regexp(r"(?i)^/?бс(\s|$)")
    | F.text.regexp(r"(?i)^/?бк(\s|$)")
)
async def cmd_basketball(message: Message, state: FSMContext) -> None:
    await state.clear()

    text = message.text.strip()
    if text.startswith("/"):
        text = text[1:]

    parts = text.split()

    if len(parts) < 2:
        await message.answer(basketball_usage_text(message.from_user))
        return

    balance = await get_balance(message.from_user.id)

    bet_token = parts[1].lower()
    is_alias = False

    if bet_token in ALL_IN_ALIASES:
        bet = round(balance, 2)
        is_alias = True
    elif bet_token in HALF_ALIASES:
        bet = round(balance / 2, 2)
        is_alias = True
    else:
        parsed_bet = parse_number(bet_token)
        if parsed_bet is None:
            await message.answer(basketball_usage_text(message.from_user))
            return
        bet = parsed_bet

    if len(parts) >= 3:
        range_token = " ".join(parts[2:]).lower()
        if range_token not in BASKETBALL_RANGES:
            await message.answer(basketball_usage_text(message.from_user))
            return
        player_range = range_token
    else:
        player_range = "классик"

    if bet < BASKETBALL_MIN_BET:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(message.from_user)}, минимальная ставка {BASKETBALL_MIN_BET}'
            '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></i>'
        )
        return

    if is_alias:
        bet = round(min(bet, balance), 2)

    ok = await try_withdraw(message.from_user.id, bet)
    if not ok:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(message.from_user)}, недостаточно средств!</i>'
        )
        return

    await basketball_start_game(
        message,
        bet,
        player_range,
        message.from_user.id,
        message.from_user,
    )


async def basketball_start_game(
    message: Message,
    bet: float,
    player_range: str,
    user_id: int,
    user,
) -> None:
    try:
        control_msg = await message.answer_dice(
            emoji=BASKETBALL_DICE_EMOJI,
            reply_markup=basketball_markup_disabled(bet, player_range),
        )
    except Exception:
        logging.exception("dice send failed")
        await add_balance(user_id, bet)
        try:
            await message.answer("Не удалось отправить игру. Ставка возвращена.")
        except Exception:
            pass
        return
    bet_id = register_bet(user_id, bet)

    async def finish() -> None:
        await asyncio.sleep(BASKETBALL_WAIT_SECONDS)

        dice_value = control_msg.dice.value
        if not pop_bet(bet_id):
            return
        result = basketball_range_from_value(dice_value, player_range)

        if result is None:
            await add_balance(user_id, bet)
            await message.answer("Ошибка результата. Ставка возвращена.")
            return

        won, landed = result

        balance_after_withdraw = await get_balance(user_id)
        balance_before = round(balance_after_withdraw + bet, 2)

        if won:
            multiplier = basketball_multiplier(player_range, dice_value)
            total_return = round(bet * multiplier, 2)
            net_win = round(total_return - bet, 2)
            new_balance = await add_balance(user_id, total_return)

            await save_basketball_game(
                user_id, bet, player_range, landed,
                multiplier, total_return, True, chat_id=message.chat.id,
                idempotency_key=f"{message.chat.id}:{message.message_id}",
            )

            quote = secrets.choice(BASKETBALL_QUOTES_WIN[player_range])

            text_out = (
                '<tg-emoji emoji-id="5449683594425410231">🔼</tg-emoji>'
                f' <i>{user_link(user)}, вы <b>выиграли</b>: +{net_win}'
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
                f' [<b> x{multiplier} </b>]</i>\n'
                '<blockquote>'
                f'<s>{balance_before}'
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></s> '
                '<tg-emoji emoji-id="5028746137645876535">📈</tg-emoji>'
                f'<b>{round(new_balance, 2)}</b>'
                '</blockquote>\n\n'
                '<blockquote>'
                '<tg-emoji emoji-id="5240369183593615679">💬</tg-emoji>'
                f' {quote}'
                '</blockquote>'
            )
        else:
            new_balance = balance_after_withdraw

            await save_basketball_game(
                user_id, bet, player_range, landed,
                0.0, 0.0, False, chat_id=message.chat.id,
                idempotency_key=f"{message.chat.id}:{message.message_id}",
            )

            quote = secrets.choice(BASKETBALL_QUOTES_LOSE[player_range])

            text_out = (
                '<tg-emoji emoji-id="5447183459602669338">🔽</tg-emoji>'
                f' <i>{user_link(user)}, вы <b>проиграли</b>: -{round(bet, 2)}'
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></i>\n'
                '<blockquote>'
                f'<s>{balance_before}'
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></s> '
                '<tg-emoji emoji-id="5028325978175177540">📉</tg-emoji>'
                f'<b>{round(new_balance, 2)}</b>'
                '</blockquote>\n\n'
                '<blockquote>'
                '<tg-emoji emoji-id="5240369183593615679">💬</tg-emoji>'
                f' {quote}'
                '</blockquote>'
            )

        try:
            await message.answer(text_out, reply_markup=basketball_markup_replay())
        except Exception:
            logging.exception("basketball result send failed")

        BASKETBALL_LAST_GAMES[user_id] = {
            "bet": bet,
            "range": player_range,
        }

    task = spawn(finish())
    task.add_done_callback(lambda t, b=bet_id: bet_task_done(t, b))


@router.callback_query(F.data == "basketball_noop")
async def basketball_noop(call: CallbackQuery) -> None:
    await call.answer()


@router.callback_query(F.data == "basketball_replay")
async def basketball_replay(call: CallbackQuery) -> None:
    data = BASKETBALL_LAST_GAMES.get(call.from_user.id)
    if not data:
        await call.answer("Нет предыдущей игры", show_alert=True)
        return

    bet = data["bet"]
    player_range = data["range"]

    ok = await try_withdraw(call.from_user.id, bet)
    if not ok:
        await call.answer("Недостаточно средств", show_alert=True)
        return

    await call.answer()

    await basketball_start_game(
        call.message,
        bet,
        player_range,
        call.from_user.id,
        call.from_user,
    )


@router.callback_query(F.data == "basketball_vabank")
async def basketball_vabank(call: CallbackQuery) -> None:
    data = BASKETBALL_LAST_GAMES.get(call.from_user.id)
    if not data:
        await call.answer("Нет предыдущей игры", show_alert=True)
        return

    player_range = data["range"]
    balance = await get_balance(call.from_user.id)

    if balance < BASKETBALL_MIN_BET:
        await call.answer("Недостаточно средств", show_alert=True)
        return

    balance = round(balance, 2)
    ok = await try_withdraw(call.from_user.id, balance)
    if not ok:
        await call.answer("Недостаточно средств", show_alert=True)
        return

    await call.answer()

    await basketball_start_game(
        call.message,
        balance,
        player_range,
        call.from_user.id,
        call.from_user,
    )


@router.message(F.text.regexp(r"(?i)^/chb$"))
async def cmd_chb(message: Message) -> None:
    if message.from_user.id != ADMIN_ID:
        return

    dice_msg = await message.answer_dice(emoji=BASKETBALL_DICE_EMOJI)

    async def report() -> None:
        await asyncio.sleep(BASKETBALL_WAIT_SECONDS)
        await message.answer(f"Value: <b>{dice_msg.dice.value}</b>")

    task = spawn(report())
    task.add_done_callback(generic_task_done)


@router.message(
    F.text.regexp(r"(?i)^/?slot(\s|$)")
    | F.text.regexp(r"(?i)^/?slots(\s|$)")
    | F.text.regexp(r"(?i)^/?слот(\s|$)")
    | F.text.regexp(r"(?i)^/?слоты(\s|$)")
    | F.text.regexp(r"(?i)^/?автомат(\s|$)")
)
async def cmd_slot(message: Message, state: FSMContext) -> None:
    await state.clear()

    text = message.text.strip()
    if text.startswith("/"):
        text = text[1:]

    parts = text.split()

    if len(parts) < 2:
        await message.answer(slot_usage_text(message.from_user))
        return

    balance = await get_balance(message.from_user.id)

    bet_token = parts[1].lower()
    is_alias = False

    if bet_token in ALL_IN_ALIASES:
        bet = round(balance, 2)
        is_alias = True
    elif bet_token in HALF_ALIASES:
        bet = round(balance / 2, 2)
        is_alias = True
    else:
        parsed_bet = parse_number(bet_token)
        if parsed_bet is None:
            await message.answer(slot_usage_text(message.from_user))
            return
        bet = parsed_bet

    if bet < SLOT_MIN_BET:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(message.from_user)}, минимальная ставка {SLOT_MIN_BET}'
            '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></i>'
        )
        return

    if is_alias:
        bet = round(min(bet, balance), 2)

    ok = await try_withdraw(message.from_user.id, bet)
    if not ok:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(message.from_user)}, недостаточно средств!</i>'
        )
        return

    await slot_start_game(
        message,
        bet,
        message.from_user.id,
        message.from_user,
    )


async def slot_start_game(
    message: Message,
    bet: float,
    user_id: int,
    user,
) -> None:
    try:
        control_msg = await message.answer_dice(
            emoji=SLOT_DICE_EMOJI,
            reply_markup=slot_markup_disabled(bet),
        )
    except Exception:
        logging.exception("dice send failed")
        await add_balance(user_id, bet)
        try:
            await message.answer("Не удалось отправить игру. Ставка возвращена.")
        except Exception:
            pass
        return
    bet_id = register_bet(user_id, bet)

    async def finish() -> None:
        await asyncio.sleep(SLOT_WAIT_SECONDS)

        dice_value = control_msg.dice.value
        if not pop_bet(bet_id):
            return
        won = dice_value == SLOT_WIN_VALUE

        balance_after_withdraw = await get_balance(user_id)
        balance_before = round(balance_after_withdraw + bet, 2)

        if won:
            total_return = round(bet * SLOT_MULTIPLIER, 2)
            net_win = round(total_return - bet, 2)
            new_balance = await add_balance(user_id, total_return)

            await save_slot_game(
                user_id, bet, dice_value,
                SLOT_MULTIPLIER, total_return, True, chat_id=message.chat.id,
                idempotency_key=f"{message.chat.id}:{message.message_id}",
            )

            quote = secrets.choice(SLOT_QUOTES_WIN)

            text_out = (
                '<tg-emoji emoji-id="5449683594425410231">🔼</tg-emoji>'
                f' <i>{user_link(user)}, вы <b>выиграли</b>: +{net_win}'
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
                f' [<b> x{SLOT_MULTIPLIER} </b>]</i>\n'
                '<blockquote>'
                f'<s>{balance_before}'
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></s> '
                '<tg-emoji emoji-id="5028746137645876535">📈</tg-emoji>'
                f'<b>{round(new_balance, 2)}</b>'
                '</blockquote>\n\n'
                '<blockquote>'
                '<tg-emoji emoji-id="5240369183593615679">💬</tg-emoji>'
                f' {quote}'
                '</blockquote>'
            )
        else:
            new_balance = balance_after_withdraw

            await save_slot_game(
                user_id, bet, dice_value,
                0.0, 0.0, False, chat_id=message.chat.id,
                idempotency_key=f"{message.chat.id}:{message.message_id}",
            )

            quote = secrets.choice(SLOT_QUOTES_LOSE)

            text_out = (
                '<tg-emoji emoji-id="5447183459602669338">🔽</tg-emoji>'
                f' <i>{user_link(user)}, вы <b>проиграли</b>: -{round(bet, 2)}'
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></i>\n'
                '<blockquote>'
                f'<s>{balance_before}'
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></s> '
                '<tg-emoji emoji-id="5028325978175177540">📉</tg-emoji>'
                f'<b>{round(new_balance, 2)}</b>'
                '</blockquote>\n\n'
                '<blockquote>'
                '<tg-emoji emoji-id="5240369183593615679">💬</tg-emoji>'
                f' {quote}'
                '</blockquote>'
            )

        try:
            await message.answer(text_out, reply_markup=slot_markup_replay())
        except Exception:
            logging.exception("slot result send failed")

        SLOT_LAST_GAMES[user_id] = {
            "bet": bet,
        }

    task = spawn(finish())
    task.add_done_callback(lambda t, b=bet_id: bet_task_done(t, b))


@router.callback_query(F.data == "slot_noop")
async def slot_noop(call: CallbackQuery) -> None:
    await call.answer()


@router.callback_query(F.data == "slot_replay")
async def slot_replay(call: CallbackQuery) -> None:
    data = SLOT_LAST_GAMES.get(call.from_user.id)
    if not data:
        await call.answer("Нет предыдущей игры", show_alert=True)
        return

    bet = data["bet"]

    ok = await try_withdraw(call.from_user.id, bet)
    if not ok:
        await call.answer("Недостаточно средств", show_alert=True)
        return

    await call.answer()

    await slot_start_game(
        call.message,
        bet,
        call.from_user.id,
        call.from_user,
    )


@router.callback_query(F.data == "slot_vabank")
async def slot_vabank(call: CallbackQuery) -> None:
    data = SLOT_LAST_GAMES.get(call.from_user.id)
    if not data:
        await call.answer("Нет предыдущей игры", show_alert=True)
        return

    balance = await get_balance(call.from_user.id)

    if balance < SLOT_MIN_BET:
        await call.answer("Недостаточно средств", show_alert=True)
        return

    balance = round(balance, 2)
    ok = await try_withdraw(call.from_user.id, balance)
    if not ok:
        await call.answer("Недостаточно средств", show_alert=True)
        return

    await call.answer()

    await slot_start_game(
        call.message,
        balance,
        call.from_user.id,
        call.from_user,
    )


@router.message(F.text.regexp(r"(?i)^/chs$"))
async def cmd_chs(message: Message) -> None:
    if message.from_user.id != ADMIN_ID:
        return

    dice_msg = await message.answer_dice(emoji=SLOT_DICE_EMOJI)

    async def report() -> None:
        await asyncio.sleep(SLOT_WAIT_SECONDS)
        await message.answer(f"Value: <b>{dice_msg.dice.value}</b>")

    task = spawn(report())
    task.add_done_callback(generic_task_done)


@router.callback_query(F.data == "ref_withdraw")
async def on_ref_withdraw(call: CallbackQuery) -> None:
    user_id = call.from_user.id
    ref_data = await get_ref_data(user_id)

    if await is_ref_frozen(user_id):
        await call.answer("Заработок с приглашений заморожен", show_alert=True)
        return

    balance = ref_data["signup_earned"] + ref_data["deposit_earned"] + ref_data.get("group_earned", 0.0)

    if balance < REF_MIN_WITHDRAW:
        await call.answer(
            f"На реферальном балансе меньше {REF_MIN_WITHDRAW}⭐️",
            show_alert=True,
        )
        return

    credited = 0.0
    async with _db_lock:
        conn = db()
        try:
            async with conn.execute(
                "SELECT signup_earned + deposit_earned + group_earned FROM ref_balance WHERE user_id = ?",
                (user_id,),
            ) as c:
                row = await c.fetchone()
            credited = round(float(row[0]), 2) if row else 0.0
            if credited + 1e-9 >= REF_MIN_WITHDRAW:
                await conn.execute(
                    "UPDATE ref_balance SET signup_earned = 0, deposit_earned = 0, group_earned = 0 "
                    "WHERE user_id = ?",
                    (user_id,),
                )
                await conn.execute(
                    "INSERT INTO balances (user_id, amount, created_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(user_id) DO UPDATE SET amount = ROUND(amount + ?, 2)",
                    (user_id, credited, now_msk().isoformat(), credited),
                )
                await conn.commit()
            else:
                await conn.rollback()
        except BaseException:
            await conn.rollback()
            raise

    failed = credited + 1e-9 < REF_MIN_WITHDRAW
    balance = credited

    if failed:
        await call.answer(
            f"На реферальном балансе меньше {REF_MIN_WITHDRAW}⭐️",
            show_alert=True,
        )
        return

    try:
        await call.message.edit_text(
            '<tg-emoji emoji-id="4965219701572503640">💰</tg-emoji>'
            f'<i> Вы успешно сняли {round(balance, 2)}'
            '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
            ' на основной баланс!</i>'
        )
    except Exception:
        logging.exception("ref withdraw edit failed")
    await call.answer()


@router.inline_query()
async def on_inline_check(query: InlineQuery) -> None:
    if _wallet_backend is None:
        await query.answer([], cache_time=0, is_personal=True)
        return
    results = await _wallet_backend.inline_check_results(query.from_user.id, query.query)
    await query.answer(results, cache_time=0, is_personal=True)


@router.pre_checkout_query()
async def on_pre_checkout(query: PreCheckoutQuery) -> None:
    if query.invoice_payload.startswith("ms_"):
        if _wallet_backend is None:
            await query.answer(ok=False, error_message="Платёжный сервис временно недоступен.")
            return
        try:
            await _wallet_backend.validate_stars_order(query.invoice_payload, query.from_user.id, query.currency, query.total_amount)
        except GameError as error:
            await query.answer(ok=False, error_message=error.message)
            return
    logging.info("pre_checkout: user=%s amount=%s", query.from_user.id, query.total_amount)
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def on_successful_payment(message: Message) -> None:
    payment = message.successful_payment
    if payment.invoice_payload.startswith("ms_"):
        if _wallet_backend is None:
            logging.error("Stars payment received while wallet backend is unavailable")
            return
        try:
            balance = await _wallet_backend.credit_stars_order(payment.invoice_payload, message.from_user.id, payment.currency, payment.total_amount, payment.telegram_payment_charge_id)
        except GameError:
            logging.error("Stars payment validation failed for user %s", message.from_user.id)
            return
        if balance is not None:
            await message.answer(f"Баланс пополнен на {payment.total_amount} Stars. Баланс: {balance:g} Stars.")
        return

    new_balance = await credit_payment(
        payment.telegram_payment_charge_id,
        message.from_user.id,
        payment.total_amount,
    )
    if new_balance is None:
        logging.warning(
            "Duplicate successful_payment: charge_id=%s user=%s",
            payment.telegram_payment_charge_id,
            message.from_user.id,
        )
        return

    logging.info(
        "successful_payment: user=%s amount=%s charge=%s",
        message.from_user.id,
        payment.total_amount,
        payment.telegram_payment_charge_id,
    )

    amount = payment.total_amount

    try:
        if _wallet_backend is None:
            await process_referral_deposit(message.from_user.id, float(amount))
    except Exception:
        logging.exception("referral deposit processing failed")

    try:
        await message.answer(
            f'<i><tg-emoji emoji-id="4976909296882156783">🪙</tg-emoji>'
            f'{user_link(message.from_user)}, вы <b>успешно</b> пополнили баланс на {amount}'
            f'<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></i>\n'
            f'<b>Текущий баланс:</b> <code>{round(new_balance, 2)}</code>⭐️'
        )
    except Exception:
        logging.exception("payment confirmation send failed")


@router.message(F.text.regexp(r"(?i)^/set(\s|$)"))
async def cmd_set(message: Message, state: FSMContext) -> None:
    await state.clear()

    if message.from_user.id != ADMIN_ID:
        return

    if not message.reply_to_message:
        return

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) != 2:
        return

    amount = parse_number(parts[1])
    if amount is None or amount < 0:
        return

    target_id = message.reply_to_message.from_user.id
    await set_balance(target_id, round(amount, 2))


@router.message(
    F.text.regexp(r"(?i)^/?crash(\s|$)")
    | F.text.regexp(r"(?i)^/?краш(\s|$)")
)
async def cmd_crash(message: Message, state: FSMContext) -> None:
    await state.clear()

    text = message.text.strip()
    if text.startswith("/"):
        text = text[1:]

    parts = text.split()

    if len(parts) != 3:
        await message.answer(crash_usage_text(message.from_user))
        return

    balance = await get_balance(message.from_user.id)

    bet_token = parts[1].lower()
    is_alias = False

    if bet_token in ALL_IN_ALIASES:
        bet = round(balance, 2)
        is_alias = True
    elif bet_token in HALF_ALIASES:
        bet = round(balance / 2, 2)
        is_alias = True
    else:
        parsed_bet = parse_number(bet_token)
        if parsed_bet is None:
            await message.answer(crash_usage_text(message.from_user))
            return
        bet = parsed_bet

    parsed_multiplier = parse_number(parts[2])
    if parsed_multiplier is None:
        await message.answer(crash_usage_text(message.from_user))
        return
    multiplier = parsed_multiplier

    if bet < MIN_BET:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(message.from_user)}, минимальная ставка {MIN_BET}'
            '<tg-emoji emoji-id="5951810621887484519">⭐️</tg-emoji></i>'
        )
        return

    if multiplier <= 1.0:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(message.from_user)}, диапазон должен быть больше 1.00</i>'
        )
        return

    if multiplier > MAX_MULTIPLIER:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(message.from_user)}, максимальный множитель {MAX_MULTIPLIER:.2f}x</i>'
        )
        return

    if is_alias:
        bet = round(min(bet, balance), 2)

    ok = await try_withdraw(message.from_user.id, bet)
    if not ok:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(message.from_user)}, недостаточно средств!</i>'
        )
        return

    bet_id = register_bet(message.from_user.id, bet)
    task = spawn(crash_game(message, bet, multiplier, bet_id))
    task.add_done_callback(
        lambda t, uid=message.from_user.id, b=bet, bid=bet_id: crash_task_done(t, uid, b, bid)
    )


@router.message(F.text.regexp(r"(?i)^/?краш$"))
async def cmd_crash_usage(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(crash_usage_text(message.from_user))


@router.message(
    F.text.regexp(r"(?i)^/?mines(\s|$)")
    | F.text.regexp(r"(?i)^/?мины(\s|$)")
)
async def cmd_mines(message: Message, state: FSMContext) -> None:
    global MINES_NEXT_ID

    await state.clear()

    text = message.text.strip()
    if text.startswith("/"):
        text = text[1:]

    parts = text.split()

    balance = await get_balance(message.from_user.id)

    if len(parts) == 1:
        await message.answer(mines_usage_text(message.from_user))
        return

    if len(parts) > 3:
        await message.answer(mines_usage_text(message.from_user))
        return

    bet_token = parts[1].lower()
    is_alias = False

    if bet_token in ALL_IN_ALIASES:
        bet = round(balance, 2)
        is_alias = True
    elif bet_token in HALF_ALIASES:
        bet = round(balance / 2, 2)
        is_alias = True
    else:
        parsed_bet = parse_number(bet_token)
        if parsed_bet is None:
            await message.answer(mines_usage_text(message.from_user))
            return
        bet = parsed_bet

    if len(parts) == 3:
        mines_count = parse_int(parts[2])
        if mines_count is None:
            await message.answer(mines_usage_text(message.from_user))
            return
    else:
        mines_count = MINES_DEFAULT

    if bet < MIN_BET:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(message.from_user)}, минимальная ставка {MIN_BET}'
            '<tg-emoji emoji-id="5951810621887484519">⭐️</tg-emoji></i>'
        )
        return

    if mines_count < MINES_MIN:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(message.from_user)}, минимальное количество мин — {MINES_MIN}</i>'
        )
        return

    if mines_count > MINES_MAX:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(message.from_user)}, максимальное количество мин — {MINES_MAX}</i>'
        )
        return

    if is_alias:
        bet = round(min(bet, balance), 2)

    ok = await try_withdraw(message.from_user.id, bet)
    if not ok:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(message.from_user)}, недостаточно средств!</i>'
        )
        return

    client_seed = str(message.from_user.id)
    nonce = await next_nonce(message.from_user.id)
    server_seed = generate_server_seed()
    mine_positions = mines_from_seeds(server_seed, client_seed, nonce, mines_count)

    game_id = MINES_NEXT_ID
    MINES_NEXT_ID += 1

    game = {
        "id": game_id,
        "owner_id": message.from_user.id,
        "chat_id": message.chat.id,
        "bet": bet,
        "mines_count": mines_count,
        "server_seed": server_seed,
        "client_seed": client_seed,
        "nonce": nonce,
        "mine_positions": mine_positions,
        "revealed": set(),
        "game_over": False,
        "won": False,
        "cashed_out": False,
        "exploded_mine": None,
        "created_at": time.monotonic(),
    }
    MINES_GAMES[game_id] = game

    next_mult = mines_multiplier(1, mines_count)
    text_out = mines_start_text(message.from_user, bet, mines_count, next_mult)
    markup = mines_grid_markup(game)

    try:
        sent = await message.answer(text_out, reply_markup=markup)
    except Exception:
        MINES_GAMES.pop(game_id, None)
        await add_balance(message.from_user.id, bet)
        raise
    game["message_id"] = sent.message_id
    game["chat_id"] = sent.chat.id


@router.message(F.text.regexp(r"(?i)^/?мины$"))
async def cmd_mines_usage(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(mines_usage_text(message.from_user))


@router.callback_query(F.data.startswith("mines_cell_"))
async def mines_process_cell(call: CallbackQuery) -> None:
    parts = call.data.split("_")
    if len(parts) != 4:
        await call.answer()
        return

    try:
        game_id = int(parts[2])
        cell_idx = int(parts[3])
    except ValueError:
        await call.answer()
        return

    game = MINES_GAMES.get(game_id)
    if not game:
        await call.answer("Игра уже завершена.", show_alert=True)
        return

    if game["owner_id"] != call.from_user.id:
        await call.answer("Это не ваша игра!", show_alert=True)
        return

    if game.get("game_over") or game.get("won") or game.get("cashed_out"):
        await call.answer("Игра уже завершена.", show_alert=True)
        return

    if not 0 <= cell_idx < MINES_TOTAL:
        await call.answer()
        return

    if cell_idx in game["revealed"]:
        await call.answer("Эта клетка уже открыта!", show_alert=True)
        return

    answer_bg(call)

    game["revealed"].add(cell_idx)

    if cell_idx in game["mine_positions"]:
        game["game_over"] = True
        game["exploded_mine"] = cell_idx

        opened_before = len(game["revealed"]) - 1
        could_mult = mines_multiplier(opened_before, game["mines_count"])
        if could_mult <= 1.0:
            could_mult = mines_multiplier(1, game["mines_count"])

        await save_mines_game(
            call.from_user.id,
            game["bet"],
            game["mines_count"],
            opened_before,
            could_mult,
            0.0,
            False,
            chat_id=game.get("chat_id"),
            idempotency_key=f"{game.get('chat_id')}:{game.get('message_id')}",
        )

        text_out = mines_lose_text(
            call.from_user,
            game["bet"],
            game["mines_count"],
            could_mult,
        )
        markup = mines_grid_markup(game, game_over=True)

        try:
            await call.message.edit_text(text_out, reply_markup=markup)
        except Exception:
            logging.exception("mines lose edit failed")

        MINES_GAMES.pop(game_id, None)
        return

    opened = len(game["revealed"])
    safe_total = MINES_TOTAL - game["mines_count"]

    if opened >= safe_total:
        game["game_over"] = True
        game["won"] = True

        mult = mines_multiplier(opened, game["mines_count"])
        win_amount = round(game["bet"] * mult, 2)
        await add_balance(call.from_user.id, win_amount)

        await save_mines_game(
            call.from_user.id,
            game["bet"],
            game["mines_count"],
            opened,
            mult,
            win_amount,
            True,
            chat_id=game.get("chat_id"),
            idempotency_key=f"{game.get('chat_id')}:{game.get('message_id')}",
        )

        text_out = mines_win_text(
            call.from_user,
            game["bet"],
            game["mines_count"],
            mult,
        )
        markup = mines_grid_markup(game, won=True)

        try:
            await call.message.edit_text(text_out, reply_markup=markup)
        except Exception:
            logging.exception("mines win edit failed")

        MINES_GAMES.pop(game_id, None)
        return

    current_mult = mines_multiplier(opened, game["mines_count"])
    next_mult = mines_multiplier(opened + 1, game["mines_count"])

    text_out = mines_playing_text(
        call.from_user,
        game["bet"],
        game["mines_count"],
        opened,
        current_mult,
        next_mult,
    )
    markup = mines_grid_markup(game)

    try:
        await call.message.edit_text(text_out, reply_markup=markup)
    except Exception:
        logging.exception("mines continue edit failed")


@router.callback_query(F.data.startswith("mines_noop_"))
async def mines_process_noop(call: CallbackQuery) -> None:
    await call.answer()


@router.callback_query(F.data.startswith("mines_cashout_"))
async def mines_process_cashout(call: CallbackQuery) -> None:
    parts = call.data.split("_")
    if len(parts) != 3:
        await call.answer()
        return

    try:
        game_id = int(parts[2])
    except ValueError:
        await call.answer()
        return

    game = MINES_GAMES.get(game_id)
    if not game:
        await call.answer("Игра уже завершена.", show_alert=True)
        return

    if game["owner_id"] != call.from_user.id:
        await call.answer("Это не ваша игра!", show_alert=True)
        return

    if game.get("game_over") or game.get("won") or game.get("cashed_out"):
        await call.answer("Игра уже завершена.", show_alert=True)
        return

    opened = len(game["revealed"])
    if opened == 0:
        await call.answer("Откройте хотя бы одну клетку!", show_alert=True)
        return

    game["game_over"] = True
    game["won"] = True
    game["cashed_out"] = True
    answer_bg(call)

    mult = mines_multiplier(opened, game["mines_count"])
    win_amount = round(game["bet"] * mult, 2)
    await add_balance(call.from_user.id, win_amount)

    await save_mines_game(
        call.from_user.id,
        game["bet"],
        game["mines_count"],
        opened,
        mult,
        win_amount,
        True,
        chat_id=game.get("chat_id"),
        idempotency_key=f"{game.get('chat_id')}:{game.get('message_id')}",
    )

    text_out = mines_cashout_text(
        call.from_user,
        game["bet"],
        game["mines_count"],
        mult,
    )
    markup = mines_grid_markup(game, won=True)

    try:
        await call.message.edit_text(text_out, reply_markup=markup)
    except Exception:
        logging.exception("mines cashout edit failed")

    MINES_GAMES.pop(game_id, None)


@router.message(F.text.regexp(r"(?i)^/?пополнить\s+\d+$"), F.chat.type != ChatType.PRIVATE)
async def cmd_topup_group(message: Message) -> None:
    parts = message.text.replace("/", "").strip().split()
    amount = int(parts[1])
    if amount <= 0 or amount > TOPUP_MAX:
        return
    payload = generate_payload()
    logging.info("invoice from group: user=%s amount=%s payload=%s", message.from_user.id, amount, payload)
    await message.answer_invoice(
        title=f"Пополнение #{payload}",
        description=f"Пополнение баланса на {amount}⭐️",
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Пополнение баланса", amount=amount)],
    )


@router.message(F.text.regexp(r"(?i)^(б|баланс)$"))
async def cmd_balance(message: Message, bot: Bot, state: FSMContext) -> None:
    await state.clear()

    balance = await get_balance(message.from_user.id)

    if message.chat.type == ChatType.PRIVATE:
        markup = balance_markup_private()
    else:
        me = await bot.me()
        markup = balance_markup_group(me.username)

    await message.answer(
        '<blockquote>'
        '<tg-emoji emoji-id="4972482444025398275">👛</tg-emoji>'
        f'Ваш баланс: <code>{round(balance, 2)}</code>'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
        '</blockquote>',
        reply_markup=markup,
    )


@router.callback_query(F.data == "balance_topup")
async def on_topup(call: CallbackQuery) -> None:
    await call.message.edit_text(
        '<b><tg-emoji emoji-id="5053473385355412667">⭐️</tg-emoji> Пополнение</b>\n\n'
        '<i><b>Выберите</b> или <b>введите</b> сумму пополнения в '
        '<tg-emoji emoji-id="5030538831225422917">⬆️</tg-emoji></i>',
        reply_markup=topup_markup(),
    )
    await call.answer()


@router.callback_query(F.data.startswith("topup_"))
async def on_topup_amount(call: CallbackQuery) -> None:
    amount = int(call.data.split("_", 1)[1])
    payload = generate_payload()
    logging.info("invoice from callback: user=%s amount=%s payload=%s", call.from_user.id, amount, payload)
    await call.message.answer_invoice(
        title=f"Пополнение #{payload}",
        description=f"Пополнение баланса на {amount}⭐️",
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Пополнение баланса", amount=amount)],
    )
    await call.answer()


@router.message(F.text.regexp(r"^\d+$"), F.chat.type == ChatType.PRIVATE)
async def on_topup_custom(message: Message) -> None:
    amount = int(message.text)
    if amount <= 0:
        return
    if amount > TOPUP_MAX:
        await message.answer(f"Максимальная сумма пополнения — {TOPUP_MAX}")
        return
    payload = generate_payload()
    logging.info("invoice from text: user=%s amount=%s payload=%s", message.from_user.id, amount, payload)
    await message.answer_invoice(
        title=f"Пополнение #{payload}",
        description=f"Пополнение баланса на {amount}⭐️",
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Пополнение баланса", amount=amount)],
    )


DARTS_DICE_EMOJI = "🎯"
DARTS_WAIT_SECONDS = 3.0
DARTS_MIN_BET = 0.5

DARTS_RANGES = {
    "классик": 5.0,
    "мимо": 1.1,
    "отскок": 5.0,
    "красное": 1.7,
    "белое": 2.25,
}

DARTS_VALUE_MAP = {
    1: ["мимо", "отскок"],
    2: ["красное"],
    3: ["белое"],
    4: ["красное"],
    5: ["белое"],
    6: ["классик"],
}

DARTS_QUOTES_WIN = {
    "классик": [
        "Классика жанра.", "Дротик точно в цель.", "Как по учебнику.",
        "Прямо в яблочко.", "Чистое попадание.", "Без выкрутасов, зато зашло.",
    ],
    "мимо": [
        "Мимо, но ставка зашла.", "Дротик улетел в стену, а ты в плюсе.",
        "Не попал, зато заработал.", "Промах оказался выгодным.",
        "Мимо мишени, но в цель по деньгам.", "Иногда промах — это стратегия.",
    ],
    "отскок": [
        "Отскок от проволоки — и в цель.", "Дротик срикошетил, но зашёл.",
        "Отскок сыграл за тебя.", "Не без везения, но засчитано.",
        "Проволока помогла, а не помешала.", "Рикошет принёс результат.",
    ],
    "красное": [
        "Красное — и это засчитано.", "Красный сектор сыграл за тебя.",
        "Попал в красное, забрал своё.", "Красное сегодня на твоей стороне.",
        "Красный цвет приносит удачу.", "Красное — значит выигрышное.",
    ],
    "белое": [
        "Белое — и это засчитано.", "Белый сектор сыграл за тебя.",
        "Попал в белое, забрал своё.", "Белое сегодня на твоей стороне.",
        "Белый цвет приносит удачу.", "Белое — значит выигрышное.",
    ],
}

DARTS_QUOTES_LOSE = {
    "классик": [
        "Классика подвела.", "Дротик точно в цель, но не в твою пользу.",
        "Как по учебнику, но учили не тебя.", "Прямо в яблочко — и мимо тебя.",
        "Чистое попадание, грязный проигрыш.", "Без выкрутасов, зато в минус.",
    ],
    "мимо": [
        "Мимо. И это стоило тебе ставки.", "Дротик улетел в стену, деньги в никуда.",
        "Не попал, и ты тоже.", "Промах обошёлся дорого.",
        "Мимо мишени, мимо кассы.", "Промах — просто промах.",
    ],
    "отскок": [
        "Отскок от проволоки — и мимо.", "Дротик срикошетил и ушёл.",
        "Отскок сыграл против тебя.", "Везения не хватило.",
        "Проволока помешала, а не помогла.", "Рикошет принёс только разочарование.",
    ],
    "красное": [
        "Красное — но не в твою пользу.", "Красный сектор сыграл против тебя.",
        "Попал в красное, а ставка сгорела.", "Красное сегодня не на твоей стороне.",
        "Красный цвет не всегда к удаче.", "Красное — значит мимо кассы.",
    ],
    "белое": [
        "Белое — но не в твою пользу.", "Белый сектор сыграл против тебя.",
        "Попал в белое, а ставка сгорела.", "Белое сегодня не на твоей стороне.",
        "Белый цвет не всегда к удаче.", "Белое — значит мимо кассы.",
    ],
}

BOWLING_DICE_EMOJI = "🎳"
BOWLING_WAIT_SECONDS = 3.3
BOWLING_MIN_BET = 0.5

BOWLING_RANGES = {
    "классик": 2.5,
    "мимо": 5.0,
    "1": 5.0,
    "3": 5.0,
    "4": 5.0,
    "5": 5.0,
    "6": 5.0,
}

BOWLING_VALUE_MAP = {
    1: ["мимо"],
    2: ["1"],
    3: ["3"],
    4: ["4"],
    5: ["5"],
    6: ["классик", "6"],
}

BOWLING_QUOTES_WIN = {
    "классик": [
        "Страйк. Все десять с первого шара.", "Классика жанра — чистая дорожка.",
        "Страйк, и это твой день.", "Все кегли снесены одним ударом.",
        "Идеальный бросок.", "Как по учебнику — страйк.",
    ],
    "мимо": [
        "Мимо, но ставка зашла.", "Шар ушёл в жёлоб, а ты в плюсе.",
        "Не попал, зато заработал.", "Промах оказался выгодным.",
        "Мимо кеглей, но в цель по деньгам.", "Иногда промах — это стратегия.",
    ],
    "1": [
        "Одна кегля — и этого хватило.", "Всего одна, но в твою пользу.",
        "Скромно, зато зашло.", "Одна кегля сыграла за тебя.",
        "Минимум, но результат есть.", "Одна — значит выигрышная.",
    ],
    "3": [
        "Три кегли — и это засчитано.", "Три сыграли за тебя.",
        "Не много, но в твою пользу.", "Три кегли — уже результат.",
        "Тройка принесла удачу.", "Три — значит выигрышные.",
    ],
    "4": [
        "Четыре кегли — и это засчитано.", "Четыре сыграли за тебя.",
        "Половина снесена, но в твою пользу.", "Четыре кегли — уже результат.",
        "Четвёрка принесла удачу.", "Четыре — значит выигрышные.",
    ],
    "5": [
        "Пять кеглей — и это засчитано.", "Пять сыграли за тебя.",
        "Больше половины, и в твою пользу.", "Пять кеглей — уже результат.",
        "Пятёрка принесла удачу.", "Пять — значит выигрышные.",
    ],
    "6": [
        "Шесть кеглей — и это засчитано.", "Шесть сыграли за тебя.",
        "Хороший бросок, и в твою пользу.", "Шесть кеглей — уже результат.",
        "Шестёрка принесла удачу.", "Шесть — значит выигрышные.",
    ],
}

BOWLING_QUOTES_LOSE = {
    "классик": [
        "Страйк был нужен, но не случился.", "Классика подвела.",
        "Все кегли устояли.", "Идеальный бросок не получился.",
        "Как по учебнику, но учили не тебя.", "Страйк прошёл мимо.",
    ],
    "мимо": [
        "Мимо. И это стоило тебе ставки.", "Шар ушёл в жёлоб, деньги в никуда.",
        "Не попал, и ты тоже.", "Промах обошёлся дорого.",
        "Мимо кеглей, мимо кассы.", "Промах — просто промах.",
    ],
    "1": [
        "Одна кегля, а ставка сгорела.", "Всего одна, но не в твою пользу.",
        "Скромно и обидно.", "Одна кегля сыграла против тебя.",
        "Минимум, но и его не хватило.", "Одна — значит мимо кассы.",
    ],
    "3": [
        "Три кегли, а ставка сгорела.", "Три сыграли против тебя.",
        "Не много, и не в твою пользу.", "Три кегли — и ноль результата.",
        "Тройка не принесла удачу.", "Три — значит мимо кассы.",
    ],
    "4": [
        "Четыре кегли, а ставка сгорела.", "Четыре сыграли против тебя.",
        "Половина снесена, но не в твою пользу.", "Четыре кегли — и ноль результата.",
        "Четвёрка не принесла удачу.", "Четыре — значит мимо кассы.",
    ],
    "5": [
        "Пять кеглей, а ставка сгорела.", "Пять сыграли против тебя.",
        "Больше половины, но не в твою пользу.", "Пять кеглей — и ноль результата.",
        "Пятёрка не принесла удачу.", "Пять — значит мимо кассы.",
    ],
    "6": [
        "Шесть кеглей, а ставка сгорела.", "Шесть сыграли против тебя.",
        "Хороший бросок, но не в твою пользу.", "Шесть кеглей — и ноль результата.",
        "Шестёрка не принесла удачу.", "Шесть — значит мимо кассы.",
    ],
}

CUBE_DICE_EMOJI = "🎲"
CUBE_WAIT_SECONDS = 2.8
CUBE_MIN_BET = 0.5

CUBE_EVEN_WORDS = {"чет", "четное"}
CUBE_ODD_WORDS = {"нечет", "нечетное"}

CUBE_CLASSIC_MULTIPLIERS = {3: 1.1, 4: 1.2, 5: 1.4, 6: 1.5}
CUBE_EVEN_ODD_MULT = 1.8
CUBE_NUMBERS_MULT = {1: 5.0, 2: 2.7, 3: 1.8}
CUBE_LESS_MULTIPLIERS = {6: 1.08, 5: 1.35, 4: 1.8, 3: 2.7, 2: 5.4}
CUBE_MORE_MULTIPLIERS = {1: 1.08, 2: 1.35, 3: 1.8, 4: 2.7, 5: 5.4}

CUBE_QUOTES_WIN = {
    "классик": [
        "Классика жанра — и это твой день.", "Куб остановился там, где нужно.",
        "Просто, надёжно, в твою пользу.", "Как по учебнику — зашло.",
        "Стандартный бросок — стандартный успех.", "Без выкрутасов, зато выигрыш.",
        "Классик сыграл за тебя.", "Всё по плану.",
    ],
    "чет": [
        "Чёт выпал, и это твой день.", "Чётное число сыграло за тебя.",
        "Чёт — значит выигрышное.", "Двойка, четвёрка или шестёрка — неважно, зашло.",
        "Чёт сегодня на твоей стороне.", "Чётное — и ставка зашла.",
    ],
    "нечет": [
        "Нечёт выпал, и это твой день.", "Нечётное число сыграло за тебя.",
        "Нечёт — значит выигрышное.", "Единица, тройка или пятёрка — неважно, зашло.",
        "Нечёт сегодня на твоей стороне.", "Нечётное — и ставка зашла.",
    ],
    "2 числа": [
        "Два числа — и это засчитано.", "Два сыграли за тебя.",
        "Пара чисел — уже результат.", "Два — значит выигрышные.",
        "Двойка чисел принесла удачу.", "Два числа, и оба твои.",
    ],
    "3 числа": [
        "Три числа — максимум, и это твоё.", "Три сыграли за тебя.",
        "Полный набор — уже результат.", "Три — значит выигрышные.",
        "Тройка чисел принесла удачу.", "Три числа, и все твои.",
    ],
    "меньше": [
        "Меньше — и это засчитано.", "Малое число сыграло за тебя.",
        "Меньше — значит выигрышное.", "Скромно, но в твою пользу.",
        "Меньше сегодня на твоей стороне.", "Малое число принесло удачу.",
    ],
    "больше": [
        "Больше — и это засчитано.", "Большое число сыграло за тебя.",
        "Больше — значит выигрышное.", "Крупно, и в твою пользу.",
        "Больше сегодня на твоей стороне.", "Большое число принесло удачу.",
    ],
}

CUBE_QUOTES_LOSE = {
    "классик": [
        "Классика подвела.", "Куб остановился не там.",
        "Просто, надёжно, но не в твою пользу.", "Как по учебнику, но учили не тебя.",
        "Стандартный бросок — нестандартный проигрыш.", "Без выкрутасов, зато в минус.",
        "Классик сыграл против тебя.", "Всё по плану, но плану соперника.",
    ],
    "чет": [
        "Чёт не выпал.", "Чётное число сыграло против тебя.",
        "Чёт — но не в твою пользу.", "Ждал чёт, а пришло не то.",
        "Чёт сегодня не на твоей стороне.", "Чётное — и мимо кассы.",
    ],
    "нечет": [
        "Нечёт не выпал.", "Нечётное число сыграло против тебя.",
        "Нечёт — но не в твою пользу.", "Ждал нечёт, а пришло не то.",
        "Нечёт сегодня не на твоей стороне.", "Нечётное — и мимо кассы.",
    ],
    "2 числа": [
        "Два числа, а ставка сгорела.", "Два сыграли против тебя.",
        "Пара чисел — и ноль результата.", "Два — значит мимо кассы.",
        "Двойка чисел не принесла удачу.", "Два числа, но не твои.",
    ],
    "3 числа": [
        "Три числа, а ставка сгорела.", "Три сыграли против тебя.",
        "Полный набор — и ноль результата.", "Три — значит мимо кассы.",
        "Тройка чисел не принесла удачу.", "Три числа, но не твои.",
    ],
    "меньше": [
        "Меньше не выпало.", "Малое число сыграло против тебя.",
        "Меньше — но не в твою пользу.", "Ждал меньше, а пришло не то.",
        "Меньше сегодня не на твоей стороне.", "Малое число — и мимо кассы.",
    ],
    "больше": [
        "Больше не выпало.", "Большое число сыграло против тебя.",
        "Больше — но не в твою пользу.", "Ждал больше, а пришло не то.",
        "Больше сегодня не на твоей стороне.", "Большое число — и мимо кассы.",
    ],
}

_CUBE_ONE_WIN = [
    "Одно число — и этого хватило.", "Ровно одно, но в твою пользу.",
    "Одно число сыграло за тебя.", "Минимум, но результат есть.",
    "Одно — значит выигрышное.", "Одно число, зато твоё.",
]

_CUBE_ONE_LOSE = [
    "Одно число, а ставка сгорела.", "Ровно одно, но не в твою пользу.",
    "Одно число сыграло против тебя.", "Минимум, и его не хватило.",
    "Одно — значит мимо кассы.", "Одно число, но не твоё.",
]

_CUBE_NUM_WIN = {
    1: [
        "Единица выпала, и это твой день.", "Один — значит выигрышный.",
        "Первое число сыграло за тебя.", "Единица принесла удачу.",
        "Один сегодня на твоей стороне.", "Выпала единица — забирай своё.",
    ],
    2: [
        "Двойка выпала, и это твой день.", "Два — значит выигрышное.",
        "Второе число сыграло за тебя.", "Двойка принесла удачу.",
        "Два сегодня на твоей стороне.", "Выпала двойка — забирай своё.",
    ],
    3: [
        "Тройка выпала, и это твой день.", "Три — значит выигрышное.",
        "Третье число сыграло за тебя.", "Тройка принесла удачу.",
        "Три сегодня на твоей стороне.", "Выпала тройка — забирай своё.",
    ],
    4: [
        "Четвёрка выпала, и это твой день.", "Четыре — значит выигрышное.",
        "Четвёртое число сыграло за тебя.", "Четвёрка принесла удачу.",
        "Четыре сегодня на твоей стороне.", "Выпала четвёрка — забирай своё.",
    ],
    5: [
        "Пятёрка выпала, и это твой день.", "Пять — значит выигрышное.",
        "Пятое число сыграло за тебя.", "Пятёрка принесла удачу.",
        "Пять сегодня на твоей стороне.", "Выпала пятёрка — забирай своё.",
    ],
    6: [
        "Шестёрка выпала, и это твой день.", "Шесть — значит выигрышное.",
        "Шестое число сыграло за тебя.", "Шестёрка принесла удачу.",
        "Шесть сегодня на твоей стороне.", "Выпала шестёрка — забирай своё.",
    ],
}

_CUBE_NUM_LOSE = {
    1: [
        "Единица не выпала.", "Один сыграл против тебя.",
        "Первое число — но не в твою пользу.", "Единица не принесла удачу.",
        "Один сегодня не на твоей стороне.", "Ждал единицу, а пришло не то.",
    ],
    2: [
        "Двойка не выпала.", "Два сыграло против тебя.",
        "Второе число — но не в твою пользу.", "Двойка не принесла удачу.",
        "Два сегодня не на твоей стороне.", "Ждал двойку, а пришло не то.",
    ],
    3: [
        "Тройка не выпала.", "Три сыграло против тебя.",
        "Третье число — но не в твою пользу.", "Тройка не принесла удачу.",
        "Три сегодня не на твоей стороне.", "Ждал тройку, а пришло не то.",
    ],
    4: [
        "Четвёрка не выпала.", "Четыре сыграло против тебя.",
        "Четвёртое число — но не в твою пользу.", "Четвёрка не принесла удачу.",
        "Четыре сегодня не на твоей стороне.", "Ждал четвёрку, а пришло не то.",
    ],
    5: [
        "Пятёрка не выпала.", "Пять сыграло против тебя.",
        "Пятое число — но не в твою пользу.", "Пятёрка не принесла удачу.",
        "Пять сегодня не на твоей стороне.", "Ждал пятёрку, а пришло не то.",
    ],
    6: [
        "Шестёрка не выпала.", "Шесть сыграло против тебя.",
        "Шестое число — но не в твою пользу.", "Шестёрка не принесла удачу.",
        "Шесть сегодня не на твоей стороне.", "Ждал шестёрку, а пришло не то.",
    ],
}

for _n in range(1, 7):
    CUBE_QUOTES_WIN[f"число {_n}"] = _CUBE_NUM_WIN[_n] + _CUBE_ONE_WIN
    CUBE_QUOTES_LOSE[f"число {_n}"] = _CUBE_NUM_LOSE[_n] + _CUBE_ONE_LOSE

DICE_LAST_GAMES: dict = {}


def darts_resolve(spec: str, value: int):
    ranges = DARTS_VALUE_MAP.get(value)
    if not ranges:
        return None
    won = spec in ranges
    return won, DARTS_RANGES[spec], spec


def bowling_resolve(spec: str, value: int):
    ranges = BOWLING_VALUE_MAP.get(value)
    if not ranges:
        return None
    won = spec in ranges
    return won, BOWLING_RANGES[spec], spec


def cube_label(spec) -> str:
    kind, arg = spec
    if kind == "classic":
        return "классик"
    if kind == "even":
        return "чет"
    if kind == "odd":
        return "нечет"
    if kind == "less":
        return f"меньше {arg}"
    if kind == "more":
        return f"больше {arg}"
    return ",".join(str(n) for n in arg)


def cube_resolve(spec, value: int):
    if value < 1 or value > 6:
        return None
    kind, arg = spec
    if kind == "classic":
        mult = CUBE_CLASSIC_MULTIPLIERS.get(value)
        if mult is None:
            return False, 0.0, "классик"
        return True, mult, "классик"
    if kind == "even":
        return value % 2 == 0, CUBE_EVEN_ODD_MULT, "чет"
    if kind == "odd":
        return value % 2 == 1, CUBE_EVEN_ODD_MULT, "нечет"
    if kind == "less":
        return value < arg, CUBE_LESS_MULTIPLIERS[arg], "меньше"
    if kind == "more":
        return value > arg, CUBE_MORE_MULTIPLIERS[arg], "больше"
    count = len(arg)
    if count == 1:
        key = f"число {arg[0]}"
    elif count == 2:
        key = "2 числа"
    else:
        key = "3 числа"
    return value in arg, CUBE_NUMBERS_MULT[count], key


def parse_cube_spec(tokens: list[str]):
    tokens = [t for t in tokens if t]
    if not tokens:
        return ("classic", None)

    first = tokens[0]

    if len(tokens) == 1:
        if first == "классик":
            return ("classic", None)
        if first in CUBE_EVEN_WORDS:
            return ("even", None)
        if first in CUBE_ODD_WORDS:
            return ("odd", None)

    if first in ("меньше", "больше"):
        if len(tokens) != 2:
            return None
        n = parse_int(tokens[1])
        if n is None:
            return None
        if first == "меньше" and 2 <= n <= 6:
            return ("less", n)
        if first == "больше" and 1 <= n <= 5:
            return ("more", n)
        return None

    numbers = []
    for t in tokens:
        n = parse_int(t)
        if n is None or n < 1 or n > 6:
            return None
        numbers.append(n)

    if len(numbers) > 3 or len(set(numbers)) != len(numbers):
        return None

    return ("nums", tuple(sorted(numbers)))


DICE_GAMES = {
    "darts": {
        "emoji": DARTS_DICE_EMOJI,
        "wait": DARTS_WAIT_SECONDS,
        "min_bet": DARTS_MIN_BET,
        "resolve": darts_resolve,
        "label": lambda spec: spec,
        "quotes_win": DARTS_QUOTES_WIN,
        "quotes_lose": DARTS_QUOTES_LOSE,
    },
    "bowling": {
        "emoji": BOWLING_DICE_EMOJI,
        "wait": BOWLING_WAIT_SECONDS,
        "min_bet": BOWLING_MIN_BET,
        "resolve": bowling_resolve,
        "label": lambda spec: spec,
        "quotes_win": BOWLING_QUOTES_WIN,
        "quotes_lose": BOWLING_QUOTES_LOSE,
    },
    "cube": {
        "emoji": CUBE_DICE_EMOJI,
        "wait": CUBE_WAIT_SECONDS,
        "min_bet": CUBE_MIN_BET,
        "resolve": cube_resolve,
        "label": cube_label,
        "quotes_win": CUBE_QUOTES_WIN,
        "quotes_lose": CUBE_QUOTES_LOSE,
    },
}


async def init_dice_history() -> None:
    async with _db_lock:
        conn = db()
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS dice_history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "game TEXT NOT NULL, "
            "user_id INTEGER NOT NULL, "
            "bet REAL NOT NULL, "
            "player_range TEXT NOT NULL, "
            "dice_value INTEGER NOT NULL, "
            "multiplier REAL NOT NULL, "
            "win_amount REAL NOT NULL, "
            "won INTEGER NOT NULL, "
            "created_at TEXT NOT NULL"
            ")"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dice_history_user "
            "ON dice_history (user_id)"
        )
        await conn.commit()


async def save_dice_game(
    game: str,
    user_id: int,
    bet: float,
    player_range: str,
    dice_value: int,
    multiplier: float,
    win_amount: float,
    won: bool,
    chat_id: int | None = None,
    idempotency_key: str | None = None,
) -> None:
    async with _db_lock:
        conn = db()
        stamp = now_msk().isoformat()
        try:
            cursor = await conn.execute(
                "INSERT INTO dice_history (game, user_id, bet, player_range, dice_value, multiplier, win_amount, won, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (game, user_id, bet, player_range, dice_value, multiplier, win_amount, int(won), stamp),
            )
            await credit_telegram_group_loss(conn, chat_id, user_id, bet, win_amount, f"bot:dice:{idempotency_key}" if idempotency_key else f"bot:dice:{cursor.lastrowid}", stamp)
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


async def get_dice_stats(user_id: int) -> tuple[float, float, int]:
    async with _db_lock:
        async with db().execute(
            "SELECT COALESCE(MAX(win_amount), 0), COALESCE(MAX(bet), 0), COUNT(*) "
            "FROM dice_history WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return 0.0, 0.0, 0
    return float(row[0]), float(row[1]), int(row[2])


def dice_markup_disabled(amount: float, label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{round(amount, 2)}⭐️/{label}",
                    callback_data="dice_noop",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Пополнить",
                    url=f"https://t.me/{BOT_USERNAME}?start=toreplenish",
                    icon_custom_emoji_id="5443127283898405358",
                    style="success",
                ),
            ],
        ]
    )


def dice_markup_replay(game: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Повторить",
                    callback_data=f"dice_replay_{game}",
                    icon_custom_emoji_id="5264727218734524899",
                    style="primary",
                ),
                InlineKeyboardButton(
                    text="Ва-банк",
                    callback_data=f"dice_vabank_{game}",
                    icon_custom_emoji_id="5424972470023104089",
                    style="danger",
                ),
            ]
        ]
    )


def dice_usage_text(user, command_line: str, ranges_line: str) -> str:
    return (
        '<i><tg-emoji emoji-id="5008457489528652800">🤠</tg-emoji>'
        f'{user_link(user)}, правильное использование команды:\n\n '
        '<tg-emoji emoji-id="5949468670710258892">🚀</tg-emoji>'
        f'<code> {command_line}</code>\n '
        '<tg-emoji emoji-id="5055840333242303386">🤑</tg-emoji>'
        '<b>Удачной игры в Major!</b>\n\n '
        f'{ranges_line}</i>'
    )


def parse_bet_token(token: str, balance: float) -> tuple[float | None, bool]:
    token = token.lower()
    if token in ALL_IN_ALIASES:
        return round(balance, 2), True
    if token in HALF_ALIASES:
        return round(balance / 2, 2), True
    value = parse_number(token)
    if value is None:
        return None, False
    return value, False


async def dice_game_start(message: Message, game: str, bet: float, spec, user_id: int, user) -> None:
    cfg = DICE_GAMES[game]
    label = cfg["label"](spec)

    try:
        control_msg = await message.answer_dice(
            emoji=cfg["emoji"],
            reply_markup=dice_markup_disabled(bet, label),
        )
    except Exception:
        logging.exception("dice send failed: %s", game)
        await add_balance(user_id, bet)
        return

    bet_id = register_bet(user_id, bet)

    async def finish() -> None:
        await asyncio.sleep(cfg["wait"])

        dice_value = control_msg.dice.value
        if not pop_bet(bet_id):
            return
        result = cfg["resolve"](spec, dice_value)

        if result is None:
            await add_balance(user_id, bet)
            await message.answer("Ошибка результата. Ставка возвращена.")
            return

        won, multiplier, quote_key = result

        balance_after_withdraw = await get_balance(user_id)
        balance_before = round(balance_after_withdraw + bet, 2)

        if won:
            total_return = round(bet * multiplier, 2)
            net_win = round(total_return - bet, 2)
            new_balance = await add_balance(user_id, total_return)

            await save_dice_game(
                game, user_id, bet, label, dice_value,
                multiplier, total_return, True, chat_id=message.chat.id,
                idempotency_key=f"{message.chat.id}:{message.message_id}",
            )

            quote = secrets.choice(cfg["quotes_win"][quote_key])

            text_out = (
                '<tg-emoji emoji-id="5449683594425410231">🔼</tg-emoji>'
                f' <i>{user_link(user)}, вы <b>выиграли</b>: +{net_win}'
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
                f' [<b> x{multiplier} </b>]</i>\n'
                '<blockquote>'
                f'<s>{balance_before}'
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></s> '
                '<tg-emoji emoji-id="5028746137645876535">📈</tg-emoji>'
                f'<b>{round(new_balance, 2)}</b>'
                '</blockquote>\n\n'
                '<blockquote>'
                '<tg-emoji emoji-id="5240369183593615679">💬</tg-emoji>'
                f' {quote}'
                '</blockquote>'
            )
        else:
            new_balance = balance_after_withdraw

            await save_dice_game(
                game, user_id, bet, label, dice_value,
                0.0, 0.0, False, chat_id=message.chat.id,
                idempotency_key=f"{message.chat.id}:{message.message_id}",
            )

            quote = secrets.choice(cfg["quotes_lose"][quote_key])

            text_out = (
                '<tg-emoji emoji-id="5447183459602669338">🔽</tg-emoji>'
                f' <i>{user_link(user)}, вы <b>проиграли</b>: -{round(bet, 2)}'
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></i>\n'
                '<blockquote>'
                f'<s>{balance_before}'
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></s> '
                '<tg-emoji emoji-id="5028325978175177540">📉</tg-emoji>'
                f'<b>{round(new_balance, 2)}</b>'
                '</blockquote>\n\n'
                '<blockquote>'
                '<tg-emoji emoji-id="5240369183593615679">💬</tg-emoji>'
                f' {quote}'
                '</blockquote>'
            )

        try:
            await message.answer(text_out, reply_markup=dice_markup_replay(game))
        except Exception:
            logging.exception("dice result send failed: %s", game)

        DICE_LAST_GAMES[(game, user_id)] = {"bet": bet, "spec": spec}

    task = spawn(finish())
    task.add_done_callback(lambda t, b=bet_id: bet_task_done(t, b))


async def dice_game_launch(message: Message, game: str, bet: float, spec) -> None:
    cfg = DICE_GAMES[game]
    user = message.from_user
    bet = round(bet, 2)

    if bet < cfg["min_bet"]:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(user)}, минимальная ставка {cfg["min_bet"]}'
            '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></i>'
        )
        return

    ok = await try_withdraw(user.id, bet)
    if not ok:
        await message.answer(
            '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
            f'<i>{user_link(user)}, недостаточно средств!</i>'
        )
        return

    await dice_game_start(message, game, bet, spec, user.id, user)


DARTS_USAGE_LINE = "/darts [ставка] [диапазон]"
DARTS_USAGE_RANGES = "Диапазоны: классик, мимо, отскок, красное, белое"

BOWLING_USAGE_LINE = "/bowling [ставка] [диапазон]"
BOWLING_USAGE_RANGES = "Диапазоны: классик, мимо, 1, 3, 4, 5, 6"

CUBE_USAGE_LINE = "/cube [ставка] [диапазон]"
CUBE_USAGE_RANGES = (
    "Диапазоны: классик, чет, нечет, меньше N, больше N, "
    "от 1 до 3 чисел (например: куб 1 2,3)"
)


@router.message(F.text.regexp(r"(?i)^/?(darts|дартс|дс)(\s|$)"))
async def cmd_darts(message: Message, state: FSMContext) -> None:
    await state.clear()

    parts = message.text.strip().lstrip("/").split()
    user = message.from_user

    if len(parts) < 2:
        await message.answer(dice_usage_text(user, DARTS_USAGE_LINE, DARTS_USAGE_RANGES))
        return

    balance = await get_balance(user.id)
    bet, _ = parse_bet_token(parts[1], balance)
    if bet is None:
        await message.answer(dice_usage_text(user, DARTS_USAGE_LINE, DARTS_USAGE_RANGES))
        return

    if len(parts) >= 3:
        player_range = " ".join(parts[2:]).lower()
    else:
        player_range = "классик"

    if player_range not in DARTS_RANGES:
        await message.answer(dice_usage_text(user, DARTS_USAGE_LINE, DARTS_USAGE_RANGES))
        return

    await dice_game_launch(message, "darts", bet, player_range)


@router.message(F.text.regexp(r"(?i)^/?(bowling|боулинг|боул)(\s|$)"))
async def cmd_bowling(message: Message, state: FSMContext) -> None:
    await state.clear()

    parts = message.text.strip().lstrip("/").split()
    user = message.from_user

    if len(parts) < 2:
        await message.answer(dice_usage_text(user, BOWLING_USAGE_LINE, BOWLING_USAGE_RANGES))
        return

    balance = await get_balance(user.id)
    bet, _ = parse_bet_token(parts[1], balance)
    if bet is None:
        await message.answer(dice_usage_text(user, BOWLING_USAGE_LINE, BOWLING_USAGE_RANGES))
        return

    if len(parts) >= 3:
        player_range = " ".join(parts[2:]).lower()
    else:
        player_range = "классик"

    if player_range not in BOWLING_RANGES:
        await message.answer(dice_usage_text(user, BOWLING_USAGE_LINE, BOWLING_USAGE_RANGES))
        return

    await dice_game_launch(message, "bowling", bet, player_range)


@router.message(F.text.regexp(r"(?i)^/?(cubs|cube|cubes|кубы|куб|кубик)(\s|$)"))
async def cmd_cube(message: Message, state: FSMContext) -> None:
    await state.clear()

    parts = message.text.strip().lstrip("/").split()
    user = message.from_user

    if len(parts) < 2:
        await message.answer(dice_usage_text(user, CUBE_USAGE_LINE, CUBE_USAGE_RANGES))
        return

    balance = await get_balance(user.id)
    bet, _ = parse_bet_token(parts[1], balance)
    if bet is None:
        await message.answer(dice_usage_text(user, CUBE_USAGE_LINE, CUBE_USAGE_RANGES))
        return

    tokens = " ".join(parts[2:]).lower().replace("ё", "е").replace(",", " ").split()
    spec = parse_cube_spec(tokens)
    if spec is None:
        await message.answer(dice_usage_text(user, CUBE_USAGE_LINE, CUBE_USAGE_RANGES))
        return

    await dice_game_launch(message, "cube", bet, spec)


@router.callback_query(F.data == "dice_noop")
async def dice_noop(call: CallbackQuery) -> None:
    await call.answer()


@router.callback_query(F.data.startswith("dice_replay_"))
async def dice_replay(call: CallbackQuery) -> None:
    game = call.data.removeprefix("dice_replay_")
    data = DICE_LAST_GAMES.get((game, call.from_user.id))

    if game not in DICE_GAMES or not data:
        await call.answer("Нет предыдущей игры", show_alert=True)
        return

    bet = data["bet"]

    ok = await try_withdraw(call.from_user.id, bet)
    if not ok:
        await call.answer("Недостаточно средств", show_alert=True)
        return

    await call.answer()

    await dice_game_start(
        call.message, game, bet, data["spec"],
        call.from_user.id, call.from_user,
    )


@router.callback_query(F.data.startswith("dice_vabank_"))
async def dice_vabank(call: CallbackQuery) -> None:
    game = call.data.removeprefix("dice_vabank_")
    data = DICE_LAST_GAMES.get((game, call.from_user.id))

    if game not in DICE_GAMES or not data:
        await call.answer("Нет предыдущей игры", show_alert=True)
        return

    balance = round(await get_balance(call.from_user.id), 2)

    if balance < DICE_GAMES[game]["min_bet"]:
        await call.answer("Недостаточно средств", show_alert=True)
        return

    balance = round(balance, 2)
    ok = await try_withdraw(call.from_user.id, balance)
    if not ok:
        await call.answer("Недостаточно средств", show_alert=True)
        return

    await call.answer()

    await dice_game_start(
        call.message, game, balance, data["spec"],
        call.from_user.id, call.from_user,
    )


async def dice_admin_check(message: Message, emoji: str, wait: float) -> None:
    if message.from_user.id != ADMIN_ID:
        return

    dice_msg = await message.answer_dice(emoji=emoji)

    async def report() -> None:
        await asyncio.sleep(wait)
        await message.answer(f"Value: <b>{dice_msg.dice.value}</b>")

    task = spawn(report())
    task.add_done_callback(generic_task_done)


@router.message(F.text.regexp(r"(?i)^/chdr$"))
async def cmd_chdr(message: Message) -> None:
    await dice_admin_check(message, DARTS_DICE_EMOJI, DARTS_WAIT_SECONDS)


@router.message(F.text.regexp(r"(?i)^/chbw$"))
async def cmd_chbw(message: Message) -> None:
    await dice_admin_check(message, BOWLING_DICE_EMOJI, BOWLING_WAIT_SECONDS)


@router.message(F.text.regexp(r"(?i)^/chcb$"))
async def cmd_chcb(message: Message) -> None:
    await dice_admin_check(message, CUBE_DICE_EMOJI, CUBE_WAIT_SECONDS)


TRANSFER_MIN = 0.5
TRANSFER_FEE_PERCENT = 0.10
TRANSFER_WORDS = "дать|нк|send|перевод|передать|пер"

TRANSFER_SLASH_RE = rf"(?i)^/({TRANSFER_WORDS})(@\w+)?(\s|$)"
TRANSFER_PLAIN_RE = (
    rf"(?i)^({TRANSFER_WORDS})\s+.{{0,100}}(@\w|\d|все|всё|пол|банк|вб|хаф)"
)

TRANSFER_USERNAME_RE = re.compile(r"^@[A-Za-z][A-Za-z0-9_]{3,31}$")

TRANSFER_VIP_ADS = [
    '<tg-emoji emoji-id="5044126248029128166">👑</tg-emoji> Хочешь переводить без комиссии? VIP открывает ноль процентов.',
    '<tg-emoji emoji-id="5044126248029128166">👑</tg-emoji> VIP в переводах: никакой комиссии, только чистый перевод.',
    '<tg-emoji emoji-id="5044126248029128166">👑</tg-emoji> Обычные переводы — с комиссией. VIP — без. Почувствуй разницу.',
    '<tg-emoji emoji-id="5044126248029128166">👑</tg-emoji> Твои деньги должны доходить полностью. VIP — без комиссии.',
    '<tg-emoji emoji-id="5044126248029128166">👑</tg-emoji> Забудь о процентах. VIP переводит без комиссии.',
]

USER_SEEN_CACHE: dict = {}


async def init_transfer_tables() -> None:
    async with _db_lock:
        conn = db()
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS usernames ("
            "user_id INTEGER PRIMARY KEY, "
            "username TEXT, "
            "full_name TEXT NOT NULL DEFAULT '', "
            "updated_at TEXT NOT NULL"
            ")"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_usernames_username "
            "ON usernames (username)"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS transfers ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "from_id INTEGER NOT NULL, "
            "to_id INTEGER NOT NULL, "
            "amount REAL NOT NULL, "
            "fee REAL NOT NULL, "
            "received REAL NOT NULL, "
            "created_at TEXT NOT NULL"
            ")"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_transfers_from "
            "ON transfers (from_id)"
        )
        await conn.commit()


async def save_username(user_id: int, username: str | None, full_name: str) -> None:
    async with _db_lock:
        conn = db()
        await conn.execute(
            "INSERT INTO usernames (user_id, username, full_name, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "username = excluded.username, "
            "full_name = excluded.full_name, "
            "updated_at = excluded.updated_at",
            (user_id, username, full_name, now_msk().isoformat()),
        )
        await conn.commit()


async def find_user_by_username(username: str) -> tuple[int, str] | None:
    async with _db_lock:
        async with db().execute(
            "SELECT user_id, full_name FROM usernames "
            "WHERE username = ? ORDER BY updated_at DESC LIMIT 1",
            (username.lower(),),
        ) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return None
    return int(row[0]), str(row[1])


async def transfer_atomic(
    from_id: int,
    to_id: int,
    amount: float,
    fee: float,
    received: float,
) -> bool:
    async with _db_lock:
        conn = db()
        try:
            cursor = await conn.execute(
                "UPDATE balances SET amount = ROUND(amount - ?, 2) "
                "WHERE user_id = ? AND amount + 1e-9 >= ?",
                (amount, from_id, amount),
            )
            if cursor.rowcount != 1:
                await conn.rollback()
                return False

            cursor = await conn.execute(
                "UPDATE balances SET amount = ROUND(amount + ?, 2) WHERE user_id = ?",
                (received, to_id),
            )
            if cursor.rowcount != 1:
                await conn.rollback()
                return False

            await conn.execute(
                "INSERT INTO transfers (from_id, to_id, amount, fee, received, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (from_id, to_id, amount, fee, received, now_msk().isoformat()),
            )
            await conn.commit()
            return True
        except BaseException:
            await conn.rollback()
            raise


class TrackUserMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user = getattr(event, "from_user", None)
        if user is not None and not user.is_bot:
            username = user.username.lower() if user.username else None
            state_key = (username, user.full_name)
            if USER_SEEN_CACHE.get(user.id) != state_key:
                try:
                    await save_username(user.id, username, user.full_name)
                    if len(USER_SEEN_CACHE) > 50000:
                        USER_SEEN_CACHE.clear()
                    USER_SEEN_CACHE[user.id] = state_key
                except Exception:
                    logging.exception("save_username failed for %s", user.id)
        return await handler(event, data)


router.message.outer_middleware(TrackUserMiddleware())
router.callback_query.outer_middleware(TrackUserMiddleware())


def transfer_error_text(user, text: str) -> str:
    return (
        '<tg-emoji emoji-id="5161208387957950108">❌</tg-emoji>'
        f'<i>{user_link(user)}, {text}</i>'
    )


def parse_transfer_tokens(tokens: list[str], has_reply: bool):
    usernames = [t for t in tokens if t.startswith("@")]
    others = [t for t in tokens if not t.startswith("@")]

    if len(others) != 1 or len(usernames) > 1:
        return None

    if usernames:
        if not TRANSFER_USERNAME_RE.match(usernames[0]):
            return None
        return others[0], usernames[0]

    if not has_reply:
        return None

    return others[0], None


@router.message(
    F.text.regexp(TRANSFER_SLASH_RE) | F.text.regexp(TRANSFER_PLAIN_RE)
)
async def cmd_transfer(message: Message, state: FSMContext, bot: Bot) -> None:
    sender = message.from_user
    if sender is None or sender.is_bot:
        return

    text = message.text.strip()
    is_slash = text.startswith("/")
    tokens = text.lstrip("/").split()[1:]

    reply_user = None
    if message.reply_to_message is not None:
        reply_user = message.reply_to_message.from_user

    others = [t for t in tokens if not t.startswith("@")]
    amount_valid = (
        len(others) == 1
        and (
            parse_number(others[0]) is not None
            or others[0].lower() in ALL_IN_ALIASES
            or others[0].lower() in HALF_ALIASES
        )
    )

    parsed = parse_transfer_tokens(tokens, reply_user is not None)

    if parsed is None:
        if is_slash or amount_valid:
            await state.clear()
            await message.answer(
                dice_usage_text(
                    sender,
                    "/send @username [сумма]",
                    "Или ответом на сообщение: дать [сумма]. "
                    "Комиссия 10%, минимум 0.5",
                )
            )
        return

    await state.clear()

    amount_token, username_token = parsed

    balance = await get_balance(sender.id)
    amount, _ = parse_bet_token(amount_token, balance)
    if amount is None or amount <= 0:
        await message.answer(
            dice_usage_text(
                sender,
                "/send @username [сумма]",
                "Или ответом на сообщение: дать [сумма]. "
                "Комиссия 10%, минимум 0.5",
            )
        )
        return

    amount = round(amount, 2)

    if username_token is not None:
        found = await find_user_by_username(username_token[1:])
        if found is None:
            await message.answer(
                transfer_error_text(
                    sender,
                    f"пользователь {username_token} не найден. "
                    "Он должен быть зарегистрирован в боте.",
                )
            )
            return
        target_id, target_name = found
    else:
        if reply_user is None or reply_user.is_bot:
            await message.answer(
                transfer_error_text(sender, "нельзя переводить ботам.")
            )
            return
        target_id, target_name = reply_user.id, reply_user.full_name

    if target_id == sender.id:
        await message.answer(
            transfer_error_text(sender, "нельзя переводить самому себе.")
        )
        return

    if amount < TRANSFER_MIN:
        await message.answer(
            transfer_error_text(
                sender,
                f"минимальная сумма перевода — {TRANSFER_MIN}"
                '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>',
            )
        )
        return

    if not await is_registered(target_id):
        await message.answer(
            transfer_error_text(
                sender,
                "получатель не зарегистрирован в боте.",
            )
        )
        return

    fee = round(amount * TRANSFER_FEE_PERCENT, 2)
    received = round(amount - fee, 2)

    ok = await transfer_atomic(sender.id, target_id, amount, fee, received)
    if not ok:
        await message.answer(transfer_error_text(sender, "недостаточно средств!"))
        return

    target = SimpleNamespace(id=target_id, full_name=target_name)

    sender_text = (
        '<tg-emoji emoji-id="5226794552907554474">🔁</tg-emoji>'
        f' {user_link(sender)}, <i>вы <b>успешно совершили перевод</b> в размере {received}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
        f' пользователю {user_link(target)}</i>\n'
        '<blockquote>'
        '<tg-emoji emoji-id="5224295096689651881">💯</tg-emoji>'
        f' Комиссия составила: {fee}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
        '</blockquote>\n\n'
        f'<blockquote>{secrets.choice(TRANSFER_VIP_ADS)}</blockquote>'
    )

    try:
        await message.answer(sender_text)
    except Exception:
        logging.exception("transfer sender message failed")

    receiver_text = (
        '<tg-emoji emoji-id="5226794552907554474">🔁</tg-emoji>'
        f'<i> {user_link(sender)} перевел на ваш баланс {received}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></i>\n\n'
        f'<blockquote>{secrets.choice(TRANSFER_VIP_ADS)}</blockquote>'
    )

    try:
        await bot.send_message(target_id, receiver_text)
    except Exception:
        logging.exception("transfer receiver message failed: %s", target_id)


class UpdateLogMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        global LAST_UPDATE_AT
        LAST_UPDATE_AT = time.time()
        try:
            logging.info("update %s: %s", event.update_id, describe_update(event))
        except Exception:
            logging.exception("update log failed")
        return await handler(event, data)


def describe_update(update) -> str:
    message = getattr(update, "message", None)
    if message is not None:
        text = (message.text or message.caption or "")[:40].replace("\n", " ")
        user_id = message.from_user.id if message.from_user else None
        return f"message chat={message.chat.id} user={user_id} text={text!r}"

    callback = getattr(update, "callback_query", None)
    if callback is not None:
        return f"callback user={callback.from_user.id} data={callback.data!r}"

    pre_checkout = getattr(update, "pre_checkout_query", None)
    if pre_checkout is not None:
        return f"pre_checkout user={pre_checkout.from_user.id}"

    return "other"


async def on_error(event) -> bool:
    logging.error("Handler error: %r", event.exception, exc_info=event.exception)
    try:
        callback = event.update.callback_query
        if callback is not None:
            await callback.answer("Произошла ошибка, попробуйте ещё раз.", show_alert=True)
    except Exception:
        pass
    return True


async def db_ping() -> float:
    started = time.monotonic()
    async with _db_lock:
        async with db().execute("SELECT 1") as cursor:
            await cursor.fetchone()
    return (time.monotonic() - started) * 1000


async def collect_health() -> dict:
    db_ok = True
    db_ms = None
    try:
        db_ms = round(await asyncio.wait_for(db_ping(), timeout=3), 2)
    except Exception:
        db_ok = False

    now = time.time()
    return {
        "status": "ok" if db_ok else "degraded",
        "db_ok": db_ok,
        "db_ms": db_ms,
        "uptime_s": int(now - START_TIME),
        "loop_lag_s": round(LOOP_LAG, 2),
        "last_update_age_s": int(now - LAST_UPDATE_AT) if LAST_UPDATE_AT else None,
        "pending_bets": len(PENDING_BETS),
        "mines_games": len(MINES_GAMES),
        "tasks": len(asyncio.all_tasks()),
        "registered_cached": len(REGISTERED_CACHE),
    }


@router.message(F.text.regexp(r"(?i)^/health(@\w+)?$"))
async def cmd_health(message: Message, bot: Bot) -> None:
    if message.from_user is None or message.from_user.id != ADMIN_ID:
        return
    info = await collect_health()
    try:
        wh = await bot.get_webhook_info()
        wh_url = html_escape(wh.url or "-")
        wh_pending = wh.pending_update_count
        wh_err = html_escape(wh.last_error_message or "-")
    except Exception:
        wh_url, wh_pending, wh_err = "?", "?", "?"
    age = info["last_update_age_s"]
    await message.answer(
        f"{'🟢' if info['db_ok'] else '🔴'} <b>{info['status']}</b>\n"
        f"uptime: {format_delta(timedelta(seconds=info['uptime_s']))}\n"
        f"db: {info['db_ms']} ms\n"
        f"loop lag: {info['loop_lag_s']}s\n"
        f"last update: {'-' if age is None else str(age) + 's ago'}\n"
        f"tasks: {info['tasks']} | bets: {info['pending_bets']} | mines: {info['mines_games']}\n"
        f"webhook: <code>{wh_url}</code>\n"
        f"pending: {wh_pending}\n"
        f"last error: {wh_err}"
    )


@router.message(F.text.regexp(r"(?i)^/ping(@\w+)?$"))
async def cmd_ping(message: Message, bot: Bot) -> None:
    if message.from_user is not None and message.from_user.id == ADMIN_ID:
        info = await bot.get_webhook_info()
        await message.answer(
            "🏓 pong\n"
            f"webhook: <code>{html_escape(info.url or '-')}</code>\n"
            f"pending: {info.pending_update_count}\n"
            f"last error: {html_escape(info.last_error_message or '-')}"
        )
        return
    await message.answer("🏓 pong")


WELCOME_IMAGE_URL = "https://iili.io/o9YT4qX.md.png"
TELEGRAM_CHAT_STARTGROUP_URL = "https://t.me/{bot}?startgroup=chat_earn&admin=manage_chat"


def telegram_home_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Заработать на чате", callback_data="tg_menu:earn", icon_custom_emoji_id="5472270097290634771", style="success")],
        [InlineKeyboardButton(text="Профиль", callback_data="tg_menu:profile", icon_custom_emoji_id="5258011929993026890"), InlineKeyboardButton(text="Бонусы", callback_data="get_bonus", icon_custom_emoji_id="5307603391919204061")],
        [InlineKeyboardButton(text="Топ", callback_data="tg_menu:top", icon_custom_emoji_id="5312462735097764089"), InlineKeyboardButton(text="Реф. программа", callback_data="tg_menu:referral", icon_custom_emoji_id="5258513401784573443")],
        [InlineKeyboardButton(text="Хочу своё казино", callback_data="tg_menu:casino")],
    ])


def telegram_back_markup(callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Назад", callback_data=callback)]])


def telegram_earn_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Добавить в чат", url=TELEGRAM_CHAT_STARTGROUP_URL.format(bot=BOT_USERNAME), icon_custom_emoji_id="5471930335312747865", style="success")],
        [InlineKeyboardButton(text="Назад", callback_data="tg_menu:home")],
    ])


def telegram_profile_markup(language: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пополнить", callback_data="balance_topup", icon_custom_emoji_id="4988289890769699938", style="success"), InlineKeyboardButton(text="Вывести", callback_data="balance_withdraw", icon_custom_emoji_id="4983748881977181112", style="success")],
        [InlineKeyboardButton(text="Транзакции", callback_data="tg_menu:transactions", icon_custom_emoji_id="5258260149037965799")],
        [InlineKeyboardButton(text="Настройки", callback_data="tg_menu:settings", icon_custom_emoji_id="5258096772776991776")],
        [InlineKeyboardButton(text="Русский", callback_data="tg_language:ru", icon_custom_emoji_id="5449408995691341691", style="success" if language == "ru" else "primary"), InlineKeyboardButton(text="English", callback_data="tg_language:en", icon_custom_emoji_id="5202021044105257611", style="success" if language == "en" else "primary")],
        [InlineKeyboardButton(text="Назад", callback_data="tg_menu:home")],
    ])


def telegram_settings_markup(mode: str, has_nickname: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Имя Telegram", callback_data="tg_privacy:username", style="success" if mode == "username" else "primary"), InlineKeyboardButton(text="Анонимность", callback_data="tg_privacy:hidden", style="success" if mode == "hidden" else "primary")],
        [InlineKeyboardButton(text="Никнейм", callback_data="tg_privacy:nickname", style="success" if mode == "nickname" else "primary"), InlineKeyboardButton(text="Добавить никнейм" if not has_nickname else "Изменить никнейм", callback_data="tg_settings:nickname")],
        [InlineKeyboardButton(text="Назад", callback_data="tg_menu:profile")],
    ])


def telegram_transactions_markup(kind: str, page: int, total_pages: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пополнения", callback_data="tg_tx:deposit:1", icon_custom_emoji_id="5327847754628609325", style="success" if kind == "deposit" else "primary"), InlineKeyboardButton(text="Выводы", callback_data="tg_tx:withdrawal:1", icon_custom_emoji_id="5330502087367212278", style="success" if kind == "withdrawal" else "primary")],
        [InlineKeyboardButton(text="Все операции", callback_data="tg_tx:all:1", icon_custom_emoji_id="5427009714745517609", style="success" if kind == "all" else "primary")],
        [InlineKeyboardButton(text=f"‹ {max(1, page - 1)}", callback_data=f"tg_tx:{kind}:{max(1, page - 1)}", icon_custom_emoji_id="5328091751720694986"), InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="tg_tx:noop"), InlineKeyboardButton(text=f"{min(total_pages, page + 1)} ›", callback_data=f"tg_tx:{kind}:{min(total_pages, page + 1)}", icon_custom_emoji_id="5328281486195964510")],
        [InlineKeyboardButton(text="Назад", callback_data="tg_menu:profile")],
    ])


def _format_stars(value) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _format_profile_date(value: str | None) -> str:
    if not value:
        return "неизвестна"
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=MSK)
        else:
            parsed = parsed.astimezone(MSK)
        return parsed.strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return "неизвестна"


async def telegram_profile_overview(user_id: int) -> dict:
    async with _db_lock:
        conn = db()
        async with conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cursor:
            tables = {row[0] for row in await cursor.fetchall()}
        async with conn.execute("SELECT amount,created_at FROM balances WHERE user_id=?", (user_id,)) as cursor:
            balance_row = await cursor.fetchone()
        turnover_cents = 0
        if _wallet_backend is not None and hasattr(_wallet_backend, "leaderboard_events") and "webapp_rounds" in tables:
            events, _names = await _wallet_backend.leaderboard_events(conn)
            async with conn.execute("SELECT COALESCE(SUM(bet_cents),0) FROM (" + events + ") WHERE user_id=?", (user_id,)) as cursor:
                turnover_cents = (await cursor.fetchone())[0]
        else:
            sources = []
            for table in ("crash_games", "mines_history", "football_history", "basketball_history", "slot_history", "dice_history"):
                if table in tables:
                    sources.append(f"SELECT CAST(ROUND(bet*100) AS INTEGER) AS cents FROM {table} WHERE user_id=?")
            if "webapp_rounds" in tables:
                sources.append("SELECT bet_cents AS cents FROM webapp_rounds WHERE user_id=?")
            if sources:
                async with conn.execute("SELECT COALESCE(SUM(cents),0) FROM (" + " UNION ALL ".join(sources) + ")", [user_id] * len(sources)) as cursor:
                    turnover_cents = (await cursor.fetchone())[0]
        async def sum_query(sql, args):
            async with conn.execute(sql, args) as cursor:
                row = await cursor.fetchone()
            return row[0] or 0
        bonuses_cents = await sum_query("SELECT COALESCE(SUM(amount_cents),0) FROM webapp_wallet_events WHERE user_id=? AND kind='bonus'", (user_id,)) if "webapp_wallet_events" in tables else 0
        deposits_cents = (await sum_query("SELECT COALESCE(SUM(amount),0)*100 FROM payments WHERE user_id=?", (user_id,)) if "payments" in tables else 0)
        if "webapp_deposits" in tables:
            # Stars orders also have a row in payments for Telegram charge
            # reconciliation; count their webapp_deposits row only once.
            deposits_cents = (await sum_query("SELECT COALESCE(SUM(amount),0)*100 FROM payments WHERE user_id=?", (user_id,)) if "payments" in tables else 0)
            deposits_cents += await sum_query("SELECT COALESCE(SUM(stars_cents),0) FROM webapp_deposits WHERE user_id=? AND provider!='stars' AND status='paid'", (user_id,))
        withdrawals_cents = (await sum_query("SELECT CAST(ROUND(COALESCE(SUM(amount),0)*100) AS INTEGER) FROM withdrawals WHERE user_id=? AND status='approved'", (user_id,)) if "withdrawals" in tables else 0)
        if "webapp_star_withdrawals" in tables:
            withdrawals_cents += await sum_query("SELECT COALESCE(SUM(quantity),0)*100 FROM webapp_star_withdrawals WHERE user_id=? AND state='completed'", (user_id,))
    return {
        "balance": float(balance_row[0]) if balance_row else 0.0,
        "created_at": balance_row[1] if balance_row else None,
        "turnover": turnover_cents / 100,
        "bonuses": bonuses_cents / 100,
        "deposits": deposits_cents / 100,
        "withdrawals": withdrawals_cents / 100,
    }


def telegram_profile_text(user, stats: dict) -> str:
    username = "@" + user.username if getattr(user, "username", None) else "нет"
    star = '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
    return (
        '<tg-emoji emoji-id="5316727448644103237">👤</tg-emoji> <b>Профиль</b>\n\n'
        f'<tg-emoji emoji-id="5316727448644103237">👤</tg-emoji> Имя: {user_link(user)} · {html_escape(username)}\n'
        f'<tg-emoji emoji-id="5258503720928288433">🆔</tg-emoji> ID: <code>{user.id}</code>\n'
        f'<tg-emoji emoji-id="5258258882022612173">📅</tg-emoji> Дата регистрации: {_format_profile_date(stats["created_at"])}\n'
        f'<tg-emoji emoji-id="5258204546391351475">💰</tg-emoji> Баланс: <b>{_format_stars(stats["balance"])}{star}</b>\n'
        f'<tg-emoji emoji-id="5258330865674494479">📈</tg-emoji> Оборот: {_format_stars(stats["turnover"])}{star}\n'
        f'<tg-emoji emoji-id="5834781387365818180">🎁</tg-emoji> Выданные бонусы: {_format_stars(stats["bonuses"])}{star}\n'
        f'<tg-emoji emoji-id="5258336354642697821">📥</tg-emoji> Пополнения: {_format_stars(stats["deposits"])}{star}\n'
        f'<tg-emoji emoji-id="5258043150110301407">📤</tg-emoji> Выводы: {_format_stars(stats["withdrawals"])}{star}'
    )


async def get_telegram_transactions(user_id: int, kind: str, page: int, page_size: int = 5) -> tuple[list[dict], int]:
    async with _db_lock:
        conn = db()
        async with conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cursor:
            tables = {row[0] for row in await cursor.fetchall()}
        sources = []
        if "payments" in tables:
            linked_payment_filter = " AND charge_id NOT IN (SELECT provider_id FROM webapp_deposits WHERE provider_id IS NOT NULL)" if "webapp_deposits" in tables else ""
            sources.append("SELECT 'deposit' AS kind,CAST(amount*100 AS INTEGER) AS amount_cents,created_at,'telegram:'||charge_id AS source FROM payments WHERE user_id=?" + linked_payment_filter)
        if "webapp_deposits" in tables:
            async with conn.execute("PRAGMA table_info(webapp_deposits)") as cursor:
                columns = {row[1] for row in await cursor.fetchall()}
            created = "COALESCE(paid_at,created_at)" if "paid_at" in columns else "created_at"
            sources.append(f"SELECT 'deposit',stars_cents,{created},'webapp:'||id FROM webapp_deposits WHERE user_id=? AND status='paid'")
        if "withdrawals" in tables:
            sources.append("SELECT 'withdrawal',CAST(ROUND(amount*100) AS INTEGER),created_at,'withdrawal:'||id FROM withdrawals WHERE user_id=? AND status='approved'")
        if "webapp_star_withdrawals" in tables:
            sources.append("SELECT 'withdrawal',quantity*100,updated_at,'star_withdrawal:'||id FROM webapp_star_withdrawals WHERE user_id=? AND state='completed'")
        if not sources:
            return [], 1
        union = " UNION ALL ".join(sources)
        where = "" if kind == "all" else " WHERE kind=?"
        args = [user_id] * len(sources) + ([] if kind == "all" else [kind])
        async with conn.execute("SELECT COUNT(*) FROM (" + union + ")" + where, args) as cursor:
            total = (await cursor.fetchone())[0]
        pages = max(1, (total + page_size - 1) // page_size)
        page = max(1, min(page, pages))
        sql = "SELECT kind,amount_cents,created_at,source FROM (" + union + ")" + where + " ORDER BY julianday(created_at) DESC,source DESC LIMIT ? OFFSET ?"
        async with conn.execute(sql, args + [page_size, (page - 1) * page_size]) as cursor:
            rows = await cursor.fetchall()
    return ([{"kind": row[0], "amount_cents": row[1], "created_at": row[2], "source": row[3]} for row in rows], pages)


def _format_transaction_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=MSK)
        else:
            parsed = parsed.astimezone(MSK)
        return parsed.strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return "—"


def telegram_transactions_text(records: list[dict], kind: str, page: int, total_pages: int) -> str:
    text = '<tg-emoji emoji-id="5444856076954520455">🧾</tg-emoji> <b>Транзакции</b>\n\n'
    if not records:
        text += "Нет операций для выбранного фильтра."
    else:
        for record in records:
            is_deposit = record["kind"] == "deposit"
            icon = "5327847754628609325" if is_deposit else "5330502087367212278"
            fallback = "📥" if is_deposit else "📤"
            label = "Пополнение" if is_deposit else "Вывод"
            sign = "+" if is_deposit else "−"
            text += f'<tg-emoji emoji-id="{icon}">{fallback}</tg-emoji> {label}: <b>{sign}{_format_stars(record["amount_cents"] / 100)}<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji></b> · {_format_transaction_date(record["created_at"])}\n'
    return text.rstrip()


async def telegram_settings_data(user_id: int, user=None) -> dict:
    async with _db_lock:
        conn = db()
        row = await conn.execute("INSERT OR IGNORE INTO webapp_privacy(user_id,game_uid) VALUES (?,?)", (user_id, secrets.token_hex(6).upper()))
        await conn.commit()
        async with conn.execute("SELECT mode,nickname,hidden,clickable,game_uid FROM webapp_privacy WHERE user_id=?", (user_id,)) as cursor:
            values = await cursor.fetchone()
        if user is not None:
            name = " ".join(part for part in (getattr(user, "first_name", ""), getattr(user, "last_name", "")) if part)
            await conn.execute("INSERT INTO usernames(user_id,username,full_name,updated_at) VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,full_name=excluded.full_name,updated_at=excluded.updated_at WHERE usernames.username IS NOT excluded.username OR usernames.full_name != excluded.full_name", (user_id, getattr(user, "username", None), name, now_msk().isoformat()))
            await conn.commit()
            TELEGRAM_NAMES[user_id] = getattr(user, "username", None)
    mode, nickname, hidden, clickable, game_uid = values
    PRIVACY_CACHE[user_id] = (mode, nickname, hidden, clickable, game_uid)
    return {"mode": mode, "nickname": nickname, "hidden": bool(hidden), "clickable": bool(clickable), "game_uid": game_uid}


async def update_telegram_display_mode(user_id: int, user, mode: str) -> None:
    if mode not in {"username", "hidden", "nickname"}:
        raise ValueError("Unknown display mode")
    async with _db_lock:
        conn = db()
        await conn.execute("INSERT OR IGNORE INTO webapp_privacy(user_id,game_uid) VALUES (?,?)", (user_id, secrets.token_hex(6).upper()))
        if mode == "nickname":
            async with conn.execute("SELECT nickname FROM webapp_privacy WHERE user_id=?", (user_id,)) as cursor:
                row = await cursor.fetchone()
            if not row or not row[0]:
                raise ValueError("nickname_required")
        await conn.execute("UPDATE webapp_privacy SET mode=? WHERE user_id=?", (mode, user_id))
        await conn.commit()
        async with conn.execute("SELECT mode,nickname,hidden,clickable,game_uid FROM webapp_privacy WHERE user_id=?", (user_id,)) as cursor:
            state = await cursor.fetchone()
    PRIVACY_CACHE[user_id] = tuple(state)
    TELEGRAM_NAMES[user_id] = getattr(user, "username", None)


async def save_telegram_nickname(user_id: int, user, nickname: str) -> None:
    async with _db_lock:
        conn = db()
        await conn.execute("INSERT OR IGNORE INTO webapp_privacy(user_id,game_uid) VALUES (?,?)", (user_id, secrets.token_hex(6).upper()))
        await conn.execute("UPDATE webapp_privacy SET nickname=?,mode='nickname' WHERE user_id=?", (nickname, user_id))
        await conn.commit()
        async with conn.execute("SELECT mode,nickname,hidden,clickable,game_uid FROM webapp_privacy WHERE user_id=?", (user_id,)) as cursor:
            state = await cursor.fetchone()
    PRIVACY_CACHE[user_id] = tuple(state)
    TELEGRAM_NAMES[user_id] = getattr(user, "username", None)


async def send_telegram_welcome(message: Message, user) -> None:
    language = await get_telegram_language(user.id)
    fallback_name = "friend" if language == "en" else "друг"
    first_name = html_escape(getattr(user, "first_name", "") or getattr(user, "username", None) or fallback_name)
    hello = f'<tg-emoji emoji-id="5424972470023104089">🔥</tg-emoji> <b>Привет, <a href="tg://user?id={user.id}">{first_name}</a>!</b>'
    await message.answer_photo(photo=WELCOME_IMAGE_URL, caption=translate_telegram_text(hello, language))
    announcement = (
        '<tg-emoji emoji-id="5096289879969498182">✨</tg-emoji> '
        '<b>Канал обновлений: <a href="https://t.me/mjrstars">t.me/mjrstars</a></b>\n\n'
        '<tg-emoji emoji-id="5012808218385058363">🎮</tg-emoji> '
        '<b>Мы обновили MajorStars!</b> Теперь в боте удобнее следить за профилем, балансом и операциями.\n\n'
        '<blockquote><tg-emoji emoji-id="5021646904597939582">💫</tg-emoji> '
        '«Большие победы начинаются с одного шага».</blockquote>'
    )
    await message.answer(translate_telegram_text(announcement, language), reply_markup=telegram_home_markup())


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: Message, bot: Bot, state: FSMContext) -> None:
    await state.clear()

    text = message.text or ""
    args = text.split(maxsplit=1)[1] if " " in text else ""

    if args.startswith("ref_"):
        try:
            referrer_id = int(args.split("_", 1)[1])
        except ValueError:
            referrer_id = 0

        if referrer_id and referrer_id != message.from_user.id:
            if (
                await get_referral(message.from_user.id) is None
                and not await is_registered(message.from_user.id)
            ):
                await save_pending_referral(
                    message.from_user.id,
                    referrer_id,
                )

    if not await is_subscribed(bot, message.from_user.id):
        await message.answer(
            '<tg-emoji emoji-id="5228947933545635555">😫</tg-emoji>'
            f'<b>{user_link(message.from_user)}, вы не подписаны на обязательные каналы!</b>',
            reply_markup=check_markup(),
        )
        return

    pending_referrer = await get_pending_referral(message.from_user.id)
    if pending_referrer:
        await add_referral(
            message.from_user.id,
            pending_referrer,
            bool(message.from_user.is_premium),
        )
        await delete_pending_referral(message.from_user.id)

    await try_pay_referral_signup(
        message.from_user.id,
        message.from_user,
        bot,
    )

    if args == "toreplenish":
        await message.answer(
            '<b><tg-emoji emoji-id="5053473385355412667">⭐️</tg-emoji> Пополнение</b>\n\n'
            '<i><b>Выберите</b> или <b>введите</b> сумму пополнения в '
            '<tg-emoji emoji-id="5030538831225422917">⬆️</tg-emoji></i>',
            reply_markup=topup_markup(),
        )
        return

    if args == "withdraw":
        async def send(text: str, reply_markup=None) -> None:
            await message.answer(text, reply_markup=reply_markup)

        ok = await show_withdraw_menu(message.from_user.id, message.from_user, send)
        if ok:
            await state.set_state(WithdrawStates.waiting_amount)
        else:
            await state.clear()
        return

    await add_balance(message.from_user.id, 0.0)
    await save_username(
        message.from_user.id,
        message.from_user.username,
        " ".join(part for part in (message.from_user.first_name, message.from_user.last_name) if part),
    )
    await send_telegram_welcome(message, message.from_user)


@router.callback_query(F.data == "check_sub")
async def on_check_sub(call: CallbackQuery, bot: Bot) -> None:
    if not await is_subscribed(bot, call.from_user.id):
        await call.message.edit_text(
            '<tg-emoji emoji-id="5447644880824181073">⚠️</tg-emoji>'
            f'<b>{user_link(call.from_user)}, вы всё ещё не подписаны!</b>',
            reply_markup=check_markup(),
        )
        await call.answer()
        return

    pending_referrer = await get_pending_referral(call.from_user.id)
    if pending_referrer:
        await add_referral(
            call.from_user.id,
            pending_referrer,
            bool(call.from_user.is_premium),
        )
        await delete_pending_referral(call.from_user.id)

    await add_balance(call.from_user.id, 0.0)
    await try_pay_referral_signup(
        call.from_user.id,
        call.from_user,
        bot,
    )
    await call.message.delete()
    await call.answer()
    await save_username(
        call.from_user.id,
        call.from_user.username,
        " ".join(part for part in (call.from_user.first_name, call.from_user.last_name) if part),
    )
    await send_telegram_welcome(call.message, call.from_user)


@router.message(F.new_chat_members, F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
async def telegram_group_new_members(message: Message, bot: Bot) -> None:
    members = message.new_chat_members or []
    if members:
        await record_telegram_group_members(bot, message.chat.id, message.chat.title or "", members)


@router.chat_member()
async def telegram_chat_member_update(event, bot: Bot) -> None:
    if event.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    member = event.new_chat_member
    if member.status in {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}:
        return
    user = member.user
    if getattr(user, "is_bot", False):
        return
    await record_telegram_group_members(bot, event.chat.id, event.chat.title or "", [user])


@router.my_chat_member()
async def telegram_bot_chat_membership_update(event, bot: Bot) -> None:
    if event.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        return
    status = event.new_chat_member.status
    if status in {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR}:
        await refresh_telegram_group_owner(bot, event.chat.id, event.chat.title or "")


def telegram_earn_text() -> str:
    return (
        '<tg-emoji emoji-id="5472270097290634771">💬</tg-emoji> <b>Заработок на чате</b>\n\n'
        'Добавьте бота администратором. Участники, вступившие в чат, автоматически связываются с его владельцем. '
        'Владелец получает 50% чистых проигрышей по ставкам, сделанным именно в этом чате.'
    )


def telegram_settings_text(settings: dict) -> str:
    current = {"username": "Имя Telegram", "hidden": "Анонимность", "nickname": "Никнейм"}.get(settings["mode"], "Имя Telegram")
    return (
        '<tg-emoji emoji-id="5258096772776991776">⚙️</tg-emoji> <b>Настройки</b>\n\n'
        f'Отображаемое имя в топе: <b>{current}</b>.\n'
        'По умолчанию используется имя Telegram. Режим «Анонимность» показывает в рейтинге имя «Аноним».'
    )


async def show_telegram_profile(message: Message, user) -> None:
    await save_username(user.id, user.username, " ".join(part for part in (user.first_name, user.last_name) if part))
    await telegram_settings_data(user.id, user)
    stats = await telegram_profile_overview(user.id)
    language = await get_telegram_language(user.id)
    await message.edit_text(translate_telegram_text(telegram_profile_text(user, stats), language), reply_markup=telegram_profile_markup(language))


async def show_telegram_settings(message: Message, user) -> None:
    settings = await telegram_settings_data(user.id, user)
    language = await get_telegram_language(user.id)
    text = translate_telegram_text(telegram_settings_text(settings), language)
    await message.edit_text(text, reply_markup=telegram_settings_markup(settings["mode"], bool(settings["nickname"])))


async def show_telegram_transactions(message: Message, user, kind: str = "all", page: int = 1) -> None:
    if kind not in {"all", "deposit", "withdrawal"}:
        kind = "all"
    records, pages = await get_telegram_transactions(user.id, kind, page)
    page = max(1, min(page, pages))
    language = await get_telegram_language(user.id)
    text = translate_telegram_text(telegram_transactions_text(records, kind, page, pages), language)
    await message.edit_text(text, reply_markup=telegram_transactions_markup(kind, page, pages))


@router.callback_query(F.data == "tg_menu:home")
async def telegram_home_callback(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.edit_text('<b>Выберите раздел MajorStars:</b>', reply_markup=telegram_home_markup())


@router.callback_query(F.data == "tg_menu:earn")
async def telegram_earn_callback(call: CallbackQuery) -> None:
    await call.answer()
    language = await get_telegram_language(call.from_user.id)
    await call.message.edit_text(translate_telegram_text(telegram_earn_text(), language), reply_markup=telegram_earn_markup())


@router.callback_query(F.data == "tg_menu:profile")
async def telegram_profile_callback(call: CallbackQuery) -> None:
    await call.answer()
    await show_telegram_profile(call.message, call.from_user)


@router.callback_query(F.data == "tg_menu:referral")
async def telegram_referral_callback(call: CallbackQuery) -> None:
    user_id = call.from_user.id
    data = await get_ref_data(user_id)
    active = not await is_ref_frozen(user_id)
    markup = ref_markup(user_id)
    markup = markup.model_copy(update={"inline_keyboard": [*markup.inline_keyboard, [InlineKeyboardButton(text="Назад", callback_data="tg_menu:home")]]})
    await answer_referral(call.message, referral_text(user_id, data, active), markup)
    await call.answer()


@router.callback_query(F.data == "tg_menu:settings")
async def telegram_settings_callback(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.answer()
    await show_telegram_settings(call.message, call.from_user)


@router.callback_query(F.data == "tg_menu:transactions")
async def telegram_transactions_callback(call: CallbackQuery) -> None:
    await call.answer()
    await show_telegram_transactions(call.message, call.from_user)


@router.callback_query(F.data.startswith("tg_tx:"))
async def telegram_transactions_page_callback(call: CallbackQuery) -> None:
    parts = call.data.split(":")
    if len(parts) != 3:
        await call.answer()
        return
    if parts[1] == "noop":
        await call.answer()
        return
    try:
        page = int(parts[2])
    except ValueError:
        await call.answer()
        return
    if page < 1 or page > 1_000_000:
        await call.answer()
        return
    await call.answer()
    await show_telegram_transactions(call.message, call.from_user, parts[1], page)


@router.callback_query(F.data.startswith("tg_language:"))
async def telegram_language_callback(call: CallbackQuery) -> None:
    language = call.data.partition(":")[2]
    if language not in {"ru", "en"}:
        await call.answer()
        return
    await set_telegram_language(call.from_user.id, language)
    await call.answer()
    await show_telegram_profile(call.message, call.from_user)


@router.callback_query(F.data.startswith("tg_privacy:"))
async def telegram_privacy_callback(call: CallbackQuery, state: FSMContext) -> None:
    mode = call.data.partition(":")[2]
    if mode not in {"username", "hidden", "nickname"}:
        await call.answer()
        return
    try:
        await update_telegram_display_mode(call.from_user.id, call.from_user, mode)
    except ValueError as error:
        if str(error) == "nickname_required":
            await state.set_state(TelegramProfileStates.waiting_nickname)
            language = await get_telegram_language(call.from_user.id)
            prompt = translate_telegram_text("Сначала добавьте никнейм.", language) + " " + translate_telegram_text("Отправьте новый псевдоним одним сообщением. Для отмены нажмите «Назад».", language)
            await call.answer()
            await call.message.answer(prompt, reply_markup=telegram_back_markup("tg_menu:settings"))
            return
        raise
    await call.answer()
    await show_telegram_settings(call.message, call.from_user)


@router.callback_query(F.data == "tg_settings:nickname")
async def telegram_add_nickname_callback(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(TelegramProfileStates.waiting_nickname)
    language = await get_telegram_language(call.from_user.id)
    prompt = translate_telegram_text("Отправьте новый псевдоним одним сообщением. Для отмены нажмите «Назад».", language)
    await call.answer()
    await call.message.answer(prompt, reply_markup=telegram_back_markup("tg_menu:settings"))


@router.message(TelegramProfileStates.waiting_nickname, F.chat.type == ChatType.PRIVATE, F.text)
async def telegram_nickname_message(message: Message, state: FSMContext) -> None:
    nickname = (message.text or "").strip()
    language = await get_telegram_language(message.from_user.id)
    if not re.fullmatch(r"[\w]{3,20}", nickname, flags=re.UNICODE):
        text = translate_telegram_text("Псевдоним должен содержать от 3 до 20 букв, цифр или знаков подчёркивания.", language)
        await message.answer(text, reply_markup=telegram_back_markup("tg_menu:settings"))
        return
    await save_telegram_nickname(message.from_user.id, message.from_user, nickname)
    await state.clear()
    settings = await telegram_settings_data(message.from_user.id, message.from_user)
    text = translate_telegram_text("Псевдоним сохранён.", language) + "\n\n" + translate_telegram_text(telegram_settings_text(settings), language)
    await message.answer(text, reply_markup=telegram_settings_markup(settings["mode"], bool(settings["nickname"])))


@router.callback_query(F.data.in_({"tg_menu:top", "tg_menu:casino"}))
async def telegram_unimplemented_menu_callback(call: CallbackQuery) -> None:
    # Reuse the existing generic "soon" response instead of inventing new actions.
    await call.answer()
    await call.message.answer(soon_text(), reply_markup=soon_markup())


@router.message(
    F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}),
    F.text,
)
async def group_unregistered(message: Message, bot: Bot) -> None:
    if message.from_user is None:
        return
    if message.from_user.is_bot:
        return
    if message.sender_chat is not None:
        return
    if message.forward_origin is not None:
        return
    if message.text.startswith("/"):
        return
    if await is_registered(message.from_user.id):
        return
    if await was_notified(message.from_user.id):
        return

    me = await bot.me()
    try:
        await message.reply(
            '<b><tg-emoji emoji-id="5370588928401218156">😶</tg-emoji>Ты не зарегистрирован!</b>',
            reply_markup=register_markup(me.username),
        )
    except Exception:
        logging.exception(
            "Failed to notify unregistered user %s",
            message.from_user.id,
        )
        return

    await mark_notified(message.from_user.id)


@router.message(F.chat.type == ChatType.PRIVATE)
async def any_message(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(soon_text(), reply_markup=soon_markup())


async def on_startup(bot: Bot) -> None:
    global _backup_task, _maint_task

    asyncio.get_running_loop().set_exception_handler(loop_exception_handler)

    await db_init()
    await init_db()
    await init_dice_history()
    await init_transfer_tables()

    _backup_task = spawn(backup_loop())
    _maint_task = spawn(maintenance_loop())
    threading.Thread(target=_thread_watchdog, name="watchdog", daemon=True).start()

    me = await bot.get_me()
    logging.info("Bot: @%s (id=%s)", me.username, me.id)
    if me.username and me.username.lower() != BOT_USERNAME.lower():
        logging.warning(
            "BOT_USERNAME=%s does not match the real bot @%s",
            BOT_USERNAME, me.username,
        )

    webhook_url = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
    await bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=["message", "callback_query", "pre_checkout_query", "inline_query", "chat_member", "my_chat_member"],
        drop_pending_updates=False,
    )

    info = await bot.get_webhook_info()
    logging.info(
        "Webhook set: url=%s pending=%s last_error=%s",
        info.url, info.pending_update_count, info.last_error_message,
    )

    try:
        await bot.send_message(
            ADMIN_ID,
            "✅ Бот запущен\n"
            f"webhook: <code>{html_escape(info.url or '-')}</code>\n"
            f"last error: {html_escape(info.last_error_message or '-')}",
        )
    except Exception:
        logging.exception("Cannot notify admin about startup")


async def on_shutdown(bot: Bot) -> None:
    global _backup_task, _maint_task

    if _maint_task is not None and not _maint_task.done():
        _maint_task.cancel()
        try:
            await _maint_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logging.exception("maintenance task crashed during shutdown")
        _maint_task = None

    try:
        await refund_pending_bets()
        await refund_open_mines()
    except Exception:
        logging.exception("refund on shutdown failed")

    if _backup_task is not None and not _backup_task.done():
        _backup_task.cancel()
        try:
            await _backup_task
        except asyncio.CancelledError:
            pass
        except Exception:
            logging.exception("backup task crashed during shutdown")
        _backup_task = None

    await db_close()


_wallet_backend = None


TELEGRAM_AUTH_CACHE_KEY = getattr(web, "RequestKey", web.AppKey)("validated_telegram_user", tuple)
WEBAPP_ROOT = Path(__file__).resolve().parent
WEBAPP_FILES = {
    "index.html", "app_shell.html", "app.js", "styles.css", "guard.js",
    "game_names.js", "support.js", "support.css", "sw.js", "admin.js",
    "gadmin.js", "srv_panel.js", "srv_panel.css",
}
WEBAPP_DIRECTORIES = {
    "images", "lottie", "fonts", "ИграHiLo", "ИграКено", "ИграРулетка",
    "Капча", "cryptobot", "tonkeeper", "xrocket",
}


async def webapp_index(request: web.Request) -> web.StreamResponse:
    if request.path == "/app/":
        raise web.HTTPPermanentRedirect(location="/app" + ("?" + request.query_string if request.query_string else ""))
    return await static_response(request, WEBAPP_ROOT / "index.html")


def webapp_authenticated_user(request: web.Request, init_data: str | None = None):
    raw = init_data if init_data is not None else request.headers.get("X-Telegram-Init-Data", "")
    if not isinstance(raw, str) or not raw or len(raw) > 16384:
        raise web.HTTPUnauthorized(
            text='{"ok":false,"error":"Откройте приложение через Telegram."}',
            content_type="application/json",
            headers={"Cache-Control": "no-store"},
        )
    cached = request.get(TELEGRAM_AUTH_CACHE_KEY)
    if cached is not None and cached[0] == raw:
        user = cached[1]
    else:
        try:
            data = safe_parse_webapp_init_data(BOT_TOKEN, raw)
            age = time.time() - data.auth_date.timestamp()
            if age < -60 or age > 86400 or data.user is None or data.user.id <= 0:
                raise ValueError("Invalid Telegram authentication")
            user = data.user
        except (ValueError, TypeError, OverflowError):
            raise web.HTTPUnauthorized(
                text='{"ok":false,"error":"Вход устарел или недействителен. Перезапустите приложение в Telegram."}',
                content_type="application/json",
                headers={"Cache-Control": "no-store"},
            ) from None
        # Request-local only: never reuse a validated session across HTTP requests/users.
        request[TELEGRAM_AUTH_CACHE_KEY] = (raw, user)
    requested_user = request.query.get("uid")
    if requested_user is not None and requested_user != str(user.id):
        raise web.HTTPForbidden(
            text='{"ok":false,"error":"Нет доступа к чужому аккаунту."}',
            content_type="application/json",
            headers={"Cache-Control": "no-store"},
        )
    return user


@web.middleware
async def webapp_api_guard(request: web.Request, handler):
    # The WebSocket authenticates a short-lived, one-use ticket in its first frame.
    # Browsers cannot attach X-Telegram-Init-Data to the Upgrade request.
    if request.path == "/api/ws" and request.headers.get("Upgrade", "").lower() == "websocket":
        return await handler(request)
    if request.path == "/api" or request.path.startswith("/api/"):
        try:
            if request.path == "/api/auth/telegram" and request.method == "POST":
                try:
                    payload = await request.json()
                except (ValueError, TypeError, UnicodeDecodeError):
                    raise web.HTTPNotFound(headers={"Cache-Control": "no-store"}) from None
                raw = payload.get("initData", "") if isinstance(payload, dict) else ""
                webapp_authenticated_user(request, raw)
            else:
                webapp_authenticated_user(request)
        except (web.HTTPUnauthorized, web.HTTPForbidden):
            raise web.HTTPNotFound(headers={"Cache-Control": "no-store"}) from None
    return await handler(request)


async def webapp_auth(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except (ValueError, TypeError, UnicodeDecodeError):
        return web.json_response({"ok": False, "error": "Некорректный запрос."}, status=400, headers={"Cache-Control": "no-store"})
    if not isinstance(payload, dict):
        return web.json_response({"ok": False, "error": "Некорректный запрос."}, status=400, headers={"Cache-Control": "no-store"})
    user = webapp_authenticated_user(request, payload.get("initData", ""))
    display_name = " ".join(part for part in (user.first_name, user.last_name) if part)
    async with _db_lock:
        connection = db()
        try:
            await connection.execute("INSERT INTO usernames(user_id,username,full_name,updated_at) VALUES (?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username = excluded.username,full_name = excluded.full_name,updated_at = excluded.updated_at WHERE usernames.username IS NOT excluded.username OR usernames.full_name != excluded.full_name", (user.id, user.username, display_name, now_msk().isoformat()))
            await connection.commit()
        except BaseException:
            await connection.rollback()
            raise
    TELEGRAM_NAMES[user.id] = user.username
    return web.json_response({"ok": True, "userId": user.id}, headers={"Cache-Control": "no-store"})


async def webapp_state(request: web.Request) -> web.Response:
    user = webapp_authenticated_user(request)
    async with _db_lock:
        async with db().execute(
            "SELECT amount, created_at FROM balances WHERE user_id = ?", (user.id,)
        ) as cursor:
            row = await cursor.fetchone()
    display_name = " ".join(part for part in (user.first_name, user.last_name) if part)
    return web.json_response(
        {
            "ok": True,
            "id": user.id,
            "balance": float(row[0]) if row else 0.0,
            "registrationDate": row[1] if row else None,
            "displayName": display_name or user.username or "Игрок",
            "username": user.username,
            "avatarUrl": user.photo_url or "",
            "botUsername": BOT_USERNAME,
            "isAdmin": user.id == ADMIN_ID,
            "serverTz": 180,
        },
        headers={"Cache-Control": "no-store"},
    )


async def webapp_referral(request: web.Request) -> web.Response:
    user = webapp_authenticated_user(request)
    referral = await get_ref_data(user.id)
    count = await count_referrals(user.id)
    return web.json_response(
        {
            "ok": True,
            "link": f"https://t.me/{BOT_USERNAME}?start=ref_{user.id}",
            "count": count,
            "earnings": referral["signup_earned"] + referral["deposit_earned"] + referral.get("group_earned", 0.0),
            "groupEarnings": referral.get("group_earned", 0.0),
        },
        headers={"Cache-Control": "no-store"},
    )


async def webapp_api_unavailable(request: web.Request) -> web.Response:
    return web.json_response(
        {"ok": False, "error": "Этот раздел WebApp пока не подключён.", "code": "WEBAPP_BACKEND_UNAVAILABLE"},
        status=503,
        headers={"Cache-Control": "no-store", "Retry-After": "60"},
    )


async def webapp_asset(request: web.Request) -> web.StreamResponse:
    relative = Path(request.match_info["path"])
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise web.HTTPNotFound()
    if relative.parts[0] not in WEBAPP_DIRECTORIES and str(relative) not in WEBAPP_FILES:
        raise web.HTTPNotFound()
    path = (WEBAPP_ROOT / relative).resolve()
    if not path.is_relative_to(WEBAPP_ROOT):
        raise web.HTTPNotFound()
    # Resolve symlinks before authorizing their target. Public asset aliases must
    # never expose server code, wallet seed files or private directories.
    canonical = path.relative_to(WEBAPP_ROOT)
    if (not canonical.parts or any(part.startswith(".") for part in canonical.parts)
            or path.name.endswith(".ton-seed")
            or canonical.parts[0] not in WEBAPP_DIRECTORIES and str(canonical) not in WEBAPP_FILES):
        raise web.HTTPNotFound()
    if path.is_file():
        if path.suffix in {".js", ".css", ".html"}:
            return await static_response(request, path, WEBAPP_ROOT / ".cache" / "http-static")
        return web.FileResponse(path)
    placeholders = {".png": "unavailable.png", ".jpg": "unavailable.png", ".jpeg": "unavailable.png", ".webp": "unavailable.png", ".gif": "unavailable.png", ".svg": "unavailable.svg", ".lottie": "unavailable.lottie"}
    placeholder = placeholders.get(path.suffix.lower())
    if placeholder:
        logging.warning("WebApp resource missing: %s", relative)
        return web.FileResponse(WEBAPP_ROOT / "placeholders" / placeholder, headers={"Cache-Control": "no-store", "X-MjrStar-Placeholder": "1"})
    raise web.HTTPNotFound()


def main() -> None:
    global _wallet_backend
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
        force=True,
    )

    try:
        import uvloop
        uvloop.install()
        logging.info("uvloop installed")
    except ImportError:
        logging.info("uvloop not available, using default event loop")

    try:
        from aiogram.client.session.aiohttp import AiohttpSession
        session = AiohttpSession(limit=200)
        bot = Bot(
            token=BOT_TOKEN,
            session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    except Exception:
        logging.exception("custom session failed, using default")
        bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
    bot.session.middleware.register(TelegramLocaleRequestMiddleware())
    dp = Dispatcher()
    dp.include_router(router)

    dp.update.outer_middleware(TelegramLocaleContextMiddleware())
    dp.update.outer_middleware(UpdateLogMiddleware())
    dp.errors.register(on_error)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    app = web.Application(middlewares=[webapp_api_guard])
    app.router.add_get("/", webapp_index)
    app.router.add_get("/app", webapp_index)
    app.router.add_get("/app/", webapp_index)
    app.router.add_post("/api/auth/telegram", webapp_auth)
    app.router.add_get("/api/state", webapp_state)
    app.router.add_get("/api/referral", webapp_referral)
    games_backend = CompleteGamesBackend(db, _db_lock, webapp_authenticated_user, now_msk)
    _wallet_backend = games_backend
    games_backend.wallet_runtime = globals()
    games_backend.telegram_bot = bot
    games_backend.telegram_channel = CHANNEL_ID
    games_backend.register(app)
    app.router.add_route("*", "/api/{path:.*}", webapp_api_unavailable)

    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    )
    webhook_handler.register(app, path=WEBHOOK_PATH)

    app.router.add_get("/{path:.*}", webapp_asset)

    setup_application(app, dp, bot=bot)
    app.on_startup.append(games_backend.initialize)

    logging.info("Starting web server on %s:%s", WEBAPP_HOST, WEBAPP_PORT)
    web.run_app(app, host=WEBAPP_HOST, port=WEBAPP_PORT, access_log=None)


if __name__ == "__main__":
    main()
'''

# ==================== payment_errors.py ====================
_SOURCES['payment_errors'] = r'''"""Safe payment diagnostics: never return/log raw provider bodies or credentials."""
import base64
import json
import math
import re
import time
from urllib.parse import urlsplit

from games_backend import GameError


class PaymentProviderError(GameError):
    def __init__(self, provider, message, code, upstream_status=None, definitive=False, status=502):
        super().__init__(message, status, code)
        self.provider = provider
        self.upstream_status = upstream_status
        self.definitive = definitive


def rocket_token_problem(token):
    if not isinstance(token, str) or not token:
        return 'XROCKET_TOKEN_MISSING'
    try:
        parts = token.split('.')
        if len(parts) != 3 or any(not re.fullmatch(r'[A-Za-z0-9_-]+', part) for part in parts):
            return 'XROCKET_TOKEN_MALFORMED'
        decoded = []
        for segment in parts[:2]:
            decoded.append(json.loads(base64.b64decode(segment + '=' * (-len(segment) % 4), altchars=b'-_', validate=True)))
        if not all(isinstance(value, dict) for value in decoded) or decoded[0].get('alg') in {None, 'none'}:
            return 'XROCKET_TOKEN_MALFORMED'
        expires = decoded[1].get('exp')
        if expires is not None and (isinstance(expires, bool) or not isinstance(expires, (int, float)) or not math.isfinite(expires)):
            return 'XROCKET_TOKEN_MALFORMED'
        if expires is not None and expires <= time.time():
            return 'XROCKET_TOKEN_EXPIRED'
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return 'XROCKET_TOKEN_MALFORMED'
    # Format/expiry only. Authenticity and permissions can only be checked by xRocket.
    return None


def provider_rejection(provider, status, result):
    label = 'CryptoBot' if provider == 'cryptobot' else 'xRocket'
    error = result.get('error') if isinstance(result, dict) else None
    name = error.get('name') if isinstance(error, dict) else None
    code = error.get('code') if isinstance(error, dict) else None
    name = name if isinstance(name, str) else None
    code = code if isinstance(code, int) else None
    if status in {401, 403} or code in {401, 403} or name in {'UNAUTHORIZED', 'TOKEN_INVALID', 'ACCESS_DENIED'}:
        return PaymentProviderError(provider, label + ': доступ к API отклонён. Проверьте API-токен, разрешение на создание счетов, ограничения IP/сети и выбранную версию API.', 'PROVIDER_AUTH_REJECTED', status, definitive=status < 500)
    if name in {'AMOUNT_TOO_SMALL', 'AMOUNT_TOO_BIG', 'AMOUNT_INVALID', 'FIAT_AMOUNT_INVALID'}:
        return PaymentProviderError(provider, label + ': сумма счёта не соответствует ограничениям провайдера. Измените сумму пополнения.', 'PROVIDER_AMOUNT_REJECTED', status, definitive=True)
    if status == 404:
        return PaymentProviderError(provider, label + ': API-метод не найден. Проверьте окружение и версию API (для xRocket нужна Current).', 'PROVIDER_API_VERSION', status, definitive=True)
    if status in {400, 422} or provider == 'cryptobot' and isinstance(result, dict) and result.get('ok') is False:
        return PaymentProviderError(provider, label + ': запрос на счёт отклонён. Проверьте сумму, валюту и настройки приложения у провайдера.', 'PROVIDER_REQUEST_REJECTED', status, definitive=status < 500)
    return PaymentProviderError(provider, label + ': сервис вернул ошибку HTTP ' + str(status) + '. Если запрос на создание уже отправлен, сначала проверьте его статус.', 'PROVIDER_HTTP_ERROR', status)


def invoice_pay_url(provider, invoice):
    if not isinstance(invoice, dict):
        raise GameError('Некорректный ответ платёжного сервиса.', 502)
    if provider == 'cryptobot':
        url = invoice.get('bot_invoice_url') or invoice.get('mini_app_invoice_url') or invoice.get('web_app_invoice_url')
        allowed = {'t.me', 'pay.crypt.bot'}
    else:
        links = invoice.get('links')
        url = links.get('telegramBotLink') if isinstance(links, dict) else None
        allowed = {'t.me'}
    try:
        parsed = urlsplit(url) if isinstance(url, str) else None
        valid = parsed is not None and parsed.scheme == 'https' and parsed.hostname in allowed and parsed.username is None and parsed.password is None and parsed.port in {None, 443}
    except ValueError:
        valid = False
    if not valid:
        raise GameError('Провайдер вернул некорректную ссылку на оплату.', 502)
    return url
'''

# ==================== payments_backend.py ====================
_SOURCES['payments_backend'] = r'''import asyncio
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
from payment_errors import PaymentProviderError, rocket_token_problem, provider_rejection, invoice_pay_url


STAR_USD = Decimal("0.022")
PAYMENT_LIFETIME = 1800
CRYPTOBOT_API_TOKEN = __server_config__['CRYPTOBOT_API_TOKEN']
XROCKET_API_TOKEN = __server_config__['XROCKET_API_TOKEN']
XROCKET_WEBHOOK_SECRET = __server_config__['XROCKET_WEBHOOK_SECRET']


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
        for provider in ("laveshka", "sbp"):
            application.router.add_post(f"/api/deposit/{provider}/create", self.handle_lave_create)
            application.router.add_get(f"/api/deposit/{provider}/status", self.handle_lave_status)
        application.router.add_get("/api/deposit/laveshka/providers", self.handle_lave_providers)
        application.router.add_post("/laveshka", self.handle_lave_webhook)
        application.router.add_post("/api/deposit/laveshka/cancel", self.handle_lave_cancel)
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
        defaults = {"cryptobot": CRYPTOBOT_API_TOKEN, "xrocket": XROCKET_API_TOKEN, "laveshka": __server_config__.get("LAVESHKA_API_KEY", "")}
        token = getattr(self, "payment_tokens", {}).get(provider, defaults.get(provider))
        return token.strip() if isinstance(token, str) else None

    def rocket_secret(self):
        secret = getattr(self, "xrocket_webhook_secret", XROCKET_WEBHOOK_SECRET)
        return secret.strip() if isinstance(secret, str) else None

    async def payment_api(self, provider, method, path, data=None):
        token = self.payment_token(provider)
        if not token:
            raise PaymentProviderError(provider, "Платёжный провайдер ещё не настроен.", "PROVIDER_NOT_CONFIGURED", definitive=True, status=503)
        if not token.isascii() or any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in token):
            raise PaymentProviderError(provider, "API-токен содержит недопустимые символы. Замените его оригиналом из настроек провайдера.", "PROVIDER_TOKEN_MALFORMED", definitive=True, status=503)
        if provider == "xrocket":
            problem = rocket_token_problem(token)
            if problem:
                message = "xRocket: API JWT повреждён. Замените его оригинальным токеном из настроек приложения Current API." if problem != "XROCKET_TOKEN_EXPIRED" else "xRocket: срок API JWT истёк. Выпустите новый токен в настройках приложения."
                raise PaymentProviderError(provider, message, problem, definitive=True, status=503)
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
                    try:
                        result = json.loads(raw) if raw else {} if method == "DELETE" else None
                    except (ValueError, UnicodeError):
                        result = None
                    malformed = result is None or provider == "cryptobot" and (not isinstance(result, dict) or not isinstance(result.get("ok"), bool))
                    if response.status >= 300 or provider == "cryptobot" and not malformed and result["ok"] is False:
                        error = provider_rejection(provider, response.status, result)
                        logging.warning("Payment provider rejection: provider=%s endpoint=%s status=%s code=%s", provider, path.split("?")[0], response.status, error.code)
                        raise error
                    if malformed:
                        raise PaymentProviderError(provider, "Провайдер вернул некорректный ответ. Проверьте статус счёта перед повторной попыткой.", "PROVIDER_BAD_RESPONSE")
                    return result.get("result") if provider == "cryptobot" else result
        except (aiohttp.ClientError, asyncio.TimeoutError):
            logging.warning("Payment provider transport failure: provider=%s endpoint=%s", provider, path.split("?")[0])
            raise PaymentProviderError(provider, "Нет соединения с API платёжного провайдера. Проверьте исходящий HTTPS сервера; статус счёта можно проверить позже.", "PROVIDER_CONNECTION_FAILED") from None

    def payment_failure(self, error):
        if isinstance(error, PaymentProviderError):
            return self.response({"ok": False, "error": error.message, "code": error.code, "provider": error.provider, "providerStatus": error.upstream_status}, error.status)
        return self.failure(error)

    async def handle_deposit_info(self, request):
        self.validate_user(request)
        crypto_ready = bool(self.payment_token("cryptobot"))
        rocket_problem = rocket_token_problem(self.payment_token("xrocket"))
        errors = {}
        if not crypto_ready:
            errors["cryptobot"] = "CryptoBot: API-токен не настроен."
        if rocket_problem:
            errors["xrocket"] = "xRocket: API-токен отсутствует, повреждён или истёк. Нужен оригинальный JWT Current API."
        elif not self.rocket_secret():
            errors["xrocket"] = "xRocket: Webhook Secret не настроен."
        return self.response({"ok": True, "methods": {"cryptobot": crypto_ready, "xrocket": not rocket_problem and bool(self.rocket_secret()), "stars": getattr(self, "telegram_bot", None) is not None, "tonkeeper": self.ton_ready() if hasattr(self, "ton_ready") else False, "sbp": self.lave_ready(), "laveshka": self.lave_ready()}, "methodErrors": errors, "limits": {"min_deposit_cryptobot": 1, "min_deposit_xrocket": 1, "min_deposit_stars": 1, "min_deposit_sbp": 5, "min_deposit_laveshka": 5}, "laveshka": {"minUsd":5,"maxUsd":10000}, "usdPerStar": str(STAR_USD), "promo": None, "tagPromo": None})

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

    async def deposit_creation_failed(self, order_id):
        async with self.database_lock:
            connection = self.database()
            try:
                await connection.execute("UPDATE webapp_deposits SET status='failed' WHERE id=? AND status='creating'", (order_id,))
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

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
                            raise GameError("Результат создания ещё не подтверждён. Сначала проверьте статус счёта.", 409)
                        if order["status"] == "failed":
                            raise GameError("Провайдер отклонил этот запрос. Исправьте настройки или сумму и создайте новый счёт.", 409)
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
                creation_sent = False
                try:
                    if provider == "stars":
                        creation_sent = True
                        pay_url = await self.telegram_bot.create_invoice_link(title="MajorStars", description=f"Пополнение баланса на {cents // 100} Stars", payload=order_id, currency="XTR", prices=[LabeledPrice(label="Stars", amount=cents // 100)], provider_token="")
                        provider_id = order_id
                    elif provider == "cryptobot":
                        creation_sent = True
                        invoice = await self.payment_api(provider, "POST", "createInvoice", {"currency_type": "fiat", "fiat": "USD", "amount": str(price), "payload": order_id, "expires_in": PAYMENT_LIFETIME, "description": f"MajorStars: {cents / 100:g} Stars", "allow_comments": False, "allow_anonymous": False})
                        provider_id, pay_url = str(invoice["invoice_id"]), invoice_pay_url(provider, invoice)
                    else:
                        currency = await self.rocket_currency(currency)
                        rates = await self.payment_api(provider, "GET", "/api/v1/rates", {"base": "USD", "assets": currency})
                        if not isinstance(rates, list):
                            raise GameError("Некорректный формат курса валют. Проверьте версию API xRocket.", 502)
                        rate = next((decimal_amount(item.get("rate")) for item in rates if isinstance(item, dict) and item.get("currency") == currency), None)
                        if rate is None:
                            raise GameError("Нет курса выбранной валюты.", 502)
                        price = (price / rate).quantize(Decimal("0.00000001"), rounding=ROUND_UP)
                        async with self.database_lock:
                            connection = self.database()
                            await connection.execute("UPDATE webapp_deposits SET price_amount = ?,price_currency = ? WHERE id = ?", (str(price), currency, order_id))
                            await connection.commit()
                        creation_sent = True
                        invoice = await self.payment_api(provider, "POST", "/api/v1/invoices", {"priceAmount": str(price), "priceCurrency": currency, "numPayments": 1, "clientInvoiceId": order_id, "expiresIn": PAYMENT_LIFETIME * 1000, "description": f"MajorStars: {cents / 100:g} Stars", "callback": {"callbackUrl": "https://mjrr.wisp.uno/xrocket", "payload": {"orderId": order_id}}})
                        provider_id, pay_url = str(invoice["id"]), invoice_pay_url(provider, invoice)
                    if provider == "stars" and (not isinstance(pay_url, str) or not pay_url.startswith("https://t.me/")):
                        raise GameError("Провайдер вернул некорректную ссылку.", 502)
                except GameError as error:
                    if not creation_sent or isinstance(error, PaymentProviderError) and error.definitive:
                        await self.deposit_creation_failed(order_id)
                    raise
                except (KeyError, TypeError, StopIteration):
                    if not creation_sent:
                        await self.deposit_creation_failed(order_id)
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
            return self.payment_failure(error)

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
            if provider != "stars" and order["status"] not in {"paid", "failed"}:
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
            return self.payment_failure(error)

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
                sources = ["SELECT 'deposit' AS type,stars_cents/100.0 AS amount,CASE provider WHEN 'cryptobot' THEN 'CryptoBot' WHEN 'xrocket' THEN 'xRocket' WHEN 'tonkeeper' THEN 'Tonkeeper (TON)' WHEN 'laveshka' THEN 'Лавэшка' WHEN 'sbp' THEN 'Лавэшка · СБП / телефон' ELSE 'Stars' END AS description,status,strftime('%s',COALESCE(paid_at,created_at)) AS created_at,user_id FROM webapp_deposits WHERE status != 'creating'", "SELECT 'deposit',amount,CASE WHEN substr(charge_id,1,14)='admin-deposit:' THEN 'Депозит от администратора' ELSE 'Stars' END,'paid',strftime('%s',created_at),user_id FROM payments WHERE charge_id NOT IN (SELECT provider_id FROM webapp_deposits WHERE provider_id IS NOT NULL)", "SELECT 'withdrawal',amount,'Stars',status,strftime('%s',created_at),user_id FROM withdrawals", "SELECT 'withdrawal',quantity,'Stars · Fragment',state,strftime('%s',created_at),user_id FROM webapp_star_withdrawals"]
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


# Fragment Connection JWT from the provider dashboard (raw JWT, never a bot token).
    def lave_ready(self):
        return bool(self.payment_token("laveshka") and __server_config__.get("LAVESHKA_WEBHOOK_SECRET"))

    async def lave_api(self, method, path, data=None):
        token = self.payment_token("laveshka")
        if not self.lave_ready():
            raise GameError("Лавэшка не настроена.", 503)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35)) as session:
                async with session.request(method, "https://laveshka.io/merchant/v1" + path,
                        headers={"X-Api-Key": token}, json=data if method == "POST" else None,
                        params=data if method == "GET" else None, allow_redirects=False) as response:
                    result = await response.json(content_type=None)
                    if response.status >= 300 or not isinstance(result, dict) or result.get("ok") is not True:
                        code = result.get("error", {}).get("code") if isinstance(result, dict) and isinstance(result.get("error"), dict) else None
                        messages = {
                            "unauthorized": "Лавэшка: API-ключ не принят. Администратору нужно проверить LAVESHKA_API_KEY.",
                            "forbidden": "Лавэшка: операция запрещена. Проверьте, что мерчант активен.",
                            "validation_error": "Лавэшка отклонила параметры или сумму счёта. Администратору нужно проверить ограничения мерчанта.",
                            "rate_limited": "Лавэшка: превышен лимит запросов. Проверим этот же счёт позже.",
                            "provider_not_configured": "Лавэшка: это направление временно отключено у провайдера.",
                            "rate_changed": "Лавэшка: курс изменился выше допустимого. Нужна проверка сохранённой заявки.",
                            "buy_blocked": "Лавэшка: покупка USDT временно заблокирована для мерчанта.",
                            "duplicate_operation": "Лавэшка: конфликт параметров существующего счёта. Не создавайте повторный платёж.",
                            "idempotency_conflict": "Лавэшка: конфликт ключа существующей покупки. Нужна проверка заявки.",
                        }
                        safe_code = code if code in messages else "api_error"
                        message = messages.get(code, "Лавэшка не подтвердила создание счёта.")
                        raise GameError(message + " (HTTP " + str(response.status) + ", " + safe_code + ")", 502, "LAVE_API_ERROR")
                    if not isinstance(result.get("data"), dict):
                        raise GameError("Некорректный ответ Лавэшки.", 502)
                    return result["data"]
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            raise GameError("Нет подтверждённого ответа Лавэшки. Счёт сохранён, проверяем статус.", 502) from None

    async def initialize_lave(self, application):
        async with self.database_lock:
            await self.database().execute("CREATE TABLE IF NOT EXISTS webapp_lave_orders(id TEXT PRIMARY KEY,request TEXT NOT NULL,object TEXT,checked_at INTEGER NOT NULL DEFAULT 0)")
            await self.database().execute("CREATE TABLE IF NOT EXISTS webapp_lave_errors(id TEXT PRIMARY KEY,message TEXT NOT NULL,updated_at TEXT NOT NULL)")
            await self.database().commit()
        if application is not None and not hasattr(self, "lave_task"):
            self.lave_task = asyncio.create_task(self.lave_reconcile_loop())
            application.on_shutdown.append(self.cleanup_lave)

    async def cleanup_lave(self, application):
        self.lave_task.cancel()
        await asyncio.gather(self.lave_task, return_exceptions=True)

    async def lave_reconcile_loop(self):
        while True:
            try:
                if self.lave_ready():
                    async with self.database_lock:
                        async with self.database().execute("SELECT d.id FROM webapp_deposits d JOIN webapp_lave_orders l ON l.id=d.id WHERE provider IN ('laveshka','sbp') AND status IN ('creating','active','pending','awaiting_payment','processing','overdue','cancelled') ORDER BY l.checked_at LIMIT 20") as cursor:
                            ids = [row[0] for row in await cursor.fetchall()]
                    for order_id in ids:
                        try:
                            await self.lave_refresh(order_id)
                        except GameError:
                            pass
            except Exception as error:
                logging.warning("Laveshka reconciliation: %s", type(error).__name__)
            await asyncio.sleep(30)

    async def lave_load(self, order_id, user_id=None):
        async with self.database_lock:
            order = await self.deposit_row(self.database(), order_id, user_id)
            if order["provider"] not in {"laveshka", "sbp"}:
                raise GameError("Счёт не найден.", 404)
            async with self.database().execute("SELECT request,object FROM webapp_lave_orders WHERE id=?", (order_id,)) as cursor:
                row = await cursor.fetchone()
            if not row:
                raise GameError("Счёт не найден.", 404)
            return order, json.loads(row[0]), json.loads(row[1]) if row[1] else {}

    async def lave_refresh(self, order_id):
        try:
            await self._lave_refresh(order_id)
        except GameError as error:
            async with self.database_lock:
                await self.database().execute("INSERT INTO webapp_lave_errors(id,message,updated_at) VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET message=excluded.message,updated_at=excluded.updated_at", (order_id, error.message, self.clock().isoformat()))
                await self.database().commit()
            # No provider response, API key or raw body is logged.
            logging.warning("Laveshka order %s: status=%s code=%s", order_id, error.status, error.code or "LAVE_CONFIRMATION_ERROR")
            raise
        async with self.database_lock:
            await self.database().execute("DELETE FROM webapp_lave_errors WHERE id=?", (order_id,))
            await self.database().commit()

    async def _lave_refresh(self, order_id):
        order, body, obj = await self.lave_load(order_id)
        async with self.database_lock:
            await self.database().execute("UPDATE webapp_lave_orders SET checked_at=? WHERE id=?", (time.time(), order_id))
            await self.database().commit()
        if order["status"] == "paid":
            return
        if order["provider"] == "laveshka":
            if order["provider_id"]:
                obj = await self.lave_api("GET", "/invoices/" + order["provider_id"])
            else:
                # order_id is a durable provider-side idempotency key.
                obj = await self.lave_api("POST", "/invoices", body)
        else:
            # Replaying the exact frozen body is safe even after a lost response.
            if order["provider_id"]:
                obj = await self.lave_api("GET", "/buy/orders/" + order["provider_id"])
            else:
                obj = await self.lave_api("POST", "/buy/orders", body)
        await self.lave_apply(order_id, obj)

    async def lave_apply(self, order_id, obj, event_id=None):
        order, body, previous = await self.lave_load(order_id)
        if not isinstance(obj, dict):
            raise GameError("Данные платежа Лавэшки не совпадают (код проверки: LAVE_CONFIRMATION_OBJECT).", 409, "LAVE_CONFIRMATION_OBJECT")
        token = self.payment_token("laveshka") or ""
        merchant = re.fullmatch(r"LAVE-([0-9]+)-[^\s]+", token)
        is_invoice = order["provider"] == "laveshka"

        def confirmation_error(code):
            return GameError("Данные платежа Лавэшки не совпадают (код проверки: " + code + ").", 409, code)

        def amount_equals(value, expected):
            try:
                return decimal_amount(value) == decimal_amount(expected)
            except GameError:
                return False

        identifier = obj.get("id")
        if (not isinstance(identifier, str)
                or not re.fullmatch(r"(?:inv|buy)_[A-Za-z0-9-]+", identifier)
                or not identifier.startswith("inv_" if is_invoice else "buy_")):
            raise confirmation_error("LAVE_CONFIRMATION_ID")
        if order["provider_id"] and identifier != order["provider_id"]:
            raise confirmation_error("LAVE_CONFIRMATION_PROVIDER_ID")
        if is_invoice:
            if obj.get("order_id") != order_id:
                raise confirmation_error("LAVE_CONFIRMATION_ORDER_ID")
            if obj.get("currency") != "USD":
                raise confirmation_error("LAVE_CONFIRMATION_CURRENCY")
            if not amount_equals(obj.get("face_amount"), order["price_amount"]):
                raise confirmation_error("LAVE_CONFIRMATION_FACE_AMOUNT")
            if not amount_equals(obj.get("amount"), order["price_amount"]):
                raise confirmation_error("LAVE_CONFIRMATION_AMOUNT")
            if not merchant or str(obj.get("merchant_id")) != merchant[1]:
                raise confirmation_error("LAVE_CONFIRMATION_MERCHANT_ID")
        else:
            if obj.get("idempotency_key") != order_id:
                raise confirmation_error("LAVE_CONFIRMATION_IDEMPOTENCY_KEY")
            if obj.get("currency") != "USDT":
                raise confirmation_error("LAVE_CONFIRMATION_CURRENCY")
            try:
                amount_usdt = decimal_amount(obj.get("amount_usdt"))
                expected_usdt = decimal_amount(order["price_amount"])
            except GameError:
                raise confirmation_error("LAVE_CONFIRMATION_AMOUNT_USDT") from None
            if amount_usdt < expected_usdt:
                raise confirmation_error("LAVE_CONFIRMATION_AMOUNT_USDT")
            if obj.get("method") != body["method"]:
                raise confirmation_error("LAVE_CONFIRMATION_METHOD")
            if str(obj.get("provider_id")) != str(body["provider_id"]):
                raise confirmation_error("LAVE_CONFIRMATION_PROVIDER_ID")
        status = obj.get("status")
        allowed = {"active", "paid", "expired", "cancelled", "refunded"} if is_invoice else {"pending", "awaiting_payment", "overdue", "completed", "cancelled"}
        if status not in allowed:
            raise confirmation_error("LAVE_CONFIRMATION_STATUS")
        paid = status == ("paid" if is_invoice else "completed")
        url = obj.get("pay_url" if is_invoice else "payment_url")
        if is_invoice and status == "active" and not url:
            raise GameError("Лавэшка вернула счёт без ссылки pay_url. Нужна проверка ответа провайдера.", 502)
        if url and not self.lave_safe_url(url, is_invoice):
            raise GameError("Некорректная ссылка оплаты.", 502)
        async with self.database_lock:
            connection = self.database()
            try:
                await connection.execute("BEGIN IMMEDIATE")
                if event_id:
                    async with connection.execute("SELECT 1 FROM webapp_payment_events WHERE provider='laveshka' AND event_id=?", (event_id,)) as cursor:
                        if await cursor.fetchone():
                            await connection.rollback()
                            return
                fresh = await self.deposit_row(connection, order_id)
                if fresh["status"] != "paid":
                    await connection.execute("UPDATE webapp_deposits SET provider_id=?,pay_url=?,status=?,paid_at=? WHERE id=?", (identifier, url, "paid" if paid else status, self.clock().isoformat() if paid else None, order_id))
                    if paid:
                        await self.wallet_credit(connection, order["user_id"], order["stars_cents"], "deposit", "deposit:" + order_id)
                        await self.referral_credit(connection, order["user_id"], order["stars_cents"], "deposit:" + order_id)
                await connection.execute("UPDATE webapp_lave_orders SET object=? WHERE id=?", (json.dumps(obj), order_id))
                if event_id:
                    await connection.execute("INSERT OR IGNORE INTO webapp_payment_events(provider,event_id,created_at) VALUES ('laveshka',?,?)", (event_id, self.clock().isoformat()))
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    @staticmethod
    def lave_safe_url(url, invoice=False):
        from urllib.parse import urlsplit
        if not isinstance(url, str):
            return False
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError:
            return False
        return parsed.scheme == "https" and parsed.hostname in ({"t.me"} if invoice else {"qr.nspk.ru"}) and not parsed.username and not parsed.password and port in (None, 443)

    async def handle_lave_providers(self, request):
        try:
            self.validate_user(request)
            rate = await self.lave_api("GET", "/buy/rate")
            providers = rate.get("providers", [])
            if not isinstance(providers, list):
                raise GameError("Некорректный список провайдеров.", 502)
            return self.response({"ok": True, "providers": providers})
        except GameError as error:
            return self.payment_failure(error)

    async def handle_lave_create(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            if not self.lave_ready():
                raise GameError("Лавэшка не настроена.", 503)
            provider = request.path.split("/")[3]
            cents = money_cents(payload.get("amount"), 100, 1000000)
            price = (Decimal(cents) / 100 * STAR_USD).quantize(Decimal("0.01"), rounding=ROUND_UP)
            if not Decimal("0.10") <= price <= Decimal("10000"):
                raise GameError("Сумма счёта должна быть от $0.10 до $10000.")
            key, digest = self.request_identity(request, payload)
            lock = self.deposit_create_locks.setdefault(user.id, asyncio.Lock())
            async with lock:
                async with self.database_lock:
                    async with self.database().execute("SELECT id,request_digest FROM webapp_deposits WHERE user_id=? AND request_key=?", (user.id, key)) as cursor:
                        existing = await cursor.fetchone()
                if existing:
                    if existing[1] != digest:
                        raise GameError("Ключ использован для другого платежа.", 409)
                    order_id = existing[0]
                else:
                    order_id = "ms_" + secrets.token_hex(16)
                    body = {"amount": str(price), "currency": "USD", "accept": ["USDT"], "order_id": order_id, "ttl": PAYMENT_LIFETIME, "description": "MajorStars"}
                    if provider == "sbp":
                        method = payload.get("method")
                        provider_id = payload.get("providerId")
                        if method not in {"sbp", "phone"} or not isinstance(provider_id, (str, int)) or isinstance(provider_id, bool):
                            raise GameError("Выберите провайдера оплаты.")
                        rates = await self.lave_api("GET", "/buy/rate", {"provider_id": str(provider_id), "method": method, "amount_usdt": str(price)})
                        if rates.get("available") is not True or rates.get("method") != method:
                            raise GameError("Этот способ временно недоступен.", 409)
                        rate = decimal_amount(rates.get("rate"))
                        body = {"amount_usdt": str(price), "max_rate": str(rate), "method": method, "provider_id": provider_id, "idempotency_key": order_id}
                    async with self.database_lock:
                        connection = self.database()
                        try:
                            async with connection.execute("SELECT COUNT(*) FROM webapp_deposits WHERE user_id=? AND created_at>=?", (user.id, self.clock().fromtimestamp(time.time()-60, self.clock().tzinfo).isoformat())) as cursor:
                                if (await cursor.fetchone())[0] >= 5:
                                    raise GameError("Слишком много счетов. Подождите минуту.", 429)
                            await connection.execute("INSERT INTO webapp_deposits(id,user_id,provider,stars_cents,price_amount,price_currency,status,created_at,expires_at,request_key,request_digest) VALUES (?,?,?,?,?,?,'creating',?,?,?,?)", (order_id,user.id,provider,cents,str(price),"USD" if provider == "laveshka" else "USDT",self.clock().isoformat(),int(time.time())+PAYMENT_LIFETIME,key,digest))
                            await connection.execute("INSERT INTO webapp_lave_orders(id,request) VALUES (?,?)", (order_id,json.dumps(body)))
                            await connection.commit()
                        except BaseException:
                            await connection.rollback()
                            raise
                try:
                    await self.lave_refresh(order_id)
                except GameError:
                    # Return the durable local ID, so clients can poll ambiguous outcomes.
                    pass
                return self.response(await self.lave_result(order_id, user.id))
        except GameError as error:
            return self.payment_failure(error)

    async def lave_result(self, order_id, user_id):
        from datetime import datetime
        order, body, obj = await self.lave_load(order_id, user_id)
        result = self.deposit_result(order)
        result.update({"paymentId":order_id,"requestId":order_id,"state":order["status"],"feePercent":0,"feeAmount":0,"total":order["stars_cents"]/100})
        if order["provider"] == "sbp":
            state = order["status"]
            result["state"] = "pending" if state in {"pending","awaiting_payment","overdue"} else state
            result.update({"rubAmount":obj.get("amount_rub"),"rate":obj.get("rate"),"method":obj.get("method"),"payPhone":obj.get("pay_phone"),"payCountry":obj.get("pay_country"),"payOperator":obj.get("pay_operator"),"overdue":state == "overdue"})
            if obj.get("pay_until"):
                try:
                    result["expiresIn"] = max(0,int(datetime.fromisoformat(obj["pay_until"]).timestamp()-time.time()))
                except (ValueError, TypeError):
                    result["expiresIn"] = 0
            else:
                result["expiresIn"] = 0
        async with self.database_lock:
            result["balance"] = await self.balance(self.database(), user_id)
            async with self.database().execute("SELECT message FROM webapp_lave_errors WHERE id=?", (order_id,)) as cursor:
                error = await cursor.fetchone()
            result["creationError"] = error[0] if error and order["status"] != "paid" else None
        return result

    async def handle_lave_status(self, request):
        try:
            user = self.validate_user(request)
            order_id = request.query.get("paymentId") or request.query.get("requestId") or ""
            order, body, obj = await self.lave_load(order_id, user.id)
            if order["provider"] != request.path.split("/")[3]:
                raise GameError("Счёт не найден.", 404)
            # Reconciliation also runs without an open browser.
            return self.response(await self.lave_result(order_id, user.id))
        except GameError as error:
            return self.payment_failure(error)

    async def handle_lave_cancel(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            order_id = payload.get("paymentId", "")
            order, body, obj = await self.lave_load(order_id, user.id)
            if order["provider"] != "laveshka":
                raise GameError("Этот способ не поддерживает отмену.", 409)
            if order["status"] == "paid":
                return self.response(await self.lave_result(order_id, user.id))
            if not order["provider_id"]:
                raise GameError("Сначала дождитесь подтверждения создания счёта.", 409)
            obj = await self.lave_api("POST", "/invoices/" + order["provider_id"] + "/cancel", {})
            await self.lave_apply(order_id, obj)
            return self.response(await self.lave_result(order_id, user.id))
        except GameError as error:
            return self.payment_failure(error)

    async def handle_lave_webhook(self, request):
        try:
            body = await request.read()
            timestamp = request.headers.get("X-LavePay-Timestamp", "")
            signature = request.headers.get("X-LavePay-Signature", "")
            secret = __server_config__.get("LAVESHKA_WEBHOOK_SECRET", "")
            if not secret or not re.fullmatch(r"[0-9]{1,12}", timestamp) or abs(time.time()-int(timestamp)) > 300:
                raise GameError("Недействительная подпись.", 401)
            expected = "v1=" + hmac.new(secret.encode(), timestamp.encode()+b"."+body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise GameError("Недействительная подпись.", 401)
            try:
                event = json.loads(body)
            except ValueError:
                raise GameError("Некорректное событие.") from None
            token = self.payment_token("laveshka") or ""
            merchant = re.fullmatch(r"LAVE-([0-9]+)-[^\s]+", token)
            if not isinstance(event, dict) or not merchant or str(event.get("merchant_id")) != merchant[1] or not re.fullmatch(r"evt_[A-Za-z0-9-]+", str(event.get("id", ""))):
                raise GameError("Событие другого мерчанта.", 401)
            if event.get("type") == "webhook.test":
                return self.response({"ok":True})
            if event.get("type") not in {"invoice.paid","invoice.expired","invoice.cancelled","buy_order.completed","buy_order.cancelled"}:
                return self.response({"ok":True})
            obj = event.get("data")
            if not isinstance(obj, dict):
                raise GameError("Некорректное событие.")
            order_id = obj.get("order_id") if event["type"].startswith("invoice.") else obj.get("idempotency_key")
            async with self.database_lock:
                async with self.database().execute("SELECT 1 FROM webapp_lave_orders WHERE id=?", (order_id,)) as cursor:
                    known = await cursor.fetchone()
            if known:
                await self.lave_apply(order_id, obj, event["id"])
            return self.response({"ok":True})
        except GameError as error:
            return self.payment_failure(error)


FRAGMENT_API_JWT = __server_config__['FRAGMENT_API_JWT']
FRAGMENT_CURRENCY = __server_config__['FRAGMENT_CURRENCY']  # or usdt_ton; USDT settlement still needs TON for gas
# Native TON receiving wallet. Empty configuration keeps Tonkeeper disabled.
TONKEEPER_ADDRESS = __server_config__['TONKEEPER_ADDRESS']
# Server-side seed: fill inline ONLY on the deployed server, or use a 0600 file.
# Never commit a real seed. Neither source is ever sent to the network/browser.
TON_WALLET_MNEMONIC = __server_config__['TON_WALLET_MNEMONIC']
TON_WALLET_SEED_FILE = __server_config__['TON_WALLET_SEED_FILE']
TON_WALLET_VERSION = __server_config__['TON_WALLET_VERSION']  # explicit v3r2/v4r2; V5 is not silently reinterpreted
TON_WALLET_WORKCHAIN = __server_config__['TON_WALLET_WORKCHAIN']
TON_WALLET_ID = __server_config__['TON_WALLET_ID']  # None = SDK default; match the actual wallet's subwallet ID
TON_RPC_URL = __server_config__['TON_RPC_URL']  # Own mainnet v3-compatible read-only indexer, e.g. http://127.0.0.1:8081/api/v3
TON_USD_RATE = __server_config__['TON_USD_RATE']  # Explicit server-side USD per TON; no client-supplied rates

'''

# ==================== pot_games.py ====================
_SOURCES['pot_games'] = r'''import hashlib
import json
import re
import secrets
from time import time as pot_now

from games_backend import GameError, integer, money_cents, serialize
from pot_rules import POT_GAMES, POT_COLORS, POT_CONFIG, pot_winner, pot_live_seconds, pot_balls, portal_layout, portal_motion, portal_owner


class PotGamesMixin:
    def register_pots(self, application):
        for game in POT_GAMES:
            for action in ("state", "history", "round", "howto"):
                application.router.add_get(f"/api/{game}/{action}", self.handle_pot_read)
            for action in ("join", "bet", "cancel"):
                application.router.add_post(f"/api/{game}/{action}", self.handle_pot_action)
        application.router.add_get("/api/portal/frames", self.handle_pot_read)

    async def initialize_pots(self):
        async with self.database_lock:
            connection = self.database()
            try:
                await connection.execute("BEGIN IMMEDIATE")
                await connection.execute("CREATE TABLE IF NOT EXISTS webapp_pot_rounds(id TEXT PRIMARY KEY,game TEXT NOT NULL,room INTEGER NOT NULL,seq INTEGER NOT NULL,phase TEXT NOT NULL,data TEXT NOT NULL,UNIQUE(game,room,seq))")
                await connection.execute("CREATE INDEX IF NOT EXISTS idx_pot_current ON webapp_pot_rounds(game,room,seq DESC)")
                for game in POT_GAMES:
                    for room in (1, 2):
                        await self.advance_pot(connection, game, room)
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    async def save_pot(self, connection, state):
        await connection.execute("UPDATE webapp_pot_rounds SET phase = ?,data = ? WHERE id = ?", (state["phase"], serialize(state), state["id"]))

    async def create_pot(self, connection, game, room, sequence):
        seed = secrets.token_hex(32)
        identifier = POT_GAMES[game] + secrets.token_hex(12).upper()
        state = {"id": identifier, "game": game, "roomId": room, "roomName": "Комната " + str(room), "seq": sequence, "phase": "waiting", "fee": 0.01, "commitHash": hashlib.sha256(seed.encode()).hexdigest(), "_seed": seed, "_players": [], "_createdAt": int(pot_now() * 1000)}
        await connection.execute("INSERT INTO webapp_pot_rounds(id,game,room,seq,phase,data) VALUES (?,?,?,?,?,?)", (identifier, game, room, sequence, state["phase"], serialize(state)))
        return state

    async def advance_pot(self, connection, game, room):
        now = int(pot_now() * 1000)
        async with connection.execute("SELECT data FROM webapp_pot_rounds WHERE game = ? AND room = ? ORDER BY seq DESC LIMIT 1", (game, room)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return await self.create_pot(connection, game, room, 1)
        state = json.loads(row[0])
        players = state["_players"]
        if state["phase"] == "waiting" and players and now >= state["_waitingUntil"]:
            for player in players:
                await self.credit(connection, player["uid"], player["cents"])
            state.update({"phase": "cancelled", "refunded": True})
            await self.save_pot(connection, state)
            return await self.create_pot(connection, game, room, state["seq"] + 1)
        if state["phase"] == "betting" and now >= state["bettingEndsAt"]:
            cents = [player["cents"] for player in players]
            state.update({"phase": "countdown", "countdownEndsAt": state["bettingEndsAt"] + 3000, "liveStartedAt": state["bettingEndsAt"] + 3000, "liveSec": pot_live_seconds(game, len(players))})
            if game == "portal":
                state["layout"] = portal_layout(state["_seed"], state["id"], cents)
                state["orbSpawn"], state["_frames"] = portal_motion(state["_seed"], state["id"])
                state["_winnerIdx"] = portal_owner(state["layout"], state["_frames"][-1][1:3])
                state["launchDelayMs"] = 2500
            else:
                state["_winnerIdx"] = pot_winner(state["_seed"], state["id"], cents)
        if state["phase"] == "countdown" and now >= state["countdownEndsAt"]:
            state["phase"] = "live"
        if state["phase"] == "live" and now >= state["liveStartedAt"] + round(state["liveSec"] * 1000):
            bank = sum(player["cents"] for player in players)
            paid = bank * 99 // 100
            winner = players[state["_winnerIdx"]]
            await self.credit(connection, winner["uid"], paid)
            state.update({"phase": "finish", "serverSeed": state["_seed"], "_paidCents": paid, "finishedAt": (state["liveStartedAt"] + round(state["liveSec"] * 1000)) / 1000, "resultAt": state["liveStartedAt"] + round(state["liveSec"] * 1000) + 1000, "nextRoundAt": state["liveStartedAt"] + round(state["liveSec"] * 1000) + 7000})
            for player in players:
                payout = paid if player["uid"] == winner["uid"] else 0
                detail = {"ok": True, "roundId": state["id"], "roomId": room, "seq": state["seq"], "userId": player["uid"], "username": player["name"], "bet": player["cents"] / 100, "winAmount": payout / 100, "result": "win" if payout else "lose", "multiplier": payout / player["cents"], "pot": bank / 100, "winner": winner["name"], "winnerId": winner["uid"], "seedHash": state["commitHash"], "serverSeed": state["_seed"]}
                await connection.execute("INSERT INTO webapp_rounds(public_id,game,user_id,username,bet_cents,payout_cents,request_id,request_digest,response,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (state["id"] + "_" + str(player["uid"]), game, player["uid"], player["name"], player["cents"], payout, "pot_settle_" + state["id"], state["commitHash"], serialize(detail), self.clock().isoformat()))
        if state["phase"] == "finish" and now >= state["resultAt"]:
            state["phase"] = "result"
        if serialize(state) != row[0]:
            await self.save_pot(connection, state)
        if state["phase"] == "result" and now >= state["nextRoundAt"]:
            return await self.create_pot(connection, game, room, state["seq"] + 1)
        return state

    def pot_projection(self, state, user_id):
        result = {key: value for key, value in state.items() if not key.startswith("_")}
        cents = [player["cents"] for player in state["_players"]]
        bank = sum(cents)
        balls = pot_balls(cents)
        finished = state["phase"] in {"finish", "result"}
        visible_winner = state.get("_winnerIdx") if state["phase"] in {"live", "finish", "result"} else None
        paid = state.get("_paidCents", bank * 99 // 100)
        players = []
        for index, player in enumerate(state["_players"]):
            won = finished and index == visible_winner
            players.append({"uid": player["uid"], "id": player["uid"], "name": player["name"], "avatar": "/api/avatar/" + str(player["uid"]), "color": player["color"], "contribution": player["cents"] / 100, "share": player["cents"] / bank, "balls": balls[index], "isMe": player["uid"] == user_id, "isWinner": won, "prize": paid / 100 if won else 0, "multiplier": paid / player["cents"] if won else 0})
        result.update({"players": players, "playersCount": len(players), "totalPot": bank / 100, "ballsTotal": sum(balls), "winnerIdx": visible_winner})
        result["winner"] = dict(players[visible_winner]) if finished else None
        if state["game"] == "portal":
            result["layout"] = state.get("layout") or portal_layout(state["_seed"], state["id"], cents)
        return result

    def pot_summary(self, state, user_id):
        public = self.pot_projection(state, user_id)
        winner = public["winner"]
        summary = {"id": state["id"], "seq": state["seq"], "roomId": state["roomId"], "totalPot": public["totalPot"], "playersCount": len(public["players"]), "winnerName": winner["name"], "winnerId": winner["uid"], "winnerAvatar": winner["avatar"], "winnerColor": winner["color"], "prize": winner["prize"], "multiplier": winner["multiplier"], "finishedAt": state["finishedAt"]}
        own = next((player for player in public["players"] if player["isMe"]), None)
        if own:
            summary.update({"myBet": own["contribution"], "myWon": own["isWinner"], "myPrize": own["prize"]})
        return summary

    async def pot_response(self, connection, state, user_id):
        room_states = []
        for room in (1, 2):
            room_states.append(await self.advance_pot(connection, state["game"], room))
        current = room_states[state["roomId"] - 1]
        public = self.pot_projection(current, user_id)
        own = next((player for player in public["players"] if player["isMe"]), None)
        async with connection.execute("SELECT data FROM webapp_pot_rounds WHERE game = ? AND phase IN ('finish','result') ORDER BY rowid DESC LIMIT 30", (state["game"],)) as cursor:
            recent = [self.pot_summary(json.loads(row[0]), user_id) for row in await cursor.fetchall()]
        live = [self.pot_projection(value, user_id) for value in room_states if value["phase"] in {"live", "finish", "result"}]
        return {"ok": True, "serverTime": int(pot_now() * 1000), "config": {**POT_CONFIG, "raceSec": 30}, "room": {"id": current["roomId"], "name": current["roomName"]}, "rooms": [{"id": value["roomId"], "name": value["roomName"], "phase": value["phase"], "players": len(value["_players"]), "pot": sum(player["cents"] for player in value["_players"]) / 100, "live": value["phase"] in {"live", "finish"}} for value in room_states], "round": public, "me": {"inGame": own is not None, "contribution": own["contribution"] if own else 0}, "live": live, "liveRound": next((value for value in live if any(player["isMe"] for player in value["players"])), None), "recent": recent, "balance": await self.balance(connection, user_id)}

    async def handle_pot_action(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            game, action = request.path.split("/")[2:4]
            room = integer(payload.get("room", 1), 1, 2)
            key, signature = self.request_identity(request, payload)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    replay = await self.load_receipt(connection, user.id, key, signature)
                    state = await self.advance_pot(connection, game, room)
                    if not replay:
                        if payload.get("roundId") != state["id"]:
                            raise GameError("Раунд изменился. Обновите игру.", 409)
                        players = state["_players"]
                        own = next((player for player in players if player["uid"] == user.id), None)
                        if action == "cancel":
                            if state["phase"] != "waiting" or own is None:
                                raise GameError("Ставку уже нельзя отменить.", 409)
                            await self.credit(connection, user.id, own["cents"])
                            players.remove(own)
                        else:
                            if state["phase"] not in {"waiting", "betting"}:
                                raise GameError("Приём ставок закрыт.", 409)
                            if action == "join" and own:
                                raise GameError("Вы уже участвуете в раунде.", 409)
                            if action == "bet" and own is None:
                                raise GameError("Сначала войдите в раунд.", 409)
                            if own is None and len(players) >= 12:
                                raise GameError("В комнате уже 12 игроков.", 409)
                            cents = money_cents(payload.get("bet"))
                            if (own["cents"] if own else 0) + cents > 100000000:
                                raise GameError("Превышен предел ставки за раунд.")
                            await self.debit(connection, user.id, cents)
                            if own:
                                own["cents"] += cents
                            else:
                                players.append({"uid": user.id, "name": " ".join(part for part in (user.first_name, user.last_name) if part), "color": POT_COLORS[len(players)], "cents": cents})
                            if len(players) == 1:
                                state["_waitingUntil"] = int(pot_now() * 1000) + 600000
                            if len(players) >= 2 and state["phase"] == "waiting":
                                state.update({"phase": "betting", "bettingEndsAt": int(pot_now() * 1000) + 15000})
                        await self.save_pot(connection, state)
                    response = await self.pot_response(connection, state, user.id)
                    if not replay:
                        await self.save_receipt(connection, user.id, key, signature, response)
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)

    async def handle_pot_read(self, request):
        try:
            user = self.validate_user(request)
            game, action = request.path.split("/")[2:4]
            room = integer(request.query.get("room", "1"), 0 if action == "history" else 1, 2)
            offset = integer(request.query.get("offset", "0"), 0, 1000000)
            scope = request.query.get("scope", "all")
            query = request.query.get("q", "").strip()
            if scope not in {"all", "mine"} or len(query) > 100:
                raise GameError("Некорректный фильтр истории.")
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    current = {number: await self.advance_pot(connection, game, number) for number in (1, 2)}
                    state = current[room or 1]
                    if action == "state":
                        response = await self.pot_response(connection, state, user.id)
                    elif action in {"round", "frames"}:
                        identifier = request.query.get("id", "")
                        if not re.fullmatch(POT_GAMES[game] + r"[A-F0-9]{24}", identifier):
                            raise GameError("Некорректный UID раунда.")
                        async with connection.execute("SELECT data FROM webapp_pot_rounds WHERE id = ? AND game = ?", (identifier, game)) as cursor:
                            row = await cursor.fetchone()
                        if row is None:
                            raise GameError("Раунд не найден.", 404)
                        detail = json.loads(row[0])
                        if action == "frames":
                            if detail["phase"] not in {"live", "finish", "result"}:
                                raise GameError("Раунд ещё не начался.", 409)
                            response = {"ok": True, "roundId": identifier, "frames": detail["_frames"]}
                        else:
                            if detail["phase"] not in {"finish", "result"}:
                                raise GameError("Раунд ещё не завершён.", 409)
                            response = {"ok": True, **self.pot_projection(detail, user.id), "status": "finished", "feePercent": 1, "commission": (sum(player["cents"] for player in detail["_players"]) - detail["_paidCents"]) / 100, "fairness": {"commitHash": detail["commitHash"], "serverSeed": detail["_seed"]}}
                            if game == "portal":
                                response["frames"] = detail["_frames"]
                    elif action == "howto":
                        async with connection.execute("SELECT data FROM webapp_pot_rounds WHERE game = ? AND phase IN ('finish','result') ORDER BY rowid DESC LIMIT 1", (game,)) as cursor:
                            record = await cursor.fetchone()
                        if record is None:
                            response = {"ok": False, "error": "Нет завершённого раунда для примера."}
                        else:
                            example = json.loads(record[0])
                            response = {"ok": True, **self.pot_projection(example, user.id), "roundId": example["id"], "feePercent": 1}
                            response.update({"prize": response["winner"]["prize"], "multiplier": response["winner"]["multiplier"], "courseSeed": hashlib.sha256((example["commitHash"] + ":" + example["id"] + ":course").encode()).hexdigest()})
                            if game == "portal":
                                response.update({"frames": example["_frames"], "layouts": [portal_layout(example["_seed"], example["id"], [player["cents"] for player in example["_players"][:count]]) for count in range(1, len(example["_players"]) + 1)]})
                    else:
                        conditions = ["game = ?", "phase IN ('finish','result')"]
                        values = [game]
                        if room:
                            conditions.append("room = ?")
                            values.append(room)
                        if scope == "mine":
                            conditions.append("EXISTS (SELECT 1 FROM json_each(json_extract(data,'$._players')) WHERE json_extract(value,'$.uid') = ?)")
                            values.append(user.id)
                        if query:
                            conditions.append("(id = ? OR CAST(seq AS TEXT) = ? OR date(json_extract(data,'$.finishedAt'),'unixepoch') = ?)")
                            values.extend([query, query, query])
                        async with connection.execute("SELECT data FROM webapp_pot_rounds WHERE " + " AND ".join(conditions) + " ORDER BY rowid DESC LIMIT 20 OFFSET ?", values + [offset]) as cursor:
                            records = [json.loads(row[0]) for row in await cursor.fetchall()]
                        response = {"ok": True, "rows": [self.pot_summary(value, user.id) for value in records]}
                    await connection.commit()
                    return self.response(response)
                except BaseException:
                    await connection.rollback()
                    raise
        except GameError as error:
            return self.failure(error)
'''

# ==================== pot_rules.py ====================
_SOURCES['pot_rules'] = r'''import math

from game_rules import digest, unit


POT_GAMES = {"portal": "PT", "race": "RC", "bomb": "BM", "sumo": "SM"}
POT_COLORS = ["#E21BE0", "#FF8A3D", "#1FE8A4", "#4560FF", "#F2D04F", "#14B8D4", "#FF5370", "#A38AFF", "#9DCE55", "#F080B5", "#EAB18A", "#70B0EE"]
POT_CONFIG = {"houseFee": 0.01, "minBet": 0.1, "maxBet": 1000000, "maxPlayers": 12, "minPlayers": 2, "bettingSec": 15, "countdownSec": 3, "resultSec": 6, "waitTtl": 600}


def pot_winner(seed, identifier, cents):
    target = int(unit(seed, identifier + ":winner") * sum(cents))
    cumulative = 0
    for index, value in enumerate(cents):
        cumulative += value
        if cumulative > target:
            return index
    return len(cents) - 1


def pot_live_seconds(game, count):
    if game == "bomb":
        return math.floor(min(30, max(12, 9 + 1.8 * (count - 1))) * 10 + 0.5) / 10
    if game == "sumo":
        return math.floor(min(20, max(12, 10 + 0.9 * count)) * 10 + 0.5) / 10
    return 30 if game == "race" else 12


def pot_balls(cents):
    count = len(cents)
    if not count:
        return []
    total = 30 if count <= 5 else min(60, 6 * count)
    quotas = [value / sum(cents) * total for value in cents]
    balls = [max(1, math.floor(value)) for value in quotas]
    while sum(balls) < total:
        index = max(range(count), key=lambda index: quotas[index] - balls[index])
        balls[index] += 1
    while sum(balls) > total:
        index = max((index for index in range(count) if balls[index] > 1), key=lambda index: balls[index] - quotas[index])
        balls[index] -= 1
    return balls


def portal_layout(seed, identifier, cents):
    if not cents:
        return {"seeds": [], "weights": []}
    total = sum(cents)
    bounds = [0]
    for value in cents:
        bounds.append(bounds[-1] + value / total * 1000)
    positions = [(bounds[index] + bounds[index + 1]) / 2 for index in range(len(cents))]
    weights = [0]
    for index in range(len(cents) - 1):
        left, right = positions[index:index + 2]
        weights.append(weights[-1] + right * right - left * left - 2 * (right - left) * bounds[index + 1])
    vertical = unit(seed, identifier + ":layout") < 0.5
    middle = 300 + 400 * unit(seed, identifier + ":layout:middle")
    return {"seeds": [[value, middle] if vertical else [middle, value] for value in positions], "weights": weights}


def portal_motion(seed, identifier):
    hexadecimal = digest(seed, identifier + ":orb")
    number = lambda offset: int(hexadecimal[offset:offset + 13], 16) / 16 ** 13
    x, y, angle = number(0) * 1000, number(13) * 1000, number(26) * math.tau
    speed = 1200 + number(39) * 800
    duration = 9.5
    frames = []
    def reflect(value):
        value %= 2000
        return value if value <= 1000 else 2000 - value
    for index in range(571):
        elapsed = duration * index / 570
        distance = speed * (elapsed - elapsed * elapsed / (2 * duration))
        frames.append([round(elapsed * 1000, 6), reflect(x + math.cos(angle) * distance), reflect(y + math.sin(angle) * distance), speed * (1 - elapsed / duration)])
    return {"x": x, "y": y, "launchAngle": angle, "speed": speed}, frames


def portal_owner(layout, point):
    x, y = point
    return min(range(len(layout["seeds"])), key=lambda index: (x - layout["seeds"][index][0]) ** 2 + (y - layout["seeds"][index][1]) ** 2 - layout["weights"][index])
'''

# ==================== privacy_rules.py ====================
_SOURCES['privacy_rules'] = r'''import json


PRIVACY_CACHE = {}
TELEGRAM_NAMES = {}


def player_identity(user_id, fallback):
    state = PRIVACY_CACHE.get(user_id)
    if not state:
        return fallback, True
    mode, nickname, hidden, clickable, game_uid = state
    if mode == "username" and TELEGRAM_NAMES.get(user_id):
        fallback = "@" + TELEGRAM_NAMES[user_id]
    name = {"hidden": "Аноним", "blank": " ", "game_id": "Игрок #" + game_uid, "nickname": nickname}.get(mode, fallback)
    return name, bool(clickable) and mode in {"username", "nickname"}


def public_names(value):
    if isinstance(value, list):
        return [public_names(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: public_names(item) for key, item in value.items()}
    for user_key, names in (("uid", ("name",)), ("user_id", ("username", "name")), ("userId", ("username", "name")), ("creatorId", ("creatorName",)), ("opponentId", ("opponentName",)), ("winnerId", ("winnerName", "winner"))):
        user_id = value.get(user_key)
        if isinstance(user_id, int):
            for field in names:
                if isinstance(result.get(field), str):
                    result[field], clickable = player_identity(user_id, result[field])
                    if not clickable:
                        result["clickableProfile"] = False
    if isinstance(result.get("meta"), str):
        try:
            result["meta"] = json.dumps(public_names(json.loads(result["meta"])), ensure_ascii=False, separators=(",", ":"))
        except (ValueError, TypeError):
            pass
    return result
'''

# ==================== pvp_games.py ====================
_SOURCES['pvp_games'] = r'''import asyncio
import json
import logging
import re
import secrets

from aiogram.exceptions import TelegramRetryAfter

from blackjack_pvp import BlackjackPvpMixin
from games_backend import GameError, integer, money_cents, serialize


PVP_EMOJI = {"dice": "🎲", "bowling": "🎳", "darts": "🎯", "basketball": "🏀", "football": "⚽", "slots": "🎰"}
PVP_GAMES = set(PVP_EMOJI) | {"blackjack"}
SLOT_SYMBOLS = ["Бар", "Виноград", "Лимон", "Семёрка"]


def slot_reels(value):
    return [SLOT_SYMBOLS[(value - 1) // 4 ** index % 4] for index in range(3)]


def duel_score(game, value):
    if game == "slots":
        reels = slot_reels(value)
        return {"Семёрка": 4, "Бар": 3, "Виноград": 2, "Лимон": 1}[reels[0]] if len(set(reels)) == 1 else 0
    if game == "football":
        return int(value >= 3)
    if game == "darts":
        return [0, 0, 1, 1, 2, 2, 3][value]
    return value


class PvpGamesMixin(BlackjackPvpMixin):
    def register_pvp(self, application):
        self.register_blackjack_pvp(application)
        for game in sorted(PVP_GAMES):
            for action in ("create", "join", "cancel"):
                application.router.add_post(f"/api/pvp/{game}/{action}", self.handle_pvp_action)
            for action in ("active", "active-search", "my-rooms", "room", "round", "history"):
                application.router.add_get(f"/api/pvp/{game}/{action}", self.handle_pvp_read)
        application.router.add_get("/api/pvp/search", self.handle_pvp_read)
        application.router.add_get("/api/pvp/active-all", self.handle_pvp_read)
        application.router.add_get("/api/pvp/my-rounds", self.handle_pvp_read)

    async def initialize_pvp(self):
        self.pvp_tasks = {}
        self.pvp_telegram_lock = asyncio.Lock()
        async with self.database_lock:
            connection = self.database()
            try:
                await connection.execute("BEGIN IMMEDIATE")
                await connection.execute("CREATE TABLE IF NOT EXISTS webapp_pvp_rooms(id TEXT PRIMARY KEY,game TEXT NOT NULL,creator_id INTEGER NOT NULL,opponent_id INTEGER,status TEXT NOT NULL,data TEXT NOT NULL)")
                await connection.execute("CREATE INDEX IF NOT EXISTS idx_webapp_pvp_list ON webapp_pvp_rooms(game,status,creator_id)")
                async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE status = 'active'") as cursor:
                    interrupted = [json.loads(row[0]) for row in await cursor.fetchall()]
                for state in interrupted:
                    await self.refund_pvp(connection, state, "Раунд прерван перезапуском сервера. Обе ставки возвращены.")
                await self.advance_blackjack_pvp(connection)
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    async def cleanup_pvp(self):
        if self.pvp_tasks:
            await asyncio.gather(*list(self.pvp_tasks.values()), return_exceptions=True)

    def pvp_public(self, state):
        result = {key: value for key, value in state.items() if not key.startswith("_")}
        result.update({"id": state["roomId"], "bet": state["betAmount"], "bet_amount": state["betAmount"], "created_at": state["createdAt"], "avatarUrl": "/api/avatar/" + str(state["creatorId"])})
        return result

    async def save_pvp(self, connection, state):
        await connection.execute("UPDATE webapp_pvp_rooms SET status = ?,opponent_id = ?,data = ? WHERE id = ?", (state["status"], state.get("opponentId"), serialize(state), state["roomId"]))

    async def pvp_response(self, connection, state, user_id):
        response = {"ok": state["status"] != "error", **self.pvp_public(state), "balance": await self.balance(connection, user_id)}
        if state["game"] == "blackjack":
            self.blackjack_pvp_projection(response, state, user_id)
        return response

    async def refund_pvp(self, connection, state, message):
        if state["status"] != "active":
            return
        await self.credit(connection, state["creatorId"], state["_betCents"])
        await self.credit(connection, state["opponentId"], state["_betCents"])
        state.update({"ok": False, "status": "error", "error": message, "refunded": True, "feeAmount": 0, "winAmount": 0, "finishedAt": self.clock().isoformat()})
        await self.save_pvp(connection, state)
        await connection.execute("UPDATE webapp_requests SET response = ? WHERE user_id = ? AND request_id = ?", (serialize(await self.pvp_response(connection, state, state["opponentId"])), state["opponentId"], state["_joinKey"]))

    async def telegram_duel_roll(self, game):
        if not getattr(self, "telegram_bot", None) or not getattr(self, "telegram_channel", None):
            raise RuntimeError("Telegram game channel is not configured")
        for attempt in range(3):
            try:
                message = await self.telegram_bot.send_dice(chat_id=self.telegram_channel, emoji=PVP_EMOJI[game], request_timeout=20)
                value = integer(message.dice.value, 1, 64 if game == "slots" else 5 if game in {"football", "basketball"} else 6)
                username = message.chat.username
                if username:
                    link = f"https://t.me/{username}/{message.message_id}"
                elif str(message.chat.id).startswith("-100"):
                    link = f"https://t.me/c/{str(message.chat.id)[4:]}/{message.message_id}"
                else:
                    raise RuntimeError("Dice proof must point to the game channel")
                return value, link
            except TelegramRetryAfter as error:
                if attempt == 2 or error.retry_after > 20:
                    raise
                await asyncio.sleep(error.retry_after)

    async def play_pvp_duel(self, room_id):
        try:
            async with self.database_lock:
                async with self.database().execute("SELECT data FROM webapp_pvp_rooms WHERE id = ? AND status = 'active'", (room_id,)) as cursor:
                    row = await cursor.fetchone()
            if row is None:
                return
            state = json.loads(row[0])
            try:
                async with asyncio.timeout(90):
                    async with self.pvp_telegram_lock:
                        first = await self.telegram_duel_roll(state["game"])
                        second = await self.telegram_duel_roll(state["game"])
                error_message = None
            except Exception:
                logging.exception("Telegram PvP rolls failed for %s", room_id)
                error_message = "Не удалось провести бой. Обе ставки возвращены."
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ? AND status = 'active'", (room_id,)) as cursor:
                        row = await cursor.fetchone()
                    if row:
                        state = json.loads(row[0])
                        if error_message:
                            await self.refund_pvp(connection, state, error_message)
                        else:
                            scores = [duel_score(state["game"], first[0]), duel_score(state["game"], second[0])]
                            draw = scores[0] == scores[1]
                            bank = state["_betCents"] * 2
                            paid = state["_betCents"] if draw else bank * 99 // 100
                            winner = None if draw else state["creatorId"] if scores[0] > scores[1] else state["opponentId"]
                            if draw:
                                await self.credit(connection, state["creatorId"], paid)
                                await self.credit(connection, state["opponentId"], paid)
                            else:
                                await self.credit(connection, winner, paid)
                            state.update({"status": "finished", "creatorResult": first[0], "opponentResult": second[0], "creatorCheckLink": first[1], "opponentCheckLink": second[1], "isDraw": draw, "winnerId": winner, "winAmount": paid / 100, "feeAmount": 0 if draw else (bank - paid) / 100, "commissionPercent": 1, "finishedAt": self.clock().isoformat()})
                            if state["game"] == "slots":
                                state.update({"creatorReels": slot_reels(first[0]), "opponentReels": slot_reels(second[0])})
                            if state["game"] == "bowling":
                                state.update({"creatorLabel": str([0, 1, 3, 4, 5, 6][first[0] - 1]) + " кеглей", "opponentLabel": str([0, 1, 3, 4, 5, 6][second[0] - 1]) + " кеглей"})
                            else:
                                state.update({"creatorLabel": " · ".join(state["creatorReels"]) if state["game"] == "slots" else str(first[0]), "opponentLabel": " · ".join(state["opponentReels"]) if state["game"] == "slots" else str(second[0])})
                            await self.save_pvp(connection, state)
                            await connection.execute("UPDATE webapp_requests SET response = ? WHERE user_id = ? AND request_id = ?", (serialize(await self.pvp_response(connection, state, state["opponentId"])), state["opponentId"], state["_joinKey"]))
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
        except Exception:
            logging.exception("PvP settlement failed for %s", room_id)
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ? AND status = 'active'", (room_id,)) as cursor:
                        row = await cursor.fetchone()
                    if row:
                        await self.refund_pvp(connection, json.loads(row[0]), "Не удалось завершить расчёт боя. Обе ставки возвращены.")
                    await connection.commit()
                except BaseException:
                    await connection.rollback()
                    raise
        finally:
            self.pvp_tasks.pop(room_id, None)

    async def handle_pvp_action(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            game, action = request.path.split("/")[3:5]
            key, signature = self.request_identity(request, payload)
            if game == "blackjack" and action in {"hit", "stand", "double"}:
                return await self.handle_blackjack_pvp_move(request, payload, user, key, signature)
            if game != "blackjack" and action == "create" and (not getattr(self, "telegram_bot", None) or not getattr(self, "telegram_channel", None)):
                raise GameError("Telegram PvP временно недоступен.", 503)
            pending_id = None
            async with self.database_lock:
                connection = self.database()
                try:
                    await connection.execute("BEGIN IMMEDIATE")
                    replay = await self.load_receipt(connection, user.id, key, signature)
                    if replay:
                        if replay.get("status") == "active" and action == "join":
                            pending_id = replay["roomId"]
                        else:
                            await connection.commit()
                            return self.response(replay)
                    if not replay:
                        if action == "create":
                            cents = money_cents(payload.get("bet"))
                            async with connection.execute("SELECT COUNT(*) FROM webapp_pvp_rooms WHERE creator_id = ? AND game = ? AND status IN ('waiting','active','playing')", (user.id, game)) as cursor:
                                count = (await cursor.fetchone())[0]
                            if count >= 10:
                                raise GameError("Достигнут предел 10 активных комнат.", 409)
                            await self.debit(connection, user.id, cents)
                            room_id = "P" + secrets.token_hex(8).upper()
                            state = {"roomId": room_id, "game": game, "creatorId": user.id, "creatorName": " ".join(part for part in (user.first_name, user.last_name) if part), "betAmount": cents / 100, "status": "waiting", "createdAt": self.clock().isoformat(), "_betCents": cents}
                            if game == "blackjack":
                                self.prepare_blackjack_pvp(state)
                            await connection.execute("INSERT INTO webapp_pvp_rooms(id,game,creator_id,status,data) VALUES (?,?,?,?,?)", (room_id, game, user.id, state["status"], serialize(state)))
                        else:
                            room_id = payload.get("roomId")
                            if not isinstance(room_id, str) or not re.fullmatch(r"P[A-F0-9]{16}", room_id):
                                raise GameError("Некорректный идентификатор комнаты.")
                            async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ? AND game = ?", (room_id, game)) as cursor:
                                row = await cursor.fetchone()
                            if row is None:
                                raise GameError("Комната не найдена.", 404)
                            state = json.loads(row[0])
                            if state["status"] != "waiting":
                                raise GameError("Комната уже закрыта или бой начался.", 409)
                            if action == "cancel":
                                if state["creatorId"] != user.id:
                                    raise GameError("Нет доступа к чужой комнате.", 403)
                                await self.credit(connection, user.id, state["_betCents"])
                                state.update({"status": "canceled", "refunded": True, "finishedAt": self.clock().isoformat()})
                            else:
                                if state["creatorId"] == user.id:
                                    raise GameError("Нельзя играть против себя.")
                                await self.debit(connection, user.id, state["_betCents"])
                                state.update({"status": "active", "opponentId": user.id, "opponentName": " ".join(part for part in (user.first_name, user.last_name) if part), "_joinKey": key})
                                if game == "blackjack":
                                    self.deal_blackjack_pvp(state)
                                else:
                                    pending_id = room_id
                            await self.save_pvp(connection, state)
                            if game == "blackjack":
                                await self.finish_blackjack_pvp(connection, state)
                        response = await self.pvp_response(connection, state, user.id)
                        await self.save_receipt(connection, user.id, key, signature, response)
                    await connection.commit()
                    if pending_id and pending_id not in self.pvp_tasks:
                        if replay:
                            try:
                                await connection.execute("BEGIN IMMEDIATE")
                                async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ?", (pending_id,)) as cursor:
                                    state = json.loads((await cursor.fetchone())[0])
                                await self.refund_pvp(connection, state, "Не удалось завершить бой. Обе ставки возвращены.")
                                await connection.commit()
                            except BaseException:
                                await connection.rollback()
                                raise
                        else:
                            self.pvp_tasks[pending_id] = asyncio.create_task(self.play_pvp_duel(pending_id))
                    task = self.pvp_tasks.get(pending_id)
                except BaseException:
                    await connection.rollback()
                    raise
            if task:
                await asyncio.shield(task)
            if pending_id:
                async with self.database_lock:
                    connection = self.database()
                    async with connection.execute("SELECT data FROM webapp_pvp_rooms WHERE id = ?", (pending_id,)) as cursor:
                        state = json.loads((await cursor.fetchone())[0])
                    response = await self.pvp_response(connection, state, user.id)
            return self.response(response)
        except GameError as error:
            return self.failure(error)

    async def handle_pvp_read(self, request):
        try:
            user = self.validate_user(request)
            parts = request.path.split("/")
            action = parts[-1]
            game = parts[3] if len(parts) == 5 else request.query.get("game", "")
            if game and game not in PVP_GAMES:
                raise GameError("Неизвестная PvP-игра.")
            offset = integer(request.query.get("offset", "0"), 0, 1000000)
            scope = request.query.get("scope", "all")
            if scope not in {"all", "mine"}:
                raise GameError("Неизвестный фильтр.")
            conditions, values = [], []
            if game:
                conditions.append("game = ?")
                values.append(game)
            identifier = request.query.get("id")
            if action in {"room", "round", "active-search", "search"}:
                conditions.append("id = ?")
                values.append(identifier)
            elif action in {"active", "active-all"}:
                conditions.append("status = 'waiting'")
            elif action == "my-rooms":
                conditions.append("status IN ('waiting','active','playing') AND creator_id = ?")
                values.append(user.id)
            else:
                conditions.append("status = 'finished'")
            query = request.query.get("q", "").strip()
            if len(query) > 100:
                raise GameError("Слишком длинный запрос.")
            if query:
                conditions.append("(id = ? OR CAST(creator_id AS TEXT) = ? OR CAST(opponent_id AS TEXT) = ?)")
                values.extend([query, query, query])
            if scope == "mine" or action == "my-rounds":
                conditions.append("(creator_id = ? OR opponent_id = ?)")
                values.extend([user.id, user.id])
            async with self.database_lock:
                connection = self.database()
                async with connection.execute("SELECT data FROM webapp_pvp_rooms" + (" WHERE " + " AND ".join(conditions) if conditions else "") + " ORDER BY rowid DESC LIMIT 21 OFFSET ?", values + [offset]) as cursor:
                    rows = [self.pvp_public(json.loads(row[0])) for row in await cursor.fetchall()]
                if action in {"room", "round", "active-search", "search"}:
                    if not rows or action == "round" and rows[0]["status"] != "finished" or action == "active-search" and rows[0]["status"] != "waiting":
                        raise GameError("Комната не найдена.", 404)
                    state = rows[0]
                    response = {**state, "ok": True, "room": state, "balance": await self.balance(connection, user.id)}
                else:
                    response = {"ok": True, "rows": rows[:20], "rooms": rows[:20], "hasMore": len(rows) > 20}
                return self.response(response)
        except GameError as error:
            return self.failure(error)
'''

# ==================== realtime_backend.py ====================
_SOURCES['realtime_backend'] = r'''"""Read-only WebSocket updates; all money-changing commands remain signed HTTP POSTs."""
import asyncio
import json
import secrets
import time
from urllib.parse import urlsplit

from aiohttp import web, WSMsgType
from pot_rules import POT_GAMES


class RealtimeMixin:
    def register_realtime(self, app):
        self.realtime_public_cache = (0, [])
        self.realtime_pending = 0
        self.realtime_tickets = {}
        self.realtime_sockets = set()
        self.realtime_users = {}
        app.router.add_post('/api/realtime/session', self.handle_realtime_session)
        app.router.add_get('/api/ws', self.handle_realtime_socket)

    async def handle_realtime_session(self, request):
        user = self.validate_user(request)
        now = time.monotonic()
        self.realtime_tickets = {k: v for k, v in self.realtime_tickets.items() if v[1] > now}
        owned = [k for k, v in self.realtime_tickets.items() if v[0] == user.id]
        for key in owned[:-4]:
            self.realtime_tickets.pop(key, None)
        if len(self.realtime_tickets) >= 2000:
            return self.response({'ok': False, 'error': 'Попробуйте позже.'}, 429)
        ticket = secrets.token_urlsafe(32)
        self.realtime_tickets[ticket] = (user.id, now + 30)
        return self.response({'ok': True, 'ticket': ticket, 'expiresIn': 30, 'path': '/api/ws'})

    async def realtime_snapshot(self, user_id):
        async with self.database_lock:
            db = self.database()
            balance = await self.balance(db, user_id)
            where, args = ('', ()) if self.support_admin(user_id) else ('WHERE user_id=?', (user_id,))
            async with db.execute('SELECT COUNT(*),COALESCE(SUM(rev),0) FROM webapp_support_tickets ' + where, args) as cur:
                support_rev = list(await cur.fetchone())
            # Public game phases are identical for every viewer. Cache only this whitelist;
            # each user's balance and support revision are always read fresh above.
            until, live = self.realtime_public_cache
            if time.monotonic() >= until:
                async with db.execute('SELECT id,game,data FROM webapp_live_rounds WHERE finished=0 ORDER BY game,id') as cur:
                    live = [{'roundId': row[0], 'game': row[1], 'phase': json.loads(row[2]).get('status')} for row in await cur.fetchall()]
                rooms = [(game, room) for game in POT_GAMES for room in (1, 2)]
                values = ','.join('(?,?)' for _ in rooms)
                sql = f"""WITH rooms(game,room) AS (VALUES {values})
                    SELECT id,game,room,phase FROM webapp_pot_rounds WHERE id IN (
                        SELECT (SELECT id FROM webapp_pot_rounds r WHERE r.game=rooms.game AND r.room=rooms.room ORDER BY seq DESC LIMIT 1) FROM rooms
                    ) ORDER BY game,room"""
                async with db.execute(sql, [value for pair in rooms for value in pair]) as cur:
                    live += [{'roundId': row[0], 'game': row[1], 'room': row[2], 'phase': row[3]} for row in await cur.fetchall()]
                self.realtime_public_cache = (time.monotonic() + 0.5, live)
        return {'type': 'state', 'balance': balance, 'supportRevision': support_rev, 'games': live}

    async def handle_realtime_socket(self, request):
        origin = request.headers.get('Origin')
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in {'https', 'http'} or parsed.netloc != request.host:
                raise web.HTTPForbidden()
        if len(self.realtime_sockets) + self.realtime_pending >= 64:
            raise web.HTTPServiceUnavailable(headers={'Retry-After': '10'})
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4096, receive_timeout=60)
        self.realtime_pending += 1
        try:
            await ws.prepare(request)
            self.realtime_sockets.add(ws)
        finally:
            self.realtime_pending -= 1
        user_id = None
        try:
            try:
                message = await asyncio.wait_for(ws.receive(), timeout=5)
                data = json.loads(message.data) if message.type == WSMsgType.TEXT else None
                ticket = data.get('ticket') if isinstance(data, dict) else None
                auth = self.realtime_tickets.pop(ticket, None) if isinstance(ticket, str) else None
                if auth is None or auth[1] <= time.monotonic():
                    await ws.close(code=1008, message=b'Authentication required')
                    return ws
                candidate = auth[0]
                if self.realtime_users.get(candidate, 0) >= 3:
                    await ws.close(code=1008, message=b'Too many connections')
                    return ws
                user_id = candidate
                self.realtime_users[user_id] = self.realtime_users.get(user_id, 0) + 1
            except (ValueError, TypeError, asyncio.TimeoutError):
                await ws.close(code=1008, message=b'Authentication required')
                return ws
            await ws.send_json({'type': 'ready', 'readOnly': True})
            previous = None
            expires = time.monotonic() + 900
            while not ws.closed and time.monotonic() < expires:
                snapshot = await self.realtime_snapshot(user_id)
                if snapshot != previous:
                    await ws.send_json({**snapshot, 'serverTime': int(time.time() * 1000)})
                    previous = snapshot
                # Client messages never execute wagers, credits or support/admin actions.
                try:
                    incoming = await asyncio.wait_for(ws.receive(), timeout=2)
                    if incoming.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR}:
                        break
                    await ws.close(code=1008, message=b'Read-only connection')
                    break
                except asyncio.TimeoutError:
                    pass
            await ws.close(code=1000, message=b'Reconnect to renew session')
            return ws
        finally:
            self.realtime_sockets.discard(ws)
            if user_id is not None:
                self.realtime_users[user_id] -= 1
                if not self.realtime_users[user_id]:
                    self.realtime_users.pop(user_id, None)

    async def cleanup_realtime(self):
        await asyncio.gather(*(ws.close(code=1001, message=b'Server shutdown') for ws in list(self.realtime_sockets)), return_exceptions=True)
        self.realtime_tickets.clear()
'''

# ==================== star_withdrawals.py ====================
_SOURCES['star_withdrawals'] = r'''"""Durable Stars reservations. A Fragment POST is never automatically replayed."""
import asyncio
import hashlib
import json
import logging
import re
import secrets
from sqlite3 import IntegrityError
import time
import uuid
from decimal import Decimal, InvalidOperation
from datetime import timedelta

import aiohttp
from games_backend import GameError, integer, serialize


STATES = {'CREATED', 'PENDING', 'BLOCKCHAIN_SENT', 'COMPLETED', 'FAILED'}
OPEN_STATES = ('queued', 'submitting', 'pending', 'blockchain_sent', 'uncertain', 'mismatch')


class StarWithdrawalsMixin:
    def register_star_withdrawals(self, app):
        app.router.add_get('/api/withdraw/info', self.handle_star_withdraw_info)
        app.router.add_post('/api/withdraw/quote', self.handle_star_withdraw_quote)
        app.router.add_post('/api/withdraw/confirm', self.handle_star_withdraw_confirm)
        app.router.add_get('/api/withdraw/job', self.handle_star_withdraw_status)
        app.router.add_get('/api/withdraw/status', self.handle_star_withdraw_status)

    def fragment_settings(self):
        from payments_backend import FRAGMENT_API_JWT, FRAGMENT_CURRENCY
        token = getattr(self, 'fragment_jwt', FRAGMENT_API_JWT).strip()
        currency = getattr(self, 'fragment_currency', FRAGMENT_CURRENCY)
        if currency not in {'ton', 'usdt_ton'} or not token or not token.isascii() or any(c.isspace() for c in token):
            raise GameError('Вывод Stars ещё не настроен. Администратору нужно заполнить Fragment Connection JWT и валюту оплаты на сервере.', 503)
        return token, currency, hashlib.sha256(token.encode()).hexdigest()

    async def star_execute_commit(self, db, sql, args=()):
        try:
            cursor = await db.execute(sql, args)
            await db.commit()
            return cursor
        except BaseException:
            await db.rollback()
            raise

    async def initialize_star_withdrawals(self):
        async with self.database_lock:
            db = self.database()
            await db.execute('CREATE TABLE IF NOT EXISTS webapp_star_quotes(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,username TEXT NOT NULL,quantity INTEGER NOT NULL,expires_at INTEGER NOT NULL,created_at INTEGER NOT NULL,used_id TEXT)')
            await db.execute('CREATE INDEX IF NOT EXISTS idx_star_quotes_user ON webapp_star_quotes(user_id,created_at)')
            await db.execute('CREATE TABLE IF NOT EXISTS webapp_star_withdrawals(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,username TEXT NOT NULL,quantity INTEGER NOT NULL,state TEXT NOT NULL,provider_id TEXT UNIQUE,token_hash TEXT NOT NULL,currency TEXT NOT NULL,request_key TEXT NOT NULL,digest TEXT NOT NULL,quote_id TEXT NOT NULL UNIQUE,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,error_code TEXT,provider_costs TEXT,UNIQUE(user_id,request_key))')
            await db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_star_withdraw_open ON webapp_star_withdrawals(user_id) WHERE state IN ('queued','submitting','pending','blockchain_sent','uncertain','mismatch')")
            # A previous process may have sent this POST. There is no documented
            # provider-side create idempotency or lookup by our local request key.
            await db.execute("UPDATE webapp_star_withdrawals SET state='uncertain',error_code='PROCESS_RESTART_DURING_POST' WHERE state='submitting'")
            await db.commit()
        self.star_withdraw_task = asyncio.create_task(self.star_withdraw_loop())

    async def cleanup_star_withdrawals(self):
        if hasattr(self, 'star_withdraw_task'):
            self.star_withdraw_task.cancel()
            await asyncio.gather(self.star_withdraw_task, return_exceptions=True)

    async def fragment_api(self, method, path, data=None, token_hash=None):
        token, currency, fingerprint = self.fragment_settings()
        if token_hash and fingerprint != token_hash:
            raise GameError('Для проверки заказа требуется исходный Fragment JWT. Автоповтор и возврат заблокированы.', 503)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.request(method, 'https://api.fragment-api.com/v1/' + path, headers={'Authorization': 'JWT ' + token, 'Accept': 'application/json'}, json=data if method == 'POST' else None, allow_redirects=False) as response:
                    if response.status not in ({200, 201, 202} if method == 'POST' else {200}):
                        # No raw body, JWT, sender phone number, or third-party error dump.
                        raise GameError('Fragment API отклонил запрос. Не повторяйте отправку автоматически.', 502, 'FRAGMENT_HTTP_' + str(response.status))
                    result = await response.json(content_type=None)
                    if not isinstance(result, dict):
                        raise ValueError
                    return result
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, UnicodeError):
            raise GameError('Результат запроса Fragment не подтверждён. Повторная покупка отключена; требуется проверка заказа.', 502, 'FRAGMENT_UNCONFIRMED') from None

    def star_username(self, user):
        username = getattr(user, 'username', None)
        if not isinstance(username, str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{2,31}', username):
            raise GameError('Для получения Stars установите Telegram username и заново откройте Mini App.', 400)
        return username

    async def star_order(self, db, identifier, user_id=None):
        sql = 'SELECT * FROM webapp_star_withdrawals WHERE id=?'
        args = [identifier]
        if user_id is not None:
            sql += ' AND user_id=?'
            args.append(user_id)
        async with db.execute(sql, args) as cursor:
            row = await cursor.fetchone()
            columns = [item[0] for item in cursor.description]
        if not row:
            raise GameError('Вывод не найден.', 404)
        return dict(zip(columns, row))

    async def star_result(self, db, order):
        state = order['state']
        status = 'done' if state == 'completed' else 'failed' if state == 'failed' else 'slow' if state in {'uncertain', 'mismatch'} else 'processing'
        return {'ok': True, 'status': status, 'state': 'done' if state == 'completed' else state, 'job': order['id'], 'withdrawalId': order['id'], 'coin': 'Stars', 'sendAmount': order['quantity'], 'usd': order['quantity'], 'username': order['username'], 'balance': await self.balance(db, order['user_id']), 'refunded': state == 'failed', 'message': 'Провайдер подтвердил отказ. Резерв возвращён на баланс.' if state == 'failed' else 'Заказ требует проверки. Сумма остаётся в резерве; не создавайте повторную заявку.' if status == 'slow' else ''}

    async def ensure_star_withdraw_requirements(self, db, user_id):
        await self.ensure_check_wager(db, user_id)
        runtime = getattr(self, 'wallet_runtime', {})
        minimum = runtime.get('WITHDRAW_MIN_DEPOSIT', 50)
        days = runtime.get('WITHDRAW_DEPOSIT_DAYS', 7)
        since = (self.clock() - timedelta(days=days)).isoformat()
        async with db.execute("SELECT COALESCE(SUM(amount),0) FROM (SELECT user_id,amount,created_at FROM payments UNION ALL SELECT user_id,stars_cents/100.0,COALESCE(paid_at,created_at) FROM webapp_deposits WHERE provider!='stars' AND status='paid') WHERE user_id=? AND julianday(created_at)>=julianday(?)", (user_id, since)) as cursor:
            deposited = (await cursor.fetchone())[0]
        if deposited < minimum:
            raise GameError(f'Для вывода нужен депозит не менее {minimum} Stars за последние {days} дней. Сейчас: {deposited:g} Stars.', 403)

    async def handle_star_withdraw_info(self, request):
        try:
            user = self.validate_user(request)
            reason = ''
            try:
                self.fragment_settings()
                username = self.star_username(user)
            except GameError as error:
                reason, username = error.message, ''
            async with self.database_lock:
                db = self.database()
                balance = await self.balance(db, user.id)
                try:
                    await self.ensure_star_withdraw_requirements(db, user.id)
                except GameError as error:
                    reason = error.message
                async with db.execute("SELECT id FROM webapp_star_withdrawals WHERE user_id=? AND state NOT IN ('completed','failed')", (user.id,)) as cursor:
                    pending = await cursor.fetchone()
                active = await self.star_result(db, await self.star_order(db, pending[0], user.id)) if pending else None
            if not reason and balance < 50:
                reason = 'Минимум вывода — 50 Stars.'
            return self.response({'ok': True, 'eligible': not reason and not pending, 'balance': balance, 'username': username, 'methods': [{'id': 'stars', 'min': 50, 'max': min(1000000, int(balance))}], 'limits': {'min': 50, 'max': min(1000000, int(balance))}, 'manual': False, 'activeWithdrawal': active, 'block': {'title': 'Вывод Stars недоступен', 'text': reason or 'Предыдущая заявка ещё обрабатывается.', 'bars': []}})
        except GameError as error:
            return self.failure(error)

    async def handle_star_withdraw_quote(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            self.fragment_settings()
            username = self.star_username(user)
            if payload.get('method') != 'stars' or payload.get('coin', 'XTR') != 'XTR':
                raise GameError('Доступен только вывод Stars.')
            quantity = integer(payload.get('amount'), 50, 1000000)
            now = int(time.time())
            async with self.database_lock:
                db = self.database()
                await self.ensure_star_withdraw_requirements(db, user.id)
                if await self.balance(db, user.id) < quantity:
                    raise GameError('Недостаточно средств.')
                async with db.execute('SELECT COUNT(*) FROM webapp_star_quotes WHERE user_id=? AND created_at>?', (user.id, now - 60)) as cursor:
                    if (await cursor.fetchone())[0] >= 10:
                        raise GameError('Слишком много запросов. Подождите минуту.', 429)
                token = secrets.token_hex(24)
                await self.star_execute_commit(db, 'INSERT INTO webapp_star_quotes(id,user_id,username,quantity,expires_at,created_at) VALUES (?,?,?,?,?,?)', (token, user.id, username, quantity, now + 300, now))
            return self.response({'ok': True, 'method': 'stars', 'token': token, 'provider': 'Fragment API', 'display': 'Stars', 'coinAmount': quantity, 'usd': quantity, 'quantity': quantity, 'username': username, 'expiresIn': 300})
        except GameError as error:
            return self.failure(error)

    async def handle_star_withdraw_confirm(self, request):
        try:
            payload = await self.payload(request)
            user = self.validate_user(request, payload)
            _, digest = self.request_identity(request, payload)
            key = payload.get('reqId') or request.headers.get('Idempotency-Key')
            if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', key):
                raise GameError('Некорректный идентификатор запроса.')
            async with self.database_lock:
                db = self.database()
                try:
                    await db.execute('BEGIN IMMEDIATE')
                    async with db.execute('SELECT id,digest FROM webapp_star_withdrawals WHERE user_id=? AND request_key=?', (user.id, key)) as cursor:
                        replay = await cursor.fetchone()
                    if replay:
                        if replay[1] != digest:
                            raise GameError('Идентификатор уже использован для другого запроса.', 409)
                        result = await self.star_result(db, await self.star_order(db, replay[0], user.id))
                    else:
                        async with db.execute('SELECT username,quantity,expires_at,used_id FROM webapp_star_quotes WHERE id=? AND user_id=?', (payload.get('token', ''), user.id)) as cursor:
                            quote = await cursor.fetchone()
                        if not quote:
                            raise GameError('Подтверждение не найдено.', 404)
                        if quote[3]:
                            result = await self.star_result(db, await self.star_order(db, quote[3], user.id))
                        else:
                            _, currency, fingerprint = self.fragment_settings()
                            if quote[2] < time.time() or quote[0].lower() != self.star_username(user).lower():
                                raise GameError('Подтверждение устарело или username изменился. Проверьте данные заново.', 409)
                            await self.ensure_star_withdraw_requirements(db, user.id)
                            async with db.execute("SELECT 1 FROM webapp_star_withdrawals WHERE user_id=? AND state NOT IN ('completed','failed')", (user.id,)) as cursor:
                                if await cursor.fetchone():
                                    raise GameError('Сначала дождитесь результата предыдущего вывода.', 409)
                            identifier = 'sw_' + secrets.token_hex(16)
                            cursor = await db.execute('UPDATE balances SET amount=ROUND(amount-?,2) WHERE user_id=? AND ROUND(amount*100)>=?', (quote[1], user.id, quote[1] * 100))
                            if cursor.rowcount != 1:
                                raise GameError('Недостаточно средств.')
                            stamp = self.clock().isoformat()
                            await db.execute('INSERT INTO webapp_star_withdrawals(id,user_id,username,quantity,state,token_hash,currency,request_key,digest,quote_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)', (identifier, user.id, quote[0], quote[1], 'queued', fingerprint, currency, key, digest, payload['token'], stamp, stamp))
                            await db.execute("INSERT INTO webapp_wallet_events(user_id,kind,amount_cents,source,created_at) VALUES (?,'withdrawal_reserve',?,?,?)", (user.id, -quote[1] * 100, identifier + ':reserve', stamp))
                            await db.execute('UPDATE webapp_star_quotes SET used_id=? WHERE id=?', (identifier, payload['token']))
                            result = await self.star_result(db, await self.star_order(db, identifier, user.id))
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
            return self.response(result)
        except GameError as error:
            return self.failure(error)

    async def handle_star_withdraw_status(self, request):
        try:
            user = self.validate_user(request)
            identifier = request.query.get('id') or request.query.get('job') or request.query.get('withdrawalId', '')
            async with self.database_lock:
                result = await self.star_result(self.database(), await self.star_order(self.database(), identifier, user.id))
            return self.response(result)
        except GameError as error:
            return self.failure(error)

    def fragment_order_matches(self, order, result):
        try:
            identifier = str(uuid.UUID(result['id']))
            return (result.get('type') == 'STARS' and result.get('status') in STATES and
                    isinstance(result.get('receiver'), str) and result['receiver'].removeprefix('@').lower() == order['username'].lower() and
                    type(result.get('goods_quantity')) is int and result['goods_quantity'] == order['quantity'] and
                    (not order.get('provider_id') or identifier == order['provider_id']))
        except (ValueError, TypeError, KeyError, AttributeError):
            return False

    def fragment_costs(self, result):
        costs = {}
        for key in ('price', 'fee'):
            item = result.get(key)
            if isinstance(item, dict) and item.get('currency') in {'ton', 'usdt_ton'}:
                try:
                    amount = Decimal(item['amount'])
                    if amount.is_finite() and amount >= 0:
                        costs[key] = {'currency': item['currency'], 'amount': str(amount)}
                except (InvalidOperation, ValueError, KeyError, TypeError):
                    pass
        return serialize(costs)

    async def process_star_withdrawal(self, identifier):
        async with self.database_lock:
            db = self.database()
            order = await self.star_order(db, identifier)
            if order['state'] in {'completed', 'failed', 'uncertain', 'mismatch', 'submitting'}:
                return
            _, _, fingerprint = self.fragment_settings()
            if order['token_hash'] != fingerprint:
                return  # Original JWT is required. Never replace credentials silently.
            creating = order['state'] == 'queued'
            if creating:
                cursor = await self.star_execute_commit(db, "UPDATE webapp_star_withdrawals SET state='submitting',updated_at=? WHERE id=? AND state='queued'", (self.clock().isoformat(), identifier))
                if cursor.rowcount != 1:
                    return
        if creating:
            try:
                result = await self.fragment_api('POST', 'order/stars/', {'username': order['username'], 'quantity': order['quantity'], 'show_sender': False, 'currency': order['currency']}, token_hash=order['token_hash'])
                matched = self.fragment_order_matches(order, result)
                provider_id = str(uuid.UUID(result['id'])) if matched else None
                state = 'pending' if matched else 'mismatch'
            except GameError:
                state, provider_id = 'uncertain', None
            async with self.database_lock:
                db = self.database()
                try:
                    await self.star_execute_commit(db, 'UPDATE webapp_star_withdrawals SET state=?,provider_id=?,updated_at=? WHERE id=?', (state, provider_id, self.clock().isoformat(), identifier))
                except IntegrityError:
                    await self.star_execute_commit(db, "UPDATE webapp_star_withdrawals SET state='mismatch',error_code='DUPLICATE_PROVIDER_ORDER' WHERE id=?", (identifier,))
                    return
            if not provider_id:
                return
            order['provider_id'] = provider_id
        # All terminal transitions require an authenticated GET, not a webhook.
        result = await self.fragment_api('GET', 'order/' + order['provider_id'] + '/', token_hash=order['token_hash'])
        async with self.database_lock:
            db = self.database()
            try:
                await db.execute('BEGIN IMMEDIATE')
                current = await self.star_order(db, identifier)
                if current['state'] in {'completed', 'failed'}:
                    await db.rollback()
                    return
                if not self.fragment_order_matches(current, result):
                    state = 'mismatch'
                elif result['status'] == 'COMPLETED' and result.get('success') is True:
                    state = 'completed'
                elif result['status'] == 'FAILED' and result.get('success') is False:
                    state = 'failed'
                    await self.wallet_credit(db, current['user_id'], current['quantity'] * 100, 'withdrawal_refund', identifier + ':refund')
                else:
                    state = 'blockchain_sent' if result['status'] == 'BLOCKCHAIN_SENT' else 'pending'
                await db.execute('UPDATE webapp_star_withdrawals SET state=?,updated_at=?,provider_costs=? WHERE id=?', (state, self.clock().isoformat(), self.fragment_costs(result), identifier))
                await db.commit()
            except BaseException:
                await db.rollback()
                raise

    async def star_withdraw_loop(self):
        while True:
            try:
                _, _, fingerprint = self.fragment_settings()
                async with self.database_lock:
                    async with self.database().execute("SELECT id FROM webapp_star_withdrawals WHERE state IN ('queued','pending','blockchain_sent') AND token_hash=? ORDER BY updated_at LIMIT 5", (fingerprint,)) as cursor:
                        ids = [row[0] for row in await cursor.fetchall()]
                for identifier in ids:
                    try:
                        await self.process_star_withdrawal(identifier)
                    except GameError:
                        async with self.database_lock:
                            await self.database().execute('UPDATE webapp_star_withdrawals SET updated_at=? WHERE id=?', (self.clock().isoformat(), identifier))
                            await self.database().commit()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if not isinstance(error, GameError):
                    logging.warning('Stars withdrawal worker error: %s', type(error).__name__)
            await asyncio.sleep(5)
'''

# ==================== static_assets.py ====================
_SOURCES['static_assets'] = r'''"""On-demand gzip variants for public text assets, without blocking the event loop.

Only call this after the application's static-file allowlist check. No API responses
or private files should be routed here. Variants are keyed by source stat metadata.
"""
import asyncio
import gzip
import hashlib
import mimetypes
import os
from pathlib import Path
import tempfile

from aiohttp import web


def accepts_gzip(value):
    encodings = {}
    for part in value.lower().split(','):
        tokens = part.strip().split(';')
        if not tokens[0]:
            continue
        quality = 1.0
        for token in tokens[1:]:
            if token.strip().startswith('q='):
                try:
                    quality = float(token.strip()[2:])
                except ValueError:
                    quality = 0
        encodings[tokens[0].strip()] = quality
    return 0 < encodings.get('gzip', encodings.get('*', 0)) <= 1


def variant_target(path, cache_root, stat):
    key = hashlib.sha256(f'{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}'.encode()).hexdigest()
    return cache_root / (key + path.suffix)


def gzip_variant(path, cache_root):
    stat = path.stat()
    target = variant_target(path, cache_root, stat)
    if target.exists():
        return target
    cache_root.mkdir(parents=True, exist_ok=True)
    data = gzip.compress(path.read_bytes(), compresslevel=6, mtime=0)
    # FileResponse infers content type from the original suffix; Content-Encoding is explicit.
    with tempfile.NamedTemporaryFile(dir=cache_root, delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(data)
            output.close()
            os.utime(temporary, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    return target


# Coalesce concurrent cold requests for the same asset. Completed tasks never retain a loop.
_pending = {}


async def shared_gzip_variant(path, cache_root):
    target = variant_target(path, cache_root, path.stat())
    if target.exists():
        return target
    key = (asyncio.get_running_loop(), str(target))
    task = _pending.get(key)
    if task is None:
        task = asyncio.create_task(asyncio.to_thread(gzip_variant, path, cache_root))
        _pending[key] = task
        def complete(done):
            _pending.pop(key, None)
            if not done.cancelled():
                done.exception()  # Consume errors even if the requesting client disconnected.
        task.add_done_callback(complete)
    return await asyncio.shield(task)


async def static_response(request, path, cache_root=None):
    path = Path(path)
    headers = {'Cache-Control': 'no-cache', 'Vary': 'Accept-Encoding'}
    if path.suffix.lower() in {'.js', '.css', '.html'} and 'Range' not in request.headers and accepts_gzip(request.headers.get('Accept-Encoding', '')):
        try:
            variant = await shared_gzip_variant(path, cache_root or path.parent / '.cache' / 'http-static')
            headers['Content-Encoding'] = 'gzip'
            headers['Content-Type'] = mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
            return web.FileResponse(variant, headers=headers)
        except OSError:
            # Read-only deployments remain usable without the optimization.
            pass
    return web.FileResponse(path, headers=headers)
'''

# ==================== support_backend.py ====================
_SOURCES['support_backend'] = r'''"""Persistent support tickets. Roles are derived only from the server's ADMIN_ID."""
import secrets
import time

from aiohttp import web
from games_backend import GameError, integer, serialize

CATEGORIES = {"general": "Общий вопрос", "payment": "Платежи", "game": "Игры", "account": "Аккаунт"}


class SupportMixin:
    def register_support(self, app):
        for path in ("state", "unread", "ticket", "file"):
            app.router.add_get("/api/support/" + path, self.handle_support)
        for path in ("ticket/create", "ticket/reply", "ticket/close", "message/edit", "message/delete", "file/delete", "typing", "faq/view", "upload"):
            app.router.add_post("/api/support/" + path, self.handle_support)

    async def initialize_support(self):
        self.support_typing = {}
        async with self.database_lock:
            db = self.database()
            for sql in (
                "CREATE TABLE IF NOT EXISTS webapp_support_tickets(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,subject TEXT NOT NULL,category TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'open',created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL,rev INTEGER NOT NULL DEFAULT 1,user_read INTEGER NOT NULL DEFAULT 0,admin_read INTEGER NOT NULL DEFAULT 0)",
                "CREATE INDEX IF NOT EXISTS idx_support_owner ON webapp_support_tickets(user_id,updated_at)",
                "CREATE TABLE IF NOT EXISTS webapp_support_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,ticket_id INTEGER NOT NULL,user_id INTEGER NOT NULL,author TEXT NOT NULL,text TEXT NOT NULL,created_at INTEGER NOT NULL,edited INTEGER NOT NULL DEFAULT 0,deleted INTEGER NOT NULL DEFAULT 0,rev INTEGER NOT NULL)",
                "CREATE INDEX IF NOT EXISTS idx_support_messages ON webapp_support_messages(ticket_id,id)",
                "CREATE INDEX IF NOT EXISTS idx_support_unread_v2 ON webapp_support_messages(ticket_id,author,deleted,id)",
                "CREATE TABLE IF NOT EXISTS webapp_support_files(id TEXT PRIMARY KEY,user_id INTEGER NOT NULL,ticket_id INTEGER,message_id INTEGER,mime TEXT NOT NULL,data BLOB NOT NULL,created_at INTEGER NOT NULL)",
                "CREATE INDEX IF NOT EXISTS idx_support_file_message ON webapp_support_files(message_id)",
                "CREATE TABLE IF NOT EXISTS webapp_support_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,ticket_id INTEGER,user_id INTEGER NOT NULL,action TEXT NOT NULL,previous TEXT NOT NULL,created_at INTEGER NOT NULL)",
            ):
                await db.execute(sql)
            await db.execute("DELETE FROM webapp_support_files WHERE ticket_id IS NULL AND created_at < ?", (int(time.time()) - 86400,))
            await db.commit()

    def support_admin(self, user_id):
        configured = getattr(self, "wallet_runtime", {}).get("ADMIN_ID")
        return isinstance(configured, int) and not isinstance(configured, bool) and user_id == configured

    async def support_ticket(self, db, ticket_id, user):
        ticket_id = integer(ticket_id, 1, 2**53 - 1)
        async with db.execute("SELECT id,user_id,subject,category,status,created_at,updated_at,rev,user_read,admin_read FROM webapp_support_tickets WHERE id=?", (ticket_id,)) as cur:
            row = await cur.fetchone()
        if row is None or (row[1] != user.id and not self.support_admin(user.id)):
            raise GameError("Тикет не найден.", 404)
        return row

    async def support_ticket_json(self, db, row, admin=False):
        if len(row) >= 12:
            preview, unread = row[10], row[11]
        else:
            async with db.execute("SELECT text FROM webapp_support_messages WHERE ticket_id=? AND deleted=0 ORDER BY id DESC LIMIT 1", (row[0],)) as cur:
                latest = await cur.fetchone()
            preview = latest[0] if latest else ""
            author = "user" if admin else "staff"
            read = row[9] if admin else row[8]
            async with db.execute("SELECT COUNT(*) FROM webapp_support_messages WHERE ticket_id=? AND author=? AND deleted=0 AND id>?", (row[0], author, read)) as cur:
                unread = (await cur.fetchone())[0]
        return {"id": row[0], "num": str(row[0]), "userId": row[1], "subject": row[2], "category": row[3], "categoryLabel": CATEGORIES.get(row[3], row[3]), "status": row[4], "createdAt": row[5], "updatedAt": row[6], "preview": preview[:150], "unread": unread, "canReply": True}

    async def support_message_json(self, db, row, admin=False, file_map=None):
        if file_map is None:
            async with db.execute("SELECT id FROM webapp_support_files WHERE message_id=?", (row[0],)) as cur:
                files = [{"t": value[0]} for value in await cur.fetchall()]
        else:
            files = file_map.get(row[0], [])
        return {"id": row[0], "userId": row[2], "author": row[3], "name": "Поддержка" if row[3] == "staff" else "Игрок", "text": row[4] if not row[7] or admin else "", "createdAt": row[5], "edited": bool(row[6]), "deleted": bool(row[7]), "files": files if not row[7] else [], "rev": row[8]}

    async def support_counters(self, db, user):
        admin = self.support_admin(user.id)
        owner = "" if admin else "AND t.user_id=?"
        read_column = "admin_read" if admin else "user_read"
        args = ("user" if admin else "staff",) + (() if admin else (user.id, user.id))
        sql = f"""SELECT
            (SELECT COUNT(*) FROM webapp_support_tickets t JOIN webapp_support_messages m ON m.ticket_id=t.id
                WHERE m.author=? AND m.deleted=0 AND m.id>t.{read_column} {owner}),
            (SELECT COUNT(*) FROM webapp_support_tickets t WHERE t.status!='closed' {owner})"""
        async with db.execute(sql, args) as cur:
            return await cur.fetchone()

    async def support_snapshot(self, db, user):
        admin = self.support_admin(user.id)
        where, args = ("", ()) if admin else ("WHERE t.user_id=?", (user.id,))
        read_column = "admin_read" if admin else "user_read"
        author = "user" if admin else "staff"
        sql = f"""SELECT t.id,t.user_id,t.subject,t.category,t.status,t.created_at,t.updated_at,t.rev,t.user_read,t.admin_read,
            COALESCE((SELECT text FROM webapp_support_messages WHERE ticket_id=t.id AND deleted=0 ORDER BY id DESC LIMIT 1),''),
            (SELECT COUNT(*) FROM webapp_support_messages WHERE ticket_id=t.id AND author=? AND deleted=0 AND id>t.{read_column})
            FROM webapp_support_tickets t {where} ORDER BY t.updated_at DESC,t.id DESC LIMIT 200"""
        async with db.execute(sql, (author, *args)) as cur:
            rows = await cur.fetchall()
        tickets = [await self.support_ticket_json(db, row, admin) for row in rows]
        unread, open_count = await self.support_counters(db, user)
        return {"ok": True, "isAdmin": admin, "teamName": "Поддержка MajorStars", "online": False, "mode": "offline", "replyEta": "по мере обработки", "nextOpen": "после ответа администратора", "today": self.clock().weekday(), "schedule": [{"on": False, "from": "", "to": ""} for _ in range(7)], "categories": [{"key": k, "label": v} for k, v in CATEGORIES.items()], "limits": {"subjectMin": 3, "subjectMax": 120, "textMax": 4000, "maxImages": 4, "editWindow": 172800}, "tickets": tickets, "unread": unread, "openCount": open_count, "faq": [], "ban": None}

    async def support_files_attach(self, db, user_id, file_ids, ticket_id, message_id):
        if not isinstance(file_ids, list) or len(file_ids) > 4 or any(not isinstance(x, str) for x in file_ids) or len(set(file_ids)) != len(file_ids):
            raise GameError("Можно приложить до четырёх фотографий.")
        for file_id in file_ids:
            result = await db.execute("UPDATE webapp_support_files SET ticket_id=?,message_id=? WHERE id=? AND user_id=? AND ticket_id IS NULL", (ticket_id, message_id, file_id, user_id))
            if result.rowcount != 1:
                raise GameError("Фото не найдено или уже использовано.")

    async def handle_support(self, request):
        try:
            return await self.support_dispatch(request)
        except GameError as error:
            return self.failure(error)

    async def support_dispatch(self, request):
        user = self.validate_user(request)
        admin = self.support_admin(user.id)
        action = request.path.removeprefix("/api/support/")
        now = int(time.time())
        if action == "upload":
            if request.content_length and request.content_length > 2 * 1024 * 1024:
                raise GameError("Фото должно быть не больше 2 MB.", 413)
            body = bytearray()
            async for chunk in request.content.iter_chunked(65536):
                body.extend(chunk)
                if len(body) > 2 * 1024 * 1024:
                    raise GameError("Фото должно быть не больше 2 MB.", 413)
            mime = "image/png" if body.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if body.startswith(b"\xff\xd8\xff") else "image/webp" if body[:4] == b"RIFF" and body[8:12] == b"WEBP" else None
            if not mime:
                raise GameError("Подходят JPG, PNG и WebP.")
            async with self.database_lock:
                db = self.database()
                try:
                    await db.execute("BEGIN IMMEDIATE")
                    await db.execute("DELETE FROM webapp_support_files WHERE ticket_id IS NULL AND created_at<?", (now - 86400,))
                    async with db.execute("SELECT COUNT(*) FROM webapp_support_files WHERE user_id=? AND created_at>?", (user.id, now - 86400)) as cur:
                        if (await cur.fetchone())[0] >= 40:
                            raise GameError("Лимит фотографий за сутки исчерпан.", 429)
                    file_id = secrets.token_urlsafe(32)
                    await db.execute("INSERT INTO webapp_support_files(id,user_id,mime,data,created_at) VALUES (?,?,?,?,?)", (file_id, user.id, mime, bytes(body), now))
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
            return self.response({"ok": True, "file": {"id": file_id}})
        if request.method == "GET":
            async with self.database_lock:
                db = self.database()
                if action == "state":
                    return self.response(await self.support_snapshot(db, user))
                if action == "unread":
                    unread, _ = await self.support_counters(db, user)
                    return self.response({"ok": True, "unread": unread})
                if action == "file":
                    async with db.execute("SELECT user_id,ticket_id,mime,data FROM webapp_support_files WHERE id=?", (request.query.get("t", ""),)) as cur:
                        row = await cur.fetchone()
                    if row is None:
                        raise GameError("Фото не найдено.", 404)
                    if row[1] is not None:
                        await self.support_ticket(db, row[1], user)
                    elif row[0] != user.id:
                        raise GameError("Фото не найдено.", 404)
                    return web.Response(body=row[3], content_type=row[2], headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
                ticket = await self.support_ticket(db, request.query.get("id", ""), user)
                after = integer(request.query.get("after", "0"), 0, 2**53 - 1)
                rev = integer(request.query.get("rev", "0"), 0, 2**53 - 1)
                async with db.execute("SELECT id,ticket_id,user_id,author,text,created_at,edited,deleted,rev FROM webapp_support_messages WHERE ticket_id=? AND (id>? OR rev>?) ORDER BY id LIMIT 500", (ticket[0], after, rev)) as cur:
                    rows = await cur.fetchall()
                file_map = {}
                if rows:
                    ids = [row[0] for row in rows]
                    async with db.execute("SELECT message_id,id FROM webapp_support_files WHERE message_id IN (" + ",".join("?" for _ in ids) + ")", ids) as cur:
                        for message_id, file_id in await cur.fetchall():
                            file_map.setdefault(message_id, []).append({"t": file_id})
                messages = [await self.support_message_json(db, row, admin, file_map) for row in rows]
                # Advance the reader only through delivered messages, never unseen rows.
                read_index = 9 if admin else 8
                delivered = max((r[0] for r in rows), default=0)
                if delivered > ticket[read_index]:
                    column = "admin_read" if admin else "user_read"
                    await db.execute(f"UPDATE webapp_support_tickets SET {column}=? WHERE id=?", (delivered, ticket[0]))
                    await db.commit()
                    ticket = list(ticket)
                    ticket[read_index] = delivered
                result = {"ok": True, "isAdmin": admin, "ticket": await self.support_ticket_json(db, ticket, admin), "messages": [m for m in messages if m["id"] > after], "changed": [m for m in messages if m["id"] <= after], "rev": ticket[7] if len(rows) < 500 else min(r[8] for r in rows), "teamName": "Поддержка MajorStars", "online": False, "ban": None, "typing": self.support_typing.get((ticket[0], not admin), 0) > time.monotonic()}
                return self.response(result)
        payload = await self.payload(request)
        self.validate_user(request, payload)
        if action == "faq/view":
            return self.response({"ok": True})
        if action == "typing":
            async with self.database_lock:
                ticket = await self.support_ticket(self.database(), payload.get("id"), user)
            # Bound transient typing entries and discard expired records.
            self.support_typing = {k: v for k, v in self.support_typing.items() if v > time.monotonic()}
            self.support_typing[(ticket[0], admin)] = time.monotonic() + 6
            return self.response({"ok": True})
        key, signature = self.request_identity(request, payload)
        async with self.database_lock:
            db = self.database()
            try:
                await db.execute("BEGIN IMMEDIATE")
                cached = await self.load_receipt(db, user.id, key, signature)
                if cached:
                    await db.commit()
                    return self.response(cached)
                if action == "file/delete":
                    if not isinstance(payload.get("id"), str):
                        raise GameError("Некорректный идентификатор фото.")
                    await db.execute("DELETE FROM webapp_support_files WHERE id=? AND user_id=? AND ticket_id IS NULL", (payload.get("id"), user.id))
                    result = {"ok": True}
                else:
                    text = payload.get("text", "")
                    if not isinstance(text, str) or len(text) > 4000:
                        raise GameError("Сообщение должно содержать до 4000 символов.")
                    text = text.strip()
                    files = payload.get("files", [])
                    if not isinstance(files, list) or len(files) > 4:
                        raise GameError("Можно приложить до четырёх фотографий.")
                    if action == "ticket/create":
                        subject = payload.get("subject")
                        category = payload.get("category", "general")
                        if not isinstance(subject, str) or not 3 <= len(subject.strip()) <= 120 or not isinstance(category, str) or category not in CATEGORIES or (len(text) < 5 and not files):
                            raise GameError("Проверьте тему, категорию и сообщение.")
                        async with db.execute("SELECT COUNT(*) FROM webapp_support_tickets WHERE user_id=? AND status!='closed'", (user.id,)) as cur:
                            if (await cur.fetchone())[0] >= 10:
                                raise GameError("Можно иметь не больше 10 открытых тикетов.", 429)
                        cur = await db.execute("INSERT INTO webapp_support_tickets(user_id,subject,category,created_at,updated_at) VALUES (?,?,?,?,?)", (user.id, subject.strip(), category, now, now))
                        ticket = await self.support_ticket(db, cur.lastrowid, user)
                    else:
                        ticket = await self.support_ticket(db, payload.get("id"), user)
                    tid, revision = ticket[0], ticket[7] + 1
                    result = {"ok": True}
                    if action in {"ticket/create", "ticket/reply"}:
                        if not text and not files:
                            raise GameError("Введите сообщение или приложите фото.")
                        author = "staff" if admin and ticket[1] != user.id else "user"
                        cur = await db.execute("INSERT INTO webapp_support_messages(ticket_id,user_id,author,text,created_at,rev) VALUES (?,?,?,?,?,?)", (tid, user.id, author, text, now, revision))
                        await self.support_files_attach(db, user.id, files, tid, cur.lastrowid)
                        await db.execute("UPDATE webapp_support_tickets SET status=? WHERE id=?", ("answered" if author == "staff" else "open", tid))
                        async with db.execute("SELECT id,ticket_id,user_id,author,text,created_at,edited,deleted,rev FROM webapp_support_messages WHERE id=?", (cur.lastrowid,)) as cur:
                            result["message"] = await self.support_message_json(db, await cur.fetchone(), admin)
                        result["messages"] = [result["message"]]
                    elif action == "ticket/close":
                        await db.execute("UPDATE webapp_support_tickets SET status='closed' WHERE id=?", (tid,))
                    elif action in {"message/edit", "message/delete"}:
                        mid = integer(payload.get("mid"), 1, 2**53 - 1)
                        async with db.execute("SELECT id,ticket_id,user_id,author,text,created_at,edited,deleted,rev FROM webapp_support_messages WHERE id=? AND ticket_id=?", (mid, tid)) as cur:
                            message = await cur.fetchone()
                        if message is None or message[2] != user.id or message[7] or ticket[4] == "closed" or now - message[5] > 172800:
                            raise GameError("Сообщение нельзя изменить.", 403)
                        await db.execute("INSERT INTO webapp_support_audit(ticket_id,user_id,action,previous,created_at) VALUES (?,?,?,?,?)", (tid, user.id, action, serialize(list(message)), now))
                        if action == "message/edit":
                            if not text:
                                raise GameError("Сообщение не может быть пустым.")
                            await db.execute("UPDATE webapp_support_messages SET text=?,edited=1,rev=? WHERE id=?", (text, revision, mid))
                        else:
                            await db.execute("UPDATE webapp_support_messages SET deleted=1,rev=? WHERE id=?", (revision, mid))
                        async with db.execute("SELECT id,ticket_id,user_id,author,text,created_at,edited,deleted,rev FROM webapp_support_messages WHERE id=?", (mid,)) as cur:
                            result["message"] = await self.support_message_json(db, await cur.fetchone(), admin)
                        result["changed"] = True
                    else:
                        raise GameError("Неизвестное действие.", 404)
                    await db.execute("UPDATE webapp_support_tickets SET rev=?,updated_at=? WHERE id=?", (revision, now, tid))
                    await db.execute("INSERT INTO webapp_support_audit(ticket_id,user_id,action,previous,created_at) VALUES (?,?,?,?,?)", (tid, user.id, action, "", now))
                    ticket = await self.support_ticket(db, tid, user)
                    result["ticket"] = await self.support_ticket_json(db, ticket, admin)
                await self.save_receipt(db, user.id, key, signature, result)
                await db.commit()
                return self.response(result)
            except BaseException:
                await db.rollback()
                raise
'''

# ==================== ton_deposits.py ====================
_SOURCES['ton_deposits'] = r'''"""Native TON deposits using a server-restored wallet and own v3 chain gateway."""
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
'''

# ==================== ton_wallet.py ====================
_SOURCES['ton_wallet'] = r'''"""Server-only TON mnemonic restoration and public/on-chain identity checks.

No HTTP endpoint, transfer broadcast, or seed/key serialization lives here.
"""
import base64
from dataclasses import dataclass
import os
import stat
from pathlib import Path

from tonsdk.boc import Cell
from tonsdk.contract.wallet import Wallets, WalletVersionEnum
from tonsdk.crypto._mnemonic import english

from ton_deposits import ton_address, ton_hash


class TonWalletError(ValueError):
    pass


def read_mnemonic(inline='', filename=''):
    """Read a local server secret; never include its contents/path in errors."""
    if not isinstance(inline, str) or not isinstance(filename, str) or (inline.strip() and filename.strip()):
        raise TonWalletError('Укажите только один источник seed-фразы.')
    if filename:
        fd = None
        try:
            resolved = Path(filename).resolve()
            root = Path(__file__).resolve().parent
            relative = resolved.relative_to(root) if resolved.is_relative_to(root) else None
            if relative is not None and (not relative.parts or relative.parts[0] != '.secrets'):
                raise ValueError
            fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid() or info.st_size > 4096:
                raise ValueError
            inline = os.read(fd, 4097).decode('ascii')
            if len(inline) > 4096:
                raise ValueError
        except (OSError, ValueError, UnicodeError):
            raise TonWalletError('Seed-файл недоступен: нужен обычный файл владельца процесса с правами 0600.') from None
        finally:
            if fd is not None:
                os.close(fd)
    if not inline.strip():
        raise TonWalletError('Seed-фраза TON не настроена на сервере.')
    return inline


@dataclass(frozen=True)
class TonWalletIdentity:
    address: str
    public_key: str
    code_hash: str
    version: str
    wallet_id: int


def restore_wallet_identity(phrase, version='v4r2', workchain=0, wallet_id=None, expected_address=''):
    """Validate native TON mnemonic, derive keys/address, retain public data only.

    TON mnemonics are not BIP39 checksums. Password-protected mnemonics and
    unsupported wallet contracts are rejected rather than silently reinterpreted.
    """
    try:
        if not isinstance(phrase, str) or len(phrase) > 4096:
            raise ValueError
        words = phrase.lower().split()
        if len(words) != 24 or any(word not in english for word in words):
            raise ValueError
        if version not in {'v3r2', 'v4r2'} or type(workchain) is not int or workchain != 0:
            raise ValueError
        if wallet_id is not None and (type(wallet_id) is not int or not 0 <= wallet_id < 2 ** 32):
            raise ValueError
        options = {} if wallet_id is None else {'wallet_id': wallet_id}
        _, public_key, private_key, wallet = Wallets.from_mnemonics(words, version=WalletVersionEnum(version), workchain=workchain, **options)
        address = wallet.address.to_string(is_user_friendly=False).lower()
        if expected_address and ton_address(expected_address) != address:
            raise TonWalletError('Seed-фраза и настроенный TON-адрес не соответствуют друг другу. Проверьте версию и wallet ID.')
        identity = TonWalletIdentity(address, public_key.hex(), wallet.options['code'].bytes_hash().hex(), version, wallet.options['wallet_id'])
        # No long-lived seed/private key object is retained for deposit checking.
        # Python cannot guarantee secure erasure of immutable bytes in RAM.
        del private_key, wallet, words
        return identity
    except TonWalletError:
        raise
    except Exception:
        raise TonWalletError('Некорректная TON seed-фраза или неподдерживаемые параметры кошелька (поддержаны v3r2/v4r2, workchain 0).') from None


def verify_chain_account(identity, account):
    """Check deployed code AND data key/subwallet, not just a positive balance."""
    try:
        if ton_address(account['address']) != identity.address or account.get('status') != 'active':
            raise ValueError
        if ton_hash(account['code_hash']) != identity.code_hash:
            raise ValueError
        balance = account['balance']
        if not isinstance(balance, str) or not balance.isascii() or not balance.isdigit() or len(balance) > 22:
            raise ValueError
        encoded = account['data_boc']
        if not isinstance(encoded, str) or len(encoded) > 32768:
            raise ValueError
        data = Cell.one_from_boc(base64.b64decode(encoded, validate=True)).begin_parse()
        seqno = data.read_uint(32)
        wallet_id = data.read_uint(32)
        public_key = data.read_bytes(32).hex()
        if wallet_id != identity.wallet_id or public_key != identity.public_key:
            raise ValueError
        # V4 plugins can spend money too; don't call such an account a clean
        # server wallet without implementing plugin-specific authorization.
        if identity.version == 'v4r2' and data.read_bit():
            raise ValueError
        return {'address': identity.address, 'version': identity.version, 'seqno': seqno, 'balanceNanotons': balance}
    except Exception:
        raise TonWalletError('Состояние TON-кошелька не подтверждено: проверьте сеть mainnet, активность, код, public key, wallet ID и отсутствие V4-плагинов.') from None
'''

_RESOURCES = {'emoji_catalog.json': '{\n  "dice": {\n    "67": 3,\n    "Меньше": 1,\n    "Больше": 1,\n    "Чётное": 1,\n    "Нечётное": 1,\n    "Сумма чётное": 2,\n    "Сумма нечётное": 2,\n    "Двойной куб меньше": 2,\n    "Двойной куб больше": 2,\n    "Куб1>Куб2": 2,\n    "Куб2>Куб1": 2,\n    "Оба чётное": 2,\n    "Оба нечётное": 2,\n    "Шаг": 2,\n    "Три чётное": 3,\n    "Три нечётное": 3,\n    "Три меньше": 3,\n    "Три больше": 3,\n    "Уникальные": 3,\n    "Рост 3к": 3,\n    "Спад 3к": 3,\n    "Без 1 и 6": 3,\n    "Больший куб:1": 3,\n    "Больший куб:2": 3,\n    "Больший куб:3": 3,\n    "Произведение ‹36": 3,\n    "Произведение ›32": 3,\n    "Произведение ‹20": 3,\n    "Произведение ›54": 3,\n    "Произведение ‹15": 3,\n    "Произведение ›60": 3,\n    "Произведение ‹9": 3,\n    "Произведение ›80": 3,\n    "Произведение ‹6": 3,\n    "Произведение ›100": 3,\n    "Произведение ‹3": 3,\n    "Произведение ›150": 3,\n    "Сумма 3к ‹5": 3,\n    "Сумма 3к ›16": 3,\n    "Сумма 3к ‹6": 3,\n    "Сумма 3к ›15": 3,\n    "Сумма 3к ‹7": 3,\n    "Сумма 3к ›14": 3,\n    "Сумма 3к ‹8": 3,\n    "Сумма 3к ›13": 3,\n    "Сумма 3к ‹9": 3,\n    "Сумма 3к ›12": 3,\n    "Сумма 3к ‹10": 3,\n    "Сумма 3к ›11": 3,\n    "Сумма 3к ‹11": 3,\n    "Сумма 3к ›10": 3,\n    "Сумма 3к =10": 3,\n    "Сумма 3к =11": 3,\n    "1-й сектор": 1,\n    "2-й сектор": 1,\n    "3-й сектор": 1,\n    "Один": 1,\n    "Два": 1,\n    "Три": 1,\n    "Четыре": 1,\n    "Пять": 1,\n    "Шесть": 1,\n    "Кроме шести": 1,\n    "Меньше 7": 2,\n    "Точно 7": 2,\n    "Больше 7": 2,\n    "Умн. 1-18": 2,\n    "Умн. 19-36": 2,\n    "Дуэль": 2\n  },\n  "slots": {\n    "3 Семёрки": 1,\n    "3 Лимона": 1,\n    "3 Винограда": 1,\n    "3 Бара": 1,\n    "Любая комбинация": 1,\n    "Уникальные символы": 1,\n    "3+ Семёрки": 2,\n    "3+ Лимона": 2,\n    "3+ Винограда": 2,\n    "3+ Бара": 2,\n    "Любые 3+ x2": 2,\n    "Любые 4+ x2": 2,\n    "Уникальные символы x2": 2,\n    "1-2 Любые комбинации": 2,\n    "2 Любые комбинации": 2,\n    "1+ Комбо x3": 3,\n    "2+ Комбо x3": 3,\n    "Любые 4+ x3": 3,\n    "Любые 5+ x3": 3,\n    "Любые 6+ x3": 3,\n    "Любые 7+ x3": 3,\n    "Уникальные символы x3": 3,\n    "Без 7 x3": 3,\n    "7 в каждом x3": 3\n  },\n  "bowl": {\n    "Промах": 1,\n    "Сбито 1/6": 1,\n    "Сбито 3/6": 1,\n    "Сбито 4/6": 1,\n    "Сбито 5/6": 1,\n    "Страйк": 1,\n    "2 Страйка": 2,\n    "2 Промаха": 2,\n    "2×Сбито 1/6": 2,\n    "2×Сбито 3/6": 2,\n    "2×Сбито 4/6": 2,\n    "2×Сбито 5/6": 2,\n    "1+ Страйк": 2,\n    "1+ Промах": 2,\n    "Без страйка": 2,\n    "Без промаха": 2,\n    "Любой дубль": 2,\n    "Шар1>Шар2": 2,\n    "Шар2>Шар1": 2,\n    "3 Промаха": 3,\n    "3×Сбито 1/6": 3,\n    "3×Сбито 3/6": 3,\n    "3×Сбито 4/6": 3,\n    "3×Сбито 5/6": 3,\n    "3 Страйка": 3,\n    "1+ Страйк x3": 3,\n    "1+ Промах x3": 3,\n    "2+ Страйк": 3,\n    "2+ Промах": 3,\n    "Спад": 3,\n    "Рост": 3,\n    "Дубль x3": 3,\n    "Трипл": 3,\n    "Без страйка x3": 3,\n    "Без промаха x3": 3,\n    "Сумма 0-2": 2,\n    "Сумма 3-5": 2,\n    "Сумма 6-9": 2,\n    "Сумма 10-12": 2,\n    "Сумма 0-6": 2,\n    "Сумма 6-12": 2,\n    "Дуэль": 2\n  },\n  "darts": {\n    "Центр": 1,\n    "Промах": 1,\n    "Сектор 2 ⚪️": 1,\n    "Сектор 2 🔴": 1,\n    "Сектор 1 ⚪️": 1,\n    "Сектор 1 🔴": 1,\n    "Любой белый сектор": 1,\n    "Сектор или Центр": 1,\n    "Любой сектор": 1,\n    "2 Центра": 2,\n    "2 Промаха": 2,\n    "2 Сектор 1": 2,\n    "2 Сектор 2": 2,\n    "2 Сектор 3": 2,\n    "2 Сектор 4": 2,\n    "2 Белых сектора": 2,\n    "Красный x2": 2,\n    "Два сектора": 2,\n    "Две рядом": 2,\n    "Любой дубль": 2,\n    "Светофор": 2,\n    "1+ Центр": 2,\n    "1-й дротик ближе": 2,\n    "2-й дротик ближе": 2,\n    "Без промахов": 2,\n    "2 Красных сектора": 2,\n    "Без центра": 2,\n    "3 Центра": 3,\n    "3 Промаха": 3,\n    "3 Сектор 1": 3,\n    "3 Сектор 2": 3,\n    "3 Сектор 3": 3,\n    "3 Сектор 4": 3,\n    "Белый x3": 3,\n    "Красный x3": 3,\n    "2+ Белый": 3,\n    "2+ Красный": 3,\n    "Спад": 3,\n    "Рост": 3,\n    "Только сектор x3": 3,\n    "Дубль x3": 3,\n    "Трипл": 3,\n    "Без промахов x3": 3,\n    "Дуэль": 2\n  },\n  "basket": {\n    "Чистый гол": 1,\n    "Отскок": 1,\n    "Близко": 1,\n    "Застрял": 1,\n    "Попал с краем": 1,\n    "Прокрут": 1,\n    "Любой гол": 1,\n    "Промах": 1,\n    "2 Чистых гола": 2,\n    "2 Отскока": 2,\n    "2 Близко": 2,\n    "2 Застряло": 2,\n    "Прокрут x2": 2,\n    "Любой дубль": 2,\n    "2 Попал с краем": 2,\n    "Любой гол x2": 2,\n    "Промах x2": 2,\n    "1+ Гол": 2,\n    "1+ Промах": 2,\n    "Гол-Промах": 2,\n    "Промах-Гол": 2,\n    "1 Гол и 1 Промах": 2,\n    "3 Чистых гола": 3,\n    "3 Прокрут гола": 3,\n    "3 Застряло": 3,\n    "3 Отскока": 3,\n    "Прокрут x3": 3,\n    "Любой гол x3": 3,\n    "Промах x3": 3,\n    "Только третий": 3,\n    "2+ гола": 3,\n    "2+ промаха": 3,\n    "Ровно 1 гол": 3,\n    "Ровно 2 гола": 3,\n    "Все разные": 3,\n    "Дубль x3": 3,\n    "Трипл": 3,\n    "Дуэль": 2\n  },\n  "foot": {\n    "Гол в центр": 1,\n    "Девятка": 1,\n    "Гол от штанги": 1,\n    "Мимо ворот": 1,\n    "Гол в угол": 1,\n    "Любой гол": 1,\n    "Штанга": 1,\n    "Удар об штангу": 1,\n    "Промах": 1,\n    "2 Гол в центр": 2,\n    "2 Девятка": 2,\n    "2 Гол от штанги": 2,\n    "2 Гол в угол": 2,\n    "Любой гол x2": 2,\n    "Промах x2": 2,\n    "Штанга x2": 2,\n    "Удар об штангу x2": 2,\n    "1+ Гол": 2,\n    "1+ Промах": 2,\n    "Любой дубль": 2,\n    "Гол-Промах": 2,\n    "Промах-Гол": 2,\n    "1 Гол и 1 Промах": 2,\n    "3 Гол в центр": 3,\n    "3 Девятка": 3,\n    "3 Гол от штанги": 3,\n    "Штанга x3": 3,\n    "Любой гол x3": 3,\n    "Промах x3": 3,\n    "Ровно 1 гол": 3,\n    "Ровно 2 гола": 3,\n    "2+ гола": 3,\n    "2+ промаха": 3,\n    "Все разные": 3,\n    "Дубль x3": 3,\n    "Есть Девятка": 3,\n    "Камбэк": 3,\n    "Трипл": 3,\n    "Дуэль - игрок точнее": 2,\n    "Дуэль - бот точнее": 2,\n    "Дуэль - игрок в штангу": 2,\n    "Дуэль - бот в штангу": 2\n  }\n}\n'}


class _EmbeddedModules(_importlib_abc.MetaPathFinder, _importlib_abc.Loader):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in _SOURCES:
            return _importlib_util.spec_from_loader(fullname, self, origin=str(_Path(__file__).resolve()))
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        name = module.__spec__.name
        # Preserve paths relative to server.py for static assets, private seed files,
        # and existing runtime behaviour, even though these module files needn't exist.
        filename = str(_Path(__file__).resolve().with_name(name + '.py'))
        module.__file__ = filename
        module.__bundled_resources__ = _RESOURCES
        module.__server_config__ = {key: _CONFIG[key] for key in _MODULE_CONFIG.get(name, ())}
        exec(compile(_SOURCES[name], filename, 'exec'), module.__dict__)


_FINDER = _EmbeddedModules()
_sys.meta_path.insert(0, _FINDER)


def load_application(name='main'):
    # Normal startup shares one application; tests/diagnostics can request an
    # isolated runtime without reading a separate main.py from disk.
    if name == 'main':
        return _importlib.import_module('main')
    if not isinstance(name, str) or not name.isidentifier() or name in _SOURCES:
        raise ValueError('Use a distinct Python module name for an isolated runtime')
    module = _types.ModuleType(name)
    module.__file__ = str(_Path(__file__).resolve().with_name('main.py'))
    module.__bundled_resources__ = _RESOURCES
    module.__server_config__ = {key: _CONFIG[key] for key in _MODULE_CONFIG['main']}
    _sys.modules[name] = module
    try:
        exec(compile(_SOURCES['main'], module.__file__, 'exec'), module.__dict__)
    except BaseException:
        if _sys.modules.get(name) is module:
            del _sys.modules[name]
        raise
    return module


async def _check_wallet(local_only):
    wallet_module = _importlib.import_module('ton_deposits')
    errors = _importlib.import_module('games_backend')
    backend = wallet_module.TonDepositsMixin()
    await backend.initialize_ton_wallet()
    identity = backend._ton_wallet_identity
    if identity is None:
        raise errors.GameError(backend._ton_wallet_problem, 503)
    if not local_only:
        await backend.verify_ton_wallet_chain()
    print(_importlib.import_module('json').dumps({
        'localValid': True, 'address': identity.address, 'version': identity.version,
        'chainAccountVerified': not local_only,
    }))


def main():
    parser = _argparse.ArgumentParser(description='MajorStars single-file Python server')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Import/check bundled backend without starting it')
    mode.add_argument('--check-config', action='store_true', help='Check conf.json for bot startup without network requests')
    mode.add_argument('--check-ton-wallet', action='store_true', help='Check server wallet without exposing its seed')
    parser.add_argument('--local-only', action='store_true', help='Only local seed/address check (with --check-ton-wallet)')
    args = parser.parse_args()
    if args.local_only and not args.check_ton_wallet:
        parser.error('--local-only requires --check-ton-wallet')
    if args.check_config:
        try:
            _require_startup_config()
        except ConfigError as error:
            parser.error(str(error))
        print('Configuration OK; no network requests made.')
    elif args.check:
        for name in _SOURCES:
            _importlib.import_module(name)
        print('Bundle OK: ' + str(len(_SOURCES)) + ' Python modules; no server started.')
    elif args.check_ton_wallet:
        try:
            _asyncio.run(_check_wallet(args.local_only))
        except Exception as error:
            errors = _importlib.import_module('games_backend')
            print(error.message if isinstance(error, errors.GameError) else 'Wallet check failed; check server settings.', file=_sys.stderr)
            raise SystemExit(1) from None
    else:
        try:
            _require_startup_config()
        except ConfigError as error:
            parser.error(str(error))
        load_application().main()


if __name__ == '__main__':
    main()
