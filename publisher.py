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
MIN_BARGAIN_DISCOUNT_PERCENT = 40
MIN_ERROR_DISCOUNT_PERCENT = 70
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
        "reference_source_url", "checked_at", "approved_by",
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
    if isinstance(days, bool) or not isinstance(days, int) or days != 90:
        raise OfferError("reference_period_days debe ser 90 para comparar el histórico normalizado")
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

    savings_pct = (reference - current) / reference * 100
    historical_low = offer.get("historical_low", False)
    if not isinstance(historical_low, bool):
        raise OfferError("historical_low debe ser true o false")
    if savings_pct + 1e-9 < MIN_BARGAIN_DISCOUNT_PERCENT and not historical_low:
        raise OfferError("se requiere un descuento verificado de al menos el 40 % o marcar un mínimo histórico revisado")

    resale_data = None
    comparables = offer.get("wallapop_comparables", [])
    if comparables is None:
        comparables = []
    if not isinstance(comparables, list):
        raise OfferError("wallapop_comparables debe ser una lista de anuncios revisados")
    if comparables and len(comparables) < 3:
        raise OfferError("si incluyes comparables, añade al menos 3 anuncios revisados de Wallapop")
    if len(comparables) > 20:
        raise OfferError("usa como máximo 20 anuncios comparables de Wallapop")
    if comparables:
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
        fees = nonnegative_money(offer.get("resale_fees_eur", 0), "resale_fees_eur")
        shipping = nonnegative_money(offer.get("resale_shipping_eur", 0), "resale_shipping_eur")
        average = sum(prices) / len(prices)
        net = average - current - fees - shipping
        resale_data = {
            "price": average,
            "count": len(prices),
            "match": "similar" if "similar" in kinds else "exacto",
            "net": net,
            "roi": (net / current) * 100,
        }

    if savings_pct + 1e-9 >= MIN_ERROR_DISCOUNT_PERCENT:
        category = "ERROR DE PRECIO"
    elif historical_low:
        category = "MÍNIMO HISTÓRICO"
    else:
        category = "GANGA"

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
        "discount_pct": savings_pct,
        "historical_low": historical_low,
        "category": category,
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
    width, height = 1080, 1080
    ink = "#131921"
    orange = "#FF9900"
    muted = "#697078"
    paper = "#F4F5F5"
    canvas = Image.new("RGB", (width, height), paper)
    draw = ImageDraw.Draw(canvas)

    # Diseño original con una paleta inspirada en Amazon; no usa su logotipo.
    draw.rounded_rectangle((24, 24, 1056, 1056), radius=34, fill="#FFFFFF", outline="#E7E9EB", width=2)
    draw.text((58, 48), "CAZA ERRORES", font=_font(26, bold=True), fill=ink)
    draw.text((58, 81), "OFERTAS REVISADAS", font=_font(15, bold=True), fill=muted)

    category = offer["category"]
    category_font = _font(22, bold=True)
    category_box = draw.textbbox((0, 0), category, font=category_font)
    badge_w = category_box[2] + 48
    badge_x = 1020 - badge_w
    draw.rounded_rectangle((badge_x, 44, 1020, 101), radius=22, fill=orange)
    draw.text((badge_x + 24, 57), category, font=category_font, fill=ink)

    # La foto ocupa el protagonismo visual; se contiene completa sin recortarla.
    photo_box = (48, 128, 1032, 718)
    draw.rounded_rectangle(photo_box, radius=28, fill="#FAFAFA", outline="#ECEEEF", width=2)
    with Image.open(offer["image_path"]) as source:
        product = ImageOps.contain(source.convert("RGB"), (920, 540), method=Image.Resampling.LANCZOS)
    canvas.paste(
        product,
        (photo_box[0] + (photo_box[2] - photo_box[0] - product.width) // 2,
         photo_box[1] + (photo_box[3] - photo_box[1] - product.height) // 2),
    )
    draw = ImageDraw.Draw(canvas)

    def fit(value: str, size: int, max_width: int, color: str, bold: bool = True):
        font = _font(size, bold=bold)
        box = draw.textbbox((0, 0), value, font=font)
        while box[2] - box[0] > max_width and size > 20:
            size -= 2
            font = _font(size, bold=bold)
            box = draw.textbbox((0, 0), value, font=font)
        draw.text((0, 0), value, font=font, fill=color)
        return font

    # Mantener el nombre del producto legible, limitado a dos líneas.
    title_words = offer["title"].split()
    title_lines = []
    line = ""
    title_font = _font(28, bold=True)
    for word in title_words:
        candidate = f"{line} {word}".strip()
        if line and draw.textbbox((0, 0), candidate, font=title_font)[2] > 950:
            title_lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        title_lines.append(line)
    if len(title_lines) > 2:
        title_lines = title_lines[:2]
        last = title_lines[1]
        while last and draw.textbbox((0, 0), last + "…", font=title_font)[2] > 950:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        title_lines[1] = last.rstrip(" .,") + "…"
    draw.text((58, 748), title_lines[0] if title_lines else "", font=title_font, fill=ink)
    if len(title_lines) > 1:
        draw.text((58, 783), title_lines[1], font=title_font, fill=ink)

    savings = offer["reference"] - offer["current"]
    savings_pct = savings / offer["reference"] * 100
    price_font = _font(76, bold=True)
    price_text = euro(offer["current"])
    while draw.textbbox((0, 0), price_text, font=price_font)[2] > 590 and price_font.size > 48:
        price_font = _font(price_font.size - 2, bold=True)
    draw.text((58, 836), price_text, font=price_font, fill=orange)

    normal_label = f"Antes {euro(offer['reference'])} · media de {offer['days']} días"
    normal_font = _font(24)
    draw.text((62, 933), normal_label, font=normal_font, fill=muted)
    normal_box = draw.textbbox((62, 933), normal_label, font=normal_font)
    draw.line((normal_box[0], 946, normal_box[2], 946), fill=muted, width=2)

    # Una sola cifra de descuento, dentro de un bloque de alto contraste.
    discount_box = (748, 828, 1018, 1000)
    draw.rounded_rectangle(discount_box, radius=26, fill=ink)
    discount_text = f"-{savings_pct:.0f}%"
    discount_font = _font(68, bold=True)
    discount_bounds = draw.textbbox((0, 0), discount_text, font=discount_font)
    while discount_bounds[2] > 230 and discount_font.size > 42:
        discount_font = _font(discount_font.size - 2, bold=True)
        discount_bounds = draw.textbbox((0, 0), discount_text, font=discount_font)
    draw.text((discount_box[0] + (discount_box[2] - discount_bounds[2]) // 2, 846),
              discount_text, font=discount_font, fill=orange)
    saving_label = f"AHORRO {euro(savings)}"
    saving_font = _font(21, bold=True)
    saving_bounds = draw.textbbox((0, 0), saving_label, font=saving_font)
    while saving_bounds[2] > 244 and saving_font.size > 16:
        saving_font = _font(saving_font.size - 1, bold=True)
        saving_bounds = draw.textbbox((0, 0), saving_label, font=saving_font)
    draw.text((discount_box[0] + (discount_box[2] - saving_bounds[2]) // 2, 939),
              saving_label, font=saving_font, fill="#FFFFFF")

    if offer["historical_low"] and category == "ERROR DE PRECIO":
        draw.text((62, 984), "MÍNIMO HISTÓRICO VERIFICADO", font=_font(17, bold=True), fill=ink)
    elif offer["resale"]:
        resale = offer["resale"]
        resale_line = f"Wallapop: ~{euro(resale['price'])} · ROI ~{resale['roi']:.0f}%"
        resale_font = _font(18, bold=True)
        while draw.textbbox((0, 0), resale_line, font=resale_font)[2] > 650 and resale_font.size > 14:
            resale_font = _font(resale_font.size - 1, bold=True)
        draw.text((62, 984), resale_line, font=resale_font, fill=ink)
    elif category == "MÍNIMO HISTÓRICO":
        draw.text((62, 984), "MÍNIMO HISTÓRICO VERIFICADO", font=_font(17, bold=True), fill=ink)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"{offer['id']}.jpg"
    canvas.save(output, format="JPEG", quality=91, optimize=True)
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
            discount_pct = offer["discount_pct"]
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
            print(f"{offer['id']}: publicado como {offer['category']} ({discount_pct:.1f}%).")
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

