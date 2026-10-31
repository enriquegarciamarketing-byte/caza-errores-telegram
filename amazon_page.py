"""Lectura directa de Amazon.es: fichas de producto y listados.

Todo lo que se publica sale de aquí. Si un dato no se puede leer con seguridad, se devuelve
None y el chollo no se publica: es preferible perder un chollo que enseñar un precio falso.
"""

from __future__ import annotations

import gzip
import html
import http.cookiejar
import json
import random
import re
import time
import urllib.error
import urllib.request
import zlib

BASE = "https://www.amazon.es"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/131.0.0.0 Safari/537.36")
ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")
BLOCK_MARKERS = (
    "api-services-support@amazon.com",
    "validatecaptcha",
    "/errors/validatecaptcha",
    "introduce los caracteres que ves",
    "type the characters you see",
    "lo sentimos, necesitamos asegurarnos de que no eres un robot",
)


class Blocked(RuntimeError):
    """Amazon ha devuelto un captcha o una página de acceso automatizado."""


# ------------------------------------------------------------------ descarga

class Session:
    """Un navegador mínimo: cookies, cabeceras de navegador y pausa entre peticiones."""

    def __init__(self, min_gap: float = 3.0, timeout: int = 25):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.ua = USER_AGENT
        self.min_gap = min_gap
        self.timeout = timeout
        self._last = 0.0
        self.requests = 0

    def get(self, url: str) -> str:
        wait = self.min_gap + random.uniform(0, 1.5) - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        request = urllib.request.Request(url, headers={
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Upgrade-Insecure-Requests": "1",
        })
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
                encoding = (response.headers.get("Content-Encoding") or "").lower()
        except urllib.error.HTTPError as exc:
            if exc.code in (503, 429):
                raise Blocked(f"HTTP {exc.code}") from exc
            raise
        finally:
            self._last = time.time()
            self.requests += 1
        if encoding == "gzip":
            raw = gzip.decompress(raw)
        elif encoding == "deflate":
            raw = zlib.decompress(raw)
        page = raw.decode("utf-8", "replace")
        if is_blocked(page):
            raise Blocked("captcha")
        return page


def is_blocked(page: str) -> bool:
    head = (page or "")[:30000].lower()
    if any(marker in head for marker in BLOCK_MARKERS):
        return True
    return len(page or "") < 8000 and "producttitle" not in head and "s-search-result" not in head


# ------------------------------------------------------------------ utilidades

def text_of(fragment: str | None) -> str:
    if not fragment:
        return ""
    no_tags = re.sub(r"<script.*?</script>|<style.*?</style>", " ", fragment, flags=re.S | re.I)
    no_tags = re.sub(r"<[^>]+>", " ", no_tags)
    return re.sub(r"\s+", " ", html.unescape(no_tags)).strip()


def parse_eur(raw: str | None) -> float | None:
    """'1.234,56 €' -> 1234.56. Devuelve None si no es un importe claro."""
    text = html.unescape(raw or "").replace("\xa0", " ").replace("\u202f", " ").strip()
    match = re.search(r"(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{1,2}))?\s*€", text)
    if not match:
        return None
    whole = match.group(1).replace(".", "")
    cents = (match.group(2) or "0").ljust(2, "0")
    try:
        return round(float(f"{whole}.{cents}"), 2)
    except ValueError:
        return None


def _block(page: str, element_id: str, length: int = 12000) -> str:
    """Fragmento desde el elemento con ese id (incluida su etiqueta). Suficiente para leer su contenido."""
    match = re.search(rf'id="{re.escape(element_id)}"', page)
    if not match:
        return ""
    start = page.rfind("<", 0, match.start())
    start = start if start >= 0 and match.start() - start < 400 else match.start()
    return page[start: match.start() + length]


NEXT_FEATURE_RE = re.compile(r'<div id="[A-Za-z0-9_]+_feature_div"')


def _feature(page: str, element_id: str, cap: int = 80000) -> str:
    """El bloque completo de una sección de la ficha, hasta que empieza la siguiente."""
    match = re.search(rf'id="{re.escape(element_id)}"', page)
    if not match:
        return ""
    start = page.rfind("<", 0, match.start())
    start = start if start >= 0 and match.start() - start < 400 else match.start()
    nxt = NEXT_FEATURE_RE.search(page, match.end())
    end = nxt.start() if nxt else len(page)
    return page[start: min(end, start + cap)]


def _offscreen_prices(fragment: str) -> list[float]:
    found = []
    for raw in re.findall(r'<span class="a-offscreen">\s*([^<]{1,60}?)\s*</span>', fragment):
        value = parse_eur(raw)
        if value is not None:
            found.append(value)
    return found


def canonical_url(asin: str, tag: str) -> str:
    return f"{BASE}/dp/{asin}?tag={tag}" if tag else f"{BASE}/dp/{asin}"


def hires_image(url: str | None) -> str | None:
    """Quita el sufijo de miniatura (._AC_SX300_.) para pedir la foto original."""
    if not url or not url.startswith("http"):
        return None
    return re.sub(r"\._[A-Za-z0-9,_-]+_\.(jpg|jpeg|png|webp)$", r".\1", url)


# ------------------------------------------------------------------ ficha

CORE_PRICE_IDS = (
    "corePriceDisplay_desktop_feature_div",
    "corePrice_desktop",
    "corePrice_feature_div",
    "apex_desktop",
)


def _pay_price(page: str) -> float | None:
    """Precio a pagar del bloque principal (el que ve el comprador junto al botón)."""
    for element_id in CORE_PRICE_IDS:
        block = _feature(page, element_id)
        if not block:
            continue
        pay = re.search(r'class="[^"]*\bpriceToPay\b[^"]*"[^>]*>.*?<span class="a-offscreen">\s*([^<]+?)\s*</span>',
                        block, re.S)
        if pay and parse_eur(pay.group(1)) is not None:
            return parse_eur(pay.group(1))
        whole = re.search(r'<span class="a-price-whole">([\d.]+)<span class="a-price-decimal">,</span></span>'
                          r'<span class="a-price-fraction">(\d{2})</span>', block)
        if whole:
            return parse_eur(f"{whole.group(1)},{whole.group(2)} €")
        prices = _offscreen_prices(block)
        if prices:
            return prices[0]
    return None


LOWEST_LABELS = ("precio más bajo reciente", "precio mas bajo reciente", "precio más bajo en los últimos 30 días",
                 "precio anterior")
LIST_LABELS = ("precio recomendado", "pvpr", "precio de venta recomendado")


def reference_prices(core: str) -> dict:
    """Precios tachados del bloque de precio, según su etiqueta.

    Amazon los pinta en spans con clase basisPrice: "Precio más bajo reciente: 39,99 €" (mínimo de 30 días,
    obligatorio en la UE) o "Precio recomendado: 49,99 €" (PVPR). Solo el primero vale como referencia.
    """
    found = {"lowest_30": None, "list_price": None, "labels": []}
    for match in re.finditer(r'class="[^"]*\bbasisPrice\b[^"]*"', core):
        open_tag = core.rfind("<", 0, match.start())
        window = core[open_tag if open_tag >= 0 else match.start(): match.start() + 2500]
        label = text_of(window)[:70].lower()
        prices = _offscreen_prices(window)
        found["labels"].append(label)
        if not prices:
            continue
        if any(word in label for word in LOWEST_LABELS) and found["lowest_30"] is None:
            found["lowest_30"] = prices[0]
        elif any(word in label for word in LIST_LABELS) and found["list_price"] is None:
            found["list_price"] = prices[0]
    return found


def _labelled_price(page: str, labels: tuple[str, ...]) -> float | None:
    """Importe que sigue a una etiqueta como 'Precio más bajo reciente:'."""
    for label in labels:
        for match in re.finditer(re.escape(label), page, re.I):
            window = page[match.end(): match.end() + 1500]
            prices = _offscreen_prices(window)
            if prices:
                return prices[0]
            value = parse_eur(text_of(window)[:60])
            if value is not None:
                return value
    return None


def _seller_and_shipper(page: str) -> tuple[str, str]:
    seller = shipper = ""
    for element_id in ("offerDisplayFeatures_desktop", "tabular-buybox", "merchantInfoFeature_feature_div",
                       "fulfillerInfoFeature_feature_div"):
        block = text_of(_block(page, element_id, 6000))
        if not block:
            continue
        sold = re.search(r"Vendido por\s+(.{2,60}?)(?:\s+(?:Enviado|Devoluciones|Pago|Envío|Vendido|Detalles)|$)", block)
        sent = re.search(r"Enviado por\s+(.{2,40}?)(?:\s+(?:Vendido|Devoluciones|Pago|Envío|Detalles)|$)", block)
        if sold and not seller:
            seller = sold.group(1).strip()
        if sent and not shipper:
            shipper = sent.group(1).strip()
    if not seller:
        legacy = re.search(r"Vendido por\s*<a[^>]*>([^<]{2,60})</a>", page)
        if legacy:
            seller = html.unescape(legacy.group(1)).strip()
    if not seller and re.search(r"Vendido y enviado por Amazon", text_of(_block(page, "merchant-info", 3000))):
        seller = shipper = "Amazon"
    return seller, shipper


def parse_product(page: str, asin: str) -> dict:
    """Datos publicables de una ficha. Los campos que no se leen con seguridad quedan en None."""
    title = text_of(_block(page, "productTitle", 2000).split("</span>", 1)[0])
    availability = text_of(_block(page, "availability", 2500).split("</div>", 1)[0])
    image = None
    landing = re.search(r'id="landingImage"[^>]*', page)
    if landing:
        hires = re.search(r'data-old-hires="([^"]+)"', landing.group(0))
        dynamic = re.search(r'data-a-dynamic-image="([^"]+)"', landing.group(0))
        if hires and hires.group(1):
            image = hires.group(1)
        elif dynamic:
            try:
                sizes = json.loads(html.unescape(dynamic.group(1)))
                image = max(sizes.items(), key=lambda kv: kv[1][0] * kv[1][1])[0]
            except (ValueError, IndexError, TypeError):
                image = None
    if not image:
        image_match = re.search(r'"hiRes":"(https://[^"]+)"', page) or re.search(r'"large":"(https://[^"]+)"', page)
        image = image_match.group(1) if image_match else None
    rating_match = re.search(r'id="acrPopover"[^>]*title="([\d,]+) de 5', page)
    reviews_match = re.search(r'id="acrCustomerReviewText"[^>]*>\s*([\d.]+)', page)
    seller, shipper = _seller_and_shipper(page)
    core = ""
    for element_id in CORE_PRICE_IDS:
        core = _feature(page, element_id)
        if core and _offscreen_prices(core):
            break
    refs = reference_prices(core)
    lowest_30 = refs["lowest_30"]
    list_price = refs["list_price"]
    if lowest_30 is None and not refs["labels"]:
        # Ficha sin clase basisPrice: etiqueta seguida de su importe, solo dentro del bloque de precio.
        lowest_30 = _labelled_price(core, ("Precio más bajo reciente", "Precio más bajo en los últimos 30 días"))
        list_price = list_price or _labelled_price(core, ("Precio recomendado", "PVPR"))
    pay = _pay_price(page)
    if lowest_30 is not None and pay is not None and abs(lowest_30 - pay) < 0.005:
        lowest_30 = None  # si coincide con el precio actual se ha leído el precio, no la referencia
    stock_text = availability.lower()
    in_stock = bool(re.search(r"\ben stock\b|quedan solo|disponible", stock_text)) and not re.search(
        r"no disponible|agotado|actualmente no", stock_text)
    if not availability and _pay_price(page) and re.search(r'id="add-to-cart-button"', page):
        in_stock = True
    return {
        "asin": asin,
        "title": title,
        "price": pay,
        "lowest_30": lowest_30,
        "list_price": list_price,
        "in_stock": in_stock,
        "availability": availability,
        "seller": seller,
        "shipper": shipper,
        "prime_only": bool(re.search(r"Precio exclusivo (?:para|de) Prime|Oferta exclusiva Prime", core or page[:200000])),
        "coupon": bool(re.search(r'id="couponBadge|Aplicar cupón|cupón de', core)),
        "rating": float(rating_match.group(1).replace(",", ".")) if rating_match else None,
        "reviews": int(reviews_match.group(1).replace(".", "")) if reviews_match else None,
        "image": hires_image(image),
        "variant_page": bool(re.search(r'id="twister', page)),
        "reference_labels": refs["labels"],
    }


def fetch_product(session: Session, asin: str) -> dict:
    if not ASIN_RE.fullmatch(asin or ""):
        raise ValueError(f"ASIN no válido: {asin!r}")
    page = session.get(f"{BASE}/dp/{asin}?th=1&psc=1")
    data = parse_product(page, asin)
    data["checked_at"] = time.time()
    return data


# ------------------------------------------------------------------ listados

def parse_listing(page: str) -> list[dict]:
    """ASIN con su precio y descuento tal como sale en un listado de búsqueda o de ofertas.

    Solo sirve para elegir qué fichas abrir: el precio que se publica sale siempre de la ficha.
    """
    found: dict[str, dict] = {}
    for match in re.finditer(r'data-asin="([A-Z0-9]{10})"', page):
        asin = match.group(1)
        if asin in found:
            continue
        chunk = page[match.start(): match.start() + 9000]
        nxt = re.search(r'data-asin="[A-Z0-9]{10}"', chunk[20:])
        if nxt:
            chunk = chunk[: nxt.start() + 20]
        prices = _offscreen_prices(chunk)
        pct = re.search(r"-\s?(\d{1,2})\s?%", text_of(chunk))
        title = re.search(r'<h2[^>]*>(.*?)</h2>', chunk, re.S)
        found[asin] = {
            "asin": asin,
            "title": text_of(title.group(1)) if title else "",
            "price": prices[0] if prices else None,
            "was": max(prices) if len(prices) > 1 and max(prices) > prices[0] else None,
            "pct": int(pct.group(1)) if pct else None,
            "sponsored": "Patrocinado" in chunk[:3000],
        }
    for asin in re.findall(r"/dp/([A-Z0-9]{10})", page):
        found.setdefault(asin, {"asin": asin, "title": "", "price": None, "was": None, "pct": None,
                                "sponsored": False})
    return list(found.values())


def listing_drop(item: dict) -> float:
    if item.get("pct"):
        return float(item["pct"])
    price, was = item.get("price"), item.get("was")
    if price and was and was > price:
        return (was - price) / was * 100
    return 0.0


def diagnose(page: str, asin: str) -> str:
    """Resumen corto del bloque de precio de una ficha, para ajustar el lector con fichas reales."""
    data = parse_product(page, asin)
    lines = [f"--- {asin} ---"]
    for key in ("title", "price", "lowest_30", "list_price", "in_stock", "availability", "seller", "shipper",
                "rating", "reviews", "prime_only", "reference_labels"):
        lines.append(f"{key}: {str(data.get(key))[:90]}")
    for element_id in CORE_PRICE_IDS:
        block = _feature(page, element_id)
        lines.append(f"[{element_id}] {len(block)} car.: {text_of(block)[:420]}")
    for match in list(re.finditer(r"(?i)precio m[aá]s bajo|precio recomendado|precio anterior|pvpr", page))[:6]:
        lines.append("· " + text_of(page[max(0, match.start() - 300): match.start() + 300])[-260:])
    return "\n".join(lines)
