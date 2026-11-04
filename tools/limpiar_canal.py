#!/usr/bin/env python3
"""Limpia los posts antiguos de @cazachollos_com para la revisión de Amazon Afiliados.

Cada post del bot pasa a «Oferta finalizada»: se cambia la tarjeta (que llevaba precios) por una neutra con
el logo, se quita el botón y el enlace, y el texto queda sin precios, sin estrellas y sin «Amazon».
Los resúmenes de texto se reescriben igual. Los mensajes que no son del bot se dejan como están.

Uso: TELEGRAM_BOT_TOKEN=... python tools/limpiar_canal.py [--hasta 250] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import canal_nube as cn  # noqa: E402
from scanner import Telegram  # noqa: E402

CHANNEL = "@cazachollos_com"
CAPTION = "⛔ <b>OFERTA FINALIZADA</b>\n\nLos chollos nuevos salen cada día en @cazachollos_com 🔔"
TEXT = "⛔ <b>RESUMEN FINALIZADO</b>\n\nLos chollos nuevos salen cada día en @cazachollos_com 🔔"


def neutral_card() -> Path:
    """Tarjeta sin precios ni fotos: el logo del canal y «Oferta finalizada»."""
    from PIL import Image, ImageDraw, ImageOps
    from publisher import BRAND_ORANGE, DEAL_LOGO, _font

    canvas = Image.new("RGB", (1080, 1080), "#F4F5F5")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((24, 24, 1056, 1056), radius=34, fill="#FFFFFF", outline="#E7E9EB", width=2)
    with Image.open(DEAL_LOGO) as source:
        logo = ImageOps.contain(source.convert("RGB"), (420, 420))
    canvas.paste(logo, ((1080 - logo.width) // 2, 170))
    for text, size, color, y in (("OFERTA FINALIZADA", 70, "#131921", 650),
                                 ("Los chollos nuevos, cada día en", 34, "#697078", 770),
                                 ("t.me/cazachollos_com", 44, BRAND_ORANGE, 820)):
        font = _font(size, bold=True)
        box = draw.textbbox((0, 0), text, font=font)
        draw.text(((1080 - (box[2] - box[0])) // 2 - box[0], y), text, font=font, fill=color)
    out = cn.OUTPUT / "oferta-finalizada.jpg"
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, "JPEG", quality=92)
    return out


def edit_media(tg: Telegram, message_id: int, image: Path) -> dict:
    """editMessageMedia con la foto subida en el mismo envío. Sin reply_markup, Telegram quita el botón."""
    boundary = "----limpia" + uuid.uuid4().hex
    media = {"type": "photo", "media": "attach://card", "caption": CAPTION, "parse_mode": "HTML"}
    fields = {"chat_id": CHANNEL, "message_id": str(message_id), "media": json.dumps(media, ensure_ascii=False)}
    parts = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8")
             for k, v in fields.items()]
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"card\"; filename=\"{image.name}\"\r\n"
                 "Content-Type: image/jpeg\r\n\r\n".encode("utf-8") + image.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    req = urllib.request.Request(tg.base + "editMessageMedia", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        result = json.loads(exc.read().decode("utf-8") or "{}")
    if not result.get("ok"):
        raise RuntimeError(f"Telegram editMessageMedia: {result.get('description')}")
    return result["result"]


def with_retry(action):
    for _ in range(4):
        try:
            return action()
        except RuntimeError as exc:
            wait = re.search(r"retry after (\d+)", str(exc))
            if not wait:
                raise
            time.sleep(int(wait.group(1)) + 1)
    return action()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hasta", type=int, default=0, help="último ID de mensaje a revisar (por defecto, el último del bot + 30)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    state = cn.load_json(cn.STATE_PATH, {})
    posts = [p for p in state.get("posts") or [] if p.get("chat") == CHANNEL and p.get("message_id")]
    last = args.hasta or (max((int(p["message_id"]) for p in posts), default=0) + 30)
    card = neutral_card()
    print(f"Reviso los mensajes 1 a {last} de {CHANNEL}")
    if args.dry_run:
        return 0
    tg = Telegram(os.environ["TELEGRAM_BOT_TOKEN"].strip())
    cleaned, skipped = [], 0
    for message_id in range(1, last + 1):
        try:
            with_retry(lambda: edit_media(tg, message_id, card))
            cleaned.append(message_id)
            print(f"  {message_id}: tarjeta y texto limpios")
        except RuntimeError as exc:
            reason = str(exc).lower()
            if "not modified" not in reason and "not found" not in reason:
                try:
                    with_retry(lambda: tg.call("editMessageText", {
                        "chat_id": CHANNEL, "message_id": message_id, "text": TEXT, "parse_mode": "HTML",
                        "link_preview_options": {"is_disabled": True}}))
                    cleaned.append(message_id)
                    print(f"  {message_id}: resumen limpio")
                except RuntimeError as text_exc:
                    skipped += 1
                    print(f"  {message_id}: sin tocar ({text_exc})")
            elif "not modified" in reason:
                cleaned.append(message_id)
            else:
                skipped += 1
                print(f"  {message_id}: sin tocar ({exc})")
        time.sleep(1.1)

    # La memoria del canal deja de vigilar estos posts y guarda su texto nuevo, para que el seguimiento
    # nunca vuelva a escribir un texto antiguo con precios.
    now = int(time.time())
    done = set(cleaned)
    for post in state.get("posts") or []:
        if post.get("chat") == CHANNEL and post.get("message_id") in done:
            post["caption"] = CAPTION
            post["ended"] = post.get("ended") or now
            post["limpiado"] = now
    cn.save_state(state)
    print(f"Hecho: {len(cleaned)} mensajes limpios, {skipped} sin tocar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
