from datetime import date, datetime, time, timedelta

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
