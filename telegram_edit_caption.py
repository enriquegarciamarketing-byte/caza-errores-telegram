#!/usr/bin/env python3
"""Update the radiator post with the branded card and concise offer copy."""

from __future__ import annotations

import json
import os
import uuid
import urllib.error
import urllib.request

from publisher import IMAGE_DIR, build_message, create_price_card


OFFER_ID = "B0FY362Y68-20261028-0305"
MESSAGE_ID = 14


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise SystemExit("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")

    with open("offers.json", encoding="utf-8") as source:
        offers = json.load(source)
    raw = next((offer for offer in offers if offer.get("id") == OFFER_ID), None)
    if raw is None:
        raise SystemExit(f"No se encontró la oferta {OFFER_ID}")

    current = float(raw["current_price_eur"])
    reference = float(raw["reference_price_eur"])
    discount = (reference - current) / reference * 100
    category = "ERROR DE PRECIO" if discount >= 70 else (
        "MÍNIMO HISTÓRICO" if raw.get("historical_low") else "GANGA"
    )
    offer = {
        "id": raw["id"],
        "title": raw["title"],
        "image_path": IMAGE_DIR / raw["image_path"],
        "category": category,
        "current": current,
        "reference": reference,
        "days": raw["reference_period_days"],
        "historical_low": bool(raw.get("historical_low")),
        "resale": None,
    }
    caption = build_message({**offer, "url": raw["affiliate_url"]})
    image_path = create_price_card(offer)

    boundary = "----telegram" + uuid.uuid4().hex
    parts: list[bytes] = []

    def field(name: str, value: str) -> None:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8")
        )

    field("chat_id", chat_id)
    field("message_id", str(MESSAGE_ID))
    field("media", json.dumps({
        "type": "photo",
        "media": "attach://photo",
        "caption": caption,
        "parse_mode": "HTML",
    }, ensure_ascii=False))
    image_data = image_path.read_bytes()
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{image_path.name}\"\r\nContent-Type: image/jpeg\r\n\r\n".encode("utf-8")
        + image_data + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/editMessageMedia",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
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
        raise SystemExit(f"Telegram rechazó la actualización: {detail}") from None
    except urllib.error.URLError:
        raise SystemExit("No se pudo conectar con Telegram") from None
    if not result.get("ok"):
        raise SystemExit("Telegram rechazó la actualización de la creatividad")
    print(f"Creatividad y copy actualizados en el mensaje {result['result']['message_id']}.")


if __name__ == "__main__":
    main()
