#!/usr/bin/env python3
"""Publish a format demo with a truthful unavailable-price status."""

from __future__ import annotations

import json
import os
import urllib.request
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

ASIN = "B0HNXPGYMF"
TITLE = "Set de 3 mesas auxiliares redondas DRW"
AFFILIATE_URL = f"https://www.amazon.es/dp/{ASIN}?tag=cazadores_errores-21"


def font(size: int, bold: bool = False):
    name = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def make_card() -> BytesIO:
    w, h = 1200, 1160
    im = Image.new("RGB", (w, h), "#f7f7f7")
    d = ImageDraw.Draw(im)

    d.rounded_rectangle((24, 20, w - 24, 105), 26, fill="#ffffff", outline="#e7e9eb", width=2)
    d.text((52, 43), "PRODUCTO NO DISPONIBLE", font=font(34, True), fill="#c9461a")

    d.rounded_rectangle((24, 128, 554, 1135), 30, fill="#ffffff", outline="#e6e8ea", width=2)
    boxes = [(582,128,1176,300),(582,318,1176,490),(582,508,1176,680),(582,698,1176,870),(582,888,1176,1060)]
    for i, box in enumerate(boxes):
        d.rounded_rectangle(box, 27, fill="#fff2e9" if i == 1 else "#ffffff", outline="#eceeef", width=1)

    # Original vector illustration of three round nesting side tables.
    # It is an illustration, not an Amazon-sourced product photograph.
    d.rounded_rectangle((56, 184, 522, 846), 34, fill="#fafafa", outline="#edf0f2", width=2)

    def table(cx, cy, rx, ry, top_color, leg_color, front=False):
        # Four slim legs with a slight outward angle.
        leg_y = cy + int(ry * 0.62)
        bottom_y = cy + int(ry * 2.25)
        spread = int(rx * 0.55)
        d.line((cx - int(rx*.42), leg_y, cx - spread, bottom_y), fill=leg_color, width=12)
        d.line((cx + int(rx*.42), leg_y, cx + spread, bottom_y), fill=leg_color, width=12)
        d.line((cx - int(rx*.18), leg_y + 8, cx - int(rx*.12), bottom_y), fill=leg_color, width=8)
        d.line((cx + int(rx*.18), leg_y + 8, cx + int(rx*.12), bottom_y), fill=leg_color, width=8)
        # Round wooden surface with gold edge.
        d.ellipse((cx-rx, cy-ry, cx+rx, cy+ry), fill="#c99e55", outline="#ae833b", width=5)
        d.ellipse((cx-rx+8, cy-ry+6, cx+rx-8, cy+ry-6), fill=top_color, outline="#e8d7b4", width=3)
        d.arc((cx-rx+20, cy-ry+14, cx+rx-20, cy+ry-14), 15, 165, fill="#eee3ce", width=3)

    table(300, 344, 148, 54, "#efe6d6", "#b68b48")
    table(200, 530, 122, 46, "#f5eee2", "#c39a59")
    table(372, 605, 100, 40, "#eaddc6", "#b68b48")

    d.text((76, 880), "Ilustración del producto", font=font(24, True), fill="#41464c")
    d.text((76, 928), "Set de 3 mesas redondas", font=font(24), fill="#41464c")
    d.text((76, 970), "DRW · acabado dorado", font=font(23), fill="#646a70")

    def metric(y, label, value, color="#17191c", size=42, note=None):
        d.text((620, y), label, font=font(24), fill="#62686e")
        d.text((620, y+48), value, font=font(size, True), fill=color)
        if note:
            d.text((620, y+112), note, font=font(19), fill="#747a80")

    metric(150, "Precio normal", "No verificado", size=36, note="Sin referencia histórica confirmada")
    metric(340, "Precio actual", "No disponible", color="#df4a1d", size=37, note="Amazon indica que no está disponible")
    metric(530, "Ahorro", "No calculable", color="#237347", size=37, note="No se puede comparar un precio actual")
    metric(720, "Reventa potencial", "No verificada", size=34, note="Sin comparables confirmados")
    metric(910, "ROI estimado", "No calculable", color="#237347", size=38, note="Sin precio actual ni comparables")

    out = BytesIO()
    im.save(out, format="PNG", optimize=True)
    out.seek(0)
    return out


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise SystemExit("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")

    boundary = "----CodexTelegramProductBoundary"
    chunks = []
    for name, value in {"chat_id": chat_id, "caption": AFFILIATE_URL}.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ])
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="photo"; filename="tarjeta-producto.png"\r\n',
        b"Content-Type: image/png\r\n\r\n",
        make_card().getvalue(),
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise SystemExit("Telegram no aceptó la tarjeta del producto")
    print(f"Tarjeta publicada. message_id={result['result']['message_id']}")


if __name__ == "__main__":
    main()
