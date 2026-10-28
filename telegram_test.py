#!/usr/bin/env python3
"""Send a clearly labeled test message to the configured Telegram channel."""

import json
import os
import urllib.error
import urllib.request


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise SystemExit("Configura TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en GitHub Actions Secrets")

    payload = {
        "chat_id": chat_id,
        "text": "🧪 PRUEBA DEL BOT\n\nMensaje de prueba. No es una oferta ni un chollo.",
        "disable_web_page_preview": True,
    }
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("description", "error de Telegram")
        except (json.JSONDecodeError, UnicodeDecodeError):
            detail = "error HTTP de Telegram"
        raise SystemExit(f"Telegram rechazó la prueba: {detail}") from None
    except urllib.error.URLError:
        raise SystemExit("No se pudo conectar con Telegram") from None

    if not result.get("ok"):
        raise SystemExit(f"Telegram rechazó la prueba: {result.get('description', 'error sin detalle')}")
    print("Mensaje de prueba enviado correctamente.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
