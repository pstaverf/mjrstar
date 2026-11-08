"""Run locally on the server. Never takes or prints mnemonic arguments."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ton_deposits import TonDepositsMixin
from games_backend import GameError


async def main(local_only):
    backend = TonDepositsMixin()
    await backend.initialize_ton_wallet()
    identity = backend._ton_wallet_identity
    if identity is None:
        raise GameError(backend._ton_wallet_problem, 503)
    if not local_only:
        await backend.verify_ton_wallet_chain()
    print(json.dumps({'localValid': True, 'address': identity.address, 'version': identity.version, 'chainAccountVerified': not local_only}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Validate server TON wallet without exposing its seed.')
    parser.add_argument('--local-only', action='store_true', help='Validate mnemonic/address locally; NOT chain readiness.')
    args = parser.parse_args()
    try:
        asyncio.run(main(args.local_only))
    except GameError as error:
        print(error.message, file=sys.stderr)
        sys.exit(1)
    except Exception:
        print('Проверка кошелька не выполнена. Проверьте серверные настройки.', file=sys.stderr)
        sys.exit(1)
