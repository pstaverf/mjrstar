"""Finished-round lookup plus explicit, scoped deterministic verification."""
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
