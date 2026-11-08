"""Server-only TON mnemonic restoration and public/on-chain identity checks.

No HTTP endpoint, transfer broadcast, or seed/key serialization lives here.
"""
import base64
from dataclasses import dataclass
import os
import stat
from pathlib import Path

from tonsdk.boc import Cell
from tonsdk.contract.wallet import Wallets, WalletVersionEnum
from tonsdk.crypto._mnemonic import english

from ton_deposits import ton_address, ton_hash


class TonWalletError(ValueError):
    pass


def read_mnemonic(inline='', filename=''):
    """Read a local server secret; never include its contents/path in errors."""
    if not isinstance(inline, str) or not isinstance(filename, str) or (inline.strip() and filename.strip()):
        raise TonWalletError('Укажите только один источник seed-фразы.')
    if filename:
        fd = None
        try:
            resolved = Path(filename).resolve()
            root = Path(__file__).resolve().parent
            relative = resolved.relative_to(root) if resolved.is_relative_to(root) else None
            if relative is not None and (not relative.parts or relative.parts[0] != '.secrets'):
                raise ValueError
            fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid() or info.st_size > 4096:
                raise ValueError
            inline = os.read(fd, 4097).decode('ascii')
            if len(inline) > 4096:
                raise ValueError
        except (OSError, ValueError, UnicodeError):
            raise TonWalletError('Seed-файл недоступен: нужен обычный файл владельца процесса с правами 0600.') from None
        finally:
            if fd is not None:
                os.close(fd)
    if not inline.strip():
        raise TonWalletError('Seed-фраза TON не настроена на сервере.')
    return inline


@dataclass(frozen=True)
class TonWalletIdentity:
    address: str
    public_key: str
    code_hash: str
    version: str
    wallet_id: int


def restore_wallet_identity(phrase, version='v4r2', workchain=0, wallet_id=None, expected_address=''):
    """Validate native TON mnemonic, derive keys/address, retain public data only.

    TON mnemonics are not BIP39 checksums. Password-protected mnemonics and
    unsupported wallet contracts are rejected rather than silently reinterpreted.
    """
    try:
        if not isinstance(phrase, str) or len(phrase) > 4096:
            raise ValueError
        words = phrase.lower().split()
        if len(words) != 24 or any(word not in english for word in words):
            raise ValueError
        if version not in {'v3r2', 'v4r2'} or type(workchain) is not int or workchain != 0:
            raise ValueError
        if wallet_id is not None and (type(wallet_id) is not int or not 0 <= wallet_id < 2 ** 32):
            raise ValueError
        options = {} if wallet_id is None else {'wallet_id': wallet_id}
        _, public_key, private_key, wallet = Wallets.from_mnemonics(words, version=WalletVersionEnum(version), workchain=workchain, **options)
        address = wallet.address.to_string(is_user_friendly=False).lower()
        if expected_address and ton_address(expected_address) != address:
            raise TonWalletError('Seed-фраза и настроенный TON-адрес не соответствуют друг другу. Проверьте версию и wallet ID.')
        identity = TonWalletIdentity(address, public_key.hex(), wallet.options['code'].bytes_hash().hex(), version, wallet.options['wallet_id'])
        # No long-lived seed/private key object is retained for deposit checking.
        # Python cannot guarantee secure erasure of immutable bytes in RAM.
        del private_key, wallet, words
        return identity
    except TonWalletError:
        raise
    except Exception:
        raise TonWalletError('Некорректная TON seed-фраза или неподдерживаемые параметры кошелька (поддержаны v3r2/v4r2, workchain 0).') from None


def verify_chain_account(identity, account):
    """Check deployed code AND data key/subwallet, not just a positive balance."""
    try:
        if ton_address(account['address']) != identity.address or account.get('status') != 'active':
            raise ValueError
        if ton_hash(account['code_hash']) != identity.code_hash:
            raise ValueError
        balance = account['balance']
        if not isinstance(balance, str) or not balance.isascii() or not balance.isdigit() or len(balance) > 22:
            raise ValueError
        encoded = account['data_boc']
        if not isinstance(encoded, str) or len(encoded) > 32768:
            raise ValueError
        data = Cell.one_from_boc(base64.b64decode(encoded, validate=True)).begin_parse()
        seqno = data.read_uint(32)
        wallet_id = data.read_uint(32)
        public_key = data.read_bytes(32).hex()
        if wallet_id != identity.wallet_id or public_key != identity.public_key:
            raise ValueError
        # V4 plugins can spend money too; don't call such an account a clean
        # server wallet without implementing plugin-specific authorization.
        if identity.version == 'v4r2' and data.read_bit():
            raise ValueError
        return {'address': identity.address, 'version': identity.version, 'seqno': seqno, 'balanceNanotons': balance}
    except Exception:
        raise TonWalletError('Состояние TON-кошелька не подтверждено: проверьте сеть mainnet, активность, код, public key, wallet ID и отсутствие V4-плагинов.') from None
