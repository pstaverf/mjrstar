import json
import math
import re
from collections import Counter
from functools import lru_cache
from itertools import product
from pathlib import Path

from games_backend import GameError
from pvp_games import slot_reels


EMOJI_CATALOG = json.loads(Path(__file__).with_name("emoji_catalog.json").read_text())
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
