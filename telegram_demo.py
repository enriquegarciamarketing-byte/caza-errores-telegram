#!/usr/bin/env python3
"""Send a clearly labeled visual demo for the requested Amazon product."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

ASIN = "B0DTB7QXRZ"
TITLE = "Bandejas de aluminio Cuki Professional con tapa RPET"
PRICE = "19,05 €"
AFFILIATE_URL = f"https://www.amazon.es/dp/{ASIN}?tag=cazadores_errores-21"


def font(size: int, bold: bool = False):
    filename = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    try:
        return ImageFont.truetype(filename, size)
    except OSError:
        return ImageFont.load_default()


def make_card() -> BytesIO:
    W, H = 1200, 1280
    image = Image.new("RGB", (W, H), "#f4f5f7")
    d = ImageDraw.Draw(image)

    d.rounded_rectangle((28, 24, W - 28, 145), radius=30, fill="#fff0cf", outline="#e39a16", width=3)
    d.text((60, 48), "EJEMPLO · NO ES UN CHOLLO VERIFICADO", font=font(34, True), fill="#8d4300")
    d.text((62, 100), "Datos parciales; comprueba el precio antes de comprar", font=font(22), fill="#624b36")

    d.rounded_rectangle((28, 170, 565, 1245), radius=34, fill="#ffffff", outline="#e1e4e8", width=3)
    d.rounded_rectangle((595, 170, W - 28, 348), radius=30, fill="#ffffff")
    d.rounded_rectangle((595, 370, W - 28, 570), radius=30, fill="#fff2e8")
    d.rounded_rectangle((595, 592, W - 28, 776), radius=30, fill="#ffffff")
    d.rounded_rectangle((595, 798, W - 28, 984), radius=30, fill="#ffffff")
    d.rounded_rectangle((595, 1006, W - 28, 1190), radius=30, fill="#ffffff")

    # Neutral illustration of foil trays: it is explicitly marked as an illustration,
    # not an Amazon product photograph.
    d.rounded_rectangle((85, 435, 505, 790), radius=48, fill="#f0f2f4", outline="#bbc2c9", width=5)
    d.polygon([(120, 485), (470, 485), (425, 740), (165, 740)], fill="#b8bec5", outline="#7e8790")
    d.line([(120, 485), (165, 740)], fill="#e8ebee", width=13)
    d.line([(470, 485), (425, 740)], fill="#8d959d", width=12)
    d.rounded_rectangle((143, 455, 484, 515), radius=23, fill="#d9dde1", outline="#8d959d", width=4)
    d.line([(160, 520), (435, 520)], fill="#7b838b", width=4)
    d.line([(174, 560), (420, 560)], fill="#dfe3e7", width=4)
    d.text((108, 825), "Ilustración del producto", font=font(25, True), fill="#40464d")
    d.text((86, 885), "Bandejas aluminio + tapa RPET", font=font(25), fill="#454b52")
    d.text((86, 930), "Cuki Professional", font=font(24), fill="#666d75")

    def metric(y, label, value, color="#17191c", value_size=44, sub=None):
        d.text((638, y), label, font=font(25), fill="#5e646b")
        d.text((638, y + 54), value, font=font(value_size, True), fill=color)
        if sub:
            d.text((638, y + 121), sub, font=font(20), fill="#6a7077")

    metric(198, "Precio habitual", "No verificado", value_size=38, sub="Sin histórico fiable disponible")
    metric(398, "Precio observado en Amazon", PRICE, color="#e44819", value_size=62, sub="Consulta: 28/10/2026 · puede cambiar")
    metric(620, "Ahorro", "No calculable", color="#287446", value_size=40, sub="Falta un precio de referencia válido")
    metric(826, "Reventa potencial", "No verificable", value_size=39, sub="Producto desechable; sin comparables")
    metric(1034, "ROI estimado", "No calculable", color="#287446", value_size=42, sub="No se inventan cifras")

    output = BytesIO()
    image.save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise SystemExit("Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")

    caption = (
        "🧪 <b>EJEMPLO DE FORMATO · NO ES UN CHOLLO VERIFICADO</b>\n"
        f"{TITLE}\n"
        f"Precio observado en Amazon: <b>{PRICE}</b> (28/10/2026; puede cambiar).\n"
        "No hay datos fiables para afirmar precio habitual, ahorro, reventa o ROI. "
        "La imagen es una ilustración de ejemplo.\n"
        f'<a href="{AFFILIATE_URL}">Ver producto en Amazon</a> · enlace afiliado'
    )
    boundary = "----CodexTelegramDemoBoundary"
    photo = make_card().getvalue()
    fields = {
        "chat_id": chat_id,
        "caption": caption,
        "parse_mode": "HTML",
    }
    chunks = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ])
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="photo"; filename="demo-caza-errores.png"\r\n',
        b"Content-Type: image/png\r\n\r\n",
        photo,
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
        raise SystemExit("Telegram no aceptó la tarjeta de demostración")
    print(f"Demo publicada correctamente. message_id={result['result']['message_id']}")


if __name__ == "__main__":
    main()
