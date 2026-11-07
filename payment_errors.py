"""Safe payment diagnostics: never return/log raw provider bodies or credentials."""
import base64
import json
import math
import re
import time
from urllib.parse import urlsplit

from games_backend import GameError


class PaymentProviderError(GameError):
    def __init__(self, provider, message, code, upstream_status=None, definitive=False, status=502):
        super().__init__(message, status, code)
        self.provider = provider
        self.upstream_status = upstream_status
        self.definitive = definitive


def rocket_token_problem(token):
    if not isinstance(token, str) or not token:
        return 'XROCKET_TOKEN_MISSING'
    try:
        parts = token.split('.')
        if len(parts) != 3 or any(not re.fullmatch(r'[A-Za-z0-9_-]+', part) for part in parts):
            return 'XROCKET_TOKEN_MALFORMED'
        decoded = []
        for segment in parts[:2]:
            decoded.append(json.loads(base64.b64decode(segment + '=' * (-len(segment) % 4), altchars=b'-_', validate=True)))
        if not all(isinstance(value, dict) for value in decoded) or decoded[0].get('alg') in {None, 'none'}:
            return 'XROCKET_TOKEN_MALFORMED'
        expires = decoded[1].get('exp')
        if expires is not None and (isinstance(expires, bool) or not isinstance(expires, (int, float)) or not math.isfinite(expires)):
            return 'XROCKET_TOKEN_MALFORMED'
        if expires is not None and expires <= time.time():
            return 'XROCKET_TOKEN_EXPIRED'
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return 'XROCKET_TOKEN_MALFORMED'
    # Format/expiry only. Authenticity and permissions can only be checked by xRocket.
    return None


def provider_rejection(provider, status, result):
    label = 'CryptoBot' if provider == 'cryptobot' else 'xRocket'
    error = result.get('error') if isinstance(result, dict) else None
    name = error.get('name') if isinstance(error, dict) else None
    code = error.get('code') if isinstance(error, dict) else None
    name = name if isinstance(name, str) else None
    code = code if isinstance(code, int) else None
    if status in {401, 403} or code in {401, 403} or name in {'UNAUTHORIZED', 'TOKEN_INVALID', 'ACCESS_DENIED'}:
        return PaymentProviderError(provider, label + ': доступ к API отклонён. Проверьте API-токен, разрешение на создание счетов, ограничения IP/сети и выбранную версию API.', 'PROVIDER_AUTH_REJECTED', status, definitive=status < 500)
    if name in {'AMOUNT_TOO_SMALL', 'AMOUNT_TOO_BIG', 'AMOUNT_INVALID', 'FIAT_AMOUNT_INVALID'}:
        return PaymentProviderError(provider, label + ': сумма счёта не соответствует ограничениям провайдера. Измените сумму пополнения.', 'PROVIDER_AMOUNT_REJECTED', status, definitive=True)
    if status == 404:
        return PaymentProviderError(provider, label + ': API-метод не найден. Проверьте окружение и версию API (для xRocket нужна Current).', 'PROVIDER_API_VERSION', status, definitive=True)
    if status in {400, 422} or provider == 'cryptobot' and isinstance(result, dict) and result.get('ok') is False:
        return PaymentProviderError(provider, label + ': запрос на счёт отклонён. Проверьте сумму, валюту и настройки приложения у провайдера.', 'PROVIDER_REQUEST_REJECTED', status, definitive=status < 500)
    return PaymentProviderError(provider, label + ': сервис вернул ошибку HTTP ' + str(status) + '. Если запрос на создание уже отправлен, сначала проверьте его статус.', 'PROVIDER_HTTP_ERROR', status)


def invoice_pay_url(provider, invoice):
    if not isinstance(invoice, dict):
        raise GameError('Некорректный ответ платёжного сервиса.', 502)
    if provider == 'cryptobot':
        url = invoice.get('bot_invoice_url') or invoice.get('mini_app_invoice_url') or invoice.get('web_app_invoice_url')
        allowed = {'t.me', 'pay.crypt.bot'}
    else:
        links = invoice.get('links')
        url = links.get('telegramBotLink') if isinstance(links, dict) else None
        allowed = {'t.me'}
    try:
        parsed = urlsplit(url) if isinstance(url, str) else None
        valid = parsed is not None and parsed.scheme == 'https' and parsed.hostname in allowed and parsed.username is None and parsed.password is None and parsed.port in {None, 443}
    except ValueError:
        valid = False
    if not valid:
        raise GameError('Провайдер вернул некорректную ссылку на оплату.', 502)
    return url
