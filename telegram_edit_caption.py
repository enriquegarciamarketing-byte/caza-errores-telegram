#!/usr/bin/env python3
"""Replace the existing post caption with the user's verified short affiliate URL."""
import json
import os
import urllib.parse
import urllib.request

CHAT_ID = "@caza_errores"
MESSAGE_ID = 11
CAPTION = "https://link.amazon/B07TxYJ9t"


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Falta TELEGRAM_BOT_TOKEN")
    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "message_id": MESSAGE_ID,
        "caption": CAPTION,
    }).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/editMessageCaption",
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode())
    if not result.get("ok"):
        raise SystemExit("Telegram no permitió actualizar el pie")
    print("Pie actualizado con el enlace corto solicitado.")


if __name__ == "__main__":
    main()
