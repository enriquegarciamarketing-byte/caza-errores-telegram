#!/usr/bin/env python3
"""Replace an existing Telegram deal card with an Amazon product image and labeled estimates."""

from __future__ import annotations

import json
import os
import urllib.request
from io import BytesIO

from PIL import Image, ImageDraw, ImageFont, ImageOps

CHAT_ID = "@caza_errores"
MESSAGE_ID = 11
AFFILIATE_URL = "https://link.amazon/B07TxYJ9t"
AMAZON_IMAGE_URL = "https://m.media-amazon.com/images/I/61u8m0d%2BCbL.jpg"
CURRENT_PRICE = "71,00 €"
NORMAL_PRICE = "≈128 €"
SAVINGS = "≈57 €"
SAVINGS_PERCENT = "-45 %"
RESALE = "≈40 €"
ROI = "≈-44 %"


def font(size: int, bold: bool = False):
    name = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, size)
    except OSError:
        return ImageFont.load_default()


def fetch_product_image() -> Image.Image:
    request = urllib.request.Request(
        AMAZON_IMAGE_URL,
        headers={"User-Agent": "Mozilla/5.0 (compatible; DealCard/1.0)"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
    return Image.open(BytesIO(raw)).convert("RGB")


def make_card() -> bytes:
    width, height = 1200, 1200
    image = Image.new("RGB", (width, height), "#f7f7f7")
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((24, 20, width - 24, 104), 28, fill="#ffffff", outline="#e7e9eb", width=2)
    draw.text((48, 42), "Contour Unimouse · inalámbrico para zurdos", font=font(30, True), fill="#287b27")

    # Product photo on the left.
    draw.rounded_rectangle((24, 124, 552, 1176), 30, fill="#ffffff", outline="#e6e8ea", width=2)
    photo = fetch_product_image()
    photo.thumbnail((468, 870), Image.Resampling.LANCZOS)
    px = 288 - photo.width // 2
    py = 640 - photo.height // 2
    image.paste(photo, (px, py))

    # Five populated metrics on the right.
    boxes = [
        (576, 124, 1176, 322),
        (576, 336, 1176, 534),
        (576, 548, 1176, 746),
        (576, 760, 1176, 958),
        (576, 972, 1176, 1176),
    ]
    for index, box in enumerate(boxes):
        fill = "#fff2e9" if index == 1 else ("#eef9f0" if index == 2 else "#ffffff")
        draw.rounded_rectangle(box, 26, fill=fill, outline="#eceeef", width=1)

    def metric(index: int, label: str, value: str, color: str = "#17191c", size: int = 49, note: str = ""):
        left, top, right, bottom = boxes[index]
        draw.text((left + 38, top + 22), label, font=font(25), fill="#62686e")
        value_y = top + 64
        draw.text((left + 38, value_y), value, font=font(size, True), fill=color)
        if note:
            draw.text((left + 38, top + 142), note, font=font(18), fill="#747a80")
        return (left + 38, value_y, draw.textbbox((left + 38, value_y), value, font=font(size, True)))

    _, normal_y, normal_bbox = metric(0, "Precio normal", NORMAL_PRICE, size=52, note="Referencia de tienda nueva · aprox.")
    draw.line((normal_bbox[0], normal_y + 32, normal_bbox[2], normal_y + 32), fill="#55585b", width=5)

    metric(1, "Precio actual", CURRENT_PRICE, color="#e4481d", size=58, note="Amazon · precio observado")
    metric(2, "Ahorras", SAVINGS, color="#187543", size=52, note=f"Frente a {NORMAL_PRICE} · {SAVINGS_PERCENT}")
    metric(3, "Reventa potencial", RESALE, size=52, note="Estimación con ratones ergonómicos usados")
    metric(4, "ROI estimado", ROI, color="#187543", size=56, note="Al revender por el valor estimado")

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("Falta TELEGRAM_BOT_TOKEN")

    boundary = "----CodexTelegramEditMediaBoundary"
    media = json.dumps({
        "type": "photo",
        "media": "attach://photo",
        "caption": AFFILIATE_URL,
    }, ensure_ascii=False)
    fields = {
        "chat_id": CHAT_ID,
        "message_id": str(MESSAGE_ID),
        "media": media,
    }
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ])
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="photo"; filename="unimouse-deal-card.png"\r\n',
        b"Content-Type: image/png\r\n\r\n",
        make_card(),
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/editMessageMedia",
        data=b"".join(chunks),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.loads(response.read().decode())
    if not result.get("ok"):
        raise SystemExit("Telegram no permitió actualizar la imagen")
    print(f"Tarjeta actualizada. message_id={result['result']['message_id']}")


if __name__ == "__main__":
    main()
