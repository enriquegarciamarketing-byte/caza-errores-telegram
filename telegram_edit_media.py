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
    # Proporción apaisada y jerarquía tipográfica de la imagen de referencia.
    width, height = 1244, 1080
    image = Image.new("RGB", (width, height), "#f7f7f7")
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((34, 28, 674, 1052), 34, fill="#ffffff", outline="#eceeef", width=2)
    photo = ImageOps.contain(fetch_product_image(), (590, 940), method=Image.Resampling.LANCZOS)
    image.paste(photo, (58 + (590 - photo.width) // 2, 70 + (940 - photo.height) // 2))

    boxes = [
        (700, 28, 1218, 213),
        (700, 231, 1218, 443),
        (700, 461, 1218, 646),
        (700, 664, 1218, 847),
        (700, 865, 1218, 1052),
    ]
    fills = ["#ffffff", "#fff2e9", "#ffffff", "#ffffff", "#ffffff"]
    for box, fill in zip(boxes, fills):
        draw.rounded_rectangle(box, 28, fill=fill, outline="#eceeef", width=1)

    label_font = font(29)
    label_color = "#64696f"
    value_color = "#101114"
    x = 744

    # Precio normal de referencia: valor aproximado y tachado.
    draw.text((x, 58), "Precio normal", font=label_font, fill=label_color)
    normal_font = font(76, True)
    normal_y = 96
    draw.text((x, normal_y), NORMAL_PRICE, font=normal_font, fill=value_color)
    normal_box = draw.textbbox((x, normal_y), NORMAL_PRICE, font=normal_font)
    draw.line((normal_box[0] - 2, normal_y + 55, normal_box[2] + 3, normal_y + 25), fill="#60646a", width=5)

    # Precio actual en naranja.
    draw.text((x, 258), "Precio actual", font=label_font, fill=label_color)
    draw.text((x, 293), CURRENT_PRICE, font=font(84, True), fill="#e8471d")

    # Ahorro y porcentaje en verde, como en la referencia.
    draw.text((x, 486), "Ahorras", font=label_font, fill=label_color)
    draw.text((x, 521), SAVINGS, font=font(66, True), fill="#087a3a")
    pill = (1052, 510, 1190, 602)
    draw.rounded_rectangle(pill, 20, fill="#e4f6e9")
    pct_font = font(48, True)
    pct_box = draw.textbbox((0, 0), SAVINGS_PERCENT, font=pct_font)
    pct_x = pill[0] + (pill[2] - pill[0] - pct_box[2]) // 2
    pct_y = pill[1] + (pill[3] - pill[1] - (pct_box[3] - pct_box[1])) // 2 - pct_box[1]
    draw.text((pct_x, pct_y), SAVINGS_PERCENT, font=pct_font, fill="#087a3a")

    # Reventa y ROI llevan tilde de aproximación; no se presentan como precio garantizado.
    draw.text((x, 689), "Reventa potencial", font=label_font, fill=label_color)
    draw.text((x, 724), RESALE, font=font(76, True), fill=value_color)
    draw.text((x, 890), "ROI estimado", font=label_font, fill=label_color)
    draw.text((x, 925), ROI, font=font(80, True), fill="#087a3a")

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
