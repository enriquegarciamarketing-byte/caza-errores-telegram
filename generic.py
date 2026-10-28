#!/usr/bin/env python3
"""Canal normal @cazachollos_com.

Publica un flujo de chollos variados (todas las categorías y tiendas), con el
mismo tono que el canal premium y sin tarjeta de reventa. No usa TELEGRAM_CHAT_ID:
el destino sale de config.json → generic.chat_id.

Cada pasada:
1. Comprueba con getChatMember que el bot puede publicar.
2. Lee el RSS de Chollometro (calientes primero) y las listas de Amazon ya configuradas.
3. Tira caducados, sin precio, duplicados y temperatura baja.
4. Limpia el enlace: Amazon siempre con la etiqueta del canal; el resto, ficha directa.
5. Respeta el ritmo (hora, día y silencio nocturno) y apunta el historial en state/generic.json.
"""

from __future__ import annotations

import argparse
import copy
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import affiliate
import feeds
import premium
import scanner
from publisher import euro, short_title


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state" / "generic.json"
SCANNER_STATE = ROOT / "state" / "scanner.json"
MADRID = ZoneInfo("Europe/Madrid")
USER_AGENT = "CazaErroresBot/1.0 (+https://t.me/cazachollos_com)"
JIMMY_DETAIL = "https://jimmyleaks.com/es/dp/{id}/"
OUTPUT_DIR = ROOT / "output" / "generic"

PRIVATE_PREFIX = (
    "🧪 PRUEBA · canal normal\n"
    "<i>Solo para ti. No se publica en @cazachollos_com.</i>\n\n"
)

# Redes de afiliado y agregadores: si el enlace no sale de aquí, se descarta.
NETWORK_HOSTS = (
    "awin1.com", "awin.com", "tradedoubler.com", "admitad.com", "admitad.",
    "anrdoezrs.net", "dpbolvw.net", "jdoqocy.com", "tkqlhce.com", "kqzyfj.com",
    "shareasale.com", "impactradius", "prf.hn", "redirectingat.com", "viglink.com",
    "skimresources.com", "linksynergy.com", "chollometro.com", "pepper.com",
    "hotukdeals.com", "zanox.com", "tradetracker.net", "tradetracker.com",
    "effiliation.com", "publicidees.com", "webgains.com", "clk.tradedoubler.com",
)
FOREIGN_KEYS = {
    "tag", "ascsubtag", "linkcode", "linkid", "ref", "ref_", "creative", "creativeasin",
    "camp", "campid", "awc", "awaid", "tduid", "affiliate", "affid", "aff_id",
    "clickid", "clickref", "irclickid", "sharedid", "zanpid", "subid", "u1",
    "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "cm_mmc", "mkwid", "partnerid",
    "spm", "scm", "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id",
}
UNWRAP_KEYS = {"url", "ued", "redirect", "dest", "destination", "target"}
EXTRA_STORES = (
    ("aliexpress.", "AliExpress"),
    ("miravia.", "Miravia"),
    ("privalia.", "Privalia"),
    ("primeriti.", "Primeriti"),
    ("decathlon.", "Decathlon"),
    ("leroymerlin.", "Leroy Merlin"),
    ("worten.", "Worten"),
    ("mediamarkt.", "MediaMarkt"),
)

DEFAULTS = {
    "chat_id": "@cazachollos_com",
    "feeds": [
        "https://www.chollometro.com/rss/hot",
        "https://www.chollometro.com/rss/nuevos",
    ],
    "use_amazon_sources": True,
    "min_temperature": 80,
    "min_price_eur": 3,
    "min_discount_pct": 20,
    "max_discount_pct": 95,
    "min_reliable_discount_pct": 5,
    "max_posts_per_hour": 4,
    "max_posts_per_day": 40,
    "max_posts_per_run": 1,
    "test_private_posts": 3,
    "min_minutes_between_posts": 15,
    "quiet_hours": [1, 8],
    "repost_after_days": 14,
    "max_deal_age_hours": 36,
    "max_amazon_age_minutes": 120,
    "max_opens_per_run": 8,
}


def settings(cfg: dict | None) -> dict:
    raw = (cfg or {}).get("generic") if isinstance(cfg, dict) else None
    merged = dict(DEFAULTS)
    if isinstance(raw, dict):
        for key, value in raw.items():
            if value is not None:
                merged[key] = value
    hours = merged.get("quiet_hours") or [1, 8]
    merged["quiet_hours"] = [int(hours[0]), int(hours[1])]
    merged["chat_id"] = str(merged.get("chat_id") or "@cazachollos_com").strip() or "@cazachollos_com"
    feeds_ = merged.get("feeds") or DEFAULTS["feeds"]
    merged["feeds"] = [str(item) for item in feeds_ if str(item).strip()]
    return merged


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def resolve_admin(state: dict) -> int | str | None:
    """El administrador es el mismo que el del canal premium, sin escribir su memoria."""
    admin = (state or {}).get("admin_chat_id")
    if admin:
        return admin
    scanner_state = load_json(SCANNER_STATE, {})
    if isinstance(scanner_state, dict) and scanner_state.get("admin_chat_id"):
        return scanner_state["admin_chat_id"]
    return None


# ---------------------------------------------------------------- formato

def discount_percent(previous: float, current: float) -> int:
    if previous <= 0:
        return 0
    return int((previous - current) / previous * 100 + 0.5)


def reliable_previous(current: float, previous: float | None, cfg: dict | None = None) -> float | None:
    """PVP usable en el post. Si no es creíble, el mensaje se queda solo con AHORA."""
    rules = settings(cfg)
    if previous is None:
        return None
    try:
        old = float(previous)
        price = float(current)
    except (TypeError, ValueError):
        return None
    if old <= price or price <= 0:
        return None
    pct = discount_percent(old, price)
    if pct < int(rules["min_reliable_discount_pct"]) or pct > int(rules["max_discount_pct"]):
        return None
    return old


def hook_line(temperature: int, pct: int | None) -> str:
    if pct is not None and pct >= 60:
        return "🔥 <b>BAJÓN DE PRECIO</b>"
    if temperature >= 250:
        return "🔥 <b>SE ESTÁ VOLANDO</b>"
    if temperature >= 100:
        return "🔥 <b>CHOLLO CALIENTE</b>"
    return "✨ <b>CAZADO</b>"


def build_caption(deal: dict, cfg: dict | None = None) -> str:
    """Texto del canal: gancho, título y bloque de precio. Sin ROI ni reventa."""
    e = html.escape
    store = (deal.get("store") or "la tienda").strip()
    title = short_title(deal.get("title") or "Chollo", deal.get("brand") or "", limit=110)
    brand = (deal.get("brand") or "").strip()
    current = float(deal["price"])
    previous = reliable_previous(current, deal.get("previous"), cfg)
    pct = discount_percent(previous, current) if previous else None
    lines = [hook_line(int(deal.get("temperature") or 0), pct), ""]
    if brand and brand.lower() not in title.lower() and brand.lower() != store.lower():
        lines.append(f"<b>{e(brand)}</b> {e(title)}")
    else:
        lines.append(f"<b>{e(title)}</b>")
    category = (deal.get("category") or "").strip()
    if category:
        lines.append(f"📂 {e(category)}")
    lines.append("")
    if previous:
        saved = previous - current
        lines.append(f"❌ PVP {e(store)}: <s>{e(euro(previous))}</s>")
        lines.append(f"💰 AHORA: {e(euro(current))}")
        lines.append(f"📉 −{pct} % sobre PVP")
        lines.append(f"🤑 Te ahorras: {e(euro(saved))}")
    else:
        lines.append(f"💰 AHORA: {e(euro(current))}")
    url = deal.get("url") or ""
    lines.append("")
    lines.append(f'🔗 <b><a href="{e(url, quote=True)}">Ver en {e(store)}</a></b>')
    text = "\n".join(lines)
    if len(text) > 1000:
        text = text[:999].rstrip() + "…"
    return text


def button_for(deal: dict) -> dict:
    store = (deal.get("store") or "la tienda").strip()
    label = f"🛒 Ver en {store}"
    if len(label) > 64:
        label = store[:64]
    return {"inline_keyboard": [[{"text": label, "url": deal["url"]}]]}


def bigger_image(url: str) -> str:
    if not url:
        return ""
    return re.sub(r"/re/\d+x\d+/qt/\d+/", "/", url)


def fingerprint(title: str) -> str:
    text = unicodedata.normalize("NFKD", title or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).lower()
    return " ".join(text.split())[:90]


# ---------------------------------------------------------------- enlaces

def _host(url: str) -> str:
    return (urllib.parse.urlsplit(url or "").hostname or "").lower().rstrip(".")


def _is_blocked_host(url: str) -> bool:
    host = _host(url)
    if not host:
        return True
    for marker in NETWORK_HOSTS:
        needle = marker.strip(".")
        if host == needle or host.endswith("." + needle) or needle in host:
            return True
    return False


def _is_amazon_family(url: str) -> bool:
    if affiliate.is_short_link(url) or affiliate.is_amazon_es(url):
        return True
    host = _host(url)
    return host == "amazon.com" or host.endswith(".amazon.com") or (
        "amazon." in host and not host.endswith("amazon-adsystem.com")
    )


def _foreign_param(key: str) -> bool:
    name = (key or "").lower()
    if name.startswith("utm_") or name.startswith("aff_"):
        return True
    return name in FOREIGN_KEYS


def _strip_query(url: str) -> str:
    parts = urllib.parse.urlsplit(url.strip())
    query = [(key, value) for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if not _foreign_param(key)]
    return urllib.parse.urlunsplit((parts.scheme or "https", parts.netloc, parts.path,
                                    urllib.parse.urlencode(query), parts.fragment))


def _unwrap_network(url: str) -> str | None:
    """Saca la ficha de la tienda si el destino sigue siendo una red de afiliado."""
    current = url
    for _ in range(3):
        if not _is_blocked_host(current):
            return current
        parts = urllib.parse.urlsplit(current)
        nxt = ""
        for key, value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
            if key.lower() in UNWRAP_KEYS and value.startswith("https://"):
                nxt = urllib.parse.unquote(value)
                break
        if not nxt or nxt == current:
            return None
        current = nxt
    return None if _is_blocked_host(current) else current


def _amazon_link(url: str, tag: str, *, asin: str | None, gtin: str | None, resolve) -> str | None:
    found = affiliate.extract_asin(url)
    expected = (asin or found or "").upper() or None
    if expected and not re.fullmatch(r"[A-Z0-9]{10}", expected):
        expected = None
    target = url
    if not affiliate.is_amazon_es(url) and not affiliate.is_short_link(url):
        if not expected:
            return None
        target = f"https://www.amazon.es/dp/{expected}"
    link, warnings = affiliate.prepare_amazon_link(
        target, tag, asin=expected, gtin=gtin, resolve=resolve,
    )
    for warning in warnings:
        print(f"  Afiliado: {warning}")
    if not link or not affiliate.is_amazon_es(link):
        return None
    if affiliate.tag_values(link) != [tag]:
        return None
    got = affiliate.extract_asin(link)
    if expected and got != expected:
        return None
    if not expected:
        if got:
            return link
        if gtin and gtin in link:
            return link
        return None
    return link


def clean_merchant_url(url: str | None, cfg: dict, *, asin: str | None = None,
                       gtin: str | None = None, resolve=None) -> str | None:
    """Enlace publicable. None si no se puede dejar limpio: ese chollo no sale."""
    raw = (url or "").strip()
    if not raw.lower().startswith("https://"):
        return None
    tag = str((cfg or {}).get("affiliate_tag") or "").strip()
    if not tag:
        return None
    if _is_amazon_family(raw):
        return _amazon_link(raw, tag, asin=asin, gtin=gtin, resolve=resolve)
    target = raw
    if _is_blocked_host(raw):
        target = _unwrap_network(raw) or ""
        if not target:
            return None
        if _is_amazon_family(target):
            return _amazon_link(target, tag, asin=asin or affiliate.extract_asin(target),
                                gtin=gtin, resolve=resolve)
    if _is_blocked_host(target):
        return None
    direct = _strip_query(target)
    if not direct.lower().startswith("https://") or _is_blocked_host(direct):
        return None
    if direct.rstrip("/").count("/") < 3:
        return None
    final = premium.apply_store_template(direct, cfg)
    if not str(final).lower().startswith("https://"):
        return None
    return final


def store_label(url: str) -> str:
    store_id, label = premium.store_of(url)
    if store_id != "tienda":
        return label
    host = _host(url)
    for needle, name in EXTRA_STORES:
        if needle in host:
            return name
    return label


# ---------------------------------------------------------------- ficha de Chollometro

def thread_id_from_link(link: str) -> str:
    match = re.search(r"(\d{5,})/?$", link or "")
    return match.group(1) if match else ""


def _last_number(window: str, key: str) -> float | None:
    matches = list(re.finditer(rf'"{key}":(null|-?[0-9]+(?:\.[0-9]+)?)', window))
    if not matches:
        return None
    raw = matches[-1].group(1)
    if raw == "null":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _first_bool(window: str, key: str) -> bool | None:
    match = re.search(rf'"{key}":(true|false)', window)
    if not match:
        return None
    return match.group(1) == "true"


def _first_str(window: str, key: str) -> str:
    match = re.search(rf'"{key}":"([^"]*)"', window)
    return match.group(1) if match else ""


def parse_thread(page: str, thread_id: str) -> dict | None:
    if not page or not thread_id:
        return None
    marker = f'"threadId":"{thread_id}"'
    index = page.find(marker)
    if index < 0:
        return None
    before = page[max(0, index - 900):index]
    after = page[index:index + 2200]
    price = _last_number(before, "price")
    previous = _last_number(before, "nextBestPrice")
    if not previous:
        standard = _last_number(before, "standardPrice")
        if standard and standard > 0:
            previous = standard
    status = _first_str(after, "status")
    expired = bool(
        _first_bool(after, "isExpired")
        or _first_bool(after, "isMaybeExpired")
        or _first_bool(after, "stale")
        or (status and status not in {"Activated", "Active"})
    )
    return {
        "price": price,
        "previous": previous,
        "temperature": _last_number(before, "temperature") or 0,
        "expired": expired,
        "status": status,
    }


def parse_pubdate(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _deal_shell(*, ident: str, title: str, price: float, previous, url: str, image: str,
                category: str, temperature: int, brand: str, asin: str, origin: str) -> dict:
    store_id, _label = premium.store_of(url)
    return {
        "id": ident,
        "fp": fingerprint(title),
        "title": title.strip(),
        "brand": (brand or "").strip(),
        "store": store_label(url),
        "store_id": store_id,
        "price": float(price),
        "previous": float(previous) if previous else None,
        "url": url,
        "image": bigger_image(image),
        "category": (category or "").strip(),
        "temperature": int(temperature or 0),
        "asin": (asin or "").upper(),
        "origin": origin,
    }


def consider_chollometro(entry: dict, page: str, cfg: dict, resolve) -> tuple[dict | None, str]:
    rules = settings(cfg)
    link = entry.get("link") or ""
    thread = thread_id_from_link(link)
    if not thread:
        return None, "sin identificador"
    facts = parse_thread(page, thread)
    if not facts:
        return None, "ficha no reconocida"
    if facts["expired"]:
        return None, "caducado"
    price = facts["price"] if facts["price"] else entry.get("price")
    if not price or float(price) <= 0:
        return None, "sin precio"
    price = float(price)
    if price + 1e-9 < float(rules["min_price_eur"]):
        return None, "precio bajo"
    temperature = int(entry.get("temperature") or 0) or int(facts["temperature"] or 0)
    if temperature < int(rules["min_temperature"]):
        return None, "temperatura baja"
    try:
        merchant = resolve(page) if resolve else None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"  No se pudo resolver el enlace de {thread} ({exc})")
        merchant = None
    if not merchant:
        return None, "enlace no limpiable"
    asin = affiliate.extract_asin(merchant)
    cleaned = clean_merchant_url(merchant, cfg, asin=asin)
    if not cleaned:
        return None, "enlace no limpiable"
    title = entry.get("title") or ""
    if not title.strip():
        return None, "sin título"
    return _deal_shell(
        ident=f"cm-{thread}", title=title, price=price, previous=facts.get("previous"),
        url=cleaned, image=entry.get("image") or "", category=entry.get("category") or "",
        temperature=temperature, brand=entry.get("brand") or "", asin=asin or affiliate.extract_asin(cleaned) or "",
        origin="chollometro",
    ), ""


def asin_in_html(page: str) -> str | None:
    """El ASIN dentro de una ficha, también si el enlace no termina en barra."""
    match = re.search(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})(?![A-Z0-9])", page or "", re.I)
    return match.group(1).upper() if match else affiliate.extract_asin(page or "")


def consider_amazon(item: dict, page: str, cfg: dict) -> tuple[dict | None, str]:
    rules = settings(cfg)
    detail = scanner.parse_detail(page or "")
    if not detail.get("in_stock"):
        # Una página bloqueada no trae ficha: se reintenta. Un agotado real, no.
        if not detail.get("name") and not detail.get("price"):
            return None, ""
        return None, "agotado"
    price = detail.get("price") or item.get("price")
    if not price or float(price) <= 0:
        return None, "sin precio"
    price = float(price)
    if price + 1e-9 < float(rules["min_price_eur"]):
        return None, "precio bajo"
    asin = asin_in_html(page or "")
    gtin = detail.get("gtin") if re.fullmatch(r"\d{8,14}", str(detail.get("gtin") or "")) else None
    raw_url = f"https://www.amazon.es/dp/{asin}" if asin else ""
    cleaned = clean_merchant_url(raw_url, cfg, asin=asin, gtin=gtin) if raw_url else clean_merchant_url(
        affiliate.fallback_link(cfg.get("affiliate_tag") or "", gtin=gtin) or "", cfg, gtin=gtin,
    )
    if not cleaned:
        return None, "enlace no limpiable"
    title = detail.get("name") or item.get("title") or ""
    if not title.strip():
        return None, "sin título"
    was = item.get("was")
    return _deal_shell(
        ident=f"az-{item.get('id')}", title=title, price=price, previous=was,
        url=cleaned, image=detail.get("image") or "", category="",
        temperature=0, brand=detail.get("brand") or item.get("brand") or "",
        asin=asin or "", origin="amazon",
    ), ""


# ---------------------------------------------------------------- ritmo e historial

def _posts(state: dict) -> list[dict]:
    posts = (state or {}).get("posts") or []
    return [item for item in posts if isinstance(item, dict)]


def pace_reason(cfg: dict, state: dict, now: datetime) -> str | None:
    rules = settings(cfg)
    local = now.astimezone(MADRID)
    start, end = rules["quiet_hours"]
    if start <= local.hour < end:
        return f"horario de silencio ({start:02d}:00–{end:02d}:00 Europe/Madrid)"
    posts = _posts(state)
    stamp = now.timestamp()
    today = [item for item in posts
             if datetime.fromtimestamp(item.get("t") or 0, MADRID).date() == local.date()]
    if len(today) >= int(rules["max_posts_per_day"]):
        return "cupo diario cubierto"
    hour_ago = stamp - 3600
    recent = [item for item in posts if float(item.get("t") or 0) >= hour_ago]
    if len(recent) >= int(rules["max_posts_per_hour"]):
        return "cupo por hora cubierto"
    gap = int(rules["min_minutes_between_posts"]) * 60
    if posts and gap > 0:
        last = max(float(item.get("t") or 0) for item in posts)
        if stamp - last < gap:
            return "demasiado pronto respecto al último post"
    return None


def is_duplicate(state: dict, deal: dict, now: datetime, days: int) -> bool:
    cutoff = now.timestamp() - days * 86400
    for post in _posts(state):
        if float(post.get("t") or 0) < cutoff:
            continue
        if post.get("id") and post.get("id") == deal.get("id"):
            return True
        if deal.get("asin") and post.get("asin") == deal.get("asin"):
            return True
        if post.get("fp") and post.get("fp") == deal.get("fp") and post.get("store") == deal.get("store"):
            return True
    return False


def _skip_hours(reason: str) -> int:
    if "caduc" in reason or "agot" in reason:
        return 72
    if "enlace" in reason or "ficha" in reason:
        return 24
    return 12


def note_skip(state: dict, deal_id: str, reason: str, now: datetime) -> None:
    skipped = state.setdefault("skipped", {})
    if not isinstance(skipped, dict):
        skipped = {}
        state["skipped"] = skipped
    skipped[deal_id] = {
        "t": int(now.timestamp()),
        "until": int(now.timestamp() + _skip_hours(reason) * 3600),
        "reason": reason,
    }
    if len(skipped) > 400:
        oldest = sorted(skipped, key=lambda key: skipped[key].get("t") or 0)
        for key in oldest[: len(skipped) - 400]:
            skipped.pop(key, None)


def recently_skipped(state: dict, deal_id: str, now: datetime) -> bool:
    skipped = (state or {}).get("skipped") or {}
    if not isinstance(skipped, dict):
        return False
    item = skipped.get(deal_id) or {}
    return float(item.get("until") or 0) > now.timestamp()


def remember(state: dict, deal: dict, now: datetime) -> None:
    posts = state.setdefault("posts", [])
    posts.append({
        "id": deal["id"],
        "fp": deal.get("fp") or "",
        "asin": deal.get("asin") or "",
        "price": deal["price"],
        "store": deal.get("store") or "",
        "title": (deal.get("title") or "")[:140],
        "t": int(now.timestamp()),
    })
    state["posts"] = posts[-500:]
    skipped = state.get("skipped")
    if isinstance(skipped, dict):
        skipped.pop(deal["id"], None)


# ---------------------------------------------------------------- selección

def _published_too_old(entry: dict, now: datetime, hours: int) -> bool:
    published = parse_pubdate(entry.get("published") or "")
    if not published:
        return False
    return (now - published).total_seconds() > hours * 3600


def build_queue(cfg: dict, state: dict, now: datetime, fetch) -> tuple[list[dict], dict[str, str]]:
    rules = settings(cfg)
    queue: list[dict] = []
    skips: dict[str, str] = {}
    seen_ids: set[str] = set()

    def remember_skip(ident: str, reason: str) -> None:
        if ident and ident not in skips:
            skips[ident] = reason

    for feed in rules["feeds"]:
        try:
            xml = fetch(feed)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"Aviso: no se pudo leer {feed} ({exc})")
            continue
        entries = feeds.parse_rss(xml if isinstance(xml, str) else str(xml))
        print(f"Chollometro {feed}: {len(entries)} chollos")
        for entry in entries:
            thread = thread_id_from_link(entry.get("link") or "")
            ident = f"cm-{thread}" if thread else ""
            if not ident or ident in seen_ids:
                continue
            if recently_skipped(state, ident, now):
                continue
            if not entry.get("price"):
                remember_skip(ident, "sin precio")
                continue
            if float(entry["price"]) + 1e-9 < float(rules["min_price_eur"]):
                remember_skip(ident, "precio bajo")
                continue
            if _published_too_old(entry, now, int(rules["max_deal_age_hours"])):
                remember_skip(ident, "caducado")
                continue
            temperature = int(entry.get("temperature") or 0)
            if temperature and temperature < int(rules["min_temperature"]):
                remember_skip(ident, "temperatura baja")
                continue
            seen_ids.add(ident)
            queue.append({
                "kind": "chollometro",
                "id": ident,
                "url": entry["link"],
                "temperature": temperature,
                "discount": 0.0,
                "entry": entry,
            })

    if rules.get("use_amazon_sources", True):
        max_age = int(rules["max_amazon_age_minutes"]) * 60
        for source in (cfg or {}).get("sources") or []:
            try:
                page = fetch(source)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                print(f"Aviso: no se pudo leer {source} ({exc})")
                continue
            listings = scanner.parse_listing(page if isinstance(page, str) else str(page))
            print(f"Amazon {source}: {len(listings)} productos")
            for item in listings:
                ident = f"az-{item.get('id')}"
                if not item.get("id") or ident in seen_ids or recently_skipped(state, ident, now):
                    continue
                price = item.get("price")
                if not price:
                    continue
                if float(price) + 1e-9 < float(rules["min_price_eur"]):
                    continue
                ts = int(item.get("ts") or 0)
                if not ts or now.timestamp() - ts > max_age:
                    continue
                was = item.get("was")
                if not was or float(was) <= float(price):
                    continue
                discount = (float(was) - float(price)) / float(was) * 100
                if discount + 1e-9 < float(rules["min_discount_pct"]):
                    continue
                if discount > float(rules["max_discount_pct"]):
                    remember_skip(ident, "descuento no fiable")
                    continue
                seen_ids.add(ident)
                queue.append({
                    "kind": "amazon",
                    "id": ident,
                    "url": JIMMY_DETAIL.format(id=item["id"]),
                    "temperature": 0,
                    "discount": discount,
                    "entry": item,
                })

    def rank(item: dict) -> tuple:
        # Primero los calientes de Chollometro, luego el RSS sin temperatura y al final Amazon.
        if item["kind"] == "chollometro" and item["temperature"]:
            group = 2
        elif item["kind"] == "chollometro":
            group = 1
        else:
            group = 0
        return (group, item["temperature"], item["discount"])

    queue.sort(key=rank, reverse=True)
    return queue, skips


def select_deals(cfg: dict, state: dict, now: datetime, *, limit: int, fetch, resolve) -> tuple[list[dict], dict[str, str]]:
    rules = settings(cfg)
    queue, skips = build_queue(cfg, state, now, fetch)
    deals: list[dict] = []
    chosen: set[str] = set()
    opens = 0
    for raw in queue:
        if len(deals) >= limit or opens >= int(rules["max_opens_per_run"]):
            break
        if is_duplicate(state, {"id": raw["id"], "asin": "", "fp": "", "store": ""}, now, int(rules["repost_after_days"])):
            continue
        opens += 1
        try:
            page = fetch(raw["url"])
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"  {raw['id']}: no se pudo abrir la ficha ({exc})")
            continue
        if raw["kind"] == "chollometro":
            deal, reason = consider_chollometro(raw["entry"], page, cfg, resolve)
        else:
            deal, reason = consider_amazon(raw["entry"], page, cfg)
        if not deal:
            if reason:
                skips[raw["id"]] = reason
                print(f"  {raw['id']}: {reason}")
            continue
        if deal["id"] in chosen or is_duplicate(state, deal, now, int(rules["repost_after_days"])):
            skips[deal["id"]] = "duplicado"
            continue
        chosen.add(deal["id"])
        deals.append(deal)
        print(f"  Listo {deal['id']}: {deal['store']} {euro(deal['price'])} · {deal['temperature']}°")
    return deals, skips


# ---------------------------------------------------------------- envío

def membership_can_post(member: dict, chat_id: str) -> tuple[bool, str]:
    status = str((member or {}).get("status") or "")
    if status == "creator":
        return True, f"El bot es propietario de {chat_id} y puede publicar."
    if status == "administrator":
        if member.get("can_post_messages", True):
            return True, f"El bot es administrador de {chat_id} y puede publicar."
        return False, (
            f"El bot es administrador de {chat_id} pero no tiene permiso para publicar mensajes."
        )
    if not status:
        return False, f"No he podido leer el estado del bot en {chat_id}."
    return False, (
        f"El bot no puede publicar en {chat_id}: su estado es «{status}». "
        "Tiene que ser administrador con permiso para publicar."
    )


def check_can_post(tg, chat_id: str) -> tuple[bool, str]:
    try:
        me = tg.call("getMe")
        member = tg.call("getChatMember", {"chat_id": chat_id, "user_id": me["id"]})
    except RuntimeError as exc:
        return False, f"No he podido comprobar con getChatMember si el bot puede publicar en {chat_id}: {exc}"
    ok, message = membership_can_post(member if isinstance(member, dict) else {}, chat_id)
    who = me.get("username") or me.get("id")
    return ok, f"@{who}: {message}"


def http_get(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/rss+xml,application/xml,text/xml,*/*",
        "Accept-Language": "es-ES,es;q=0.9",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def http_bytes(url: str, timeout: int = 20) -> bytes | None:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    if not data or len(data) > 9 * 1024 * 1024:
        return None
    return data


def _write_image(deal_id: str, blob: bytes) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_-]", "", deal_id)[:60] or "chollo"
    path = OUTPUT_DIR / f"{safe}.jpg"
    path.write_bytes(blob)
    return path


def deliver(tg, chat_id, deal: dict, *, dry: bool, prefix: str = "", download=None, cfg: dict | None = None) -> None:
    caption = prefix + build_caption(deal, cfg)
    markup = button_for(deal)
    if dry or tg is None:
        where = "simulación" if dry else "sin bot"
        print(f"  [{where}] {chat_id}: {deal.get('title', '')[:80]} · {euro(float(deal['price']))}")
        print(caption)
        return
    blob = None
    image = deal.get("image") or ""
    if image and download:
        try:
            blob = download(image)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"  Foto no disponible ({exc}); publico solo el texto.")
            blob = None
    if blob:
        path = _write_image(deal["id"], blob)
        tg.send_photo(chat_id, path, caption, {"reply_markup": markup})
        return
    tg.call("sendMessage", {
        "chat_id": chat_id,
        "text": caption,
        "parse_mode": "HTML",
        "reply_markup": markup,
        "link_preview_options": {"is_disabled": True},
    })


def execute(cfg: dict, state: dict, now: datetime, *, dry: bool, test_private: bool, tg,
            fetch, resolve, download, pause: float = 0) -> int:
    rules = settings(cfg)
    persist = not dry and not test_private
    working = state if persist else copy.deepcopy(state)
    if not test_private:
        reason = pace_reason(cfg, working, now)
        if reason:
            print(f"No publico: {reason}")
            return 0
    limit = int(rules["test_private_posts"] if test_private else rules["max_posts_per_run"])
    deals, skips = select_deals(cfg, working, now, limit=max(limit, 0), fetch=fetch, resolve=resolve)
    if persist:
        for deal_id, why in skips.items():
            note_skip(working, deal_id, why, now)
    prefix = ""
    if test_private:
        target = resolve_admin(state)
        prefix = PRIVATE_PREFIX
        if not target:
            print("Prueba privada: no hay admin_chat_id; no envío.")
            return 2 if not dry else 0
        print(f"Prueba privada: {len(deals)} ejemplo(s) para el administrador, no para el canal.")
    else:
        target = rules["chat_id"]
    if not deals:
        print("No hay chollos que publicar en esta pasada.")
        if persist:
            save_state(working)
        return 0
    sent = 0
    for index, deal in enumerate(deals):
        try:
            deliver(tg, target, deal, dry=dry or tg is None, prefix=prefix, download=download, cfg=cfg)
        except RuntimeError as exc:
            print(f"  No se pudo enviar {deal['id']}: {exc}")
            continue
        sent += 1
        if persist:
            remember(working, deal, now)
            # El cupo de esta pasada ya está cubierto; el siguiente ciclo traerá otro.
            if sent >= limit:
                break
        if pause and not dry and index < len(deals) - 1:
            time.sleep(pause)
    kind = "prueba privada" if test_private else ("simulación" if dry else "canal normal")
    print(f"Enviados: {sent} ({kind})")
    if persist:
        save_state(working)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Canal normal @cazachollos_com")
    parser.add_argument("--dry-run", action="store_true", help="No publica nada; solo muestra qué haría")
    parser.add_argument("--test-private", action="store_true",
                        help="Envía 2 o 3 ejemplos solo al chat del administrador, sin guardar memoria")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_json(CONFIG_PATH, {})
    if not isinstance(cfg, dict):
        print("config.json no es un objeto", file=sys.stderr)
        return 2
    state = load_json(STATE_PATH, {"posts": [], "skipped": {}})
    if not isinstance(state, dict):
        state = {"posts": [], "skipped": {}}
    state.setdefault("posts", [])
    state.setdefault("skipped", {})
    rules = settings(cfg)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg = scanner.Telegram(token) if token else None
    if not args.dry_run and not tg:
        print("Falta TELEGRAM_BOT_TOKEN", file=sys.stderr)
        return 2
    if args.test_private and not args.dry_run and not resolve_admin(state):
        print("Prueba privada: falta admin_chat_id en state/generic.json o state/scanner.json.", file=sys.stderr)
        return 2
    if tg:
        ok, message = check_can_post(tg, rules["chat_id"])
        print(message if ok else "NO PUEDE PUBLICAR: " + message)
        if not ok and not args.test_private:
            return 0
    else:
        print(f"Dry-run: no compruebo getChatMember. Canal configurado: {rules['chat_id']}")
    return execute(
        cfg, state, datetime.now(timezone.utc),
        dry=args.dry_run, test_private=args.test_private, tg=tg,
        fetch=http_get, resolve=feeds.resolve_deal_url, download=http_bytes,
        pause=1,
    )


if __name__ == "__main__":
    raise SystemExit(main())
