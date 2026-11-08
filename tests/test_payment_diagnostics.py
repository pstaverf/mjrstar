import bundle_test_support  # Register backend modules from server.py.
import base64
import json
import unittest

from games_backend import GameError
from payment_errors import invoice_pay_url, rocket_token_problem, provider_rejection
from complete_games import CompleteGamesBackend


def jwt(header=None, payload=None):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
    return encode(header or {'alg': 'HS256'}) + '.' + encode(payload or {'sub': 'local-test'}) + '.dGVzdA'


class PaymentDiagnosticsTests(unittest.TestCase):
    def test_jwt_format_expiry_not_authenticity(self):
        self.assertIsNone(rocket_token_problem(jwt()))
        self.assertEqual(rocket_token_problem(jwt(payload={'exp': 1})), 'XROCKET_TOKEN_EXPIRED')
        self.assertEqual(rocket_token_problem(jwt(payload={'exp': 'invalid'})), 'XROCKET_TOKEN_MALFORMED')
        self.assertEqual(rocket_token_problem(jwt(payload={'exp': float('nan')})), 'XROCKET_TOKEN_MALFORMED')
        self.assertEqual(rocket_token_problem(jwt(header={'alg': 'none'})), 'XROCKET_TOKEN_MALFORMED')
        self.assertEqual(rocket_token_problem('broken.jwt.secret'), 'XROCKET_TOKEN_MALFORMED')
        self.assertEqual(rocket_token_problem(None), 'XROCKET_TOKEN_MISSING')

    def test_url_fallbacks_and_host_validation(self):
        for key, url in (('bot_invoice_url', 'https://t.me/CryptoBot?start=test'), ('mini_app_invoice_url', 'https://t.me/CryptoBot/app?startapp=test'), ('web_app_invoice_url', 'https://pay.crypt.bot/invoice/test')):
            self.assertEqual(invoice_pay_url('cryptobot', {key: url}), url)
        for url in ('https://t.me.evil.test/test', 'https://t.me@evil.test/test', 'https://evil.test@t.me/test', 'http://t.me/test', 'https://t.me:444/test', 'javascript:alert(1)', None):
            with self.assertRaises(GameError):
                invoice_pay_url('cryptobot', {'bot_invoice_url': url})
        self.assertEqual(invoice_pay_url('xrocket', {'links': {'telegramBotLink': 'https://t.me/xRocket?start=test'}}), 'https://t.me/xRocket?start=test')

    def test_source_defaults_and_explicit_backend_configuration(self):
        import payments_backend as payments
        backend = CompleteGamesBackend(None, None, None, None)
        self.assertTrue(backend.payment_token('cryptobot') == payments.CRYPTOBOT_API_TOKEN.strip(), 'CryptoBot must use its source constant')
        self.assertTrue(backend.payment_token('xrocket') == payments.XROCKET_API_TOKEN.strip(), 'xRocket must use its source constant')
        self.assertTrue(backend.rocket_secret() == payments.XROCKET_WEBHOOK_SECRET.strip(), 'Webhook must use its source constant')
        backend.payment_tokens = {'cryptobot': None, 'xrocket': ' test-override '}
        self.assertIsNone(backend.payment_token('cryptobot'))
        self.assertEqual(backend.payment_token('xrocket'), 'test-override')
        backend.xrocket_webhook_secret = None
        self.assertIsNone(backend.rocket_secret())

    def test_upstream_raw_messages_and_unexpected_shapes_are_never_echoed(self):
        for error in ({'code': 400, 'name': 'AMOUNT_TOO_SMALL', 'message': 'private-token'}, {'code': [], 'name': {}, 'message': 'private-token'}, 'private-token'):
            result = provider_rejection('cryptobot', 400, {'ok': False, 'error': error})
            self.assertTrue(result.definitive)
            self.assertNotIn('private-token', result.message)
        self.assertFalse(provider_rejection('xrocket', 503, {}).definitive)
