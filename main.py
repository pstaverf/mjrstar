import asyncio
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
from functools import lru_cache
from html import escape as html_escape
from types import SimpleNamespace
from pathlib import Path

import aiosqlite
from complete_games import CompleteGamesBackend
from games_backend import GameError
from privacy_rules import TELEGRAM_NAMES, player_identity
from aiohttp import web
from static_assets import static_response

from aiogram import BaseMiddleware, Bot, Dispatcher, Router, F
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

BOT_TOKEN = os.getenv("BOT_TOKEN", "8861223578:AAEPy9SNIVtHHTiOvWJqjRbnkm4g_q_oLsg")
CHANNEL_ID = "@mjrstars"
CHANNEL_URL = "https://t.me/mjrstars"
CHAT_URL = "https://t.me/mjrstars"

DB_PATH = "bot.db"
BACKUP_PATH = "bot_backup.db"
BACKUP_INTERVAL_SECONDS = 6 * 3600
TOPUP_MAX = 10000
MINES_STALE_SECONDS = 6 * 3600
DB_LOCK_TIMEOUT = 30

HASH_ALPHABET = string.ascii_lowercase + string.digits

WEBHOOK_HOST = "https://mjrr.wisp.uno"
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "kJ8xQ2mNpR7vT4wYbG3zLdF6hS9cV1aZ")
WEBAPP_HOST = "0.0.0.0"
WEBAPP_PORT = 16341

HOUSE_EDGE = 0.90
MAX_MULTIPLIER = 10.0
MIN_BET = 0.5

ALL_IN_ALIASES = {"все", "всё", "вб", "банк"}
HALF_ALIASES = {"пол", "половина", "половину", "хаф"}

ADMIN_ID = 6025818386

MSK = timezone(timedelta(hours=3))
BONUS_COOLDOWN = timedelta(hours=12)
BONUS_BIO_TEXT = "@mjrstars"
BONUS_BASE_MIN = 1.0
BONUS_BASE_MAX = 3.0
BONUS_STREAK_BASE = 0.1
BONUS_STREAK_STEP = 0.05

REF_SIGNUP_BASE = 2.5
REF_SIGNUP_PREMIUM = 5.0
REF_DEPOSIT_PERCENT = 0.10
REF_BASE_LIMIT = 2
REF_LIMIT_PER_DEPOSIT = 2
REF_MIN_WITHDRAW = 10
BOT_USERNAME = "mjrstarsbot"

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


router = Router()


def db() -> aiosqlite.Connection:
    if _db_conn is None:
        raise RuntimeError("DB is not initialized")
    return _db_conn


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
            "frozen INTEGER NOT NULL DEFAULT 0"
            ")"
        )
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS payments ("
            "charge_id TEXT PRIMARY KEY, "
            "user_id INTEGER NOT NULL, "
            "amount INTEGER NOT NULL, "
            "created_at TEXT NOT NULL"
            ")"
        )
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
            "SELECT signup_earned, deposit_earned, frozen FROM ref_balance WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return {"signup_earned": 0.0, "deposit_earned": 0.0, "frozen": 0}
            return {
                "signup_earned": row[0],
                "deposit_earned": row[1],
                "frozen": row[2],
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
) -> None:
    async with _db_lock:
        conn = db()
        await conn.execute(
            "INSERT INTO crash_games ("
            "user_id, server_seed, client_seed, nonce, crash_point, "
            "raw_crash_point, bet, multiplier, won, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, server_seed, client_seed, nonce,
                crash_point, raw_crash_point,
                bet, multiplier, int(won),
                now_msk().isoformat(),
            ),
        )
        await conn.commit()


async def save_mines_game(
    user_id: int,
    bet: float,
    mines_count: int,
    opened: int,
    multiplier: float,
    win_amount: float,
    won: bool,
) -> None:
    async with _db_lock:
        conn = db()
        await conn.execute(
            "INSERT INTO mines_history ("
            "user_id, bet, mines_count, opened, multiplier, win_amount, won, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, bet, mines_count, opened,
                multiplier, win_amount, int(won),
                now_msk().isoformat(),
            ),
        )
        await conn.commit()


async def save_football_game(
    user_id: int,
    bet: float,
    player_range: str,
    landed_range: str,
    multiplier: float,
    win_amount: float,
    won: bool,
) -> None:
    async with _db_lock:
        conn = db()
        await conn.execute(
            "INSERT INTO football_history ("
            "user_id, bet, player_range, landed_range, multiplier, win_amount, won, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, bet, player_range, landed_range,
                multiplier, win_amount, int(won),
                now_msk().isoformat(),
            ),
        )
        await conn.commit()


async def save_basketball_game(
    user_id: int,
    bet: float,
    player_range: str,
    landed_range: str,
    multiplier: float,
    win_amount: float,
    won: bool,
) -> None:
    async with _db_lock:
        conn = db()
        await conn.execute(
            "INSERT INTO basketball_history ("
            "user_id, bet, player_range, landed_range, multiplier, win_amount, won, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, bet, player_range, landed_range,
                multiplier, win_amount, int(won),
                now_msk().isoformat(),
            ),
        )
        await conn.commit()


async def save_slot_game(
    user_id: int,
    bet: float,
    dice_value: int,
    multiplier: float,
    win_amount: float,
    won: bool,
) -> None:
    async with _db_lock:
        conn = db()
        await conn.execute(
            "INSERT INTO slot_history ("
            "user_id, bet, dice_value, multiplier, win_amount, won, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                user_id, bet, dice_value,
                multiplier, win_amount, int(won),
                now_msk().isoformat(),
            ),
        )
        await conn.commit()


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
            bet, multiplier, won,
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

    balance = ref_data["signup_earned"] + ref_data["deposit_earned"]
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
    stats = await get_profile_stats(user.id)

    d_win, d_bet, d_games = await get_dice_stats(user.id)
    stats["max_win"] = max(stats["max_win"], d_win)
    stats["max_bet"] = max(stats["max_bet"], d_bet)
    stats["games"] += d_games

    username_display = f"@{user.username}" if user.username else "нету"

    reg_date = format_registration_date(stats["created_at"])

    await message.answer(
        '<tg-emoji emoji-id="5308004189677330658">👤</tg-emoji>'
        f' <i>{user_link(user)}, <b>ваш профиль:</b></i>\n\n'
        '<tg-emoji emoji-id="5888781182249738113">🆔</tg-emoji>'
        f' <code>{user.id}</code>\n'
        '<tg-emoji emoji-id="5771887475421090729">👤</tg-emoji>'
        f' {username_display}\n'
        '<tg-emoji emoji-id="5431897022456145283">📆</tg-emoji>'
        f' Дата регистрации: {reg_date}\n\n'
        '<blockquote>'
        '<tg-emoji emoji-id="5055840333242303386">🤑</tg-emoji>'
        f' Самый большой выигрыш: {round(stats["max_win"], 2)}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
        '</blockquote>\n'
        '<blockquote>'
        '<tg-emoji emoji-id="5028746137645876535">📈</tg-emoji>'
        f' Самая большая ставка за игру: {round(stats["max_bet"], 2)}'
        '<tg-emoji emoji-id="5954135079662916434">⭐️</tg-emoji>'
        '</blockquote>\n'
        '<blockquote>'
        '<tg-emoji emoji-id="5098552537460508672">💰</tg-emoji>'
        f' Сыграно игр: {stats["games"]}'
        '</blockquote>'
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
                multiplier, total_return, True,
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
                0.0, 0.0, False,
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
                multiplier, total_return, True,
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
                0.0, 0.0, False,
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
                SLOT_MULTIPLIER, total_return, True,
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
                0.0, 0.0, False,
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

    balance = ref_data["signup_earned"] + ref_data["deposit_earned"]

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
                "SELECT signup_earned + deposit_earned FROM ref_balance WHERE user_id = ?",
                (user_id,),
            ) as c:
                row = await c.fetchone()
            credited = round(float(row[0]), 2) if row else 0.0
            if credited + 1e-9 >= REF_MIN_WITHDRAW:
                await conn.execute(
                    "UPDATE ref_balance SET signup_earned = 0, deposit_earned = 0 "
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
) -> None:
    async with _db_lock:
        conn = db()
        await conn.execute(
            "INSERT INTO dice_history ("
            "game, user_id, bet, player_range, dice_value, multiplier, win_amount, won, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                game, user_id, bet, player_range, dice_value,
                multiplier, win_amount, int(won),
                now_msk().isoformat(),
            ),
        )
        await conn.commit()


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
                multiplier, total_return, True,
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
                0.0, 0.0, False,
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
    spawn(start_animation(message)).add_done_callback(generic_task_done)


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
        allowed_updates=["message", "callback_query", "pre_checkout_query", "inline_query"],
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
            "earnings": referral["signup_earned"] + referral["deposit_earned"],
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
    dp = Dispatcher()
    dp.include_router(router)

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
