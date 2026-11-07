import math

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
