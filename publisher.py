#!/usr/bin/env python3
"""Publish fresh, explicitly approved offers to one Telegram channel."""

from __future__ import annotations

import html

import affiliate
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

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps


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
AMAZON_SHORT_HOSTS = {
    "link.amazon", "www.link.amazon", "amzn.to", "www.amzn.to",
    "amzn.eu", "www.amzn.eu", "amzlinks.in", "www.amzlinks.in",
}
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
    "RESERVA COLECCIONISTA": "🎴 <b>RESERVA COLECCIONISTA</b>",
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


def store_label(url: str) -> str:
    import premium
    return premium.store_of(url)[1]


def build_caption(*, url: str, category: str, title: str, current: float, reference: float,
                  brand: str = "", historical_low: bool = False, rating: float | None = None,
                  reviews: int | None = None, ref_text: str = "frente a su precio medio de 90 días",
                  resale_price: float | None = None, resale_count: int | None = None,
                  sold_out: bool = False, sizes: list | None = None, note: str = "",
                  hold: bool = False, demand: str = "", profit: float | None = None,
                  source_label: str = "", store: str = "") -> str:
    """Copy del canal: categoría, marca en negrita, precio, beneficio y enlace de la tienda."""
    e = html.escape
    brand = nice_brand(brand)
    pct = round((reference - current) / reference * 100) if reference else 0
    product = e(short_title(title, brand))
    shop = store or store_label(url)
    lines = [CATEGORY_HEADERS.get(category, f"🔥 <b>{e(category)}</b>")]
    if sold_out:
        lines.append("⛔ <b>AGOTADO</b> · ejemplo de lo que cazamos")
    lines.append("")
    lines.append(f"<b>{e(brand)}</b> {product}" if brand else f"<b>{product}</b>")
    lines.append("")
    if sizes:
        lines.append(f"📏 Tallas a este precio: <b>{e(', '.join(sizes))}</b>")
    if reference and reference > current:
        lines.append(f"💰 <b>{e(euro(current))}</b>   <s>{e(euro(reference))}</s>")
        lines.append(f"🏷️ <b>-{pct}%</b> {e(ref_text)}")
    else:
        lines.append(f"💰 <b>{e(euro(current))}</b> en {e(shop)}")
    if historical_low:
        lines.append("🏆 <b>Precio más bajo de su historia</b>")
    if hold:
        lines.append("🏷️ <b>Producto de colección / hold</b>")
    if resale_price:
        gain = profit if profit is not None else resale_price - current
        roi = gain / current * 100 if current else 0
        where = source_label or "Wallapop"
        lines.append("")
        lines.append(f"♻️ Reventa en {e(where)} <b>~{resale_price:.0f} €</b>")
        lines.append(f"📈 Beneficio estimado <b>{gain:+.0f} €</b> · ROI <b>{roi:+.0f}%</b>")
    if demand:
        lines.append(f"🔥 Demanda: <b>{e(demand)}</b>")
    if rating and rating >= 4.0 and reviews:
        lines.append(f"⭐ {str(round(rating, 1)).replace('.', ',')} ({reviews} opiniones)")
    if note:
        lines.append("")
        for line in str(note).splitlines():
            if line.strip():
                lines.append(e(line.strip()))
    lines.append("")
    lines.append(f'🔗 <b><a href="{e(url, quote=True)}">Ver en {e(shop)}</a></b>')
    return "\n".join(lines)


DEAL_CLOSERS = (
    "Si te encaja, no lo dejes escapar: estos precios duran poco.",
    "Hoy está así. Mañana puede que ya no.",
    "De los que conviene mirar antes de que lo corrijan.",
    "Un precio que no se ve todos los días.",
    "Entra, comprueba que es el modelo que buscas y decide.",
)
TRIP_CLOSERS = (
    "Si esas fechas te valen, míralo antes de que suba.",
    "Maleta lista: un precio así no suele aguantar.",
    "Un viaje a este precio merece que le eches un ojo hoy.",
)
TRIP_WORDS = ("viaje", "vuelo", "crucero", "hotel", "vacaciones")
DEAL_LOGO = ROOT / "images" / "logo-caza-chollos.png"


def _is_trip(title: str) -> bool:
    folded = (title or "").lower()
    return any(word in folded for word in TRIP_WORDS)


def deal_closer(title: str) -> str:
    """Remate distinto según el título. Nunca cita grados ni la fuente del listado."""
    pool = TRIP_CLOSERS if _is_trip(title) else DEAL_CLOSERS
    return pool[sum((title or "").encode()) % len(pool)]


def deal_badge(title: str, current: float, previous: float | None) -> str:
    if _is_trip(title):
        return "VIAJE"
    if previous is not None and previous > current * 1.02 and (previous - current) / previous * 100 >= 50:
        return "CHOLLAZO"
    return "CHOLLO"


def build_deal_caption(*, url: str, title: str, current: float, store: str,
                      previous: float | None = None, temperature: int | None = None) -> str:
    """Post del canal normal: precio en formato español, sin reventa, sin ROI y sin grados."""
    del temperature  # solo sirve para ordenar; no se enseña
    shop = (store or "la tienda").strip()
    product = html.escape(short_title(title, "", limit=140))
    lines = ["🔥 <b>Se ha colado un precio</b>", "", f"<b>{product}</b>", ""]
    reliable = previous is not None and previous > current * 1.02
    if reliable:
        saved = previous - current
        pct = round(saved / previous * 100)
        lines.append(f"❌ PVP {html.escape(shop)}: <s>{html.escape(euro(previous))}</s>")
        lines.append(f"💰 AHORA: {html.escape(euro(current))}")
        lines.append(f"📉 −{pct} % sobre PVP")
        lines.append(f"🤑 Te ahorras: {html.escape(euro(saved))}")
    else:
        lines.append(f"💰 AHORA: {html.escape(euro(current))}")
    lines.append("")
    lines.append(deal_closer(title))
    lines.append("")
    lines.append(f'🔗 <b><a href="{html.escape(url, quote=True)}">Ver en {html.escape(shop)}</a></b>')
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


def _fit_font(draw, text: str, max_width: int, start: int, minimum: int, bold: bool = True):
    """Baja el cuerpo hasta que el texto cabe en su columna."""
    size = start
    font = _font(size, bold=bold)
    while size > minimum and draw.textbbox((0, 0), text, font=font)[2] > max_width:
        size -= 2
        font = _font(size, bold=bold)
    return font


def _centered(draw, box, y, text, font, fill):
    b = draw.textbbox((0, 0), text, font=font)
    x = box[0] + (box[2] - box[0] - (b[2] - b[0])) // 2 - b[0]
    draw.text((x, y), text, font=font, fill=fill)


def _resale_panels(draw, offer, info_x, info_width, savings_pct, ink, orange, muted):
    """Variante de reventa: precio anterior con descuento, precio actual y bloque Wallapop + ROI."""
    resale = offer["resale"]
    green = "#3DDC84"
    old_box = (info_x, 390, 1028, 510)
    draw.rounded_rectangle(old_box, radius=24, fill="#F5F6F6", outline="#E7E9EB", width=2)
    draw.text((info_x + 24, 404), offer.get("ref_label") or "ANTES", font=_font(20, bold=True), fill=muted)
    old_font = _font(36, bold=True)
    old_pos = (info_x + 24, 440)
    old_price = euro(offer["reference"])
    draw.text(old_pos, old_price, font=old_font, fill=muted)
    ob = draw.textbbox(old_pos, old_price, font=old_font)
    sy = old_pos[1] + (ob[3] - ob[1]) // 2 + 2
    draw.line((ob[0] - 2, sy, ob[2] + 2, sy), fill=muted, width=3)
    pill_text = f"-{savings_pct:.0f}%"
    pill_font = _font(30, bold=True)
    pb = draw.textbbox((0, 0), pill_text, font=pill_font)
    pill = (1028 - 24 - (pb[2] - pb[0]) - 32, 430, 1028 - 24, 486)
    draw.rounded_rectangle(pill, radius=18, fill=ink)
    draw.text((pill[0] + 16, pill[1] + (pill[3] - pill[1] - (pb[3] - pb[1])) // 2 - pb[1]), pill_text, font=pill_font, fill=orange)

    cur_box = (info_x, 528, 1028, 708)
    draw.rounded_rectangle(cur_box, radius=24, fill="#FFF5E8", outline="#F6E2C8", width=2)
    draw.text((info_x + 24, 546), ("PRECIO DEL ERROR" if offer.get("sold_out") else "PRECIO ACTUAL"), font=_font(22, bold=True), fill=muted)
    price_font = _font(72, bold=True)
    price_text = euro(offer["current"])
    while draw.textbbox((0, 0), price_text, font=price_font)[2] > info_width - 48 and price_font.size > 44:
        price_font = _font(price_font.size - 2, bold=True)
    draw.text((info_x + 24, 588), price_text, font=price_font, fill=orange)

    box = (info_x, 726, 1028, 1000)
    draw.rounded_rectangle(box, radius=26, fill=ink)
    mid = (box[0] + box[2]) // 2
    draw.line((mid, box[1] + 36, mid, box[3] - 64), fill="#2B3440", width=2)
    left, right = (box[0], box[1], mid, box[3]), (mid, box[1], box[2], box[3])
    small = _font(19, bold=True)
    col_w = (mid - box[0]) - 20
    _centered(draw, left, box[1] + 28, "REVENTA", small, "#AEB6BF")
    source = str(resale.get("source_label") or "WALLAPOP")
    source_font = _fit_font(draw, source, col_w, 19, 11, bold=True)
    _centered(draw, left, box[1] + 50, source, source_font, "#AEB6BF")
    context = bool(resale.get("context_only"))
    _centered(draw, right, box[1] + 28, "REFERENCIA" if context else "BENEFICIO", small, "#AEB6BF")
    _centered(draw, right, box[1] + 50, "PREVIA" if context else "ESTIMADO", small, "#AEB6BF")
    price_text = f"~{resale['price']:.0f} €"
    if context:
        gain_text = f"{int(resale.get('count') or 0)} an."
    else:
        gain = resale["profit"] if resale.get("profit") is not None else resale["price"] - offer["current"]
        gain_text = f"{gain:+.0f} €"
    price_font = _fit_font(draw, price_text, col_w, 52, 26, bold=True)
    gain_font = _fit_font(draw, gain_text, col_w, 52, 26, bold=True)
    _centered(draw, left, box[1] + 86, price_text, price_font, "#FFFFFF")
    _centered(draw, right, box[1] + 86, gain_text, gain_font, "#FFFFFF" if context else (green if gain_text.startswith("+") or gain_text.startswith("~") else "#FF6B6B"))
    roi = resale.get("roi")
    if roi is not None and not context:
        roi_text = f"ROI {roi:+.0f}%"
        roi_font = _fit_font(draw, roi_text, col_w, 22, 12, bold=True)
        _centered(draw, right, box[1] + 148, roi_text, roi_font, green if roi >= 0 else "#FF6B6B")
    if resale.get("sample"):
        note = "EJEMPLO · no son anuncios reales"
    elif resale.get("note"):
        note = str(resale["note"])
    else:
        note = f"Mediana de {resale['count']} anuncios" if resale.get("count") else "Mediana de anuncios"
    note_font = _font(19)
    max_note = (box[2] - box[0]) - 28
    while getattr(note_font, "size", 19) > 12 and draw.textbbox((0, 0), note, font=note_font)[2] > max_note:
        note_font = _font(note_font.size - 1)
    if draw.textbbox((0, 0), note, font=note_font)[2] > max_note and resale.get("count"):
        note = f"Mediana de {resale['count']} anuncios"
    _centered(draw, box, box[3] - 50, note, note_font, "#AEB6BF")


def _paste_cover(canvas, box, image, radius: int = 26, inset: int = 3) -> None:
    """Llena el panel (cover) y recorta las esquinas como el marco redondeado."""
    inner = (box[0] + inset, box[1] + inset, box[2] - inset, box[3] - inset)
    width = inner[2] - inner[0]
    height = inner[3] - inner[1]
    rgb = image.convert("RGB")
    scale = max(width / rgb.width, height / rgb.height)
    resized = rgb.resize((max(width, int(rgb.width * scale + 0.5)), max(height, int(rgb.height * scale + 0.5))),
                         Image.Resampling.LANCZOS)
    left = max(0, (resized.width - width) // 2)
    top = max(0, (resized.height - height) // 2)
    cropped = resized.crop((left, top, left + width, top + height))
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, width - 1, height - 1), radius=radius, fill=255)
    canvas.paste(cropped, (inner[0], inner[1]), mask)


def _trim_margins(image: Image.Image, tolerance: int = 18) -> Image.Image:
    """Quita el marco blanco o transparente y deja el producto con un par de píxeles de aire."""
    rgba = image.convert("RGBA")
    flat = Image.alpha_composite(Image.new("RGBA", rgba.size, (255, 255, 255, 255)), rgba).convert("RGB")
    diff = ImageChops.difference(flat, Image.new("RGB", flat.size, (255, 255, 255)))
    mask = diff.convert("L").point(lambda pixel: 255 if pixel > tolerance else 0)
    bbox = mask.getbbox()
    if not bbox:
        return flat
    left, top, right, bottom = bbox
    pad = 4
    left = max(0, left - pad)
    top = max(0, top - pad)
    right = min(flat.width, right + pad)
    bottom = min(flat.height, bottom + pad)
    if right - left < flat.width * 0.12 or bottom - top < flat.height * 0.12:
        return flat
    return flat.crop((left, top, right, bottom))


def _place_product(canvas, photo_box, offer: dict) -> None:
    """Foto del producto, o el logo del canal si no hay una imagen usable."""
    path = offer.get("image_path")
    if path:
        try:
            with Image.open(path) as source:
                if min(source.size) >= 48:
                    if offer.get("cover"):
                        import photos
                        inner_w = (photo_box[2] - photo_box[0]) - 6
                        inner_h = (photo_box[3] - photo_box[1]) - 6
                        prepared = photos.fit_for_panel(source.convert("RGB"), inner_w, inner_h, cover=True)
                        _paste_cover(canvas, photo_box, prepared)
                    else:
                        import photos
                        product = _trim_margins(source)
                        panel_w = (photo_box[2] - photo_box[0]) - 16
                        panel_h = (photo_box[3] - photo_box[1]) - 16
                        product = photos.fit_for_panel(product, panel_w, panel_h, cover=False)
                        product = ImageOps.contain(product, (panel_w, panel_h), method=Image.Resampling.LANCZOS)
                        canvas.paste(product, (
                            photo_box[0] + (photo_box[2] - photo_box[0] - product.width) // 2,
                            photo_box[1] + (photo_box[3] - photo_box[1] - product.height) // 2,
                        ))
                    return
        except (OSError, ValueError):
            pass
    logo_file = Path(offer["logo_path"]) if offer.get("logo_path") else ROOT / "images" / "logo-caza-errores.png"
    with Image.open(logo_file) as logo_source:
        mark = ImageOps.contain(logo_source.convert("RGB"), (300, 300), method=Image.Resampling.LANCZOS)
    x = photo_box[0] + (photo_box[2] - photo_box[0] - mark.width) // 2
    y = photo_box[1] + (photo_box[3] - photo_box[1] - mark.height) // 2 - 36
    canvas.paste(mark, (x, y))
    label = str(offer.get("fallback_label") or "").strip()
    if label:
        draw = ImageDraw.Draw(canvas)
        _centered(draw, photo_box, y + mark.height + 18, label.upper(), _font(28, bold=True), "#131921")


def _price_only_panel(draw, offer: dict, info_x: int, info_width: int, orange: str, muted: str) -> None:
    """Sin PVP fiable: una sola caja de precio, del mismo alto que el bloque completo."""
    box = (info_x, 420, 1028, 980)
    draw.rounded_rectangle(box, radius=24, fill="#FFF5E8", outline="#F6E2C8", width=2)
    draw.text((info_x + 24, 470), "PRECIO ACTUAL", font=_font(23, bold=True), fill=muted)
    price_font = _font(76, bold=True)
    price_text = euro(offer["current"])
    while draw.textbbox((0, 0), price_text, font=price_font)[2] > info_width - 48 and price_font.size > 48:
        price_font = _font(price_font.size - 2, bold=True)
    draw.text((info_x + 24, 560), price_text, font=price_font, fill=orange)
    shop = str(offer.get("store") or "").strip()
    if shop:
        draw.text((info_x + 24, 900), shop.upper(), font=_font(22, bold=True), fill=muted)


def create_deal_card(offer: dict) -> Path:
    """Tarjeta del canal normal: el mismo lienzo que el canal antiguo, con el logo de Caza Chollos."""
    current = float(offer["current"])
    previous = offer.get("previous")
    reliable = previous is not None and float(previous) > current * 1.02
    title = offer.get("title") or ""
    image_path = offer.get("image_path")
    cover = False
    if _is_trip(title) and not offer.get("skip_destination"):
        import destinations
        found = destinations.destination_image(title, offer.get("destination_cache"))
        if found:
            image_path = found
            cover = True
        else:
            image_path = None
    return create_price_card({
        "id": offer.get("id") or "chollo",
        "title": title,
        "image_path": image_path,
        "cover": cover,
        "category": offer.get("category") or deal_badge(title, current, float(previous) if reliable else None),
        "current": current,
        "reference": float(previous) if reliable else current,
        "ref_label": offer.get("ref_label") or "ANTES · PVP",
        "hide_reference": not reliable,
        "logo_path": offer.get("logo_path") or DEAL_LOGO,
        "fallback_label": offer.get("fallback_label") or ("VIAJE" if _is_trip(title) else ""),
        "store": offer.get("store") or "",
        "days": 0,
        "jpeg_quality": 95,
    })


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
    logo_file = Path(offer["logo_path"]) if offer.get("logo_path") else ROOT / "images" / "logo-caza-errores.png"
    with Image.open(logo_file) as logo_source:
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
    if offer.get("sold_out"):
        so_text = "AGOTADO"
        so_bounds = draw.textbbox((0, 0), so_text, font=category_font)
        so_w = so_bounds[2] - so_bounds[0] + 40
        so_badge = (badge[0] - 14 - so_w, badge[1], badge[0] - 14, badge[3])
        draw.rounded_rectangle(so_badge, radius=22, fill="#D93025")
        draw.text((so_badge[0] + 20, so_badge[1] + (so_badge[3] - so_badge[1] - (so_bounds[3] - so_bounds[1])) // 2 - so_bounds[1]),
                  so_text, font=category_font, fill="#FFFFFF")
    if offer.get("hold"):
        hold_text = "COLECCIÓN / HOLD"
        hold_font = _font(16, bold=True)
        hold_bounds = draw.textbbox((0, 0), hold_text, font=hold_font)
        hold_w = hold_bounds[2] - hold_bounds[0] + 28
        hold_badge = (1028 - hold_w, 146, 1028, 186)
        draw.rounded_rectangle(hold_badge, radius=16, fill=ink)
        draw.text((hold_badge[0] + 14, hold_badge[1] + 8), hold_text, font=hold_font, fill=orange)

    # Portrait photo on the left; an aligned information column keeps the offer easy to scan.
    photo_box = (48, 192, 568, 1032)
    draw.rounded_rectangle(photo_box, radius=28, fill="#FAFAFA", outline="#ECEEEF", width=2)
    _place_product(canvas, photo_box, offer)
    draw = ImageDraw.Draw(canvas)

    info_x = 610
    info_width = 418
    if offer.get("store_label"):
        draw.text((info_x, 168), str(offer["store_label"]).upper(), font=_font(18, bold=True), fill=orange)
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

    if offer.get("hide_reference"):
        _price_only_panel(draw, offer, info_x, info_width, orange, muted)
        return _save_card(canvas, offer)

    savings = offer["reference"] - offer["current"]
    savings_pct = savings / offer["reference"] * 100
    resale = offer.get("resale")
    if resale:
        _resale_panels(draw, offer, info_x, info_width, savings_pct, ink, orange, muted)
    else:
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
        draw.text((info_x + 24, 580), ("PRECIO DEL ERROR" if offer.get("sold_out") else "PRECIO ACTUAL"), font=_font(23, bold=True), fill=muted)
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


    return _save_card(canvas, offer)


def _save_card(canvas, offer: dict) -> Path:
    """JPEG de alta calidad. 4:4:4 a partir de 95 para que Telegram no parta de un archivo ya borroso."""
    quality = int(offer.get("jpeg_quality") or 91)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"{offer['id']}.jpg"
    options = {"quality": quality, "optimize": True}
    if quality >= 95:
        options["subsampling"] = 0
    canvas.save(output, format="JPEG", **options)
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
    link = re.search(r'href="([^"]+)"', caption)
    if link:
        shop = store_label(html.unescape(link.group(1)))
        field("reply_markup", json.dumps({"inline_keyboard": [[{"text": f"🛒 Ver en {shop}", "url": html.unescape(link.group(1))}]]}))
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


def _affiliate_tag() -> str:
    try:
        config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    tag = config.get("affiliate_tag") if isinstance(config, dict) else ""
    return tag.strip() if isinstance(tag, str) else ""


def _alert_admin(token: str, text: str) -> None:
    try:
        state = json.loads((ROOT / "state" / "scanner.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(text)
        return
    admin = state.get("admin_chat_id") if isinstance(state, dict) else None
    if not token or not admin:
        print(text)
        return
    body = json.dumps({"chat_id": admin, "text": text}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=20).read()
    except (urllib.error.URLError, TimeoutError):
        print(text)


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
        tag = _affiliate_tag()
        for raw in approved:
            offer = validate_offer(raw, now)
            discount_pct = offer["discount_pct"]
            if offer["id"] in published_set:
                print(f"{offer['id']}: ya publicado; se omite.")
                continue
            link, warnings = affiliate.prepare_amazon_link(offer["url"], tag, asin=offer.get("asin"))
            for warning in warnings:
                print(f"{offer['id']}: {warning}")
                _alert_admin(token, "⚠️ " + warning)
            if not link:
                print(f"{offer['id']}: el enlace no lleva la etiqueta de afiliado; no se publica.", file=sys.stderr)
                continue
            offer["url"] = link
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

