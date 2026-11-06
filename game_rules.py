import hashlib
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
