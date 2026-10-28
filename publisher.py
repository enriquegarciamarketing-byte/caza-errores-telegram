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
    if len(title) > 180:
        title = title[:177].rstrip() + "…"
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
    width, height = 1200, 1100
    canvas = Image.new("RGB", (width, height), "#f5f5f5")
    draw = ImageDraw.Draw(canvas)
    panel = "#ffffff"
    draw.rounded_rectangle((28, 28, 670, 1072), radius=36, fill=panel)

    with Image.open(offer["image_path"]) as source:
        product = ImageOps.contain(source.convert("RGB"), (590, 865), method=Image.Resampling.LANCZOS)
    canvas.paste(product, (50 + (598 - product.width) // 2, 125 + (865 - product.height) // 2))
    draw = ImageDraw.Draw(canvas)
    title = offer["title"].strip()
    title_font = _font(30, bold=True)
    title_display = title
    while draw.textbbox((0, 0), title_display, font=title_font)[2] > 555 and len(title_display) > 16:
        title_display = title_display[:-2].rstrip()
    if title_display != title:
        title_display = title_display.rstrip(" .…") + "…"
    draw.text((54, 52), title_display, font=title_font, fill="#30343b")

    savings = offer["reference"] - offer["current"]
    savings_pct = savings / offer["reference"] * 100
    cards = [
        ("Precio normal", euro(offer["reference"]), "normal"),
        ("Precio actual", euro(offer["current"]), "current"),
        ("Ahorras", f"{euro(savings)}   -{savings_pct:.0f} %", "saving"),
    ]
    resale = offer.get("resale")
    if resale:
        type_text = "Media de anuncios similares" if resale["match"] == "similar" else "Media del producto exacto"
        cards.extend([
            ("Reventa potencial", "~" + euro(resale["price"]), "resale"),
            (f"ROI estimado · {resale['count']} anuncios", f"~{resale['roi']:.0f} %", "roi"),
        ])
    x1, x2 = 700, 1172
    y = 28
    heights = [170, 190, 175, 165, 165]
    for index, (label, value, kind) in enumerate(cards):
        card_height = heights[index]
        if kind == "current":
            fill, value_color = "#fff3e8", "#ec4c19"
        elif kind in {"saving", "roi"}:
            fill, value_color = "#ffffff", "#087a3a"
        else:
            fill, value_color = "#ffffff", "#202124"
        draw.rounded_rectangle((x1, y, x2, y + card_height), radius=30, fill=fill)
        draw.text((x1 + 38, y + 22), label, font=_font(28), fill="#5b6068")
        value_font = _font(54 if len(value) < 19 else 42, bold=True)
        value_box = draw.textbbox((0, 0), value, font=value_font)
        while value_box[2] > (x2 - x1 - 76) and value_font.size > 30:
            value_font = _font(value_font.size - 2, bold=True)
            value_box = draw.textbbox((0, 0), value, font=value_font)
        draw.text((x1 + 38, y + 70), value, font=value_font, fill=value_color)
        if kind == "normal":
            value_width = min(value_box[2], x2 - x1 - 76)
            draw.line((x1 + 38, y + 100, x1 + 38 + value_width, y + 112), fill="#5c6066", width=5)
        if kind == "roi":
            draw.text((x1 + 38, y + card_height - 40), "Antes de impuestos", font=_font(19), fill="#6a7078")
        if kind == "resale":
            draw.text((x1 + 38, y + card_height - 40), type_text, font=_font(19), fill="#6a7078")
        y += card_height + 18

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
