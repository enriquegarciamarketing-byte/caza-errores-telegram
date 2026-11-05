#!/usr/bin/env python3
"""Canal @cazachollos_com con AliExpress (GitHub Actions), usando la API oficial de afiliados.

Reglas que no se saltan:
- Datos y enlaces SOLO de la API oficial de afiliados (nada de scraping) y con tu ID de rastreo.
- Descuento honesto: frente al precio más bajo que el propio bot ha visto en los 30 días anteriores,
  y solo si lo ha visto suficientes días (min_history_days). Nunca el "precio original" de la ficha,
  que en AliExpress suele estar inflado. Sin historial suficiente, como mucho sale como TOP VENTAS,
  sin precio tachado ni porcentaje.
- Justo antes de publicar se relee la ficha en vivo: si el precio ha cambiado, no sale.
- Post doble: la foto del producto tal cual la da AliExpress (sin recortar ni retocar) y la tarjeta
  roja de Caza Chollos, que no lleva ni logo ni gráficos de AliExpress.
- Cada post lleva #Publicidad y "Enlace de afiliado". Para X, el bot te manda el texto por privado
  con el enlace de la etiqueta de X, listo para copiar y pegar (no se usa la API de X, que es de pago).
- Los posts de las últimas 48 h se revisan; si sube el precio o desaparece, se marcan
  «⛔ YA NO ESTÁ A ESTE PRECIO».
- Con "live": false en config.json solo aprende precios (historial) y no publica nada en el canal.
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
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from aliexpress_api import AliExpressAPI, AliExpressError, normalize

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state" / "aliexpress.json"
OTHER_STATES = [ROOT / "state" / "canal_nube.json", ROOT / "state" / "scanner.json"]
MADRID = ZoneInfo("Europe/Madrid")
USER_AGENT = "CazaChollosBot/3.0 (+https://t.me/cazachollos_com)"
EPOCH = date(2020, 1, 1)

DEFAULTS = {
    "live": False,
    "chat_id": "@cazachollos_com",
    "admin_username": "",
    "x_drafts": True,
    "queries": [],
    "queries_per_pass": 6,
    "page_size": 50,
    "min_price_eur": 3,
    "max_price_eur": 1500,
    "min_rating": 90,
    "min_volume": 50,
    "min_history_days": 7,
    "error_min_history_days": 14,
    "min_discount_pct": 25,
    "chollazo_pct": 45,
    "error_discount_pct": 70,
    "max_discount_pct": 90,
    "top_sales": {"enabled": True, "min_volume": 1000, "min_rating": 94, "max_per_day": 6,
                  "min_minutes_between": 90},
    "max_per_hour": 4,
    "max_per_day": 30,
    "max_per_run": 2,
    "min_minutes_between_posts": 8,
    "quiet_hours": [0, 8],
    "repost_after_days": 14,
    "repost_min_extra_drop_pct": 10,
    "track_hours": 48,
    "max_tracking_checks_per_run": 20,
    "history_days": 45,
    "max_products": 5000,
    "test_private_posts": 3,
    "block_keywords": [],
    "promo_codes": [],
}

HEADERS = {
    "ERROR DE PRECIO": "🚨 <b>ERROR DE PRECIO EN ALIEXPRESS</b> 🚨",
    "CHOLLAZO": "🔥 <b>CHOLLAZO EN ALIEXPRESS</b>",
    "CHOLLO": "💥 <b>CHOLLO EN ALIEXPRESS</b>",
    "TOP VENTAS": "🔝 <b>TOP VENTAS EN ALIEXPRESS</b>",
}
TAGS = {"ERROR DE PRECIO": "#ErrorDePrecio", "CHOLLAZO": "#Chollazo", "CHOLLO": "#Chollo", "TOP VENTAS": "#TopVentas"}
X_EMOJI = {"ERROR DE PRECIO": "🚨", "CHOLLAZO": "🔥", "CHOLLO": "💥", "TOP VENTAS": "🔝"}
TOP_NOTE = "De lo más vendido en AliExpress"
ENDED = "⛔ <b>YA NO ESTÁ A ESTE PRECIO</b> (comprobado a las {hour})"


# ------------------------------------------------------------------ utilidades
def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def rules_from(cfg: dict) -> dict:
    rules = {**DEFAULTS, **(cfg.get("aliexpress_channel") or {})}
    rules["top_sales"] = {**DEFAULTS["top_sales"], **(rules.get("top_sales") or {})}
    return rules


def euro(amount: float) -> str:
    whole = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{whole} €"


def day_num(d: date) -> int:
    return (d - EPOCH).days


def fold(text: str) -> str:
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(ch))


def clean_title(title: str, limit: int = 110) -> str:
    text = re.sub(r"\s+", " ", title or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(" ,.-/") + "…"


def pct(price: float, reference: float) -> float:
    return (reference - price) / reference * 100 if reference else 0.0


def blocked(title: str, rules: dict) -> str | None:
    folded = f" {fold(title)} "
    for word in rules.get("block_keywords") or []:
        w = fold(str(word)).strip()
        if w and re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", folded):
            return w
    return None


# ------------------------------------------------------------------ historial de precios
def record(state: dict, product: dict, today: date) -> None:
    """Guarda el precio más bajo visto hoy de cada producto: [día, céntimos]."""
    if not product.get("id") or not product.get("price"):
        return
    hist = state.setdefault("history", {})
    item = hist.setdefault(product["id"], {"p": []})
    item["t"] = clean_title(product["title"], 80)
    item["s"] = day_num(today)
    cents = int(round(product["price"] * 100))
    points = item["p"]
    if points and points[-1][0] == day_num(today):
        points[-1][1] = min(points[-1][1], cents)
    else:
        points.append([day_num(today), cents])


def reference_30(state: dict, pid: str, today: date) -> tuple[float | None, int]:
    """Precio más bajo visto en los 30 días anteriores (sin contar hoy) y cuántos días se vio."""
    points = ((state.get("history") or {}).get(pid) or {}).get("p") or []
    t = day_num(today)
    window = [c for d, c in points if t - 30 <= d < t]
    return (min(window) / 100 if window else None), len(window)


def prune(state: dict, today: date, rules: dict) -> None:
    hist = state.get("history") or {}
    keep_from = day_num(today) - int(rules["history_days"])
    for pid in list(hist):
        item = hist[pid]
        item["p"] = [p for p in item.get("p") or [] if p[0] >= keep_from]
        if not item["p"] or item.get("s", 0) < keep_from:
            del hist[pid]
    limit = int(rules["max_products"])
    if len(hist) > limit:
        for pid in sorted(hist, key=lambda k: hist[k].get("s", 0))[: len(hist) - limit]:
            del hist[pid]


# ------------------------------------------------------------------ evaluación
def badge_for(discount: float, days: int, rules: dict) -> str:
    if discount + 1e-9 >= float(rules["error_discount_pct"]) and days >= int(rules["error_min_history_days"]):
        return "ERROR DE PRECIO"
    return "CHOLLAZO" if discount >= float(rules["chollazo_pct"]) else "CHOLLO"


def evaluate(product: dict, state: dict, today: date, rules: dict) -> tuple[str, dict]:
    """('ok', deal) | ('top', deal) | (motivo de descarte, {})"""
    price = product.get("price")
    if not product.get("id") or not product.get("link"):
        return "sin enlace de afiliado", {}
    if not price or product.get("currency", "EUR") != "EUR":
        return "sin precio en euros", {}
    if not (float(rules["min_price_eur"]) <= price <= float(rules["max_price_eur"])):
        return "precio fuera de rango", {}
    word = blocked(product.get("title") or "", rules)
    if word:
        return f"bloqueado ({word})", {}
    rating = product.get("rating")
    if rating is not None and rating < float(rules["min_rating"]):
        return "valoración baja", {}
    if product.get("volume", 0) < int(rules["min_volume"]):
        return "pocas ventas", {}
    reference, days = reference_30(state, product["id"], today)
    base = {**product, "reference": None, "discount": 0.0, "days": days}
    if reference and days >= int(rules["min_history_days"]) and reference > price:
        discount = pct(price, reference)
        if discount > float(rules["max_discount_pct"]):
            return "descuento sospechoso", {}
        if discount >= float(rules["min_discount_pct"]):
            return "ok", {**base, "reference": reference, "discount": discount,
                          "badge": badge_for(discount, days, rules)}
    top = rules["top_sales"]
    if top.get("enabled") and product.get("volume", 0) >= int(top["min_volume"]) and \
            (rating or 0) >= float(top["min_rating"]):
        return "top", {**base, "badge": "TOP VENTAS"}
    if days < int(rules["min_history_days"]):
        return f"aprendiendo precio ({days} días)", {}
    return "sin descuento real", {}


def rank(deal: dict) -> tuple:
    kind = 0 if deal["badge"] != "TOP VENTAS" else 1
    return (kind, -round(deal.get("discount", 0)), -(deal.get("volume") or 0))


# ------------------------------------------------------------------ cupos y repeticiones
def posts_since(state: dict, since: datetime, top_only: bool = False) -> list[dict]:
    out = []
    for post in state.get("posts") or []:
        ts = datetime.fromtimestamp(post["ts"], timezone.utc)
        if ts >= since and (not top_only or post.get("badge") == "TOP VENTAS"):
            out.append(post)
    return out


def in_quiet_hours(now: datetime, rules: dict) -> bool:
    start, end = rules.get("quiet_hours") or [0, 0]
    hour = now.astimezone(MADRID).hour
    return start <= hour < end if start < end else (hour >= start or hour < end)


def quota_reason(state: dict, now: datetime, rules: dict, deal: dict, already: int) -> str:
    if already >= int(rules["max_per_run"]):
        return "cupo de esta pasada"
    if len(posts_since(state, now - timedelta(hours=1))) >= int(rules["max_per_hour"]):
        return "cupo de la hora"
    local_midnight = now.astimezone(MADRID).replace(hour=0, minute=0, second=0, microsecond=0)
    if len(posts_since(state, local_midnight)) >= int(rules["max_per_day"]):
        return "cupo del día"
    last = max((p["ts"] for p in state.get("posts") or []), default=0)
    if now.timestamp() - last < int(rules["min_minutes_between_posts"]) * 60:
        return "muy seguido del anterior"
    if deal["badge"] == "TOP VENTAS":
        top = rules["top_sales"]
        if len(posts_since(state, local_midnight, top_only=True)) >= int(top["max_per_day"]):
            return "cupo de top ventas"
        last_top = max((p["ts"] for p in posts_since(state, now - timedelta(days=1), top_only=True)), default=0)
        if now.timestamp() - last_top < int(top["min_minutes_between"]) * 60:
            return "top ventas muy seguido"
    return ""


def recently_posted(state: dict, deal: dict, now: datetime, rules: dict) -> bool:
    since = now - timedelta(days=int(rules["repost_after_days"]))
    for post in posts_since(state, since):
        if post.get("id") == deal["id"]:
            extra = pct(deal["price"], float(post.get("price") or 0))
            return extra < float(rules["repost_min_extra_drop_pct"])
    return False


# ------------------------------------------------------------------ códigos de afiliado
def campaign_code(price: float, rules: dict, now: datetime) -> dict | None:
    """El mejor código de la Guía de promoción (Portals) que se puede usar con este precio y sigue vigente."""
    best = None
    for code in rules.get("promo_codes") or []:
        try:
            until = datetime.fromisoformat(str(code["until"]))
            starts = datetime.fromisoformat(str(code["from"])) if code.get("from") else None
            off, minimum = float(code["off"]), float(code["min"])
        except (KeyError, TypeError, ValueError):
            continue
        if now >= until or (starts and now < starts) or price < minimum:
            continue
        if best is None or off > best[0]:
            best = (off, minimum, until, str(code["code"]))
    if not best:
        return None
    off, minimum, until, code = best
    fmt = lambda v: euro(v).replace(",00 €", " €")
    return {"code": code, "value": f"-{fmt(off)}", "min_spend": f"desde {fmt(minimum)}",
            "ends": f"hasta el {until.astimezone(MADRID):%d/%m}", "campaign": True}


def with_coupon(deal: dict, rules: dict, now: datetime) -> dict:
    """El cupón de la propia ficha manda; si no hay, el código de campaña de afiliado que encaje."""
    if (deal.get("coupon") or {}).get("code"):
        return deal
    code = campaign_code(float(deal["price"]), rules, now)
    return {**deal, "coupon": code} if code else deal


def coupon_text(coupon: dict) -> str:
    bits = [coupon.get("value"), coupon.get("min_spend"), coupon.get("ends")]
    if coupon.get("min_spend") and not str(coupon["min_spend"]).startswith("desde"):
        bits[1] = f"compra mínima {coupon['min_spend']}"
    return " · ".join(str(b) for b in bits if b)


# ------------------------------------------------------------------ textos
def build_caption(deal: dict, seen_hhmm: str) -> str:
    e = html.escape
    badge = deal["badge"]
    from aliexpress_card import card_title
    lines = [HEADERS[badge], "", f"<b>{e(card_title(deal['title'], 120))}</b>", ""]
    price = deal["price"]
    if deal.get("reference"):
        ref = deal["reference"]
        lines.append(f"💰 <b>{e(euro(price))}</b>   <s>{e(euro(ref))}</s>")
        lines.append(f"📉 <b>-{round(deal['discount'])} %</b> frente a su precio más bajo de los 30 días anteriores")
        lines.append(f"🤑 Te ahorras <b>{e(euro(ref - price))}</b>")
    else:
        lines.append(f"💰 <b>{e(euro(price))}</b>")
        lines.append(f"🛒 {TOP_NOTE}")
    if deal.get("app_price") and deal["app_price"] < price - 0.25:
        lines.append(f"📱 En la app de AliExpress <b>{e(euro(deal['app_price']))}</b>")
    coupon = deal.get("coupon") or {}
    if coupon.get("code"):
        extra = coupon_text(coupon)
        lines.append(f"🎟️ Cupón <code>{e(coupon['code'])}</code>" + (f" · {e(extra)}" if extra else ""))
    if deal.get("rating"):
        lines.append(f"⭐ {round(deal['rating'])} % de valoraciones positivas")
    lines += ["", f"🕒 Precio a las {seen_hhmm} · puede cambiar", "",
              f'🔗 <b><a href="{e(deal["link"], quote=True)}">Ver en AliExpress</a></b> (enlace de afiliado)', "",
              f"#Publicidad {TAGS[badge]} #AliExpress"]
    return "\n".join(lines)


def x_length(text: str) -> int:
    """Longitud aproximada en X: los enlaces cuentan 23 y los emojis 2."""
    text = re.sub(r"https?://\S+", "x" * 23, text)
    return sum(2 if ord(ch) > 0x2000 else 1 for ch in text)


def build_x_text(deal: dict, link: str, handles: dict | None = None) -> str:
    """Formato fijo de X (ver x_post.py): sin precio ni %, marca etiquetada si la conocemos y #ad."""
    from x_post import build_x_post
    coupon = deal.get("coupon") or {}
    extra = f"🎟️ Cupón {coupon['code']}" if coupon.get("code") else ""
    return build_x_post(deal.get("title") or "", deal.get("brand") or "", link, seed=str(deal.get("id") or link),
                        extra_handles=handles, extra_line=extra)


def ended_caption(caption: str, hour: str) -> str:
    kept = [line for line in caption.split("\n") if not line.startswith("🔗")]
    while kept and not kept[-1].strip():
        kept.pop()
    return ENDED.format(hour=hour) + "\n\n" + "\n".join(kept)


# ------------------------------------------------------------------ Telegram
class Telegram:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"

    def _send(self, req) -> dict:
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                result = json.loads(exc.read().decode("utf-8") or "{}")
            except (json.JSONDecodeError, UnicodeDecodeError):
                result = {"ok": False, "description": f"HTTP {exc.code}"}
        if not result.get("ok"):
            raise RuntimeError(f"Telegram: {result.get('description')}")
        return result["result"]

    def call(self, method: str, params: dict | None = None):
        body = json.dumps(params or {}).encode("utf-8")
        return self._send(urllib.request.Request(self.base + method, data=body,
                                                 headers={"Content-Type": "application/json"}))

    def multipart(self, method: str, fields: dict, files: dict[str, tuple[str, bytes]]):
        boundary = "----caza" + uuid.uuid4().hex
        parts = []
        for key, value in fields.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n"
                         .encode("utf-8"))
        for key, (name, data) in files.items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; filename=\"{name}\"\r\n"
                         "Content-Type: image/jpeg\r\n\r\n".encode("utf-8") + data + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode("ascii"))
        req = urllib.request.Request(self.base + method, data=b"".join(parts),
                                     headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        return self._send(req)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def send_post(tg: Telegram, chat_id, photo_url: str, card: Path, caption: str, log=print) -> list[int]:
    """Álbum de dos fotos: la del producto tal cual (por URL o, si Telegram no la baja, los mismos bytes
    sin tocar) y la tarjeta. El texto va en la primera."""
    card_bytes = card.read_bytes()
    media = [{"type": "photo", "media": photo_url, "caption": caption, "parse_mode": "HTML"},
             {"type": "photo", "media": "attach://card"}]
    try:
        result = tg.multipart("sendMediaGroup", {"chat_id": str(chat_id), "media": media},
                              {"card": (card.name, card_bytes)})
    except RuntimeError as exc:
        log(f"  Telegram no ha podido bajar la foto por URL ({exc}); la subo tal cual")
        media[0]["media"] = "attach://photo"
        result = tg.multipart("sendMediaGroup", {"chat_id": str(chat_id), "media": media},
                              {"photo": ("producto.jpg", download(photo_url)), "card": (card.name, card_bytes)})
    return [m["message_id"] for m in result]


def send_x_draft(tg: Telegram, admin: int, photo_url: str, text: str, test: bool = False) -> None:
    head = "🧪 PRUEBA · " if test else ""
    caption = f"{head}🐦 <b>Para X</b> · mantén pulsado el texto para copiarlo y activa la bandera «Paid partnership» antes de publicar\n\n<pre>{html.escape(text)}</pre>"
    try:
        tg.call("sendPhoto", {"chat_id": admin, "photo": photo_url, "caption": caption, "parse_mode": "HTML"})
    except RuntimeError:
        tg.call("sendMessage", {"chat_id": admin, "text": caption, "parse_mode": "HTML",
                                "disable_web_page_preview": True})


def admin_chat_id(state: dict, rules: dict, tg: Telegram | None, log=print) -> int | None:
    username = str(rules.get("admin_username") or "").lstrip("@").lower()
    if not username:
        return None
    known = (state.get("private_chats") or {}).get(username)
    for path in OTHER_STATES:
        known = known or (load_json(path, {}).get("private_chats") or {}).get(username)
    if not known and tg is not None:
        try:
            for upd in tg.call("getUpdates", {"timeout": 0, "allowed_updates": ["message"]}):
                chat = (upd.get("message") or {}).get("chat") or {}
                if chat.get("type") == "private" and str(chat.get("username") or "").lower() == username:
                    known = chat["id"]
        except RuntimeError as exc:
            log(f"  No he podido leer los mensajes del bot ({exc})")
    if known:
        state.setdefault("private_chats", {})[username] = int(known)
        return int(known)
    return None


# ------------------------------------------------------------------ una pasada
def pick_queries(rules: dict, state: dict) -> list[dict]:
    queries = rules.get("queries") or []
    if not queries:
        return []
    n = min(int(rules["queries_per_pass"]), len(queries))
    start = int(state.get("query_cursor", 0)) % len(queries)
    state["query_cursor"] = (start + n) % len(queries)
    return [queries[(start + i) % len(queries)] for i in range(n)]


def fetch_products(api, query: dict, rules: dict) -> list[dict]:
    common = {"page_size": int(rules["page_size"]), "min_price": float(rules["min_price_eur"]),
              "max_price": float(rules["max_price_eur"]), "sort": query.get("sort") or "LAST_VOLUME_DESC"}
    if query.get("kind") == "search":
        return api.search(keywords=query.get("keywords", ""), category_ids=query.get("category_ids", ""), **common)
    return api.hot_products(category_ids=query.get("category_ids", ""), keywords=query.get("keywords", ""), **common)


def track_posts(api, tg, state: dict, now: datetime, rules: dict, chat_id, log, dry: bool) -> None:
    since = now - timedelta(hours=int(rules["track_hours"]))
    open_posts = [p for p in posts_since(state, since) if not p.get("ended") and p.get("message_ids")]
    open_posts = open_posts[: int(rules["max_tracking_checks_per_run"])]
    if not open_posts:
        return
    try:
        live = {p["id"]: p for p in api.details([p["id"] for p in open_posts])}
    except AliExpressError as exc:
        log(f"  Seguimiento: no he podido releer las fichas ({exc})")
        return
    hour = f"{now.astimezone(MADRID):%H:%M}"
    for post in open_posts:
        current = live.get(post["id"])
        gone = current is None or not current.get("price")
        up = not gone and current["price"] > float(post["price"]) * 1.03
        if not (gone or up):
            continue
        log(f"  ⛔ {post['title'][:60]}: {'ya no está' if gone else 'ha subido a ' + euro(current['price'])}")
        post["ended"] = now.timestamp()
        if dry or tg is None:
            continue
        try:
            tg.call("editMessageCaption", {"chat_id": chat_id, "message_id": post["message_ids"][0],
                                           "caption": ended_caption(post["caption"], hour), "parse_mode": "HTML"})
        except RuntimeError as exc:
            log(f"    No he podido marcar el post ({exc})")


def run_pass(args, rules: dict, state: dict, now: datetime, api, tg, log=print) -> int:
    """Devuelve cuántos posts ha enviado."""
    import aliexpress_card

    today = now.astimezone(MADRID).date()
    test = bool(args.test_private)
    publish = (rules.get("live") or test) and not args.dry_run
    chat_id = rules["chat_id"]
    admin = admin_chat_id(state, rules, tg, log) if tg is not None else None
    if test:
        if not admin:
            log("No encuentro tu chat privado con el bot: escríbele /start y vuelve a probar.")
            return 0
        chat_id = admin

    if not test and not args.dry_run:
        track_posts(api, tg, state, now, rules, chat_id, log, dry=not rules.get("live"))

    candidates: dict[str, dict] = {}
    reasons: dict[str, int] = {}
    for query in pick_queries(rules, state):
        label = query.get("label") or query.get("keywords") or query.get("category_ids")
        try:
            products = fetch_products(api, query, rules)
        except AliExpressError as exc:
            log(f"  {label}: error de la API ({exc})")
            continue
        found = 0
        for product in products:
            verdict, deal = evaluate(product, state, today, rules)
            record(state, product, today)
            if verdict in ("ok", "top"):
                found += 1
                old = candidates.get(deal["id"])
                if not old or rank(deal) < rank(old):
                    candidates[deal["id"]] = deal
            else:
                key = verdict.split(" (")[0]
                reasons[key] = reasons.get(key, 0) + 1
        log(f"  {label}: {len(products)} productos, {found} candidatos")
    if reasons:
        log("  Descartes: " + ", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])))
    prune(state, today, rules)

    if in_quiet_hours(now, rules) and not test:
        log("  Horario nocturno: no publico.")
        return 0
    sent = 0
    limit = int(rules["test_private_posts"]) if test else None
    for deal in sorted(candidates.values(), key=rank):
        if limit is not None and sent >= limit:
            break
        if not test:
            if recently_posted(state, deal, now, rules):
                continue
            why = quota_reason(state, now, rules, deal, sent)
            if why:
                log(f"  Espera ({why}): {deal['title'][:60]}")
                if why.startswith("cupo") and "top" not in why:
                    break
                continue
        # Segunda lectura en vivo justo antes de publicar.
        try:
            fresh = {p["id"]: p for p in api.details([deal["id"]])}.get(deal["id"])
        except AliExpressError as exc:
            log(f"  No he podido releer la ficha ({exc}): {deal['title'][:60]}")
            continue
        if not fresh or not fresh.get("price") or abs(fresh["price"] - deal["price"]) > max(0.01, deal["price"] * 0.01):
            log(f"  El precio ha cambiado al releer: {deal['title'][:60]}")
            continue
        deal = with_coupon({**deal, **{k: fresh[k] for k in ("coupon", "app_price") if fresh.get(k)}}, rules, now)
        seen = now.astimezone(MADRID).strftime("%H:%M")
        caption = build_caption(deal, seen)
        log(f"  ✅ {deal['badge']} {euro(deal['price'])} "
            f"{'-' + str(round(deal['discount'])) + ' %' if deal.get('reference') else ''} {deal['title'][:70]}")
        if not publish:
            log("     (no se publica: " + ("prueba sin envío" if args.dry_run else "live desactivado") + ")")
            sent += 1
            continue
        card = aliexpress_card.create_card({**deal, "seen_hhmm": seen,
                                            "note": TOP_NOTE if deal["badge"] == "TOP VENTAS" else ""})
        try:
            message_ids = send_post(tg, chat_id, deal["image"], card,
                                    ("🧪 <b>PRUEBA</b> · solo te llega a ti\n\n" if test else "") + caption, log)
        except (RuntimeError, urllib.error.URLError) as exc:
            log(f"  No he podido publicar ({exc})")
            continue
        sent += 1
        if not test:
            state.setdefault("posts", []).append({
                "id": deal["id"], "title": deal["title"], "price": deal["price"], "badge": deal["badge"],
                "reference": deal.get("reference"), "ts": now.timestamp(), "message_ids": message_ids,
                "caption": caption})
        if rules.get("x_drafts") and admin:
            x_tracking = os.environ.get("ALIEXPRESS_TRACKING_ID_X", "").strip()
            link = deal["link"]
            if x_tracking and deal.get("url"):
                try:
                    link = api.affiliate_links([deal["url"]], x_tracking).get(deal["url"]) or link
                except AliExpressError as exc:
                    log(f"  No he podido sacar el enlace de X ({exc}); uso el de Telegram")
            try:
                send_x_draft(tg, admin, deal["image"], build_x_text(deal, link, rules.get("x_brand_handles")), test)
            except RuntimeError as exc:
                log(f"  No he podido mandarte el texto de X ({exc})")
    state["posts"] = [p for p in state.get("posts") or []
                      if p["ts"] >= (now - timedelta(days=int(rules["repost_after_days"]) + 2)).timestamp()]
    return sent


class FixtureAPI:
    """API de mentira para pruebas: lee productos de un JSON con el formato de la API."""

    def __init__(self, path: str):
        raw = load_json(Path(path), [])
        self.products = [normalize(p) for p in raw]
        self.calls = 0

    def hot_products(self, **_):
        self.calls += 1
        return list(self.products)

    search = hot_products

    def details(self, ids):
        return [p for p in self.products if p["id"] in ids]

    def affiliate_links(self, urls, tracking_id=None):
        return {u: u + ("&" if "?" in u else "?") + f"aff_fcid=prueba-{tracking_id}" for u in urls}


# ------------------------------------------------------------------ post manual (pruebas)
def run_manual(spec, rules: dict, tg, args, now: datetime, log=print) -> int:
    """Post hecho a mano a partir de un JSON (un producto o una lista). De momento solo como prueba privada.
    Campos: title, price, image, link y opcionales reference (mínimo de 30 días), badge, app_price, rating,
    coupon (código de la ficha) y url (ficha, para el enlace de X)."""
    import aliexpress_card

    items = spec if isinstance(spec, list) else [spec]
    if not args.test_private:
        log("El post manual solo va como prueba privada (--test-private).")
        return 1
    state = load_json(STATE_PATH, {})
    admin = admin_chat_id(state, rules, tg, log) if tg else None
    if not admin and not args.dry_run:
        log("No encuentro tu chat privado con el bot: escríbele /start y vuelve a probar.")
        return 1
    seen = now.astimezone(MADRID).strftime("%H:%M")
    sent = 0
    for raw in items:
        price = float(raw["price"])
        reference = float(raw["reference"]) if raw.get("reference") else None
        discount = pct(price, reference) if reference and reference > price else 0.0
        badge = raw.get("badge") or (badge_for(discount, 30, rules) if discount else "TOP VENTAS")
        deal = {"id": str(raw.get("id") or "manual"), "title": raw["title"], "price": price,
                "reference": reference if discount else None, "discount": discount, "badge": badge,
                "image": raw["image"], "link": raw["link"], "url": raw.get("url") or raw["link"],
                "app_price": float(raw["app_price"]) if raw.get("app_price") else None,
                "rating": float(raw["rating"]) if raw.get("rating") else None,
                "coupon": {"code": raw["coupon"]} if raw.get("coupon") else None}
        deal = with_coupon(deal, rules, now)
        caption = build_caption(deal, raw.get("seen_at") or seen)
        card = aliexpress_card.create_card({**deal, "seen_hhmm": raw.get("seen_at") or seen})
        log(f"  {badge} {euro(price)} {deal['title'][:70]} → tarjeta {card.name}")
        if args.dry_run:
            print(caption)
            print("---- X ----")
            print(build_x_text(deal, deal["link"]))
            continue
        note = str(raw.get("note") or "")
        head = "🧪 <b>PRUEBA</b> · solo te llega a ti" + (f" · {html.escape(note)}" if note else "") + "\n\n"
        send_post(tg, admin, deal["image"], card, head + caption, log)
        if rules.get("x_drafts"):
            send_x_draft(tg, admin, deal["image"], build_x_text(deal, deal["link"]), test=True)
        sent += 1
    log(f"Enviadas {sent} pruebas a tu chat privado.")
    return 0


# ------------------------------------------------------------------ main
def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(STATE_PATH)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="no envía nada")
    parser.add_argument("--test-private", action="store_true", help="hasta 3 ejemplos solo a tu chat privado")
    parser.add_argument("--minutes", type=float, default=0, help="pasadas seguidas durante estos minutos")
    parser.add_argument("--every", type=int, default=300, help="segundos entre pasadas")
    parser.add_argument("--fixture", help="productos de prueba en JSON en vez de la API")
    parser.add_argument("--manual", help="post hecho a mano (JSON de un producto o una lista); solo prueba privada")
    args = parser.parse_args(argv)

    cfg = load_json(CONFIG_PATH, {})
    rules = rules_from(cfg)
    if args.manual:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        tg = Telegram(token) if token else None
        if tg is None:
            args.dry_run = True
        return run_manual(json.loads(args.manual), rules, tg, args, datetime.now(timezone.utc))
    if args.fixture:
        api = FixtureAPI(args.fixture)
    else:
        api = AliExpressAPI.from_env()
        if api is None:
            print("Todavía no hay llaves de AliExpress (ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET y "
                  "ALIEXPRESS_TRACKING_ID en GitHub Secrets). No hago nada.")
            return 0
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg = Telegram(token) if token else None
    if tg is None and not args.dry_run:
        print("Falta TELEGRAM_BOT_TOKEN: paso a modo prueba sin envío.")
        args.dry_run = True
    state = load_json(STATE_PATH, {})
    if not rules.get("live") and not args.test_private and not args.dry_run:
        print("live desactivado en config.json: solo aprendo precios, no publico en el canal.")

    deadline = time.time() + args.minutes * 60
    total = 0
    while True:
        now = datetime.now(timezone.utc)
        print(f"Pasada {now.astimezone(MADRID):%d/%m %H:%M}")
        total += run_pass(args, rules, state, now, api, tg)
        if not args.test_private:
            save_state(state)
        if args.test_private or time.time() + args.every > deadline:
            break
        time.sleep(args.every)
    print(f"Fin: {total} posts, {getattr(api, 'calls', 0)} llamadas a la API, "
          f"{len(state.get('history') or {})} productos en el historial.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
