import json


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
