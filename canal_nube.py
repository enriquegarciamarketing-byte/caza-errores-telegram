#!/usr/bin/env python3
"""Canal @cazachollos_com en la nube (GitHub Actions): solo Amazon.es, solo chollos de verdad.

Amazon bloquea las lecturas desde GitHub, así que los datos salen de Jimmyleaks, que sigue
el precio de Amazon.es producto a producto. Reglas que no se saltan:

- Enlace al producto EXACTO: el ASIN sale del botón de compra de Jimmyleaks (/p/ID/ → amazon.es/dp/ASIN)
  y se publica como https://www.amazon.es/dp/ASIN?tag=<tu etiqueta>. Nunca una búsqueda por EAN.
- El precio tiene que haberse visto en Amazon hace muy poco (max_price_age_minutes) y coincidir
  en el listado y en la ficha. Justo antes de enviar se vuelve a leer la ficha: si cambia, no sale.
- El descuento se calcula frente al precio MÁS BAJO de los 30 días anteriores a la bajada, el mismo
  criterio que la ley europea exige a las tiendas. Nada de PVP tachados ni medias infladas por picos.
- Los posts de las últimas 48 h se vuelven a mirar; si sube el precio o se agota, se marca el post.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import scanner

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state" / "canal_nube.json"
PREMIUM_STATE = ROOT / "state" / "scanner.json"
OUTPUT = ROOT / "output" / "canal_nube"
MADRID = ZoneInfo("Europe/Madrid")
JL = "https://jimmyleaks.com"
USER_AGENT = "CazaChollosBot/2.0 (+https://t.me/cazachollos_com)"
ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")

DEFAULTS = {
    "chat_id": "@cazachollos_com",
    "sources": [],
    "max_price_age_minutes": 60,
    "min_discount_pct": 40,
    "error_discount_pct": 70,
    "max_discount_pct": 92,
    "min_price_eur": 8,
    "max_price_eur": 3000,
    "min_rating": 4.0,
    "min_reviews": 20,
    "min_history_days": 45,
    "max_drop_age_days": 7,
    "max_per_hour": 3,
    "max_per_day": 30,
    "max_per_run": 1,
    "test_private_posts": 3,
    "quiet_hours": [1, 8],
    "max_details_per_run": 15,
    "max_tracking_checks_per_run": 4,
    "recheck_rejected_hours": 6,
    "repost_after_days": 14,
    "repost_min_extra_drop_pct": 10,
    "track_hours": 48,
    "block_keywords": [],
}


# ------------------------------------------------------------------ utilidades

def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def rules_from(cfg: dict) -> dict:
    rules = dict(DEFAULTS)
    rules.update((cfg or {}).get("amazon_channel") or {})
    rules["tag"] = ((cfg or {}).get("affiliate_tag") or "").strip()
    return rules


def save_state(state: dict) -> None:
    state["posts"] = sorted(state.get("posts") or [], key=lambda p: p.get("t") or 0)[-3000:]
    cutoff = time.time() - 30 * 86400
    state["seen"] = {k: v for k, v in (state.get("seen") or {}).items() if (v.get("t") or 0) >= cutoff}
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def admin_chat_id(state: dict, rules: dict | None = None, tg=None, log=print) -> int | None:
    """Tu chat privado con el bot. Con admin_username en config.json se busca por tu @usuario:
    en la memoria de esta pasada, en la del escáner premium o en los mensajes pendientes del bot.
    Leer los mensajes pendientes sin offset no los marca como leídos, así que no molesta al escáner."""
    username = str((rules or {}).get("admin_username") or "").lstrip("@").lower()
    if not username:
        admin = state.get("admin_chat_id") or load_json(PREMIUM_STATE, {}).get("admin_chat_id")
        return int(admin) if admin else None
    known = (state.get("private_chats") or {}).get(username) or \
        (load_json(PREMIUM_STATE, {}).get("private_chats") or {}).get(username)
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


def euro(amount: float) -> str:
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def fold(text: str) -> str:
    return (text or "").lower().translate(str.maketrans("áéíóúüñ", "aeiouun"))


def http_get(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "es-ES,es;q=0.9"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def asin_from_jl(jl_id: str, opener=None) -> str | None:
    """Lee a qué ficha de Amazon apunta el botón de compra de Jimmyleaks, sin ir a Amazon."""
    opener = opener or urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(f"{JL}/p/{jl_id}/", headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(request, timeout=15):
            return None
    except urllib.error.HTTPError as exc:
        location = exc.headers.get("Location") if exc.headers else ""
    except (urllib.error.URLError, TimeoutError):
        return None
    return parse_asin(location or "")


def parse_asin(location: str) -> str | None:
    match = re.match(r"https?://(?:www\.)?amazon\.es/(?:[^/?#]+/)?(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?#]|$)", location)
    return match.group(1) if match else None


# ------------------------------------------------------------------ historial

def daily_prices(points: list, first: date, last: date) -> dict[date, float]:
    """Precio de cada día entre first y last, a partir de los cambios del historial."""
    parsed = []
    for raw_day, price in points or []:
        try:
            parsed.append((date.fromisoformat(str(raw_day)[:10]), float(price)))
        except (TypeError, ValueError):
            continue
    parsed.sort()
    days: dict[date, float] = {}
    if not parsed:
        return days
    current = None
    idx = 0
    day = first
    while idx < len(parsed) and parsed[idx][0] <= first:
        current = parsed[idx][1]
        idx += 1
    while day <= last:
        while idx < len(parsed) and parsed[idx][0] <= day:
            current = parsed[idx][1]
            idx += 1
        if current is not None:
            days[day] = current
        day += timedelta(days=1)
    return days


def amazon_series(series: list) -> list:
    for entry in series or []:
        if "amazon.es" in str(entry.get("flag") or "").lower() or str(entry.get("label") or "").lower() == "amazon es":
            return entry.get("points") or []
    return []


def history_reference(points: list, price: float, today: date) -> dict:
    """Precio habitual (mediana diaria de los 90 días anteriores a la bajada) y mínimo de los 30 previos."""
    ordered = sorted((str(d)[:10], float(p)) for d, p in points or [] if p)
    if not ordered:
        return {"ok": False, "why": "sin historial"}
    # La bajada actual empieza en el primer punto, desde el final, cuyo precio ya es el de ahora.
    drop_start = None
    for raw_day, value in reversed(ordered):
        if abs(value - price) <= max(0.01, price * 0.01):
            drop_start = date.fromisoformat(raw_day)
            continue
        break
    drop_start = drop_start or today
    before_end = drop_start - timedelta(days=1)
    window = daily_prices(points, drop_start - timedelta(days=90), before_end)
    last30 = [v for d, v in window.items() if d >= drop_start - timedelta(days=30)]
    if not window:
        return {"ok": False, "why": "sin historial antes de la bajada"}
    return {
        "ok": True,
        "reference": round(statistics.median(window.values()), 2),
        "min_30": min(last30) if last30 else None,
        "days": len(window),
        "drop_start": drop_start.isoformat(),
        "drop_age_days": (today - drop_start).days,
    }


# ------------------------------------------------------------------ evaluación

def discount_pct(price: float, reference: float | None) -> float:
    if not reference or reference <= price:
        return 0.0
    return (reference - price) / reference * 100


def evaluate(item: dict, detail: dict, rules: dict, now: datetime) -> tuple[str, dict]:
    """Motivo de descarte (o '') y los datos del chollo ya calculados."""
    title = detail.get("name") or item.get("title") or ""
    price = detail.get("price")
    if not title:
        return "sin título", {}
    if price is None:
        return "sin precio en la ficha", {}
    if item.get("price") is not None and abs(float(item["price"]) - float(price)) > 0.009:
        return f"el listado ({item['price']}) y la ficha ({price}) no coinciden", {}
    age = (now.timestamp() - int(item.get("ts") or 0)) / 60
    if not item.get("ts") or age > float(rules["max_price_age_minutes"]):
        return f"precio visto hace {age:.0f} min (máximo {rules['max_price_age_minutes']})", {}
    if not detail.get("in_stock"):
        return "sin stock", {}
    if price < float(rules["min_price_eur"]) or price > float(rules["max_price_eur"]):
        return f"precio fuera de rango ({price} €)", {}
    hist = history_reference(amazon_series(detail.get("series")), float(price), now.astimezone(MADRID).date())
    if not hist.get("ok"):
        return hist.get("why", "sin historial"), {}
    if hist["days"] < int(rules["min_history_days"]):
        return f"poco historial ({hist['days']} días)", {}
    reference = hist.get("min_30")
    if not reference:
        return "sin precios de los 30 días anteriores", {}
    pct = discount_pct(float(price), reference)
    if pct + 1e-9 < float(rules["min_discount_pct"]):
        return f"solo -{pct:.0f}% frente a su mínimo de los 30 días anteriores ({euro(reference)})", {}
    if pct > float(rules["max_discount_pct"]):
        return f"descuento sospechoso (-{pct:.0f}%)", {}
    if hist["drop_age_days"] > int(rules["max_drop_age_days"]):
        return f"lleva {hist['drop_age_days']} días a este precio", {}
    rating, reviews = detail.get("rating"), detail.get("reviews")
    if rating is None or reviews is None:
        return "sin valoraciones", {}
    if rating + 1e-9 < float(rules["min_rating"]):
        return f"valoración baja ({rating})", {}
    if reviews < int(rules["min_reviews"]):
        return f"pocas opiniones ({reviews})", {}
    folded = fold(title)
    for word in rules.get("block_keywords") or []:
        if re.search(rf"\b{re.escape(fold(word))}\b", folded):
            return f"categoría excluida («{word}»)", {}
    if not detail.get("image"):
        return "sin foto", {}
    low = detail.get("low")
    return "", {
        "jl_id": item["id"], "title": title, "price": float(price), "reference": reference,
        "median_90": hist["reference"],
        "discount": pct, "historical_low": bool(low and price <= low + 0.009), "rating": rating,
        "reviews": reviews, "image": detail["image"], "seen_ts": int(item["ts"]), "brand": item.get("brand") or "",
    }


# ------------------------------------------------------------------ cupos

def in_quiet_hours(now: datetime, rules: dict) -> bool:
    start, end = rules.get("quiet_hours") or [1, 8]
    return start <= now.astimezone(MADRID).hour < end


def quota_reason(state: dict, now: datetime, rules: dict, already: int = 0) -> str:
    if in_quiet_hours(now, rules):
        return "horario de silencio"
    posts = state.get("posts") or []
    last_hour = [p for p in posts if (p.get("t") or 0) >= now.timestamp() - 3600]
    today = now.astimezone(MADRID).date()
    today_posts = [p for p in posts
                   if datetime.fromtimestamp(p.get("t") or 0, timezone.utc).astimezone(MADRID).date() == today]
    if len(last_hour) + already >= int(rules["max_per_hour"]):
        return "cupo de la hora cubierto"
    if len(today_posts) + already >= int(rules["max_per_day"]):
        return "cupo del día cubierto"
    return ""


def recently_posted(state: dict, asin: str, price: float, now: datetime, rules: dict) -> bool:
    window = float(rules["repost_after_days"]) * 86400
    for post in reversed(state.get("posts") or []):
        if post.get("asin") != asin:
            continue
        if now.timestamp() - (post.get("t") or 0) > window:
            return False
        before = float(post.get("price") or 0)
        return ((before - price) / before * 100 if before else 0) < float(rules["repost_min_extra_drop_pct"])
    return False


# ------------------------------------------------------------------ texto y tarjeta

def clean_title(title: str, limit: int = 95) -> str:
    text = re.sub(r"\s+", " ", title or "").strip(" ,-|")
    cuts = [i for i in (text.find(sep, 28) for sep in (" | ", " – ", " - ", " — ", ", ", "; ")) if 0 < i <= limit]
    if cuts:
        text = text[:min(cuts)]
    text = re.sub(r"[\[(][^\])]{0,60}$", "", text).strip(" ,-|(")
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(" ,-(") + "…"
    return text


def badge_for(pct: float, rules: dict) -> str:
    if pct + 1e-9 >= float(rules["error_discount_pct"]):
        return "ERROR DE PRECIO"
    return "CHOLLAZO" if pct >= 55 else "CHOLLO"


HEADERS = {
    "ERROR DE PRECIO": "🚨 <b>ERROR DE PRECIO EN AMAZON</b> 🚨",
    "CHOLLAZO": "🔥 <b>CHOLLAZO EN AMAZON</b>",
    "CHOLLO": "💥 <b>CHOLLO EN AMAZON</b>",
}


def build_caption(deal: dict, url: str, rules: dict) -> str:
    e = html.escape
    pct = deal["discount"]
    seen = datetime.fromtimestamp(deal["seen_ts"], timezone.utc).astimezone(MADRID)
    lines = [HEADERS[badge_for(pct, rules)], "", f"<b>{e(clean_title(deal['title'], 140))}</b>", ""]
    lines.append(f"💰 <b>{e(euro(deal['price']))}</b>   <s>{e(euro(deal['reference']))}</s>")
    lines.append(f"📉 <b>-{round(pct)} %</b> frente a su precio más bajo de los 30 días anteriores")
    lines.append(f"🤑 Te ahorras <b>{e(euro(deal['reference'] - deal['price']))}</b>")
    if deal.get("historical_low"):
        lines.append("🏆 <b>Precio más bajo de su historia</b>")
    if deal.get("rating") and deal.get("reviews"):
        lines.append(f"⭐ {str(round(deal['rating'], 1)).replace('.', ',')} ({deal['reviews']} opiniones)")
    lines.append("")
    lines.append(f"🕒 Precio visto en Amazon.es a las {seen:%H:%M}. Puede cambiar en cualquier momento.")
    lines.append("")
    lines.append(f'🔗 <b><a href="{e(url, quote=True)}">Ver en Amazon</a></b>')
    return "\n".join(lines)


def buttons(url: str) -> dict:
    return {"inline_keyboard": [[{"text": "🛒 Ver en Amazon", "url": url}]]}


def make_card(deal: dict, rules: dict) -> Path:
    import photos
    from publisher import DEAL_LOGO, create_price_card

    raw = photos.fetch_best(deal["image"])
    if not raw:
        raise ValueError("no he podido descargar la foto")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    image_path = OUTPUT / f"{deal['asin']}.img"
    image_path.write_bytes(raw)
    return create_price_card({
        "id": f"amz-{deal['asin']}",
        "title": clean_title(deal["title"]),
        "image_path": image_path,
        "category": badge_for(deal["discount"], rules),
        "current": deal["price"],
        "reference": deal["reference"],
        "ref_label": "MÍNIMO 30 DÍAS ANTES",
        "logo_path": DEAL_LOGO,
        "store": "Amazon",
        "days": 90,
        "jpeg_quality": 95,
    })


# ------------------------------------------------------------------ seguimiento

ENDED = "⛔ <b>YA NO ESTÁ A ESTE PRECIO</b> (comprobado a las {hour})"


def track_posts(tg, state: dict, now: datetime, rules: dict, log, dry: bool, fetch) -> None:
    horizon = now.timestamp() - float(rules["track_hours"]) * 3600
    live = [p for p in state.get("posts") or []
            if (p.get("t") or 0) >= horizon and not p.get("ended") and p.get("message_id") and p.get("jl_id")]
    live.sort(key=lambda p: p.get("checked") or p.get("t") or 0)
    for post in live[: int(rules["max_tracking_checks_per_run"])]:
        try:
            detail = scanner.parse_detail(fetch(f"{JL}/es/dp/{post['jl_id']}/"))
        except Exception as exc:
            log(f"  Seguimiento {post['asin']}: {exc}")
            continue
        post["checked"] = int(now.timestamp())
        price = detail.get("price")
        if detail.get("in_stock") and price is not None and price <= float(post["price"]) + 0.009:
            log(f"  Seguimiento {post['asin']}: sigue a {euro(float(post['price']))}")
            continue
        log(f"  Seguimiento {post['asin']}: terminado (ahora {price}, stock {detail.get('in_stock')})")
        if dry or tg is None:
            continue
        caption = ENDED.format(hour=f"{now.astimezone(MADRID):%H:%M}") + "\n\n" + post["caption"]
        try:
            tg.call("editMessageCaption", {"chat_id": post["chat"], "message_id": post["message_id"],
                                           "caption": caption[:1024], "parse_mode": "HTML",
                                           "reply_markup": buttons(post["url"])})
            post["ended"] = int(now.timestamp())
        except RuntimeError as exc:
            log(f"  No he podido marcar el post {post['message_id']}: {exc}")


def listing_priority(item: dict) -> tuple:
    """Qué fichas abrir antes: mínimos históricos y grandes bajadas en el listado, y luego las más recientes."""
    verdict = fold(item.get("verdict") or "")
    price, was = item.get("price") or 0, item.get("was") or 0
    drop = (was - price) / was if was and was > price else 0
    return ("minimo historico" in verdict, round(drop, 2), item.get("ts") or 0)


# ------------------------------------------------------------------ pasada

def run(args, cfg: dict, state: dict, now: datetime, tg=None, fetch=None, resolve_asin=None, log=print) -> int:
    rules = rules_from(cfg)
    fetch = fetch or http_get
    resolve_asin = resolve_asin or asin_from_jl
    if not rules["tag"]:
        log("Falta affiliate_tag en config.json. No publico nada sin tu etiqueta.")
        return 2
    target = rules["chat_id"]
    if args.test_private:
        target = admin_chat_id(state, rules, tg, log)
        if not target:
            who = rules.get("admin_username") or "tu cuenta"
            log(f"Prueba privada: no encuentro el chat de @{str(who).lstrip('@')}. "
                f"Escribe /start a @cazaerroresAmazon_bot desde esa cuenta y repite la prueba.")
            return 2
        log(f"Prueba privada: envío solo a tu chat ({target}), nunca al canal.")
    dry = bool(args.dry_run or tg is None)
    if not args.test_private:
        track_posts(tg, state, now, rules, log, dry, fetch)
        if not args.ignore_limits:
            why = quota_reason(state, now, rules)
            if why:
                log(f"No publico: {why}.")
                return 0
    approved = find_deals(rules, state, now, fetch, resolve_asin, log, remember=not args.test_private)
    approved.sort(key=lambda pair: pair[1]["discount"], reverse=True)
    limit = int(rules["test_private_posts"] if args.test_private else rules["max_per_run"])
    sent = 0
    for item, deal in approved:
        if sent >= limit:
            break
        # Segunda lectura justo antes de enviar: mismo precio y todavía reciente.
        try:
            again = scanner.parse_detail(fetch(f"{JL}/es/dp/{item['id']}/"))
        except Exception as exc:
            log(f"  ✗ {deal['asin']} sin segunda lectura: {exc}")
            continue
        if again.get("price") is None or abs(float(again["price"]) - deal["price"]) > 0.009 or not again.get("in_stock"):
            log(f"  ✗ {deal['asin']} el precio ha cambiado ({deal['price']} → {again.get('price')})")
            continue
        url = f"https://www.amazon.es/dp/{deal['asin']}?tag={rules['tag']}"
        caption = build_caption(deal, url, rules)
        if dry:
            log("  [prueba, no se envía]\n" + caption)
            sent += 1
            continue
        try:
            card = make_card(deal, rules)
        except (OSError, ValueError) as exc:
            log(f"  ✗ {deal['asin']} sin tarjeta: {exc}")
            continue
        message = tg.send_photo(target, card, caption, {"reply_markup": buttons(url)})
        log(f"  Enviado a {target} (mensaje {message['message_id']}): {clean_title(deal['title'], 70)}")
        sent += 1
        if not args.test_private:
            state.setdefault("posts", []).append({
                "asin": deal["asin"], "jl_id": deal["jl_id"], "price": deal["price"],
                "reference": deal["reference"], "t": int(now.timestamp()), "url": url, "chat": target,
                "message_id": int(message["message_id"]), "caption": caption, "title": deal["title"][:140],
            })
        time.sleep(2)
    if not sent:
        log("Nada que cumpla todas las reglas en esta pasada.")
    return 0


def find_deals(rules: dict, state: dict, now: datetime, fetch, resolve_asin, log, remember: bool = True) -> list:
    """Busca en los listados y devuelve [(item, deal)] que cumplen todas las reglas, mejor descuento primero."""
    seen = state.setdefault("seen", {})
    recheck = float(rules["recheck_rejected_hours"]) * 3600
    max_age = float(rules["max_price_age_minutes"]) * 60
    pool: dict[str, dict] = {}
    for url in rules.get("sources") or []:
        try:
            items = scanner.parse_listing(fetch(url))
        except Exception as exc:
            log(f"  Listado {url}: {exc}")
            continue
        fresh = [i for i in items if i.get("ts") and now.timestamp() - i["ts"] <= max_age and i.get("price")]
        log(f"  Listado {url}: {len(items)} productos, {len(fresh)} vistos en la última hora")
        for item in fresh:
            last = seen.get(item["id"]) or {}
            same_price = last.get("price") is not None and abs(float(last["price"]) - float(item["price"])) < 0.01
            if same_price and now.timestamp() - (last.get("t") or 0) < recheck:
                continue  # ya descartado a este mismo precio; si baja más, se vuelve a mirar
            pool.setdefault(item["id"], item)
    ordered = sorted(pool.values(), key=listing_priority, reverse=True)
    log(f"Candidatos a revisar: {len(ordered)}")
    approved = []
    for item in ordered[: int(rules["max_details_per_run"])]:
        try:
            detail = scanner.parse_detail(fetch(f"{JL}/es/dp/{item['id']}/"))
        except Exception as exc:
            log(f"  Ficha {item['id']}: {exc}")
            continue
        why, deal = evaluate(item, detail, rules, now)
        if not why:
            asin = resolve_asin(item["id"])
            if not asin or not ASIN_RE.fullmatch(asin):
                why = "no he podido sacar el producto exacto de Amazon (ASIN)"
            else:
                deal["asin"] = asin
                if recently_posted(state, asin, deal["price"], now, rules):
                    why = "ya publicado hace poco y no ha bajado más"
        if why and remember:
            # Solo se aparta lo descartado. Lo aprobado que no cabe en esta pasada sale en la siguiente.
            seen[item["id"]] = {"t": int(now.timestamp()), "why": why, "price": item.get("price")}
        label = clean_title(detail.get("name") or item.get("title") or "", 60)
        if why:
            log(f"  ✗ {item['id']} {label}: {why}")
            continue
        log(f"  ✓ {deal['asin']} {label}: {euro(deal['price'])} (-{deal['discount']:.0f}% vs {euro(deal['reference'])})")
        approved.append((item, deal))
    approved.sort(key=lambda pair: pair[1]["discount"], reverse=True)
    return approved


# ------------------------------------------------------------------ resumen de la noche

def summary_items(state: dict, now: datetime, rules: dict, fetch, log, limit: int = 10) -> list[dict]:
    """Los posts de hoy que siguen activos (vuelve a mirar el precio), mejor descuento primero."""
    today = now.astimezone(MADRID).date()
    items = []
    for post in state.get("posts") or []:
        if post.get("ended") or not post.get("jl_id"):
            continue
        if datetime.fromtimestamp(post.get("t") or 0, timezone.utc).astimezone(MADRID).date() != today:
            continue
        try:
            detail = scanner.parse_detail(fetch(f"{JL}/es/dp/{post['jl_id']}/"))
        except Exception as exc:
            log(f"  Resumen: no he podido releer {post['asin']} ({exc}); lo dejo fuera")
            continue
        price = detail.get("price")
        if not detail.get("in_stock") or price is None or price > float(post["price"]) + 0.009:
            log(f"  Resumen: {post['asin']} ya no está a {post['price']} €; fuera")
            continue
        items.append({"asin": post["asin"], "title": post.get("title") or "", "price": float(price),
                      "reference": float(post["reference"]), "url": post["url"],
                      "discount": discount_pct(float(price), float(post["reference"]))})
    items.sort(key=lambda item: item["discount"], reverse=True)
    return items[:limit]


NUMBERS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]


def build_summary(items: list[dict], now: datetime, test: bool = False) -> str:
    e = html.escape
    hour = now.astimezone(MADRID).strftime("%H:%M")
    lines = []
    if test:
        lines += ["🧪 <b>PRUEBA</b> · así saldría el resumen de la noche", ""]
    lines += ["🌙 <b>LO MEJOR DEL DÍA EN AMAZON</b>", "",
              f"Los {len(items)} chollos más bestias de hoy que siguen activos ahora mismo 👇", ""]
    for index, item in enumerate(items):
        lines.append(f"{NUMBERS[index]} <b>{e(clean_title(item['title'], 70))}</b>")
        lines.append(f"💰 <b>{e(euro(item['price']))}</b>  <s>{e(euro(item['reference']))}</s>  "
                     f"📉 <b>-{round(item['discount'])} %</b>")
        lines.append(f'🔗 <a href="{e(item["url"], quote=True)}">Ver en Amazon</a>')
        lines.append("")
    lines.append(f"🕒 Precios comprobados a las {hour}. Pueden cambiar en cualquier momento.")
    lines.append("🔔 Activa las notificaciones para no perderte los de mañana.")
    return "\n".join(lines)


def run_summary(args, cfg: dict, state: dict, now: datetime, tg=None, fetch=None, resolve_asin=None, log=print) -> int:
    rules = rules_from(cfg)
    fetch = fetch or http_get
    local = now.astimezone(MADRID)
    hour, minute = (int(x) for x in str(rules.get("summary_time") or "23:30").split(":"))
    if not args.ignore_limits:
        if local.hour != hour:
            log(f"Resumen: no es la hora ({local:%H:%M}); se manda a las {hour:02d}:{minute:02d}.")
            return 0
        if state.get("summary_sent") == local.date().isoformat():
            log("Resumen: ya enviado hoy.")
            return 0
    items = summary_items(state, now, rules, fetch, log, int(rules.get("summary_size") or 10))
    if args.test_private and len(items) < 5:
        # En la prueba, si hoy aún hay pocos posts, se completa con chollos que cumplen las reglas ahora.
        for item, deal in find_deals(rules, state, now, fetch, resolve_asin or asin_from_jl, log, remember=False):
            if len(items) >= 8 or any(x["asin"] == deal["asin"] for x in items):
                continue
            items.append({"asin": deal["asin"], "title": deal["title"], "price": deal["price"],
                          "reference": deal["reference"], "discount": deal["discount"],
                          "url": f"https://www.amazon.es/dp/{deal['asin']}?tag={rules['tag']}"})
        items.sort(key=lambda item: item["discount"], reverse=True)
    if len(items) < int(rules.get("summary_min_items") or 3) and not args.test_private:
        log(f"Resumen: solo {len(items)} chollos activos hoy; no mando lista.")
        state["summary_sent"] = local.date().isoformat()
        return 0
    if not items:
        log("Resumen: nada que listar.")
        return 0
    text = build_summary(items, now, test=bool(args.test_private))
    target = admin_chat_id(state, rules, tg, log) if args.test_private else rules["chat_id"]
    if args.dry_run or tg is None:
        log("[prueba, no se envía]\n" + text)
        return 0
    message = tg.call("sendMessage", {"chat_id": target, "text": text, "parse_mode": "HTML",
                                      "disable_web_page_preview": True})
    log(f"Resumen enviado a {target} (mensaje {message.get('message_id')}) con {len(items)} chollos.")
    if not args.test_private:
        state["summary_sent"] = local.date().isoformat()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Canal @cazachollos_com: solo Amazon, precio verificado")
    parser.add_argument("--dry-run", action="store_true", help="Lo revisa todo pero no envía nada")
    parser.add_argument("--test-private", action="store_true", help="Hasta 3 ejemplos a tu chat, nunca al canal")
    parser.add_argument("--ignore-limits", action="store_true", help="Salta cupos y horario (pruebas)")
    parser.add_argument("--resumen", action="store_true", help="Manda el resumen de la noche (a las 23:30)")
    args = parser.parse_args()
    cfg = load_json(CONFIG_PATH, {})
    state = load_json(STATE_PATH, {"posts": [], "seen": {}})
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token and not args.dry_run:
        print("Falta TELEGRAM_BOT_TOKEN", file=sys.stderr)
        return 2
    tg = scanner.Telegram(token) if token else None
    now = datetime.now(timezone.utc)
    print(f"== {now.astimezone(MADRID):%Y-%m-%d %H:%M} ==")
    code = (run_summary if args.resumen else run)(args, cfg, state, now, tg=tg)
    if not args.dry_run and not args.test_private:
        save_state(state)
    return code


if __name__ == "__main__":
    sys.exit(main())
