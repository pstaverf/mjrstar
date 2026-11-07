import asyncio
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
