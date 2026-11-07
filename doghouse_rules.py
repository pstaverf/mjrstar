from functools import lru_cache
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
