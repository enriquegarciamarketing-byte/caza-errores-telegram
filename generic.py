#!/usr/bin/env python3
"""Canal normal @cazachollos_com.

Chollos variados de Chollometro y de las listas de Amazon, sin tarjeta de reventa.
No comparte memoria con el escáner premium (state/scanner.json).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import affiliate
import feeds
import premium
from publisher import build_deal_caption, create_deal_card
import scanner

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state" / "generic.json"
PREMIUM_STATE = ROOT / "state" / "scanner.json"
MADRID = scanner.MADRID
OUTPUT = scanner.OUTPUT_DIR / "generic"


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def channel_rules(cfg: dict) -> dict:
    rules = (cfg or {}).get("generic") or {}
    if not isinstance(rules, dict):
        return {}
    return rules


def save_state(state: dict) -> None:
    posts = state.get("posts") or []
    if len(posts) > 4000:
        posts = sorted(posts, key=lambda item: item.get("t") or 0)[-4000:]
        state["posts"] = posts
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def admin_chat_id(state: dict) -> int | None:
    if state.get("admin_chat_id"):
        return state["admin_chat_id"]
    premium_state = load_json(PREMIUM_STATE, {})
    admin = premium_state.get("admin_chat_id")
    return int(admin) if admin else None


def posting_rights(member: dict | None) -> bool:
    status = (member or {}).get("status")
    if status == "creator":
        return True
    if status == "administrator":
        return bool(member.get("can_post_messages", True))
    return False


def check_channel(tg, chat: str) -> bool:
    """True si el bot puede publicar. Un fallo de permiso se explica y no rompe la pasada."""
    try:
        me = tg.call("getMe")
        member = tg.call("getChatMember", {"chat_id": chat, "user_id": me["id"]})
    except RuntimeError as exc:
        print(f"AVISO: no he podido comprobar si el bot publica en {chat} ({exc}). "
              f"Tiene que ser administrador del canal.")
        return False
    if posting_rights(member):
        print(f"El bot @{me.get('username')} puede publicar en {chat}.")
        return True
    print(f"AVISO: el bot @{me.get('username')} NO puede publicar en {chat} "
          f"(estado: {member.get('status')}). Añádelo como administrador con permiso para publicar. "
          f"Esta pasada no envía nada al canal.")
    return False


def in_quiet_hours(now: datetime, rules: dict) -> bool:
    local = now.astimezone(MADRID)
    start, end = rules.get("quiet_hours") or [1, 8]
    return start <= local.hour < end


def posts_today(posts: list[dict], now: datetime) -> list[dict]:
    day = now.astimezone(MADRID).date()
    found = []
    for post in posts:
        stamp = post.get("t") or 0
        if datetime.fromtimestamp(stamp, timezone.utc).astimezone(MADRID).date() == day:
            found.append(post)
    return found


def posts_last_hour(posts: list[dict], now: datetime) -> list[dict]:
    cutoff = now.timestamp() - 3600
    # Un envío manual no consume el cupo de la hora.
    return [post for post in posts if not post.get("manual") and (post.get("t") or 0) >= cutoff]


def quota_reason(state: dict, now: datetime, rules: dict, already: int = 0) -> str:
    if in_quiet_hours(now, rules):
        return "horario de silencio (01:00–08:00 Madrid)"
    posts = state.get("posts") or []
    if len(posts_last_hour(posts, now)) + already >= int(rules.get("max_per_hour", 4)):
        return "cupo de la hora cubierto"
    if len(posts_today(posts, now)) + already >= int(rules.get("max_per_day", 40)):
        return "cupo del día cubierto"
    return ""


def known_keys(state: dict) -> set[str]:
    keys = set()
    for post in state.get("posts") or []:
        if post.get("id"):
            keys.add(str(post["id"]))
        if post.get("key"):
            keys.add(str(post["key"]))
    return keys


def deal_key(title: str, store: str) -> str:
    return premium.product_key({"name": title, "title": title, "brand": store})


def reliable_previous(current: float, previous: float | None, rules: dict) -> float | None:
    if previous is None or previous <= current * 1.02:
        return None
    discount = (previous - current) / previous * 100
    if discount + 1e-9 > float(rules.get("max_discount_pct", 95)):
        return None
    return previous


def too_old(published: str, now: datetime, rules: dict) -> bool:
    if not published:
        return False
    try:
        stamp = parsedate_to_datetime(published)
    except (TypeError, ValueError, IndexError):
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    age = now - stamp
    return age.total_seconds() > float(rules.get("max_age_hours", 36)) * 3600


def reject_feed(entry: dict, rules: dict, now: datetime, seen: set[str]) -> str:
    title = entry.get("title") or ""
    if re.search(r"\b(expirad[oa]|caducad[oa])\b", title, re.I):
        return "caducado"
    if too_old(entry.get("published") or "", now, rules):
        return "demasiado antiguo"
    price = entry.get("price")
    if not price or price <= 0:
        return "sin precio"
    if price + 1e-9 < float(rules.get("min_price_eur", 1)):
        return "precio demasiado bajo"
    if int(entry.get("temperature") or 0) < int(rules.get("min_temperature", 80)):
        return "temperatura baja"
    ident = thread_id(entry.get("link") or "")
    key = deal_key(title, entry.get("merchant") or "")
    if (ident and ident in seen) or key in seen:
        return "duplicado"
    return ""


def thread_id(link: str) -> str:
    match = re.search(r"(\d{5,})/?$", link or "")
    return f"cm-{match.group(1)}" if match else ""


def discount_of(current: float, previous: float | None) -> float:
    if not previous or previous <= current:
        return 0.0
    return (previous - current) / previous * 100


def gather(cfg: dict, state: dict, now: datetime, fetch=None) -> list[dict]:
    """Chollometro primero (por temperatura) y, si queda sitio en la lectura, listas de Amazon."""
    rules = channel_rules(cfg)
    fetch = fetch or _fetch
    seen = known_keys(state)
    found: list[dict] = []
    entries: list[dict] = []
    for feed in rules.get("feeds") or []:
        try:
            _status, raw = fetch(feed)
            parsed = feeds.parse_rss(raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            print(f"  Chollometro {feed}: {exc}")
            continue
        print(f"  Chollometro {feed}: {len(parsed)} chollos")
        entries.extend(parsed)
    entries.sort(key=lambda item: int(item.get("temperature") or 0), reverse=True)
    opened = 0
    limit_pages = int(rules.get("max_pages_per_run", 8))
    for entry in entries:
        why = reject_feed(entry, rules, now, seen)
        if why:
            continue
        if opened >= limit_pages:
            break
        opened += 1
        try:
            _status, raw = fetch(entry["link"])
            page = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            print(f"  Ficha Chollometro: {exc}")
            continue
        current = float(entry["price"])
        signals = feeds.deal_signals(page, current=current)
        if signals.get("expired"):
            print(f"  Caducado: {entry['title'][:70]}")
            continue
        raw_url = feeds.resolve_deal_url(page)
        asin = affiliate.extract_asin(raw_url or "")
        url = affiliate.clean_store_url(raw_url, cfg, expected_asin=asin)
        if not url:
            print(f"  Enlace no publicable: {entry['title'][:70]}")
            continue
        _store_id, store = premium.store_of(url)
        previous = reliable_previous(current, signals.get("previous"), rules)
        minimum = float(rules.get("min_discount_pct", 20))
        if previous is None or discount_of(current, previous) + 1e-9 < minimum:
            print(f"  Sin PVP fiable o bajada menor del {minimum:.0f} %: {entry['title'][:70]}")
            continue
        temperature = max(int(entry.get("temperature") or 0), int(signals.get("temperature") or 0))
        ident = thread_id(entry.get("link") or "") or deal_key(entry["title"], store)
        found.append({
            "id": ident,
            "key": deal_key(entry["title"], store),
            "title": entry["title"],
            "price": current,
            "previous": previous,
            "temperature": temperature,
            "image": entry.get("image") or "",
            "images": _merchant_images(url, fetch),
            "url": url,
            "store": store,
            "origin": "chollometro",
        })
        seen.add(ident)
        seen.add(found[-1]["key"])
    found.extend(amazon_candidates(cfg, rules, now, seen, fetch))
    found.sort(key=lambda item: (int(item.get("temperature") or 0), discount_of(item["price"], item.get("previous"))),
               reverse=True)
    return found


def amazon_candidates(cfg: dict, rules: dict, now: datetime, seen: set[str], fetch) -> list[dict]:
    tagged = (cfg or {}).get("affiliate_tag") or ""
    minimum = float(rules.get("min_discount_pct", 20))
    ranked = []
    for url in rules.get("amazon_sources") or []:
        origin = "minimos" if "minimos" in url else "amazon"
        try:
            _status, raw = fetch(url)
            page = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            listings = scanner.parse_listing(page)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            print(f"  Amazon {url}: {exc}")
            continue
        print(f"  Amazon {url}: {len(listings)} productos")
        for item in listings:
            price = item.get("price")
            if not price or price <= 0:
                continue
            if price + 1e-9 < float(rules.get("min_price_eur", 1)):
                continue
            if item.get("ts") and now.timestamp() - int(item["ts"]) > float(rules.get("max_age_hours", 36)) * 3600:
                continue
            previous = reliable_previous(float(price), item.get("was"), rules)
            if previous is None:
                continue
            if discount_of(float(price), previous) + 1e-9 < minimum:
                continue
            ident = f"jl-{item['id']}"
            if ident in seen or deal_key(item.get("title") or "", "Amazon") in seen:
                continue
            ranked.append((discount_of(float(price), previous), item, previous, ident, origin))
    ranked.sort(key=lambda row: row[0], reverse=True)
    found = []
    for _discount, item, previous, ident, origin in ranked[: int(rules.get("max_amazon_details", 6))]:
        try:
            _status, raw = fetch(f"{scanner.BASE}/es/dp/{item['id']}/")
            page = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
            detail = scanner.parse_detail(page)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            print(f"  Ficha Amazon {item['id']}: {exc}")
            continue
        price = float(detail.get("price") or item["price"])
        checked = reliable_previous(price, previous, rules)
        if checked is None or discount_of(price, checked) + 1e-9 < minimum:
            print(f"  Sin PVP fiable en la ficha: {item.get('title', '')[:70]}")
            continue
        gtin = detail.get("gtin") if re.fullmatch(r"\d{8,14}", detail.get("gtin") or "") else None
        link = affiliate.fallback_link(tagged, gtin=gtin)
        link = affiliate.clean_store_url(link, cfg)
        if not link:
            print(f"  Sin enlace de Amazon etiquetado: {item.get('title', '')[:70]}")
            continue
        # El canal normal enlaza siempre /dp/ASIN con la etiqueta propia, sin otros parámetros.
        asin = item.get("id") or ""
        if re.fullmatch(r"[A-Z0-9]{10}", str(asin).upper()):
            link = amazon_deal_url(str(asin), cfg) or link
        title = detail.get("name") or item.get("title") or ""
        images = feeds.merchant_image_urls(page)
        found.append({
            "id": ident,
            "key": deal_key(title, "Amazon"),
            "title": title,
            "price": price,
            "previous": checked,
            "temperature": 0,
            "image": detail.get("image") or "",
            "images": images,
            "url": link,
            "store": "Amazon",
            "origin": origin,
        })
        seen.add(ident)
    return found


def amazon_deal_url(asin: str, cfg: dict) -> str | None:
    """https://www.amazon.es/dp/<ASIN>?tag=… sin más parámetros ni etiquetas ajenas."""
    code = (asin or "").upper()
    tag = ((cfg or {}).get("affiliate_tag") or "").strip()
    if not tag or not re.fullmatch(r"[A-Z0-9]{10}", code):
        return None
    return affiliate.fallback_link(tag, asin=code)


def _merchant_images(url: str, fetch) -> list[str]:
    try:
        _status, raw = fetch(url)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"  Foto de la tienda: {exc}")
        return []
    page = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    return feeds.merchant_image_urls(page)


def _fetch(url: str):
    return feeds._get(url)


def choose(candidates: list[dict], state: dict, now: datetime, rules: dict, limit: int,
           ignore_quota: bool) -> list[dict]:
    chosen = []
    for cand in candidates:
        if len(chosen) >= limit:
            break
        if not ignore_quota:
            why = quota_reason(state, now, rules, already=len(chosen))
            if why:
                print(f"  Paro: {why}")
                break
        chosen.append(cand)
    return chosen


def deliver(tg, chat, cand: dict, dry: bool) -> int | None:
    """Publica un chollo. None si no hay foto válida. 0 en dry-run. El id del mensaje si sale."""
    image = _image(cand)
    if image is None:
        print(f"  Sin foto válida, salto al siguiente: {cand['title'][:70]}")
        return None
    origin = cand.get("origin") or ""
    caption = build_deal_caption(url=cand["url"], title=cand["title"], current=cand["price"],
                                 store=cand["store"], previous=cand.get("previous"), origin=origin)
    buttons = scanner.buttons_for(cand["url"])
    if dry or tg is None:
        print(f"  [prueba] {cand['store']} · {cand['price']} € · {cand['title'][:80]}")
        print(caption)
        return 0
    try:
        card = create_deal_card({
            "id": cand["id"],
            "title": cand["title"],
            "current": cand["price"],
            "previous": cand.get("previous"),
            "image_path": image,
            "store": cand.get("store") or "",
            "origin": origin,
        })
    except (OSError, ValueError) as exc:
        print(f"  No pude crear la tarjeta de {cand.get('id')} ({exc})")
        return None
    message = tg.send_photo(chat, card, caption, {"reply_markup": buttons})
    print(f"  Publicado en {chat} (mensaje {message['message_id']}): {cand['title'][:80]}")
    return int(message["message_id"])


def _image(cand: dict) -> Path | None:
    import photos
    urls: list[str] = []
    for item in cand.get("images") or []:
        if item and item not in urls:
            urls.append(item)
    extra = cand.get("image") or ""
    if extra.startswith("http") and extra not in urls:
        urls.append(extra)
    raw = photos.fetch_clean(urls) if urls else None
    if not raw:
        return None
    OUTPUT.mkdir(parents=True, exist_ok=True)
    path = OUTPUT / f"{re.sub(r'[^A-Za-z0-9_-]', '', cand['id'])[:40] or 'chollo'}.jpg"
    path.write_bytes(raw)
    return path


def manual_candidate(url: str, cfg: dict, price_raw: str, pvp_raw: str, fetch) -> dict | None:
    """Un solo chollo a partir de una URL. Los precios escritos a mano mandan sobre la página."""
    rules = channel_rules(cfg)
    manual_price = feeds.parse_price(price_raw) if (price_raw or "").strip() else None
    manual_pvp = feeds.parse_price(pvp_raw) if (pvp_raw or "").strip() else None
    fetched = ""
    try:
        _status, raw = fetch(url)
        fetched = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"  No he podido abrir la ficha ({exc}). Sigo con los precios manuales si vienen.")
    asin = affiliate.extract_asin(url) or affiliate.extract_asin(fetched)
    if asin or affiliate.is_amazon_es(url):
        if not asin:
            print("  Amazon sin ASIN: no publico.")
            return None
        store_url = amazon_deal_url(asin, cfg)
        if not store_url:
            print("  Falta la etiqueta de afiliado: no publico el enlace de Amazon.")
            return None
        box = feeds.amazon_buybox(fetched) if fetched else {}
        title = (box.get("title") or "").strip() or f"Amazon {asin}"
        current = box.get("price")
        previous = box.get("previous")
        images = list(box.get("images") or [])
        store = "Amazon"
    else:
        store_url = affiliate.clean_store_url(url, cfg)
        if not store_url:
            print("  Enlace no publicable.")
            return None
        _store_id, store = premium.store_of(store_url)
        titled = re.search(r"<title>(.*?)</title>", fetched or "", re.S)
        title = feeds.html_unescape(re.sub(r"\s+", " ", titled.group(1))).strip() if titled else store
        current = None
        previous = None
        images = feeds.merchant_image_urls(fetched)
    if manual_price is not None:
        current = manual_price
    if manual_pvp is not None:
        previous = manual_pvp
    if not title:
        print("  Sin título.")
        return None
    if not current or current <= 0:
        print("  Sin precio actual. Pasa manual_price.")
        return None
    previous = reliable_previous(float(current), previous, rules)
    minimum = float(rules.get("min_discount_pct", 20))
    if previous is None or discount_of(float(current), previous) + 1e-9 < minimum:
        print(f"  Modo manual: sin PVP fiable o bajada menor del {minimum:.0f} %. No publico.")
        return None
    ident = f"manual-{asin or deal_key(title, store)[:24]}"
    return {
        "id": ident,
        "key": ident,
        "title": title,
        "price": float(current),
        "previous": previous,
        "temperature": 0,
        "image": "",
        "images": images,
        "url": store_url,
        "store": store,
        "origin": "manual",
    }


def run(args, cfg: dict, state: dict, now: datetime, tg=None, fetch=None) -> int:
    rules = channel_rules(cfg)
    if not rules.get("chat_id"):
        print("Falta generic.chat_id en config.json", file=sys.stderr)
        return 2
    chat = rules["chat_id"]
    can_post = True
    if tg is not None:
        can_post = check_channel(tg, chat)
    manual_url = (getattr(args, "manual_url", "") or "").strip()
    if args.test_private:
        admin = admin_chat_id(state)
        if not admin:
            print("Prueba privada: falta admin_chat_id en state/generic.json o state/scanner.json.")
            return 0
        target = admin
        print(f"Prueba privada: envío solo al administrador {admin}, no a {chat}.")
    else:
        target = chat
        if not can_post and not args.dry_run:
            return 0
        if not manual_url and in_quiet_hours(now, rules):
            print("Canal normal en silencio (01:00–08:00 Madrid). No publico.")
            return 0
    fetch = fetch or _fetch
    if manual_url:
        print(f"Modo manual: {manual_url}")
        cand = manual_candidate(
            manual_url, cfg,
            getattr(args, "manual_price", "") or "",
            getattr(args, "manual_pvp", "") or "",
            fetch,
        )
        candidates = [cand] if cand else []
        limit = 1
        ignore_quota = True
    else:
        candidates = gather(cfg, state, now, fetch=fetch)
        limit = int(rules.get("test_private_posts", 3) if args.test_private else rules.get("max_per_run", 1))
        ignore_quota = bool(args.test_private)
    posted = 0
    for cand in candidates:
        if posted >= limit:
            break
        if not ignore_quota:
            why = quota_reason(state, now, rules, already=posted)
            if why:
                print(f"  Paro: {why}")
                break
        if not args.test_private and not args.dry_run and not can_post:
            break
        message_id = deliver(tg, target, cand, args.dry_run or tg is None)
        if message_id is None:
            continue
        posted += 1
        if args.test_private or args.dry_run or not message_id:
            continue
        state.setdefault("posts", []).append({
            "id": cand["id"], "key": cand["key"], "price": cand["price"],
            "t": int(now.timestamp()), "url": cand["url"], "message_id": message_id,
            "title": cand["title"][:140], "store": cand["store"],
            "manual": bool(manual_url),
        })
        time.sleep(2)
    if posted == 0:
        if manual_url:
            print("Modo manual: no se ha publicado.")
        else:
            print("Canal normal: nada nuevo que publicar.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Canal normal @cazachollos_com")
    parser.add_argument("--dry-run", action="store_true", help="No publica; muestra el texto")
    parser.add_argument("--test-private", action="store_true",
                        help="Envía 2 o 3 ejemplos solo al administrador y no guarda memoria")
    parser.add_argument("--manual-url", default="",
                        help="Publica solo esta URL y no escanea fuentes. Ignora silencio y cupo horario.")
    parser.add_argument("--manual-price", default="",
                        help="Precio actual. Si viene, manda sobre el extraído de la página.")
    parser.add_argument("--manual-pvp", default="",
                        help="PVP o precio recomendado. Si viene, manda sobre el extraído de la página.")
    args = parser.parse_args()
    cfg = load_json(CONFIG_PATH, {})
    state = load_json(STATE_PATH, {"posts": []})
    token = __import__("os").environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg = scanner.Telegram(token) if token else None
    if not tg and not args.dry_run:
        print("Falta TELEGRAM_BOT_TOKEN", file=sys.stderr)
        return 2
    now = datetime.now(timezone.utc)
    code = run(args, cfg, state, now, tg=tg)
    if code == 0 and not args.dry_run and not args.test_private:
        save_state(state)
    return code


if __name__ == "__main__":
    sys.exit(main())
