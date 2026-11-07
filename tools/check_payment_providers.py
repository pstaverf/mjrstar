"""Read-only, redacted connectivity/configuration check. Never creates invoices."""
import argparse
import asyncio
import json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    # Keep --help usable before installing application dependencies.
    from complete_games import CompleteGamesBackend
    from games_backend import GameError
    from payment_errors import PaymentProviderError

    async def check():
        backend = CompleteGamesBackend(None, None, None, None)
        report = {}
        for provider, path in (("cryptobot", "getMe"), ("xrocket", "/api/v1/currencies")):
            try:
                result = await backend.payment_api(provider, "GET", path)
                expected = dict if provider == "cryptobot" else list
                if not isinstance(result, expected):
                    raise PaymentProviderError(provider, "Неожиданный формат ответа; проверьте версию API.", "PROVIDER_BAD_RESPONSE")
                report[provider] = {"ok": True, "check": "read-only API access (not invoice creation)"}
            except GameError as error:
                report[provider] = {"ok": False, "code": error.code, "error": error.message, "providerStatus": getattr(error, "upstream_status", None)}
        report["xrocketWebhookSecretConfigured"] = bool(backend.rocket_secret())
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if all(report[p]["ok"] for p in ("cryptobot", "xrocket")) and report["xrocketWebhookSecretConfigured"] else 1

    raise SystemExit(asyncio.run(check()))


if __name__ == "__main__":
    main()
