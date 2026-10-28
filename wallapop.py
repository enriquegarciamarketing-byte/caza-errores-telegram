"""Consulta la búsqueda pública de Wallapop para estimar el precio de reventa en España."""

from __future__ import annotations

import json
import re
import statistics
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

SEARCH_URL = "https://api.wallapop.com/api/v3/search"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9",
    "Origin": "https://es.wallapop.com",
    "Referer": "https://es.wallapop.com/",
    # Cabecera que envía la web pública; sin ella la API no responde.
    "x-deviceos": "0",
}
STOP = {
    "de", "del", "la", "el", "los", "las", "para", "con", "por", "una", "uno", "un", "y", "en", "al",
    "the", "and", "of", "nuevo", "nueva", "original", "oficial", "amazon", "pack", "set", "kit",
    "color", "negro", "negra", "blanco", "blanca", "azul", "rojo", "roja",
}
# Descriptores que, juntos, dejan la búsqueda en cero resultados.
NOISE = STOP | {
    "tela", "bordes", "cosidos", "hombre", "mujer", "manga", "corta", "largo", "solid", "linen",
    "accesorios", "flotador", "pelota", "litros", "unisex", "adulto", "profesional", "talla",
    "size", "cm", "mm", "eu", "white", "black", "nino", "nina", "adulto",
}
TOKEN_RE = re.compile(r"[a-z0-9]+")
_LAST_REQUEST = 0.0


def fold_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value or "")
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return stripped.lower()


def tokens(text: str) -> list[str]:
    return TOKEN_RE.findall(fold_text(text))


def keyword_in(text: str, keyword: str) -> bool:
    haystack = fold_text(text)
    needle = fold_text(keyword).strip()
    if not needle or not haystack:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def capacities(text: str) -> set[int]:
    """Gigabytes declarados, tratando 2x8 GB como 16 GB y no como un módulo de 8."""
    folded = fold_text(text)
    totals: set[int] = set()
    for match in re.finditer(r"(\d+)\s*x\s*(\d+)\s*gb", folded):
        totals.add(int(match.group(1)) * int(match.group(2)))
        folded = folded.replace(match.group(0), " ", 1)
    for match in re.finditer(r"(\d+)\s*gb", folded):
        totals.add(int(match.group(1)))
    return totals


def ddr_versions(text: str) -> set[str]:
    return {f"ddr{number}" for number in re.findall(r"ddr\s*([345])", fold_text(text))}


def product_cache_key(cand: dict, query: str) -> str:
    """La misma frase puede salir de dos productos distintos; la caché no debe mezclarlos."""
    identity = f"{cand.get('brand') or ''}|{cand.get('name') or cand.get('title') or ''}|{query}"
    return fold_text(identity)


def query_keywords(cand: dict, limit: int = 3) -> str:
    """Marca más una o dos palabras de modelo. Una frase larga deja la búsqueda a cero."""
    brand = [token for token in tokens(cand.get("brand") or "") if token not in NOISE and len(token) >= 3]
    name = [token for token in tokens(cand.get("name") or cand.get("title") or "")
            if token not in NOISE and token not in brand and (len(token) >= 3 or any(ch.isdigit() for ch in token))]
    if not brand:
        # La marca a veces solo está en el título.
        brand = name[:1]
        name = name[1:]
    digits = [token for token in name if any(ch.isdigit() for ch in token)]
    # Un «1» suelto (Air Force 1) no identifica el modelo y tira anuncios que no lo llevan.
    strong = [token for token in digits if len(token) >= 2]
    words = [token for token in name if token not in digits]
    picked = list(brand[:2])
    for token in (strong[:1] + words[:1]):
        if len(picked) >= limit:
            break
        if token not in picked:
            picked.append(token)
    return " ".join(picked)


def listing_matches(cand: dict, title: str, rules: dict) -> bool:
    product = f"{cand.get('brand') or ''} {cand.get('name') or cand.get('title') or ''}"
    listing = title or ""
    for word in rules.get("bundle_keywords") or []:
        if keyword_in(listing, word) and not keyword_in(product, word):
            return False
    for word in rules.get("accessory_keywords") or []:
        if keyword_in(listing, word) and not keyword_in(product, word):
            return False
    product_caps, listing_caps = capacities(product), capacities(listing)
    if product_caps and listing_caps and product_caps.isdisjoint(listing_caps):
        return False
    product_ddr, listing_ddr = ddr_versions(product), ddr_versions(listing)
    if product_ddr and listing_ddr and product_ddr.isdisjoint(listing_ddr):
        return False
    core = tokens(query_keywords(cand, int(rules.get("max_keywords", 6))))
    found = set(tokens(listing))
    brand = [token for token in tokens(cand.get("brand") or "") if token not in STOP and len(token) >= 3]
    if brand and not any(token in found for token in brand):
        return False
    overlap = [token for token in core if token in found]
    if len(overlap) < min(2, len(core) or 2):
        return False
    numbered = [token for token in core if any(char.isdigit() for char in token)]
    if numbered and not any(token in found for token in numbered):
        return False
    return True


def _amount(price) -> float | None:
    if isinstance(price, (int, float)) and not isinstance(price, bool):
        return float(price)
    if not isinstance(price, dict):
        return None
    raw = price.get("amount")
    if raw is None and isinstance(price.get("cash"), dict):
        raw = price["cash"].get("amount")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def matching_stats(cand: dict, items: list[dict], rules: dict) -> dict:
    """Precios comparables y cuántos estaban reservados. La reserva es señal de demanda, no entra en la mediana."""
    prices = []
    reserved = 0
    demand_known = False
    for item in items:
        if not isinstance(item, dict):
            continue
        if "reserved" in item:
            demand_known = True
        flag = item.get("reserved")
        is_reserved = flag is True or (isinstance(flag, dict) and flag.get("flag"))
        title = str(item.get("title") or "")
        if not listing_matches(cand, title, rules):
            continue
        if is_reserved:
            reserved += 1
            continue
        amount = _amount(item.get("price"))
        if amount and amount > 0:
            prices.append(amount)
    return {"prices": prices, "reserved": reserved, "demand_known": demand_known}


def matching_prices(cand: dict, items: list[dict], rules: dict) -> list[float]:
    return matching_stats(cand, items, rules)["prices"]


def roi_floor(buy: float, rules: dict) -> float:
    """25 % en general y 30 % si el precio de compra no llega a 60 €."""
    floor = float(rules.get("min_roi", 0.25))
    cutoff = rules.get("min_roi_below_eur")
    if cutoff is not None and buy + 1e-9 < float(cutoff):
        floor = max(floor, float(rules.get("min_roi_below", floor)))
    return floor


def _without_outliers(prices: list[float], rules: dict) -> list[float]:
    if len(prices) < 3:
        return prices
    center = statistics.median(prices)
    low = float(rules.get("outlier_low_ratio", 0.45))
    high = float(rules.get("outlier_high_ratio", 2.2))
    kept = [price for price in prices if center * low <= price <= center * high]
    return kept or prices


def evaluate(cand: dict, prices: list[float], rules: dict, label: str = "Wallapop",
             reserved: int = 0, demand_known: bool = False) -> dict:
    """ROI = (reventa - precio) / precio. Hace falta un mínimo de anuncios, de ROI y de euros."""
    buy = float(cand.get("price") or 0)
    minimum = int(rules.get("min_listings", 5))
    kept = _without_outliers(prices, rules)
    many = int(rules.get("demand_many_listings", 12))
    if len(kept) < minimum:
        return {"ok": False, "transient": False, "count": len(kept), "reserved": reserved,
                "reason": f"{label} solo tiene {len(kept)} anuncios parecidos (mínimo {minimum})"}
    if demand_known and reserved < int(rules.get("min_reserved", 1)) and len(kept) < many:
        return {"ok": False, "transient": False, "count": len(kept), "reserved": reserved,
                "reason": (f"sin señal de demanda en {label}: {reserved} reservas y {len(kept)} anuncios "
                           f"(hace falta una reserva o al menos {many})")}
    stat = (rules.get("price_stat") or "median").lower()
    resale = float(statistics.mean(kept) if stat == "mean" else statistics.median(kept))
    profit = resale - buy
    roi = profit / buy if buy else -1
    min_roi = roi_floor(buy, rules)
    min_profit = float(rules.get("min_profit_eur", 15))
    demand = "Reservas recientes" if reserved else ("Muchos anuncios" if len(kept) >= many else "")
    if roi + 1e-9 < min_roi or profit + 1e-9 < min_profit:
        return {"ok": False, "transient": False, "price": resale, "count": len(kept), "roi": roi, "profit": profit,
                "reserved": reserved, "demand": demand,
                "reason": (f"reventa en {label} ~{resale:.0f} € ({len(kept)} anuncios): "
                           f"ROI {roi * 100:.0f} % y {profit:.0f} €, por debajo del mínimo "
                           f"({min_roi * 100:.0f} % y {min_profit:.0f} €)")}
    return {"ok": True, "transient": False, "price": resale, "count": len(kept), "roi": roi, "profit": profit,
            "reserved": reserved, "demand": demand, "reason": ""}


def _request(url: str) -> tuple[int, int, dict]:
    global _LAST_REQUEST
    _LAST_REQUEST = time.monotonic()
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read()
            payload = json.loads(raw.decode("utf-8"))
            return int(resp.status), len(raw), payload
    except urllib.error.HTTPError as exc:
        detail = exc.read()
        transient = exc.code in {403, 408, 429} or exc.code >= 500
        raise LookupError(transient, f"HTTP {exc.code} ({len(detail)} bytes) {detail[:120].decode('utf-8', 'replace')}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LookupError(True, str(exc)) from None


class LookupError(Exception):
    def __init__(self, transient: bool, message: str):
        super().__init__(message)
        self.transient = transient


def fetch_items(keywords: str, rules: dict) -> tuple[list[dict], dict]:
    params = {
        "source": "search_box",
        "keywords": keywords,
        "latitude": rules.get("latitude", 40.4168),
        "longitude": rules.get("longitude", -3.7038),
        "order_by": rules.get("order_by") or "most_relevance",
    }
    url = SEARCH_URL + "?" + urllib.parse.urlencode(params)
    status, size, payload = _request(url)
    section = ((payload.get("data") or {}).get("section") or {}).get("payload") or {}
    items = section.get("items") or []
    if not isinstance(items, list):
        items = []
    info = {"status": status, "bytes": size, "raw": len(items), "query": keywords}
    return items, info


def lookup(cand: dict, rules: dict, state: dict | None = None) -> dict:
    """Busca en Wallapop, con caché y una pausa entre peticiones. No publica nada."""
    rules = rules or {}
    query = query_keywords(cand, int(rules.get("max_keywords", 3)))
    if len(tokens(query)) < 2:
        return {"ok": False, "transient": False, "count": 0, "prices": [], "query": query,
                "reason": "el título no da suficientes palabras para buscar en Wallapop"}
    cache = {} if state is None else state.setdefault("wallapop_cache", {})
    ttl = float(rules.get("cache_hours", 12)) * 3600
    key = product_cache_key(cand, query)
    hit = cache.get(key)
    if isinstance(hit, dict) and time.time() - float(hit.get("t") or 0) < ttl:
        stored = hit.get("prices")
        if stored is None and isinstance(hit.get("result"), dict):
            stored = hit["result"].get("prices") or []
        result = evaluate(cand, list(stored or []), rules, reserved=int(hit.get("reserved") or 0),
                          demand_known=bool(hit.get("demand_known")))
        result.update(query=hit.get("query") or query, prices=list(stored or []), cached=True,
                      http_status=hit.get("http_status"), bytes=hit.get("bytes"), raw_count=hit.get("raw_count"))
        return result
    queries = [query]
    short = " ".join(tokens(query)[:2])
    if short and short != query:
        queries.append(short)
    best_prices: list[float] = []
    best_info: dict = {}
    best_reserved = 0
    best_demand = False
    used = query
    last_error = ""
    transient = False
    for attempt in queries:
        wait = float(rules.get("min_seconds_between_requests", 1.0)) - (time.monotonic() - _LAST_REQUEST)
        if _LAST_REQUEST and wait > 0:
            time.sleep(wait)
        try:
            fetched = fetch_items(attempt, rules)
        except LookupError as exc:
            last_error = str(exc)
            transient = exc.transient
            print(f"  Wallapop «{attempt}»: {exc}")
            continue
        items, info = fetched if isinstance(fetched, tuple) else (fetched, {"status": 200, "bytes": 0, "raw": len(fetched), "query": attempt})
        if items and not isinstance(items[0], dict):
            stats = {"prices": [float(price) for price in items], "reserved": 0, "demand_known": False}
        else:
            stats = matching_stats(cand, items, rules)
        prices = stats["prices"]
        print(f"  Wallapop «{attempt}»: {info.get('status')} / {info.get('bytes')} bytes, "
              f"{info.get('raw')} anuncios, {len(prices)} parecidos, {stats['reserved']} reservas")
        if len(prices) > len(best_prices):
            best_prices, best_info, used = prices, info, attempt
            best_reserved, best_demand = stats["reserved"], stats["demand_known"]
        if len(prices) >= int(rules.get("min_listings", 5)):
            break
    if last_error and not best_prices and not best_info:
        return {"ok": False, "transient": transient, "count": 0, "prices": [], "query": used,
                "reason": f"no he podido consultar Wallapop ({last_error})"}
    result = evaluate(cand, best_prices, rules, reserved=best_reserved, demand_known=best_demand)
    result.update(query=used, prices=best_prices, http_status=best_info.get("status"),
                  bytes=best_info.get("bytes"), raw_count=best_info.get("raw"))
    if state is not None:
        cache[key] = {"t": time.time(), "query": used, "prices": best_prices,
                      "reserved": best_reserved, "demand_known": best_demand,
                      "http_status": best_info.get("status"), "bytes": best_info.get("bytes"),
                      "raw_count": best_info.get("raw")}
        if len(cache) > 200:
            oldest = sorted(cache, key=lambda key: cache[key].get("t") or 0)[: len(cache) - 200]
            for key in oldest:
                cache.pop(key, None)
    return result
