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


def query_keywords(cand: dict, limit: int = 6) -> str:
    """Marca y las palabras que identifican el modelo, no el texto comercial."""
    name = f"{cand.get('brand') or ''} {cand.get('name') or cand.get('title') or ''}"
    picked: list[str] = []
    for token in tokens(name):
        if token in STOP:
            continue
        if len(token) < 3 and not any(char.isdigit() for char in token):
            continue
        if token not in picked:
            picked.append(token)
        if len(picked) >= limit:
            break
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


def matching_prices(cand: dict, items: list[dict], rules: dict) -> list[float]:
    prices = []
    for item in items:
        if not isinstance(item, dict):
            continue
        reserved = item.get("reserved")
        if reserved is True or (isinstance(reserved, dict) and reserved.get("flag")):
            continue
        title = str(item.get("title") or "")
        if not listing_matches(cand, title, rules):
            continue
        amount = _amount(item.get("price"))
        if amount and amount > 0:
            prices.append(amount)
    return prices


def _without_outliers(prices: list[float], rules: dict) -> list[float]:
    if len(prices) < 3:
        return prices
    center = statistics.median(prices)
    low = float(rules.get("outlier_low_ratio", 0.45))
    high = float(rules.get("outlier_high_ratio", 2.2))
    kept = [price for price in prices if center * low <= price <= center * high]
    return kept or prices


def evaluate(cand: dict, prices: list[float], rules: dict) -> dict:
    """ROI = (reventa - precio) / precio. Hace falta un mínimo de anuncios, de ROI y de euros."""
    buy = float(cand.get("price") or 0)
    minimum = int(rules.get("min_listings", 5))
    kept = _without_outliers(prices, rules)
    if len(kept) < minimum:
        return {"ok": False, "transient": False, "count": len(kept),
                "reason": f"Wallapop solo tiene {len(kept)} anuncios parecidos (mínimo {minimum})"}
    stat = (rules.get("price_stat") or "median").lower()
    resale = float(statistics.mean(kept) if stat == "mean" else statistics.median(kept))
    profit = resale - buy
    roi = profit / buy if buy else -1
    min_roi = float(rules.get("min_roi", 0.25))
    min_profit = float(rules.get("min_profit_eur", 15))
    if roi + 1e-9 < min_roi or profit + 1e-9 < min_profit:
        return {"ok": False, "transient": False, "price": resale, "count": len(kept), "roi": roi, "profit": profit,
                "reason": (f"reventa en Wallapop ~{resale:.0f} € ({len(kept)} anuncios): "
                           f"ROI {roi * 100:.0f} % y {profit:.0f} €, por debajo del mínimo "
                           f"({min_roi * 100:.0f} % y {min_profit:.0f} €)")}
    return {"ok": True, "transient": False, "price": resale, "count": len(kept), "roi": roi, "profit": profit,
            "reason": ""}


def _request(url: str) -> dict:
    global _LAST_REQUEST
    _LAST_REQUEST = time.monotonic()
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:160]
        transient = exc.code in {403, 408, 429} or exc.code >= 500
        raise LookupError(transient, f"HTTP {exc.code} {detail}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LookupError(True, str(exc)) from None
    return payload


class LookupError(Exception):
    def __init__(self, transient: bool, message: str):
        super().__init__(message)
        self.transient = transient


def fetch_items(keywords: str, rules: dict) -> list[dict]:
    params = {
        "source": "search_box",
        "keywords": keywords,
        "latitude": rules.get("latitude", 40.4168),
        "longitude": rules.get("longitude", -3.7038),
        "order_by": "newest",
    }
    url = SEARCH_URL + "?" + urllib.parse.urlencode(params)
    payload = _request(url)
    section = ((payload.get("data") or {}).get("section") or {}).get("payload") or {}
    items = section.get("items") or []
    return items if isinstance(items, list) else []


def lookup(cand: dict, rules: dict, state: dict | None = None) -> dict:
    """Busca en Wallapop, con caché y una pausa entre peticiones. No publica nada."""
    rules = rules or {}
    query = query_keywords(cand, int(rules.get("max_keywords", 6)))
    if len(tokens(query)) < 2:
        return {"ok": False, "transient": False, "count": 0, "query": query,
                "reason": "el título no da suficientes palabras para buscar en Wallapop"}
    cache = {} if state is None else state.setdefault("wallapop_cache", {})
    ttl = float(rules.get("cache_hours", 12)) * 3600
    hit = cache.get(query)
    if isinstance(hit, dict) and time.time() - float(hit.get("t") or 0) < ttl:
        cached = dict(hit.get("result") or {})
        cached["cached"] = True
        return cached
    wait = float(rules.get("min_seconds_between_requests", 1.2)) - (time.monotonic() - _LAST_REQUEST)
    if wait > 0:
        time.sleep(wait)
    try:
        items = fetch_items(query, rules)
    except LookupError as exc:
        return {"ok": False, "transient": exc.transient, "count": 0, "query": query,
                "reason": f"no he podido consultar Wallapop ({exc})"}
    result = evaluate(cand, matching_prices(cand, items, rules), rules)
    result["query"] = query
    if state is not None:
        cache[query] = {"t": time.time(), "result": {k: v for k, v in result.items() if k != "cached"}}
        if len(cache) > 200:
            oldest = sorted(cache, key=lambda key: cache[key].get("t") or 0)[: len(cache) - 200]
            for key in oldest:
                cache.pop(key, None)
    return result
