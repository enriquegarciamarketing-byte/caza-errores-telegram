"""Búsqueda pública de Milanuncios. Si el anti-bot responde, se registra y se sigue sin esa fuente."""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.parse
import urllib.request

import wallapop

SEARCH = "https://www.milanuncios.com/anuncios/"
_LAST = 0.0
CARD_RE = re.compile(
    r'class="ma-AdCard-titleLink"[^>]*>(.*?)</a>.*?class="ma-AdPrice[^"]*"[^>]*>(.*?)</',
    re.S,
)
PRICE_RE = re.compile(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:[.,]\d{2})?)\s*€")


def _eur(raw: str) -> float | None:
    text = re.sub(r"[^\d.,]", "", raw or "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def is_blocked(page: str) -> bool:
    head = (page or "")[:6000].lower()
    return ("pardon our interruption" in head or "incapsula" in head or "_incapsula_resource" in head
            or "cf-browser-verification" in head)


def parse_listings(page: str) -> list[dict]:
    items = []
    for title_html, price_html in CARD_RE.findall(page or ""):
        title = re.sub(r"<[^>]+>", " ", title_html)
        title = re.sub(r"\s+", " ", title).strip()
        amount = _eur(price_html)
        if title and amount:
            items.append({"title": title, "price": {"amount": amount}, "reserved": {"flag": False}})
    return items


def fetch_items(keywords: str, rules: dict | None = None) -> tuple[list[dict], dict]:
    global _LAST
    wait = 1.0 - (time.monotonic() - _LAST)
    if _LAST and wait > 0:
        time.sleep(wait)
    _LAST = time.monotonic()
    url = SEARCH + "?" + urllib.parse.urlencode({"palabras": keywords})
    request = urllib.request.Request(url, headers={
        "User-Agent": wallapop.HEADERS["User-Agent"],
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "es-ES,es;q=0.9",
        "Referer": "https://www.milanuncios.com/",
    })
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        print(f"  Milanuncios «{keywords}»: HTTP {exc.code}, {len(body)} bytes")
        raise wallapop.LookupError(exc.code in {403, 408, 429} or exc.code >= 500,
                                   f"HTTP {exc.code} ({len(body)} bytes)") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"  Milanuncios «{keywords}»: {exc}")
        raise wallapop.LookupError(True, str(exc)) from None
    page = raw.decode("utf-8", "replace")
    blocked = is_blocked(page)
    items = [] if blocked else parse_listings(page)
    print(f"  Milanuncios «{keywords}»: HTTP {status}, {len(raw)} bytes, "
          f"{'bloqueado' if blocked else str(len(items)) + ' anuncios'}")
    return items, {"status": status, "bytes": len(raw), "raw": len(items), "blocked": blocked, "query": keywords}


def lookup(cand: dict, rules: dict, state: dict | None = None) -> dict:
    rules = rules or {}
    query = wallapop.query_keywords(cand, int(rules.get("max_keywords", 3)))
    if len(wallapop.tokens(query)) < 2:
        return {"ok": False, "prices": [], "query": query, "count": 0, "transient": False, "reason": "título corto"}
    cache = {} if state is None else state.setdefault("milanuncios_cache", {})
    ttl = float(rules.get("cache_hours", 12)) * 3600
    key = wallapop.product_cache_key(cand, query)
    hit = cache.get(key) or cache.get(query)
    if isinstance(hit, dict) and time.time() - hit.get("t", 0) < ttl:
        if hit.get("blocked") or (isinstance(hit.get("result"), dict) and hit["result"].get("blocked")):
            reason = hit.get("reason") or (hit.get("result") or {}).get("reason") or "Milanuncios bloqueado"
            return {"ok": False, "prices": [], "query": query, "count": 0, "transient": False,
                    "blocked": True, "cached": True, "reason": reason}
        stored = hit.get("prices")
        if stored is None and isinstance(hit.get("result"), dict):
            stored = hit["result"].get("prices") or []
        result = wallapop.evaluate(cand, list(stored or []), rules, label="Milanuncios",
                                   reserved=int(hit.get("reserved") or 0),
                                   demand_known=bool(hit.get("demand_known")))
        result.update(prices=list(stored or []), query=query, cached=True,
                      reserved=int(hit.get("reserved") or 0), demand_known=bool(hit.get("demand_known")))
        return result
    try:
        items, info = fetch_items(query, rules)
    except wallapop.LookupError as exc:
        return {"ok": False, "prices": [], "query": query, "count": 0, "transient": exc.transient,
                "blocked": True, "reason": f"Milanuncios no disponible ({exc})"}
    if info.get("blocked"):
        result = {"ok": False, "prices": [], "query": query, "count": 0, "transient": False, "blocked": True,
                  "http_status": info["status"], "bytes": info["bytes"],
                  "reason": f"Milanuncios bloqueado (HTTP {info['status']}, {info['bytes']} bytes)"}
    else:
        stats = wallapop.matching_stats(cand, items, rules)
        prices = stats["prices"]
        print(f"  Milanuncios «{query}»: {len(prices)} parecidos de {info['raw']}")
        result = wallapop.evaluate(cand, prices, rules, label="Milanuncios", reserved=stats["reserved"],
                                   demand_known=stats["demand_known"])
        result.update(prices=prices, query=query, http_status=info["status"], bytes=info["bytes"],
                      raw_count=info["raw"], reserved=stats["reserved"], demand_known=stats["demand_known"])
    if state is not None and not result.get("transient"):
        cache[key] = {"t": time.time(), "prices": list(result.get("prices") or []),
                      "reserved": int(result.get("reserved") or 0), "demand_known": bool(result.get("demand_known")),
                      "blocked": bool(result.get("blocked")), "reason": result.get("reason") or ""}
    return result
