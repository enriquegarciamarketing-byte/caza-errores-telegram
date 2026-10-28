"""Chollometro, más vendidos de Amazon y watchlist de piezas de colección. Si una fuente falla, se sigue."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import affiliate
import premium
import wallapop

ROOT = Path(__file__).resolve().parent
WATCHLIST_PATH = ROOT / "watchlist.json"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

ITEM_RE = re.compile(r"<item>(.*?)</item>", re.S)
VISIT_RE = re.compile(r'linkCloakedItemMainButton":"(https?:\\?/\\?/[^"]+)"')
ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")
TITLE_RE = re.compile(r'alt="([^"]{12,140})"')

PREORDER = ("ya en reserva", "reservar ahora", "precompra", "preventa", "proximamente", "próximamente")
IN_STOCK = ("añadir a la cesta", "añadir al carrito", "comprar ahora", "añadir a la bolsa")
OUT_OF_STOCK = ("agotado", "no disponible", "sin stock", "temporalmente no disponible")


def _get(url: str, timeout: int = 20) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/rss+xml,application/xml,text/xml,*/*",
        "Accept-Language": "es-ES,es;q=0.9",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.status), response.read()


def _cdata(block: str, tag: str) -> str:
    match = re.search(rf"<{tag}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", block, re.S)
    return re.sub(r"\s+", " ", match.group(1)).strip() if match else ""


def parse_price(raw: str) -> float | None:
    text = (raw or "").strip().replace("€", "").replace(" ", "")
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


def parse_rss(xml: str) -> list[dict]:
    items = []
    for block in ITEM_RE.findall(xml or ""):
        title = _cdata(block, "title")
        temp = re.match(r"(\d+)\s*°", title)
        merchant = re.search(r'<pepper:merchant[^>]*name="([^"]*)"[^>]*price="([^"]*)"', block)
        image = re.search(r'<media:content[^>]*url="([^"]+)"', block)
        link = _cdata(block, "link")
        category = _cdata(block, "category")
        published = _cdata(block, "pubDate")
        clean = re.sub(r"^\d+\s*°\s*-\s*", "", title).strip()
        price = parse_price(merchant.group(2) if merchant else "")
        items.append({
            "title": clean or title,
            "temperature": int(temp.group(1)) if temp else 0,
            "merchant": merchant.group(1) if merchant else "",
            "price": price,
            "image": image.group(1) if image else "",
            "link": link,
            "category": category,
            "published": published,
        })
    return items


def page_status(html: str) -> str:
    """in_stock, preorder, out, blocked o unknown. Una página anti-bot no cuenta como stock."""
    head = wallapop.fold_text((html or "")[:12000])
    if any(word in head for word in ("pardon our interruption", "cf-browser-verification", "access denied")):
        return "blocked"
    preorder = tuple(wallapop.fold_text(word) for word in PREORDER)
    in_stock = tuple(wallapop.fold_text(word) for word in IN_STOCK)
    out_of_stock = tuple(wallapop.fold_text(word) for word in OUT_OF_STOCK)
    if any(word in head for word in preorder):
        return "preorder"
    available = any(phrase in head for phrase in in_stock)
    gone = any(phrase in head for phrase in out_of_stock)
    if available and not gone:
        return "in_stock"
    if gone and not available:
        return "out"
    if available:
        return "in_stock"
    return "unknown"


def load_watchlist(path: Path | None = None) -> list[dict]:
    file = path or WATCHLIST_PATH
    if not file.exists():
        return []
    data = json.loads(file.read_text(encoding="utf-8"))
    items = data.get("items") if isinstance(data, dict) else data
    return [item for item in items or [] if isinstance(item, dict) and item.get("enabled", True)]


def _matches_watch(title: str, item: dict) -> bool:
    text = wallapop.fold_text(title)
    needles = item.get("match") or item.get("keywords") or []
    return bool(needles) and all(wallapop.keyword_in(text, word) for word in needles)


def resolve_deal_url(page: str) -> str | None:
    """Saca la URL de la tienda del botón de Chollometro, sin seguir su afiliado."""
    match = VISIT_RE.search(page or "")
    if not match:
        host = re.search(r'"linkHost":"(www\.[^"]+)"', page or "")
        return None if not host else f"https://{host.group(1)}/"
    visit = match.group(1).replace("\\/", "/")
    return _unwrap_visit(visit)


def _unwrap_visit(visit: str) -> str | None:
    class _Stop(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener = urllib.request.build_opener(_Stop)
    request = urllib.request.Request(visit, headers={"User-Agent": USER_AGENT, "Accept-Language": "es-ES"})
    try:
        opener.open(request, timeout=15)
        return None
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location") or ""
    except (urllib.error.URLError, TimeoutError):
        return None
    parsed = urllib.parse.urlparse(location)
    target = (urllib.parse.parse_qs(parsed.query).get("url") or [None])[0]
    if target:
        return urllib.parse.unquote(target)
    if location.startswith("http") and "chollometro" not in location and "pepper" not in location:
        return location
    return None


def _store_link(url: str, cfg: dict) -> str:
    store_id, _label = premium.store_of(url)
    if store_id == "amazon":
        tagged = affiliate.force_tag(url.split("?")[0] if "/dp/" in url else url, (cfg or {}).get("affiliate_tag") or "")
        # force_tag on a bare /dp/ keeps the path; if the URL had a query, rebuild from the ASIN.
        asin = affiliate.extract_asin(url)
        if asin:
            return affiliate.force_tag(f"https://www.amazon.es/dp/{asin}", (cfg or {}).get("affiliate_tag") or "")
        return tagged
    return premium.apply_store_template(url, cfg)


def _from_feed(entry: dict, cfg: dict, watch: list[dict], page: str) -> dict | None:
    store_url = resolve_deal_url(page)
    if not store_url or "chollometro.com" in store_url:
        return None
    if store_url.rstrip("/").count("/") < 3:
        return None
    store_url = _store_link(store_url, cfg)
    _store_id, label = premium.store_of(store_url)
    thread = re.search(r"(\d{5,})/?$", entry.get("link") or "")
    cand = {
        "id": f"cm-{thread.group(1) if thread else wallapop.product_cache_key(entry, entry.get('title') or '')[:24]}",
        "name": entry["title"],
        "title": entry["title"],
        "brand": entry.get("merchant") or "",
        "price": entry.get("price"),
        "image": entry.get("image") or "",
        "store_url": store_url,
        "direct_url": store_url,
        "store_label": label,
        "origin": "chollometro",
        "temperature": entry.get("temperature") or 0,
        "in_stock": True,
        "category": "OPORTUNIDAD DE REVENTA",
    }
    for item in watch:
        if _matches_watch(entry["title"], item):
            cand.update(collector=True, watch_id=item.get("id"), hold=True,
                        justification=item.get("justification") or "",
                        past_query=item.get("past_query") or "")
            if item.get("brand"):
                cand["brand"] = item["brand"]
            break
    return cand


def _from_watch(item: dict, status: str, cfg: dict) -> dict | None:
    if status not in {"in_stock", "preorder"}:
        return None
    url = _store_link(item.get("url") or "", cfg)
    _store_id, label = premium.store_of(url)
    price = item.get("price")
    return {
        "id": f"watch-{item.get('id')}",
        "watch_id": item.get("id"),
        "name": item.get("title") or "",
        "title": item.get("title") or "",
        "brand": item.get("brand") or "",
        "price": float(price) if price else None,
        "image": item.get("image") or "",
        "store_url": url,
        "direct_url": url,
        "store_label": label,
        "origin": "watchlist",
        "collector": True,
        "hold": True,
        "justification": item.get("justification") or "",
        "past_query": item.get("past_query") or "",
        "in_stock": status == "in_stock",
        "preorder": status == "preorder",
        "category": "RESERVA COLECCIONISTA" if status == "preorder" else "OPORTUNIDAD DE REVENTA",
    }


def amazon_hot_titles(cfg: dict, state: dict | None = None) -> list[str]:
    """Títulos de más vendidos y movers. Si Amazon corta, la lista queda vacía y el escaneo sigue."""
    rules = (cfg or {}).get("resale") or {}
    pages = list(rules.get("discovery_pages") or [])
    cache = None if state is None else state.setdefault("discovery_cache", {})
    if isinstance(cache, dict) and time.time() - float(cache.get("t") or 0) < 6 * 3600 and cache.get("titles"):
        return list(cache["titles"])
    titles: list[str] = []
    for url in pages[:3]:
        try:
            status, raw = _get(url, timeout=18)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"  Más vendidos {url}: {exc}")
            continue
        page = raw.decode("utf-8", "replace")
        blocked = "captcha" in page[:4000].lower() and "bestsellers" not in page[:4000].lower() and "/dp/" not in page
        found = [wallapop.fold_text(html_unescape(item)) for item in TITLE_RE.findall(page)]
        found = [item for item in found if not item.startswith("amazon")]
        print(f"  Más vendidos {url}: HTTP {status}, {len(raw)} bytes, "
              f"{'bloqueado' if blocked else str(len(set(ASIN_RE.findall(page)))) + ' ASIN, ' + str(len(found)) + ' títulos'}")
        if not blocked:
            titles.extend(found[:40])
        time.sleep(0.5)
    titles = list(dict.fromkeys(titles))[:80]
    if isinstance(cache, dict) and titles:
        cache.clear()
        cache.update(t=time.time(), titles=titles)
    return titles


def html_unescape(value: str) -> str:
    return value.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")


def external_precheck(cfg: dict, cand: dict) -> tuple[bool, str]:
    rules = (cfg or {}).get("resale") or {}
    price = float(cand.get("price") or 0)
    minimum = float(rules.get("min_price_eur", 25))
    if price + 1e-9 < minimum:
        return False, f"precio por debajo del mínimo premium ({minimum:.0f} €)"
    if not cand.get("image"):
        return False, "sin imagen"
    hit = premium.commodity_hit(cand, rules)
    if hit:
        return False, f"producto de poco valor («{hit}»)"
    info = premium.priority_info(cand, rules)
    if info["score"] <= 0 and not cand.get("collector"):
        return False, "fuera de las categorías premium"
    cand["hold"] = bool(info["hold"] or cand.get("collector"))
    cand["priority"] = info["id"]
    if not cand.get("priority"):
        cand["priority"] = "coleccion" if cand.get("collector") else ""
    return True, ""


def external_candidates(cfg: dict, state: dict | None = None) -> list[dict]:
    """Chollos de otras tiendas y la watchlist. Un bloqueo se registra y no tumba el resto."""
    rules = (cfg or {}).get("resale") or {}
    found: list[dict] = []
    watch = []
    try:
        watch = load_watchlist()
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  Watchlist no legible ({exc})")
    for item in watch:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        try:
            status, raw = _get(url, timeout=18)
            page = raw.decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"  Watchlist {item.get('id')}: {exc}")
            continue
        availability = page_status(page)
        print(f"  Watchlist {item.get('id')}: HTTP {status}, {len(raw)} bytes, {availability}")
        if availability == "blocked":
            continue
        cand = _from_watch(item, availability, cfg)
        if cand:
            found.append(cand)
        time.sleep(0.4)
    minimum_temp = int(rules.get("chollometro_min_temperature", 80))
    budget = int(rules.get("max_feed_items_per_run", 5))
    opened = 0
    for feed in rules.get("chollometro_feeds") or []:
        try:
            status, raw = _get(feed, timeout=20)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"  Chollometro {feed}: {exc}")
            continue
        entries = parse_rss(raw.decode("utf-8", "replace"))
        print(f"  Chollometro {feed}: HTTP {status}, {len(raw)} bytes, {len(entries)} chollos")
        for entry in entries:
            if opened >= budget:
                break
            if entry["temperature"] < minimum_temp:
                continue
            text = {"name": entry["title"], "title": entry["title"], "brand": ""}
            if premium.commodity_hit(text, rules):
                continue
            watched = any(_matches_watch(entry["title"], item) for item in watch)
            if premium.priority_info(text, rules)["score"] <= 0 and not watched:
                continue
            if not entry.get("price") or entry["price"] < float(rules.get("min_price_eur", 25)):
                continue
            if not entry.get("link"):
                continue
            opened += 1
            try:
                _status, body = _get(entry["link"], timeout=18)
                page = body.decode("utf-8", "replace")
            except (urllib.error.URLError, TimeoutError) as exc:
                print(f"  Chollometro ficha: {exc}")
                continue
            cand = _from_feed(entry, cfg, watch, page)
            if cand:
                print(f"  Chollometro «{entry['title'][:70]}»: {cand['store_label']} {cand.get('price')} €")
                found.append(cand)
            time.sleep(0.4)
    return found
