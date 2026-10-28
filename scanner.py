#!/usr/bin/env python3
"""Escáner automático de Caza Errores.

Cada ejecución:
1. Lee las respuestas privadas del administrador al bot (vinculación y enlaces cortos).
2. Revisa las listas públicas de Jimmyleaks (mínimos de hoy, actualizados y mayor bajada).
3. Para cada candidato nuevo abre su ficha, que da la media real de 90 días y el EAN.
4. Clasifica: ERROR DE PRECIO (>=70 % bajo la media), MÍNIMO HISTÓRICO o GANGA (>=40 %).
5. Publica la tarjeta en el canal con el enlace de afiliado y avisa al administrador.

Solo usa páginas que el robots.txt de Jimmyleaks permite (no /p/, /products ni ?search=).
"""

from __future__ import annotations

import argparse
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

from publisher import OUTPUT_DIR, build_caption, create_price_card, euro

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state" / "scanner.json"
MADRID = ZoneInfo("Europe/Madrid")
USER_AGENT = "CazaErroresBot/1.0 (+https://t.me/caza_errores)"
BASE = "https://jimmyleaks.com"
LINK_RE = re.compile(r"https://(?:link\.amazon|amzn\.to|amzn\.eu|www\.amazon\.es)/\S+", re.I)


# ---------------------------------------------------------------- utilidades

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def parse_eur(text: str | None) -> float | None:
    if not text:
        return None
    clean = re.sub(r"[^\d,\.]", "", text)
    if not clean:
        return None
    if "," in clean:
        clean = clean.replace(".", "").replace(",", ".")
    try:
        return float(clean)
    except ValueError:
        return None


def fetch(url: str, binary: bool = False, timeout: int = 25):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept-Language": "es-ES,es;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    return data if binary else data.decode("utf-8", "replace")


def strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


# ---------------------------------------------------------------- Jimmyleaks

ARTICLE_RE = re.compile(r'<article class="ticket[^"]*">(.*?)</article>', re.S)


def parse_listing(page: str) -> list[dict]:
    items = []
    for block in ARTICLE_RE.findall(page):
        m = re.search(r'href="/es/dp/([A-Za-z0-9]+)/"', block)
        if not m:
            continue
        def grab(pattern: str) -> str | None:
            found = re.search(pattern, block, re.S)
            return strip_tags(found.group(1)) if found else None
        reviews_text = grab(r'class="tk-rating".*?<em>(.*?)</em>') or ""
        reviews = int(re.sub(r"\D", "", reviews_text) or 0)
        ts = re.search(r'data-timestamp="(\d+)"', block)
        items.append({
            "id": m.group(1),
            "title": grab(r'<h2 class="tk-title">(.*?)</h2>') or "",
            "brand": grab(r'class="tk-brand"[^>]*>(.*?)</a>') or "",
            "rating": parse_eur(grab(r'class="tk-rating".*?<span>(.*?)</span>')),
            "reviews": reviews,
            "price": parse_eur(grab(r'<span class="now[^"]*">(.*?)</span>')),
            "was": parse_eur(grab(r'<span class="was">(.*?)</span>')),
            "verdict": grab(r'<span class="verdict[^"]*">(.*?)</span>') or "",
            "ts": int(ts.group(1)) if ts else 0,
        })
    return items


def parse_detail(page: str) -> dict:
    product = {}
    for raw in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if data.get("@type") == "Product":
            product = data
        elif data.get("@type") == "ItemPage":
            product["_modified"] = data.get("dateModified")
    stats = {}
    for label, value in re.findall(r"<dt>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", page, re.S):
        stats[strip_tags(label).lower()] = strip_tags(value)
    offer = product.get("offers") or {}
    images = product.get("image") or []
    brand = product.get("brand") or {}
    low_text = stats.get("mínimo histórico", "")
    rating = re.search(r"</h1>\s*<p[^>]*>(.*?)</p>", page, re.S)
    rating_m = re.search(r"([\d.]+)\s*\(([\d.,]+)\+?\)", strip_tags(rating.group(1))) if rating else None
    return {
        "name": product.get("name", ""),
        "brand": brand.get("name", "") if isinstance(brand, dict) else str(brand),
        "gtin": str(product.get("gtin") or "").strip(),
        "image": images[0] if images else None,
        "price": parse_eur(str(offer.get("price") or "")),
        "in_stock": "InStock" in str(offer.get("availability", "")),
        "avg90": parse_eur(stats.get("media 90 días")),
        "low": parse_eur(low_text.split("€")[0] + "€") if low_text else None,
        "modified": product.get("_modified"),
        "rating": float(rating_m.group(1)) if rating_m else None,
        "reviews": int(re.sub(r"\D", "", rating_m.group(2))) if rating_m else None,
    }


# ---------------------------------------------------------------- Telegram

class Telegram:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, params: dict | None = None) -> dict:
        body = json.dumps(params or {}).encode("utf-8")
        req = urllib.request.Request(self.base + method, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                result = json.loads(exc.read().decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                result = {"ok": False, "description": f"HTTP {exc.code}"}
        if not result.get("ok"):
            raise RuntimeError(f"Telegram {method}: {result.get('description')}")
        return result["result"]

    def send_photo(self, chat_id, image: Path, caption: str, extra: dict | None = None) -> dict:
        boundary = "----caza" + uuid.uuid4().hex
        fields = {"chat_id": str(chat_id), "caption": caption, "parse_mode": "HTML", **(extra or {})}
        parts = []
        for key, value in fields.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, bool):
                value = "true" if value else "false"
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode("utf-8"))
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{image.name}\"\r\n"
            "Content-Type: image/jpeg\r\n\r\n".encode("utf-8") + image.read_bytes() + b"\r\n"
        )
        parts.append(f"--{boundary}--\r\n".encode("ascii"))
        req = urllib.request.Request(self.base + "sendPhoto", data=b"".join(parts),
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            result = json.loads(exc.read().decode("utf-8") or "{}")
        if not result.get("ok"):
            raise RuntimeError(f"Telegram sendPhoto: {result.get('description')}")
        return result["result"]


def caption_data(cand: dict) -> dict:
    return {"category": cand["category"], "title": cand.get("name") or cand.get("title") or "",
            "brand": cand.get("brand") or "", "current": cand["price"], "reference": cand["avg90"],
            "historical_low": bool(cand.get("historical_low")), "rating": cand.get("rating"),
            "reviews": cand.get("reviews")}


def buttons_for(url: str) -> dict:
    return {"inline_keyboard": [[{"text": "🛒 Ver en Amazon", "url": url}]]}


def caption_for(url: str, cap: dict | None = None) -> str:
    if not cap:
        return f'🔗 <b><a href="{html.escape(url, quote=True)}">Ver en Amazon</a></b>'
    return build_caption(url=url, **cap)


# ---------------------------------------------------------------- lógica

def classify(cfg: dict, cand: dict) -> tuple[str | None, str]:
    price, avg = cand["price"], cand["avg90"]
    if not price or not avg or avg <= price:
        return None, "sin media de 90 días por encima del precio"
    disc = (avg - price) / avg * 100
    cand["discount"] = disc
    is_low = bool(cand.get("low")) and price <= cand["low"] + 0.01
    cand["historical_low"] = is_low
    if disc >= cfg["error_min_discount"]:
        if price < cfg["error_min_price_eur"]:
            return None, f"error de precio pero importe demasiado bajo ({price} €)"
        return "ERROR DE PRECIO", f"-{disc:.0f}% bajo la media"
    if disc < cfg["bargain_min_discount"]:
        return None, f"solo -{disc:.0f}% bajo la media"
    if price < cfg["bargain_min_price_eur"]:
        return None, "importe demasiado bajo para ganga"
    if (cand.get("rating") or 0) < cfg["bargain_min_rating"] or cand.get("reviews", 0) < cfg["bargain_min_reviews"]:
        return None, f"valoraciones flojas ({cand.get('rating')} / {cand.get('reviews')})"
    return ("MÍNIMO HISTÓRICO" if is_low else "GANGA"), f"-{disc:.0f}% bajo la media"


def card_title(cand: dict) -> str:
    name = cand.get("name") or cand.get("title") or ""
    brand = cand.get("brand") or ""
    if brand and not name.lower().startswith(brand.lower()):
        name = f"{brand.title()} {name}"
    return re.sub(r"\s+", " ", name).strip(" ,-")[:160]


def affiliate_link(cfg: dict, gtin: str) -> str:
    return f"https://www.amazon.es/s?k={urllib.parse.quote(gtin)}&tag={cfg['affiliate_tag']}"


def handle_updates(tg: Telegram, cfg: dict, state: dict, channel: str, dry: bool) -> None:
    try:
        updates = tg.call("getUpdates", {"offset": state.get("tg_offset", 0), "timeout": 0,
                                          "allowed_updates": ["message"]})
    except RuntimeError as exc:
        print(f"Aviso: no se pudieron leer mensajes del bot ({exc})")
        return
    admin = state.get("admin_chat_id")
    for upd in updates:
        state["tg_offset"] = upd["update_id"] + 1
        msg = upd.get("message") or {}
        chat = msg.get("chat") or {}
        text = (msg.get("text") or "").strip()
        if chat.get("type") != "private":
            continue
        claim = os.environ.get("ADMIN_CLAIM_CODE", "").strip() or cfg.get("admin_claim_code", "")
        if claim and claim in text and not admin:
            state["admin_chat_id"] = admin = chat["id"]
            print(f"Administrador vinculado: chat {chat['id']}")
            if not dry:
                tg.call("sendMessage", {"chat_id": admin, "text":
                        "✅ Listo. A partir de ahora te aviso aquí de cada chollo que publique.\n\n"
                        "Si quieres tu enlace corto en un post, responde a mi aviso con el enlace y lo cambio en el canal."})
            continue
        if chat.get("id") != admin:
            continue
        link = LINK_RE.search(text)
        reply_to = (msg.get("reply_to_message") or {}).get("message_id")
        post = next((p for p in state.get("posts", []) if p.get("alert_id") == reply_to), None)
        if link and post:
            url = link.group(0).rstrip(").,")
            if dry:
                print(f"[prueba] usaría {url} para el post de {post['id']}")
                continue
            if post.get("pending"):
                post["url"] = url
                continue
            try:
                tg.call("editMessageCaption", {"chat_id": channel, "message_id": post["message_id"],
                                               "caption": caption_for(url, post.get("cap")), "parse_mode": "HTML",
                                               "reply_markup": buttons_for(url)})
                post["url"] = url
                tg.call("sendMessage", {"chat_id": admin, "reply_to_message_id": msg["message_id"],
                                        "text": "✅ Enlace cambiado en el canal."})
            except RuntimeError as exc:
                tg.call("sendMessage", {"chat_id": admin, "text": f"No pude cambiar el enlace: {exc}"})
        elif link and not dry:
            tg.call("sendMessage", {"chat_id": admin, "text":
                    "Para cambiar el enlace de un post, responde directamente a mi aviso de ese chollo."})


def scan(cfg: dict, state: dict, now: datetime) -> list[dict]:
    seen = state.setdefault("seen", {})
    listings: dict[str, dict] = {}
    for url in cfg["sources"]:
        try:
            for item in parse_listing(fetch(url)):
                listings.setdefault(item["id"], item)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"Aviso: no se pudo leer {url} ({exc})")
        time.sleep(1)
    print(f"Listados: {len(listings)} productos únicos")

    max_age = cfg["max_listing_age_minutes"] * 60
    fresh = []
    for item in listings.values():
        if not item["price"] or now.timestamp() - item["ts"] > max_age:
            continue
        verdict = item["verdict"].lower()
        if "encima" in verdict or "habitual" in verdict:
            continue
        m = re.search(r"(\d+)% por debajo", verdict)
        if m and int(m.group(1)) < cfg["bargain_min_discount"]:
            continue
        if item["was"] and (item["was"] - item["price"]) / item["was"] * 100 < cfg["bargain_min_discount"]:
            continue
        prev = seen.get(item["id"])
        if prev and abs(prev.get("price", 0) - item["price"]) < 0.01:
            continue
        fresh.append(item)
    fresh.sort(key=lambda i: (i["was"] - i["price"]) / i["was"] if i["was"] else 0, reverse=True)
    print(f"Candidatos nuevos tras el filtro rápido: {len(fresh)}")

    qualified = []
    for item in fresh[: cfg["max_detail_fetches_per_run"]]:
        try:
            detail = parse_detail(fetch(f"{BASE}/es/dp/{item['id']}/"))
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"Aviso: ficha {item['id']} no disponible ({exc})")
            continue
        time.sleep(1)
        cand = {**item, **{k: v for k, v in detail.items() if v not in (None, "")}}
        cand["price"] = detail.get("price") or item["price"]
        category, reason = classify(cfg, cand)
        seen[item["id"]] = {"price": cand["price"], "t": int(now.timestamp()), "result": category or reason}
        if category and not detail["in_stock"]:
            category, reason = None, "sin stock"
        if category and not detail.get("image"):
            category, reason = None, "sin imagen"
        print(f"  {item['id']} · {cand['price']} € · media {cand.get('avg90')} → {category or 'descartado'} ({reason}) · {card_title(cand)[:60]}")
        if category:
            cand["category"] = category
            qualified.append(cand)
    # Limpia memoria antigua (más de 14 días)
    cutoff = now.timestamp() - 14 * 86400
    state["seen"] = {k: v for k, v in seen.items() if v.get("t", 0) >= cutoff}
    return qualified


def allowed_to_post(cfg: dict, state: dict, cand: dict, now: datetime) -> tuple[bool, str]:
    posts = state.get("posts", [])
    for p in posts:
        same = p["id"] == cand["id"] or (cand.get("gtin") and p.get("gtin") == cand.get("gtin"))
        if same and now.timestamp() - p["t"] < cfg["repost_after_days"] * 86400:
            if cand["price"] > p["price"] * (1 - cfg["repost_min_extra_drop_pct"] / 100):
                return False, "ya publicado recientemente"
    if cand["category"] == "ERROR DE PRECIO":
        return True, ""
    local = now.astimezone(MADRID)
    start, end = cfg["bargain_quiet_hours"]
    if start <= local.hour < end:
        return False, "horario nocturno: las gangas esperan al día"
    today = [p for p in posts if p["category"] != "ERROR DE PRECIO"
             and datetime.fromtimestamp(p["t"], MADRID).date() == local.date()]
    if len(today) >= cfg["max_bargains_per_day"]:
        return False, "cupo diario de gangas cubierto"
    if today and now.timestamp() - max(p["t"] for p in today) < cfg["min_minutes_between_bargains"] * 60:
        return False, "esperando separación entre gangas"
    return True, ""


def publish(tg: Telegram | None, cfg: dict, state: dict, cand: dict, channel: str, dry: bool,
            link_override: str | None = None) -> bool:
    img_dir = OUTPUT_DIR / "src"
    img_dir.mkdir(parents=True, exist_ok=True)
    src = img_dir / f"{cand['id']}.jpg"
    try:
        src.write_bytes(fetch(cand["image"], binary=True))
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"  No se pudo descargar la foto de {cand['id']} ({exc})")
        return False
    offer = {
        "id": f"scan-{cand['id']}",
        "title": card_title(cand),
        "image_path": src,
        "category": cand["category"],
        "current": cand["price"],
        "reference": cand["avg90"],
        "days": 90,
    }
    card = create_price_card(offer)
    gtin = cand.get("gtin") if re.fullmatch(r"\d{8,14}", cand.get("gtin") or "") else None
    url = link_override or (affiliate_link(cfg, gtin) if gtin else None)
    summary = (f"{cand['category']} · {card_title(cand)[:90]}\n"
               f"{euro(cand['price'])} (media 90 días {euro(cand['avg90'])}, -{cand['discount']:.0f}%)")
    if dry:
        print(f"  [prueba] publicaría: {summary.replace(chr(10), ' · ')} · enlace {url or 'pendiente de tu enlace corto'}")
        return True
    admin = state.get("admin_chat_id")
    record = {"id": cand["id"], "gtin": gtin, "price": cand["price"], "category": cand["category"],
              "t": int(now_utc().timestamp()), "title": card_title(cand)[:120], "cap": caption_data(cand)}
    if url:
        silent = cand["category"] != "ERROR DE PRECIO" and now_utc().astimezone(MADRID).hour < 9
        msg = tg.send_photo(channel, card, caption_for(url, caption_data(cand)),
                            {"disable_notification": silent, "reply_markup": buttons_for(url)})
        record.update(message_id=msg["message_id"], url=url)
        print(f"  Publicado en el canal (mensaje {msg['message_id']}): {summary.splitlines()[0]}")
    elif not admin:
        print("  Sin EAN ni administrador vinculado: no se puede publicar.")
        return False
    if admin:
        icon = "🚨" if cand["category"] == "ERROR DE PRECIO" else "🟢"
        if url:
            text = (f"{icon} Publicado {summary}\n\nSi quieres tu enlace corto en este post, "
                    "respóndeme a este mensaje con él y lo cambio.")
        else:
            text = (f"{icon} {summary}\n\nNo tiene EAN, así que no lo he publicado. "
                    "Respóndeme con tu enlace corto y saldrá en el canal.")
        buttons = [[{"text": "Ver histórico", "url": f"{BASE}/es/dp/{cand['id']}/"}]]
        if url:
            buttons[0].insert(0, {"text": "Abrir en Amazon", "url": url})
        alert = tg.send_photo(admin, card, html.escape(text), {"reply_markup": {"inline_keyboard": buttons},
                                                               "disable_notification": cand["category"] != "ERROR DE PRECIO"})
        record["alert_id"] = alert["message_id"]
    if not url:
        record["pending"] = True
        record["card_data"] = {"title": offer["title"], "category": offer["category"],
                               "current": offer["current"], "reference": offer["reference"],
                               "image": cand["image"]}
    state.setdefault("posts", []).append(record)
    state["posts"] = state["posts"][-300:]
    return True


def publish_pending_from_reply(tg: Telegram, state: dict, channel: str) -> None:
    """Publica los chollos sin EAN cuando el administrador responde con su enlace."""
    for post in state.get("posts", []):
        data = post.get("card_data")
        if not (post.get("pending") and post.get("url") and data):
            continue
        try:
            src = OUTPUT_DIR / "src" / f"{post['id']}.jpg"
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_bytes(fetch(data["image"], binary=True))
            card = create_price_card({"id": f"scan-{post['id']}", "title": data["title"], "image_path": src,
                                      "category": data["category"], "current": data["current"],
                                      "reference": data["reference"], "days": 90})
            msg = tg.send_photo(channel, card, caption_for(post["url"], post.get("cap")),
                                {"reply_markup": buttons_for(post["url"])})
        except (RuntimeError, urllib.error.URLError, TimeoutError) as exc:
            print(f"No se pudo publicar el pendiente {post['id']}: {exc}")
            continue
        post["message_id"] = msg["message_id"]
        post["t"] = int(now_utc().timestamp())
        post.pop("pending", None)
        post.pop("card_data", None)
        print(f"Publicado el pendiente {post['id']} con tu enlace corto (mensaje {msg['message_id']})")
        if state.get("admin_chat_id"):
            tg.call("sendMessage", {"chat_id": state["admin_chat_id"], "text": "✅ Publicado en el canal con tu enlace."})


def publish_manual(tg, cfg: dict, state: dict, channel: str, jl_id: str, link: str, dry: bool) -> int:
    """Publica un producto concreto con el enlace corto de SiteStripe sacado a mano."""
    if not re.fullmatch(r"[A-Za-z0-9]{4,20}", jl_id) or not LINK_RE.fullmatch(link):
        print("ID o enlace no válidos", file=sys.stderr)
        return 2
    detail = parse_detail(fetch(f"{BASE}/es/dp/{jl_id}/"))
    cand = {"id": jl_id, **detail}
    category, reason = classify({**cfg, "bargain_min_rating": 0, "bargain_min_reviews": 0}, cand)
    print(f"{jl_id}: {detail.get('price')} € · media {detail.get('avg90')} → {category or 'descartado'} ({reason})")
    if not category or not detail["in_stock"] or not detail.get("image"):
        print("No cumple para publicarse (descuento, stock o imagen).", file=sys.stderr)
        return 1
    cand["category"] = category
    ok = publish(tg, cfg, state, cand, channel, dry, link_override=link)
    if ok and not dry:
        save_state(state)
    return 0 if ok else 1


def edit_manual(tg, cfg: dict, state: dict, channel: str, jl_id: str, link: str, message_id: int) -> int:
    """Rehace el texto de un post publicado con el formato actual."""
    if not re.fullmatch(r"[A-Za-z0-9]{4,20}", jl_id) or not LINK_RE.fullmatch(link):
        print("ID o enlace no válidos", file=sys.stderr)
        return 2
    detail = parse_detail(fetch(f"{BASE}/es/dp/{jl_id}/"))
    cand = {"id": jl_id, **detail}
    category, reason = classify({**cfg, "bargain_min_rating": 0, "bargain_min_reviews": 0,
                                 "bargain_min_price_eur": 0}, cand)
    cand["category"] = category or "GANGA"
    cap = caption_data(cand)
    try:
        tg.call("editMessageCaption", {"chat_id": channel, "message_id": message_id,
                                       "caption": caption_for(link, cap), "parse_mode": "HTML",
                                       "reply_markup": buttons_for(link)})
    except RuntimeError as exc:
        if "not modified" not in str(exc):
            raise
        print(f"El post {message_id} ya estaba al día")
    for post in state.get("posts", []):
        if post.get("message_id") == message_id:
            post.update(cap=cap, url=link)
    save_state(state)
    print(f"Texto del post {message_id} actualizado ({cand['category']}, {reason})")
    return 0


def custom_post(tg, state: dict, channel: str, spec: dict) -> int:
    """Crea o rehace un post con datos dados a mano (foto, precios, enlace).

    Si spec trae message_id, sustituye imagen, texto y botón de ese post."""
    for key in ("title", "current", "reference", "category", "image", "link"):
        if not spec.get(key):
            print(f"Falta {key}", file=sys.stderr)
            return 2
    if not LINK_RE.fullmatch(spec["link"]):
        print("Enlace no válido", file=sys.stderr)
        return 2
    pid = re.sub(r"[^A-Za-z0-9]", "", spec.get("id") or "custom")[:30] or "custom"
    src = OUTPUT_DIR / "src" / f"{pid}.jpg"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(fetch(spec["image"], binary=True))
    offer = {"id": f"custom-{pid}", "title": card_title({"name": spec["title"], "brand": spec.get("brand", "")}),
             "image_path": src, "category": spec["category"], "current": float(spec["current"]),
             "reference": float(spec["reference"]), "days": 90, "ref_label": spec.get("ref_label"),
             "sold_out": bool(spec.get("sold_out"))}
    if spec.get("resale_price"):
        rp = float(spec["resale_price"])
        offer["resale"] = {"price": rp, "count": spec.get("resale_count"),
                           "roi": (rp - offer["current"]) / offer["current"] * 100}
    card = create_price_card(offer)
    cap = {"category": spec["category"], "title": spec["title"], "brand": spec.get("brand", ""),
           "current": float(spec["current"]), "reference": float(spec["reference"]),
           "historical_low": bool(spec.get("historical_low")), "rating": spec.get("rating"),
           "reviews": spec.get("reviews")}
    if spec.get("ref_text"):
        cap["ref_text"] = spec["ref_text"]
    if spec.get("sold_out"):
        cap["sold_out"] = True
    if spec.get("resale_price"):
        cap["resale_price"] = float(spec["resale_price"])
        cap["resale_count"] = spec.get("resale_count")
    caption = caption_for(spec["link"], cap)
    if spec.get("message_id"):
        mid = int(spec["message_id"])
        boundary = "----caza" + uuid.uuid4().hex
        media = {"type": "photo", "media": "attach://photo", "caption": caption, "parse_mode": "HTML"}
        fields = {"chat_id": channel, "message_id": str(mid), "media": json.dumps(media, ensure_ascii=False),
                  "reply_markup": json.dumps(buttons_for(spec["link"]))}
        parts = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8")
                 for k, v in fields.items()]
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"card.jpg\"\r\n"
                     "Content-Type: image/jpeg\r\n\r\n".encode("utf-8") + card.read_bytes() + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("ascii"))
        req = urllib.request.Request(tg.base + "editMessageMedia", data=b"".join(parts),
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            result = json.loads(exc.read().decode("utf-8") or "{}")
        if not result.get("ok"):
            print(f"Telegram no dejó editar el post {mid}: {result.get('description')}", file=sys.stderr)
            return 1
        print(f"Post {mid} rehecho con la tarjeta nueva")
    else:
        msg = tg.send_photo(channel, card, caption, {"reply_markup": buttons_for(spec["link"])})
        mid = msg["message_id"]
        print(f"Publicado como mensaje {mid}")
    state.setdefault("posts", []).append({"id": pid, "message_id": mid, "url": spec["link"], "cap": cap,
                                          "price": float(spec["current"]), "category": spec["category"],
                                          "t": int(now_utc().timestamp()), "gtin": None})
    save_state(state)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="No publica nada; solo muestra qué haría")
    parser.add_argument("--ignore-limits", action="store_true", help="Ignora cupos y horario (pruebas)")
    parser.add_argument("--manual-id", default="", help="ID de Jimmyleaks a publicar a mano")
    parser.add_argument("--manual-link", default="", help="Enlace corto de afiliado para --manual-id")
    parser.add_argument("--edit-message", type=int, default=0, help="Reescribe el texto de un post ya publicado")
    parser.add_argument("--custom", default="", help="JSON con un post hecho a mano (ver custom_post)")
    args = parser.parse_args()

    cfg = load_json(CONFIG_PATH, {})
    state = load_json(STATE_PATH, {"seen": {}, "posts": [], "tg_offset": 0})
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    channel = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    tg = Telegram(token) if token else None
    if not tg and not args.dry_run:
        print("Falta TELEGRAM_BOT_TOKEN", file=sys.stderr)
        return 2

    if tg:
        try:
            me = tg.call("getMe")
            print(f"Bot: @{me['username']}" + ("" if state.get("admin_chat_id") else " · administrador sin vincular"))
        except RuntimeError as exc:
            print(f"Aviso: {exc}")
        handle_updates(tg, cfg, state, channel, args.dry_run)
        if not args.dry_run:
            publish_pending_from_reply(tg, state, channel)

    now = now_utc()
    if args.custom:
        return custom_post(tg, state, channel, json.loads(args.custom))
    if args.manual_id and args.edit_message:
        return edit_manual(tg, cfg, state, channel, args.manual_id.strip(), args.manual_link.strip(), args.edit_message)
    if args.manual_id:
        return publish_manual(tg, cfg, state, channel, args.manual_id.strip(), args.manual_link.strip(), args.dry_run)
    candidates = scan(cfg, state, now)
    order = {"ERROR DE PRECIO": 0, "MÍNIMO HISTÓRICO": 1, "GANGA": 2}
    candidates.sort(key=lambda c: (order[c["category"]], -c["discount"]))
    posted = 0
    for cand in candidates:
        if posted >= cfg["max_posts_per_run"] and cand["category"] != "ERROR DE PRECIO":
            break
        ok, why = (True, "") if args.ignore_limits else allowed_to_post(cfg, state, cand, now)
        if not ok:
            print(f"  {cand['id']}: no se publica ({why})")
            if "recientemente" not in why:
                # Aplazado por horario o cupo: se vuelve a evaluar en la próxima pasada.
                state.get("seen", {}).pop(cand["id"], None)
            continue
        try:
            if publish(tg, cfg, state, cand, channel, args.dry_run):
                posted += 1
                time.sleep(2)
        except RuntimeError as exc:
            print(f"  Error publicando {cand['id']}: {exc}")
    print(f"Publicados en esta ejecución: {posted}")
    if not args.dry_run:
        save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
