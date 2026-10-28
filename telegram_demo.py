#!/usr/bin/env python3
"""Publish a truthful product card with only the affiliate URL as its caption."""

from __future__ import annotations

import json
import os
import urllib.request
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

ASIN = "B0D25NSSYM"
TITLE = "Contour Unimouse · ratón ergonómico inalámbrico para zurdos"
PRICE = "71,00 €"
AFFILIATE_URL = f"https://www.amazon.es/dp/{ASIN}?tag=cazadores_errores-21"


def font(size: int, bold: bool = False):
    name = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def make_card() -> BytesIO:
    w, h = 1200, 1200
    im = Image.new("RGB", (w, h), "#f7f7f7")
    d = ImageDraw.Draw(im)

    d.rounded_rectangle((26, 20, w - 26, 110), 27, fill="#ffffff", outline="#e7e9eb", width=2)
    d.text((52, 46), "Contour Unimouse · inalámbrico para zurdos", font=font(30, True), fill="#287b27")

    d.rounded_rectangle((26, 132, 550, 1170), 30, fill="#ffffff", outline="#e6e8ea", width=2)
    boxes = [(576,132,1174,302),(576,318,1174,488),(576,504,1174,674),(576,690,1174,860),(576,876,1174,1046)]
    for i, box in enumerate(boxes):
        d.rounded_rectangle(box, 27, fill="#fff2e9" if i == 1 else "#ffffff", outline="#eceeef", width=1)

    # Original illustration of a vertical ergonomic mouse; not an Amazon-sourced photo.
    d.rounded_rectangle((50, 164, 526, 882), 34, fill="#fafafa", outline="#edf0f2", width=2)
    # Adjustable tilted base and body.
    d.polygon([(124, 714), (407, 678), (462, 754), (166, 802)], fill="#b7bec5", outline="#818991")
    d.polygon([(163, 690), (236, 359), (302, 292), (389, 322), (431, 658), (370, 704)], fill="#25292e", outline="#111316")
    d.polygon([(236, 359), (302, 292), (389, 322), (405, 398), (263, 426)], fill="#343a40", outline="#111316")
    # Scroll wheel, button seams, and thumb support.
    d.rounded_rectangle((307, 344, 332, 398), 12, fill="#b8bec4", outline="#0e1012", width=3)
    d.line((278, 439, 398, 421), fill="#0c0e10", width=5)
    d.line((273, 454, 402, 437), fill="#626a72", width=3)
    d.polygon([(387, 470), (469, 452), (486, 484), (414, 516)], fill="#181b1e", outline="#0e1012")
    d.line((245, 489, 393, 467), fill="#50575e", width=3)
    d.ellipse((353, 572, 392, 611), fill="#1b1e22", outline="#6c747c", width=3)
    d.text((83, 824), "Ilustración del producto", font=font(22, True), fill="#555b61")

    def metric(y, label, value, color="#17191c", size=37, note=None):
        d.text((610, y), label, font=font(23), fill="#62686e")
        d.text((610, y+45), value, font=font(size, True), fill=color)
        if note:
            d.text((610, y+111), note, font=font(18), fill="#747a80")

    metric(151, "Precio normal", "No verificado", size=35, note="Sin referencia histórica confirmada")
    metric(337, "Precio actual", PRICE, color="#e4481d", size=54, note="En stock · observado 28/10/2026")
    metric(523, "Ahorras", "No calculable", color="#187543", size=34, note="Falta un precio normal fiable")
    metric(709, "Reventa potencial", "No verificada", size=32, note="Sin comparables confirmados")
    metric(895, "ROI estimado", "No calculable", color="#187543", size=35, note="No se inventan cifras")

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
        b'Content-Disposition: form-data; name="photo"; filename="contour-unimouse-card.png"\r\n',
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
