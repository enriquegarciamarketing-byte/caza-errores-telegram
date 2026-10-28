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
        if "resale_fees_eur" not in offer or "resale_shipping_eur" not in offer:
            raise OfferError("indica resale_fees_eur y resale_shipping_eur para calcular un ROI útil")
        fees = nonnegative_money(offer["resale_fees_eur"], "resale_fees_eur")
        shipping = nonnegative_money(offer["resale_shipping_eur"], "resale_shipping_eur")
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
    elif resale_data and resale_data["roi"] > 0:
        category = "OPORTUNIDAD DE REVENTA"
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


CATEGORY_HEADERS = {
    "ERROR DE PRECIO": "🚨 <b>ERROR DE PRECIO</b> 🚨",
    "MÍNIMO HISTÓRICO": "📉 <b>MÍNIMO HISTÓRICO</b>",
    "GANGA": "🔥 <b>GANGA</b>",
    "OPORTUNIDAD DE REVENTA": "💸 <b>OPORTUNIDAD DE REVENTA</b>",
}


def nice_brand(brand: str) -> str:
    brand = (brand or "").strip()
    return brand.title() if brand.isupper() and len(brand) > 3 else brand


def short_title(title: str, brand: str = "", limit: int = 85) -> str:
    """Quita la marca del inicio y recorta el título sin partir palabras."""
    title = re.sub(r"\s+", " ", title or "").strip(" ,-")
    if brand and title.lower().startswith(brand.lower()):
        title = title[len(brand):].strip(" ,-")
    if len(title) > limit:
        title = title[:limit].rsplit(" ", 1)[0].rstrip(" ,-(") + "…"
    return title


def build_caption(*, url: str, category: str, title: str, current: float, reference: float,
                  brand: str = "", historical_low: bool = False, rating: float | None = None,
                  reviews: int | None = None, ref_text: str = "frente a su precio medio de 90 días") -> str:
    """Copy del canal: categoría, marca en negrita, precio, precio tachado y descuento."""
    e = html.escape
    brand = nice_brand(brand)
    pct = round((reference - current) / reference * 100)
    product = e(short_title(title, brand))
    lines = [CATEGORY_HEADERS.get(category, f"🔥 <b>{e(category)}</b>"), ""]
    lines.append(f"<b>{e(brand)}</b> {product}" if brand else f"<b>{product}</b>")
    lines.append("")
    lines.append(f"💰 <b>{e(euro(current))}</b>   <s>{e(euro(reference))}</s>")
    lines.append(f"🏷️ <b>-{pct}%</b> {e(ref_text)}")
    if historical_low:
        lines.append("🏆 <b>Precio más bajo de su historia</b>")
    if rating and rating >= 4.0 and reviews:
        lines.append(f"⭐ {str(round(rating, 1)).replace('.', ',')} ({reviews} opiniones)")
    lines.append("")
    lines.append(f'🔗 <b><a href="{e(url, quote=True)}">Ver en Amazon</a></b>')
    return "\n".join(lines)


def build_message(offer: dict) -> str:
    return build_caption(
        url=offer["url"], category=offer.get("category", "GANGA"), title=offer.get("title", ""),
        current=offer["current"], reference=offer["reference"], brand=offer.get("brand", ""),
        historical_low=bool(offer.get("historical_low")),
    )


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
    draw.rounded_rectangle((24, 24, 1056, 1056), radius=34, fill="#FFFFFF", outline="#E7E9EB", width=2)

    # Use the supplied channel emblem as the only brand mark in the card.
    logo_box = (48, 36, 184, 172)
    with Image.open(ROOT / "images" / "logo-caza-errores.png") as logo_source:
        logo = ImageOps.contain(
            logo_source.convert("RGB"),
            (logo_box[2] - logo_box[0], logo_box[3] - logo_box[1]),
            method=Image.Resampling.LANCZOS,
        )
    canvas.paste(
        logo,
        (logo_box[0] + (logo_box[2] - logo.width) // 2,
         logo_box[1] + (logo_box[3] - logo.height) // 2),
    )
    draw = ImageDraw.Draw(canvas)

    category = offer["category"]
    category_font = _font(20, bold=True)
    category_bounds = draw.textbbox((0, 0), category, font=category_font)
    badge_w = category_bounds[2] - category_bounds[0] + 40
    badge = (1028 - badge_w, 78, 1028, 136)
    draw.rounded_rectangle(badge, radius=22, fill=orange)
    draw.text(
        (badge[0] + 20, badge[1] + (badge[3] - badge[1] - (category_bounds[3] - category_bounds[1])) // 2 - category_bounds[1]),
        category,
        font=category_font,
        fill=ink,
    )

    # Portrait photo on the left; an aligned information column keeps the offer easy to scan.
    photo_box = (48, 192, 568, 1032)
    draw.rounded_rectangle(photo_box, radius=28, fill="#FAFAFA", outline="#ECEEEF", width=2)
    with Image.open(offer["image_path"]) as source:
        product = ImageOps.contain(source.convert("RGB"), (480, 780), method=Image.Resampling.LANCZOS)
    canvas.paste(
        product,
        (photo_box[0] + (photo_box[2] - photo_box[0] - product.width) // 2,
         photo_box[1] + (photo_box[3] - photo_box[1] - product.height) // 2),
    )
    draw = ImageDraw.Draw(canvas)

    info_x = 610
    info_width = 418
    # The title uses a controlled line length to preserve a clean right column.
    title_words = offer["title"].split()
    title_lines: list[str] = []
    line = ""
    title_font = _font(31, bold=True)
    for word in title_words:
        candidate = f"{line} {word}".strip()
        candidate_box = draw.textbbox((0, 0), candidate, font=title_font)
        if line and candidate_box[2] - candidate_box[0] > info_width:
            title_lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        title_lines.append(line)
    if len(title_lines) > 4:
        title_lines = title_lines[:4]
        last = title_lines[-1]
        while last and draw.textbbox((0, 0), last + "…", font=title_font)[2] > info_width:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        title_lines[-1] = last.rstrip(" .,") + "…"
    for index, title_line in enumerate(title_lines):
        draw.text((info_x, 198 + index * 38), title_line, font=title_font, fill=ink)

    savings = offer["reference"] - offer["current"]
    savings_pct = savings / offer["reference"] * 100
    old_box = (info_x, 390, 1028, 540)
    draw.rounded_rectangle(old_box, radius=24, fill="#F5F6F6", outline="#E7E9EB", width=2)
    old_label = offer.get("ref_label") or f"ANTES · MEDIA {offer['days']} DÍAS"
    draw.text((info_x + 24, 408), old_label, font=_font(22, bold=True), fill=muted)
    old_price = euro(offer["reference"])
    old_font = _font(38, bold=True)
    old_pos = (info_x + 24, 447)
    draw.text(old_pos, old_price, font=old_font, fill=muted)
    old_bounds = draw.textbbox(old_pos, old_price, font=old_font)
    strike_y = old_pos[1] + (old_bounds[3] - old_bounds[1]) // 2 + 2
    draw.line((old_bounds[0] - 2, strike_y, old_bounds[2] + 2, strike_y), fill=muted, width=3)

    current_box = (info_x, 560, 1028, 770)
    draw.rounded_rectangle(current_box, radius=24, fill="#FFF5E8", outline="#F6E2C8", width=2)
    draw.text((info_x + 24, 580), "PRECIO ACTUAL", font=_font(23, bold=True), fill=muted)
    price_font = _font(76, bold=True)
    price_text = euro(offer["current"])
    while draw.textbbox((0, 0), price_text, font=price_font)[2] - draw.textbbox((0, 0), price_text, font=price_font)[0] > info_width - 48 and price_font.size > 48:
        price_font = _font(price_font.size - 2, bold=True)
    draw.text((info_x + 24, 625), price_text, font=price_font, fill=orange)

    # One high-contrast discount panel avoids competing secondary figures.
    discount_box = (info_x, 790, 1028, 1000)
    draw.rounded_rectangle(discount_box, radius=26, fill=ink)
    discount_text = f"-{savings_pct:.0f}%"
    discount_font = _font(86, bold=True)
    discount_bounds = draw.textbbox((0, 0), discount_text, font=discount_font)
    while discount_bounds[2] - discount_bounds[0] > info_width - 48 and discount_font.size > 48:
        discount_font = _font(discount_font.size - 2, bold=True)
        discount_bounds = draw.textbbox((0, 0), discount_text, font=discount_font)
    discount_text_width = discount_bounds[2] - discount_bounds[0]
    discount_text_x = discount_box[0] + (discount_box[2] - discount_box[0] - discount_text_width) // 2 - discount_bounds[0]
    draw.text((discount_text_x, 815), discount_text, font=discount_font, fill=orange)
    discount_label = "DESCUENTO"
    label_font = _font(24, bold=True)
    label_bounds = draw.textbbox((0, 0), discount_label, font=label_font)
    label_width = label_bounds[2] - label_bounds[0]
    label_x = discount_box[0] + (discount_box[2] - discount_box[0] - label_width) // 2 - label_bounds[0]
    draw.text((label_x, 921), discount_label, font=label_font, fill="#FFFFFF")

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

