#!/usr/bin/env python3
"""Publish fresh, explicitly approved offers to one Telegram channel."""

from __future__ import annotations

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parent
OFFERS_PATH = ROOT / "offers.json"
PUBLISHED_PATH = ROOT / "state" / "published.json"
IMAGE_DIR = ROOT / "images"
OUTPUT_DIR = ROOT / "output"
MAX_PRICE_AGE = timedelta(minutes=20)
ASIN_PATH = re.compile(r"/dp/([A-Z0-9]{10})(?:/|$)", re.IGNORECASE)
ASIN_PATTERN = re.compile(r"^[A-Z0-9]{10}$", re.IGNORECASE)
SAFE_ID = re.compile(r"^[A-Z0-9_-]{1,80}$", re.IGNORECASE)
AMAZON_SHORT_HOSTS = {"link.amazon", "www.link.amazon", "amzn.to", "www.amzn.to"}
AMAZON_PRODUCT_HOSTS = {"amazon.es", "www.amazon.es"}
WALLAPOP_HOSTS = {"wallapop.com", "www.wallapop.com", "es.wallapop.com"}
MADRID = ZoneInfo("Europe/Madrid")


class OfferError(ValueError):
    pass


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OfferError(f"No se pudo leer {path.name}: {exc}") from exc


def parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise OfferError("checked_at debe ser una fecha ISO 8601 con zona horaria")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise OfferError("checked_at no es una fecha ISO 8601 válida") from exc
    if parsed.tzinfo is None:
        raise OfferError("checked_at debe incluir zona horaria")
    return parsed.astimezone(timezone.utc)


def money(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OfferError(f"{field} debe ser un número en euros")
    amount = float(value)
    if amount <= 0:
        raise OfferError(f"{field} debe ser mayor que cero")
    return amount


def nonnegative_money(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OfferError(f"{field} debe ser un número en euros")
    amount = float(value)
    if amount < 0:
        raise OfferError(f"{field} no puede ser negativo")
    return amount


def validate_offer(offer: object, now: datetime) -> dict:
    if not isinstance(offer, dict):
        raise OfferError("Cada oferta debe ser un objeto JSON")

    required = (
        "id", "asin", "title", "affiliate_url", "image_path", "current_price_eur",
        "reference_price_eur", "reference_period_days", "reference_source",
        "reference_source_url", "checked_at", "approved_by", "wallapop_comparables",
        "resale_fees_eur", "resale_shipping_eur",
    )
    missing = [name for name in required if not offer.get(name)]
    if missing:
        raise OfferError("Faltan campos: " + ", ".join(missing))

    offer_id = offer["id"]
    title = offer["title"]
    if not isinstance(offer_id, str) or not SAFE_ID.fullmatch(offer_id.strip()):
        raise OfferError("id solo puede contener letras, números, guion y guion bajo (máximo 80 caracteres)")
    if not isinstance(title, str) or not title.strip():
        raise OfferError("title debe ser texto no vacío")
    if len(title.strip()) > 300:
        raise OfferError("title no puede superar 300 caracteres")
    if not isinstance(offer["approved_by"], str) or not offer["approved_by"].strip():
        raise OfferError("approved_by debe identificar a quien revisó la oferta")

    asin = offer["asin"].strip().upper() if isinstance(offer["asin"], str) else ""
    if not ASIN_PATTERN.fullmatch(asin):
        raise OfferError("asin debe contener los 10 caracteres del producto de Amazon")

    affiliate_url = offer["affiliate_url"]
    if not isinstance(affiliate_url, str):
        raise OfferError("affiliate_url debe ser texto")
    parsed_affiliate = urllib.parse.urlparse(affiliate_url)
    if parsed_affiliate.scheme != "https" or parsed_affiliate.hostname not in (AMAZON_SHORT_HOSTS | AMAZON_PRODUCT_HOSTS):
        raise OfferError("affiliate_url debe ser HTTPS y usar link.amazon, amzn.to o Amazon.es")
    if parsed_affiliate.hostname in AMAZON_PRODUCT_HOSTS:
        match = ASIN_PATH.search(parsed_affiliate.path)
        if not match or match.group(1).upper() != asin:
            raise OfferError("el enlace directo de Amazon.es debe apuntar al ASIN indicado")

    current = money(offer["current_price_eur"], "current_price_eur")
    reference = money(offer["reference_price_eur"], "reference_price_eur")
    if reference <= current:
        raise OfferError("reference_price_eur debe ser superior al precio actual")

    days = offer["reference_period_days"]
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 3650:
        raise OfferError("reference_period_days debe estar entre 1 y 3650")
    if not isinstance(offer["reference_source"], str) or not offer["reference_source"].strip():
        raise OfferError("reference_source debe identificar la fuente de la referencia")

    if not isinstance(offer["reference_source_url"], str):
        raise OfferError("reference_source_url debe ser texto")
    source_url = urllib.parse.urlparse(offer["reference_source_url"])
    if source_url.scheme != "https" or not source_url.hostname:
        raise OfferError("reference_source_url debe ser HTTPS")

    checked_at = parse_timestamp(offer["checked_at"])
    age = now - checked_at
    if age < timedelta(minutes=-5):
        raise OfferError("checked_at está más de cinco minutos en el futuro")
    if age > MAX_PRICE_AGE:
        raise OfferError("precio obsoleto: vuelve a comprobarlo y actualiza checked_at")

    image_name = offer["image_path"]
    if not isinstance(image_name, str) or Path(image_name).name != image_name:
        raise OfferError("image_path debe ser el nombre de un archivo dentro de images/")
    image_path = (IMAGE_DIR / image_name).resolve()
    if image_path.parent != IMAGE_DIR.resolve() or not image_path.is_file():
        raise OfferError(f"No se encuentra images/{image_name}")
    if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise OfferError("image_path debe terminar en JPG, JPEG, PNG o WEBP")
    if image_path.stat().st_size > 10 * 1024 * 1024:
        raise OfferError("la imagen del producto supera 10 MB")

    resale_data = None
    comparables = offer["wallapop_comparables"]
    if not isinstance(comparables, list):
        raise OfferError("wallapop_comparables debe ser una lista de anuncios revisados")
    if len(comparables) < 3:
        raise OfferError("incluye al menos 3 anuncios comparables de Wallapop para estimar la media")
    if len(comparables) > 20:
        raise OfferError("usa como máximo 20 anuncios comparables de Wallapop")
    prices = []
    kinds = set()
    for index, item in enumerate(comparables, start=1):
        if not isinstance(item, dict):
            raise OfferError(f"wallapop_comparables[{index}] debe ser un objeto")
        item_title = item.get("title")
        item_kind = item.get("match")
        listing_url = item.get("url")
        if not isinstance(item_title, str) or not item_title.strip():
            raise OfferError(f"falta el título del anuncio Wallapop {index}")
        if item_kind not in {"exacto", "similar"}:
            raise OfferError(f"wallapop_comparables[{index}].match debe ser exacto o similar")
        parsed_listing = urllib.parse.urlparse(listing_url if isinstance(listing_url, str) else "")
        if parsed_listing.scheme != "https" or parsed_listing.hostname not in WALLAPOP_HOSTS:
            raise OfferError(f"wallapop_comparables[{index}].url debe ser un enlace HTTPS de Wallapop")
        prices.append(money(item.get("price_eur"), f"precio Wallapop {index}"))
        kinds.add(item_kind)
    fees = nonnegative_money(offer.get("resale_fees_eur"), "resale_fees_eur")
    shipping = nonnegative_money(offer.get("resale_shipping_eur"), "resale_shipping_eur")
    average = sum(prices) / len(prices)
    net = average - current - fees - shipping
    resale_data = {
        "price": average,
        "count": len(prices),
        "match": "similar" if "similar" in kinds else "exacto",
        "net": net,
        "roi": (net / current) * 100,
    }

    return {
        "id": offer_id.strip(),
        "title": title.strip(),
        "url": affiliate_url,
        "asin": asin,
        "image_path": image_path,
        "current": current,
        "reference": reference,
        "days": days,
        "source": offer["reference_source"].strip(),
        "checked_at": checked_at,
        "resale": resale_data,
    }


def build_message(offer: dict) -> str:
    savings = offer["reference"] - offer["current"]
    pct = savings / offer["reference"] * 100
    checked = offer["checked_at"].astimezone(MADRID).strftime("%d/%m/%Y %H:%M %Z")
    title = offer["title"]
    if len(title) > 100:
        title = title[:97].rstrip() + "…"
    lines = [
        f"<b>{html.escape(title)}</b>",
        f"Precio normal ({offer['days']} d): <s>{offer['reference']:.2f} €</s>",
        f"Precio actual: <b>{offer['current']:.2f} €</b>",
        f"Ahorras: <b>{savings:.2f} € · -{pct:.0f} %</b>",
    ]
    if offer["resale"]:
        resale = offer["resale"]
        lines.extend([
            f"Reventa potencial: ~{resale['price']:.2f} € (media de {resale['count']} anuncios Wallapop)",
            f"ROI estimado: ~{resale['roi']:.0f} % antes de impuestos",
            "Precios anunciados; pueden no ser precios de venta.",
        ])
    safe_url = html.escape(offer["url"], quote=True)
    lines.extend([
        f"🔗 <a href=\"{safe_url}\">COMPRAR EN AMAZON</a>",
        f"Comprobado: {html.escape(checked)} · precio y stock sujetos a cambios.",
        "En calidad de Afiliado de Amazon, obtengo ingresos por las compras adscritas que cumplen los requisitos aplicables.",
    ])
    return "\n".join(lines)


def _font(size: int, bold: bool = False):
    paths = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"]
        if bold else
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"]
    )
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def euro(amount: float) -> str:
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def create_price_card(offer: dict) -> Path:
    width, height = 1244, 1080
    canvas = Image.new("RGB", (width, height), "#f7f7f7")
    draw = ImageDraw.Draw(canvas)

    # Mismo formato apaisado, panel de producto y escala tipográfica de la referencia.
    draw.rounded_rectangle((34, 28, 674, 1052), radius=34, fill="#ffffff", outline="#eceeef", width=2)
    with Image.open(offer["image_path"]) as source:
        product = ImageOps.contain(source.convert("RGB"), (590, 940), method=Image.Resampling.LANCZOS)
    canvas.paste(product, (58 + (590 - product.width) // 2, 70 + (940 - product.height) // 2))
    draw = ImageDraw.Draw(canvas)

    x = 744
    label_font = _font(29)
    label_color = "#64696f"

    def draw_fit(value: str, y: int, size: int, max_width: int, color: str, bold: bool = True):
        chosen = _font(size, bold=bold)
        box = draw.textbbox((0, 0), value, font=chosen)
        while box[2] > max_width and chosen.size > 34:
            chosen = _font(chosen.size - 2, bold=bold)
            box = draw.textbbox((0, 0), value, font=chosen)
        draw.text((x, y), value, font=chosen, fill=color)
        return box

    savings = offer["reference"] - offer["current"]
    savings_pct = savings / offer["reference"] * 100
    resale = offer["resale"]

    boxes = [
        (700, 28, 1218, 213),
        (700, 231, 1218, 443),
        (700, 461, 1218, 646),
        (700, 664, 1218, 847),
        (700, 865, 1218, 1052),
    ]
    fills = ["#ffffff", "#fff2e9", "#ffffff", "#ffffff", "#ffffff"]
    for box, fill in zip(boxes, fills):
        draw.rounded_rectangle(box, radius=28, fill=fill, outline="#eceeef", width=1)

    draw.text((x, 58), "Precio normal", font=label_font, fill=label_color)
    normal_value = euro(offer["reference"])
    normal_box = draw_fit(normal_value, 96, 76, 442, "#101114")
    draw.line((x - 2, 151, x + normal_box[2] + 5, 121), fill="#60646a", width=5)

    draw.text((x, 258), "Precio actual", font=label_font, fill=label_color)
    draw_fit(euro(offer["current"]), 293, 84, 442, "#e8471d")

    draw.text((x, 486), "Ahorras", font=label_font, fill=label_color)
    saving_text = euro(savings)
    pill = (1052, 510, 1190, 602)
    draw.rounded_rectangle(pill, radius=20, fill="#e4f6e9")
    saving_max_width = pill[0] - x - 24
    draw_fit(saving_text, 521, 66, saving_max_width, "#087a3a")
    pct_text = f"-{savings_pct:.0f} %"
    pct_size = 48
    pct_font = _font(pct_size, bold=True)
    pct_box = draw.textbbox((0, 0), pct_text, font=pct_font)
    while pct_box[2] > pill[2] - pill[0] - 12 and pct_size > 34:
        pct_size -= 2
        pct_font = _font(pct_size, bold=True)
        pct_box = draw.textbbox((0, 0), pct_text, font=pct_font)
    pct_x = pill[0] + (pill[2] - pill[0] - pct_box[2]) // 2
    pct_y = pill[1] + (pill[3] - pill[1] - (pct_box[3] - pct_box[1])) // 2 - pct_box[1]
    draw.text((pct_x, pct_y), pct_text, font=pct_font, fill="#087a3a")

    draw.text((x, 689), "Reventa potencial", font=label_font, fill=label_color)
    draw_fit("~" + euro(resale["price"]), 724, 76, 442, "#101114")

    draw.text((x, 890), "ROI estimado", font=label_font, fill=label_color)
    draw_fit(f"~{resale['roi']:.0f} %", 925, 80, 442, "#087a3a")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"{offer['id']}.jpg"
    canvas.save(output, format="JPEG", quality=90, optimize=True)
    return output


def send_photo(token: str, chat_id: str, image_path: Path, caption: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    boundary = "----telegram" + uuid.uuid4().hex
    parts = []

    def field(name: str, value: str) -> None:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))

    field("chat_id", chat_id)
    field("caption", caption)
    field("parse_mode", "HTML")
    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    data = image_path.read_bytes()
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{image_path.name}\"\r\nContent-Type: {mime}\r\n\r\n".encode("utf-8")
        + data + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    request = urllib.request.Request(
        url,
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
        raise RuntimeError(f"Telegram rechazó el mensaje: {detail}") from None
    except urllib.error.URLError:
        raise RuntimeError("No se pudo conectar con Telegram") from None

    if not result.get("ok"):
        raise RuntimeError(f"Telegram rechazó el mensaje: {result.get('description', 'error sin detalle')}")


def main() -> int:
    try:
        offers = read_json(OFFERS_PATH)
        if not isinstance(offers, list):
            raise OfferError("offers.json debe contener una lista")
        published = read_json(PUBLISHED_PATH)
        if not isinstance(published, list) or not all(isinstance(item, str) for item in published):
            raise OfferError("state/published.json debe ser una lista de IDs")

        approved = [item for item in offers if isinstance(item, dict) and item.get("status") == "approved"]
        if not approved:
            print("No hay ofertas aprobadas; no se publica nada.")
            return 0

        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat_id:
            raise OfferError("Configura TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en GitHub Actions Secrets")

        now = datetime.now(timezone.utc)
        published_set = set(published)
        for raw in approved:
            offer = validate_offer(raw, now)
            if offer["id"] in published_set:
                print(f"{offer['id']}: ya publicado; se omite.")
                continue
            card_path = create_price_card(offer)
            send_photo(token, chat_id, card_path, build_message(offer))
            published_set.add(offer["id"])
            PUBLISHED_PATH.parent.mkdir(parents=True, exist_ok=True)
            PUBLISHED_PATH.write_text(
                json.dumps(sorted(published_set), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"{offer['id']}: publicado correctamente.")
            time.sleep(1)
        return 0
    except OfferError as exc:
        print(f"Error de configuración o de oferta: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

