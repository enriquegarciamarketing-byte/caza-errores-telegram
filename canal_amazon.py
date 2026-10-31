#!/usr/bin/env python3
"""Canal @cazachollos_com: solo Amazon.es, solo chollos de verdad y con el precio real de la ficha.

Corre en el Mac de Enrique (Amazon bloquea las lecturas desde los servidores de GitHub).

Reglas que no se saltan nunca:
- El precio publicado es el que muestra la ficha de Amazon.es en ese momento, leído dos veces
  (al elegir el chollo y justo antes de enviarlo). Si cambia entre las dos lecturas, no se publica.
- El descuento se calcula frente al "Precio más bajo reciente" que enseña la propia Amazon
  (precio más bajo de los 30 días anteriores, obligatorio por ley en la UE). Nada de PVP inflados.
- El enlace va al producto exacto (/dp/ASIN) con la etiqueta del canal.
- Si algo no se puede leer con seguridad, ese chollo no sale.
- Los posts de las últimas horas se vuelven a comprobar y, si el precio sube o se agota, se marcan.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import amazon_page as amz

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state" / "canal_amazon.json"
PREMIUM_STATE = ROOT / "state" / "scanner.json"
OUTPUT = ROOT / "output" / "canal_amazon"
LOG_PATH = ROOT / "state" / "canal_amazon.log"
MADRID = ZoneInfo("Europe/Madrid")

DEFAULTS = {
    "chat_id": "@cazachollos_com",
    "min_discount_pct": 40,
    "error_discount_pct": 70,
    "max_discount_pct": 95,
    "min_price_eur": 8,
    "max_price_eur": 2500,
    "min_rating": 4.0,
    "min_reviews": 30,
    "require_amazon_fulfilment": True,
    "allow_prime_only": False,
    "max_per_hour": 3,
    "max_per_day": 30,
    "max_per_run": 1,
    "test_private_posts": 3,
    "quiet_hours": [1, 8],
    "max_listing_pages_per_run": 4,
    "max_product_checks_per_run": 12,
    "max_tracking_checks_per_run": 4,
    "recheck_rejected_hours": 6,
    "repost_after_days": 14,
    "repost_min_extra_drop_pct": 10,
    "track_hours": 48,
    "price_tolerance_eur": 0.0,
    "request_gap_seconds": 3.0,
    "discovery_urls": [],
    "block_keywords": [],
}


# ------------------------------------------------------------------ estado y config

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
    posts = state.get("posts") or []
    state["posts"] = sorted(posts, key=lambda p: p.get("t") or 0)[-3000:]
    seen = state.get("seen") or {}
    cutoff = time.time() - 30 * 86400
    state["seen"] = {k: v for k, v in seen.items() if (v.get("t") or 0) >= cutoff}
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(STATE_PATH)


def load_env() -> None:
    """Lee .env (TELEGRAM_BOT_TOKEN=...) sin pisar lo que ya venga del entorno."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def admin_chat_id(state: dict) -> int | None:
    if state.get("admin_chat_id"):
        return int(state["admin_chat_id"])
    if os.environ.get("ADMIN_CHAT_ID"):
        return int(os.environ["ADMIN_CHAT_ID"])
    admin = load_json(PREMIUM_STATE, {}).get("admin_chat_id")
    return int(admin) if admin else None


# ------------------------------------------------------------------ cupos

def in_quiet_hours(now: datetime, rules: dict) -> bool:
    start, end = rules.get("quiet_hours") or [1, 8]
    return start <= now.astimezone(MADRID).hour < end


def quota_reason(state: dict, now: datetime, rules: dict, already: int = 0) -> str:
    if in_quiet_hours(now, rules):
        return "horario de silencio"
    posts = state.get("posts") or []
    stamp = now.timestamp()
    last_hour = [p for p in posts if (p.get("t") or 0) >= stamp - 3600]
    today = now.astimezone(MADRID).date()
    today_posts = [p for p in posts
                   if datetime.fromtimestamp(p.get("t") or 0, timezone.utc).astimezone(MADRID).date() == today]
    if len(last_hour) + already >= int(rules["max_per_hour"]):
        return "cupo de la hora cubierto"
    if len(today_posts) + already >= int(rules["max_per_day"]):
        return "cupo del día cubierto"
    return ""


def recently_posted(state: dict, asin: str, price: float, now: datetime, rules: dict) -> bool:
    """Mismo producto publicado hace poco: solo se repite si ha bajado bastante más."""
    window = float(rules["repost_after_days"]) * 86400
    for post in reversed(state.get("posts") or []):
        if post.get("asin") != asin:
            continue
        if now.timestamp() - (post.get("t") or 0) > window:
            return False
        before = float(post.get("price") or 0)
        extra = (before - price) / before * 100 if before else 0
        return extra < float(rules["repost_min_extra_drop_pct"])
    return False


# ------------------------------------------------------------------ evaluación

def fold(text: str) -> str:
    table = str.maketrans("áéíóúüñ", "aeiouun")
    return (text or "").lower().translate(table)


def discount_pct(price: float, reference: float | None) -> float:
    if not reference or reference <= price:
        return 0.0
    return (reference - price) / reference * 100


def amazon_fulfils(product: dict) -> bool:
    seller = fold(product.get("seller") or "")
    shipper = fold(product.get("shipper") or "")
    return seller.startswith("amazon") or shipper.startswith("amazon")


def evaluate(product: dict, rules: dict) -> str:
    """Motivo de descarte, o cadena vacía si el chollo es publicable."""
    price = product.get("price")
    if not product.get("title"):
        return "sin título legible"
    if price is None:
        return "precio no legible en la ficha"
    if not product.get("in_stock"):
        return f"sin stock ({product.get('availability') or 'desconocido'})"
    if product.get("prime_only") and not rules.get("allow_prime_only"):
        return "precio exclusivo Prime"
    reference = product.get("lowest_30")
    if not reference:
        return "Amazon no muestra precio más bajo reciente (no hay rebaja verificable)"
    pct = discount_pct(price, reference)
    if pct + 1e-9 < float(rules["min_discount_pct"]):
        return f"solo -{pct:.0f}% frente al mínimo de 30 días"
    if pct > float(rules["max_discount_pct"]):
        return f"descuento absurdo ({pct:.0f}%), posible error de lectura"
    if price < float(rules["min_price_eur"]):
        return f"precio por debajo de {rules['min_price_eur']} €"
    if price > float(rules["max_price_eur"]):
        return f"precio por encima de {rules['max_price_eur']} €"
    if rules.get("require_amazon_fulfilment") and not amazon_fulfils(product):
        return f"ni vendido ni enviado por Amazon (vendedor: {product.get('seller') or '?'})"
    rating, reviews = product.get("rating"), product.get("reviews")
    if rating is None or reviews is None:
        return "sin valoraciones legibles"
    if rating + 1e-9 < float(rules["min_rating"]):
        return f"valoración baja ({rating})"
    if reviews < int(rules["min_reviews"]):
        return f"pocas opiniones ({reviews})"
    title = fold(product["title"])
    for word in rules.get("block_keywords") or []:
        if re.search(rf"\b{re.escape(fold(word))}\b", title):
            return f"categoría excluida («{word}»)"
    if not product.get("image"):
        return "sin foto"
    return ""


def same_offer(first: dict, second: dict, rules: dict) -> str:
    """Comprobación final: la segunda lectura tiene que dar el mismo precio y seguir publicable."""
    tolerance = float(rules.get("price_tolerance_eur") or 0)
    if second.get("price") is None or abs(second["price"] - first["price"]) > tolerance + 1e-9:
        return f"el precio ha cambiado ({first.get('price')} → {second.get('price')})"
    if second.get("lowest_30") != first.get("lowest_30"):
        return "la referencia de 30 días ha cambiado"
    return evaluate(second, rules)


# ------------------------------------------------------------------ texto y tarjeta

def euro(amount: float) -> str:
    return f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def clean_title(title: str, limit: int = 95) -> str:
    """Título legible: corta el relleno SEO de Amazon sin partir palabras."""
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
    if pct >= 55:
        return "CHOLLAZO"
    return "CHOLLO"


HEADERS = {
    "ERROR DE PRECIO": "🚨 <b>ERROR DE PRECIO EN AMAZON</b> 🚨",
    "CHOLLAZO": "🔥 <b>CHOLLAZO EN AMAZON</b>",
    "CHOLLO": "💥 <b>CHOLLO EN AMAZON</b>",
}


def build_caption(product: dict, url: str, rules: dict, checked: datetime, ended: str = "") -> str:
    e = html.escape
    price = product["price"]
    reference = product["lowest_30"]
    pct = discount_pct(price, reference)
    lines = []
    if ended:
        lines += [ended, ""]
    lines += [HEADERS[badge_for(pct, rules)], "", f"<b>{e(clean_title(product['title'], 140))}</b>", ""]
    lines.append(f"💰 <b>{e(euro(price))}</b>   <s>{e(euro(reference))}</s>")
    lines.append(f"📉 <b>-{round(pct)} %</b> frente a su precio más bajo de los últimos 30 días")
    lines.append(f"🤑 Te ahorras <b>{e(euro(reference - price))}</b>")
    extra = []
    if product.get("rating") and product.get("reviews"):
        extra.append(f"⭐ {str(round(product['rating'], 1)).replace('.', ',')} "
                     f"({product['reviews']:,} opiniones)".replace(",", "."))
    if amazon_fulfils(product):
        extra.append("📦 Enviado por Amazon")
    if extra:
        lines.append(" · ".join(extra))
    if product.get("coupon"):
        lines.append("🎟️ Mira la ficha: además tiene cupón")
    lines.append("")
    lines.append(f"🕒 Precio comprobado en Amazon.es a las {checked.astimezone(MADRID):%H:%M}. "
                 f"Puede cambiar en cualquier momento.")
    lines.append("")
    lines.append(f'🔗 <b><a href="{e(url, quote=True)}">Ver en Amazon</a></b>')
    return "\n".join(lines)


def buttons(url: str) -> dict:
    return {"inline_keyboard": [[{"text": "🛒 Ver en Amazon", "url": url}]]}


def make_card(product: dict, rules: dict) -> Path:
    import photos
    from publisher import DEAL_LOGO, create_price_card

    OUTPUT.mkdir(parents=True, exist_ok=True)
    image_path = None
    raw = photos.fetch_best(product["image"]) if product.get("image") else None
    if raw:
        image_path = OUTPUT / f"{product['asin']}.img"
        image_path.write_bytes(raw)
    if image_path is None:
        raise ValueError("no he podido descargar la foto del producto")
    pct = discount_pct(product["price"], product["lowest_30"])
    return create_price_card({
        "id": f"amz-{product['asin']}",
        "title": clean_title(product["title"]),
        "image_path": image_path,
        "category": badge_for(pct, rules),
        "current": product["price"],
        "reference": product["lowest_30"],
        "ref_label": "MÍNIMO ÚLTIMOS 30 DÍAS",
        "logo_path": DEAL_LOGO,
        "store": "Amazon",
        "days": 30,
        "jpeg_quality": 95,
    })


# ------------------------------------------------------------------ descubrimiento

def discover(session, rules: dict, state: dict, now: datetime, log) -> list[dict]:
    urls = list(rules.get("discovery_urls") or [])
    random.shuffle(urls)
    seen = state.setdefault("seen", {})
    recheck = float(rules["recheck_rejected_hours"]) * 3600
    pool: dict[str, dict] = {}
    for url in urls[: int(rules["max_listing_pages_per_run"])]:
        try:
            items = amz.parse_listing(session.get(url))
        except amz.Blocked:
            raise
        except Exception as exc:  # una página caída no para la pasada
            log(f"  Listado {url}: {exc}")
            continue
        useful = [i for i in items if amz.listing_drop(i) + 1e-9 >= float(rules["min_discount_pct"]) - 5]
        log(f"  Listado {url}: {len(items)} productos, {len(useful)} con rebaja suficiente")
        for item in useful:
            last = seen.get(item["asin"]) or {}
            if now.timestamp() - (last.get("t") or 0) < recheck:
                continue
            pool.setdefault(item["asin"], item)
    return sorted(pool.values(), key=amz.listing_drop, reverse=True)


# ------------------------------------------------------------------ seguimiento

ENDED = "⛔ <b>YA NO ESTÁ A ESTE PRECIO</b> (comprobado a las {hour})"


def track_posts(session, tg, state: dict, now: datetime, rules: dict, log, dry: bool) -> None:
    """Vuelve a mirar los posts recientes. Si el precio sube o se agota, lo marca en el canal."""
    horizon = now.timestamp() - float(rules["track_hours"]) * 3600
    live = [p for p in state.get("posts") or []
            if (p.get("t") or 0) >= horizon and not p.get("ended") and p.get("message_id")]
    live.sort(key=lambda p: p.get("checked") or p.get("t") or 0)
    for post in live[: int(rules["max_tracking_checks_per_run"])]:
        try:
            product = amz.fetch_product(session, post["asin"])
        except amz.Blocked:
            raise
        except Exception as exc:
            log(f"  Seguimiento {post['asin']}: {exc}")
            continue
        post["checked"] = int(now.timestamp())
        gone = (not product.get("in_stock") or product.get("price") is None
                or product["price"] > float(post["price"]) + 0.009)
        if not gone:
            log(f"  Seguimiento {post['asin']}: sigue a {euro(float(post['price']))}")
            continue
        note = ENDED.format(hour=f"{now.astimezone(MADRID):%H:%M}")
        caption = note + "\n\n" + post["caption"]
        log(f"  Seguimiento {post['asin']}: terminado (ahora {product.get('price')}, "
            f"stock {product.get('in_stock')})")
        if dry or tg is None:
            continue
        try:
            tg.call("editMessageCaption", {"chat_id": post["chat"], "message_id": post["message_id"],
                                           "caption": caption[:1024], "parse_mode": "HTML",
                                           "reply_markup": buttons(post["url"])})
        except RuntimeError as exc:
            log(f"  No he podido marcar el post {post['message_id']}: {exc}")
            continue
        post["ended"] = int(now.timestamp())


# ------------------------------------------------------------------ pasada

def run(args, cfg: dict, state: dict, now: datetime, tg=None, session=None, log=print) -> int:
    rules = rules_from(cfg)
    if not rules["tag"]:
        log("Falta affiliate_tag en config.json. No publico nada sin tu etiqueta.")
        return 2
    session = session or amz.Session(min_gap=float(rules["request_gap_seconds"]))
    chat = rules["chat_id"]
    target = chat
    if args.test_private:
        target = admin_chat_id(state)
        if not target:
            log("Prueba privada: no encuentro tu chat de administrador.")
            return 2
        log(f"Prueba privada: envío solo a tu chat ({target}), nunca al canal.")
    dry = bool(args.dry_run or tg is None)
    try:
        if not args.test_private:
            track_posts(session, tg, state, now, rules, log, dry)
        if not args.test_private and not args.ignore_limits:
            why = quota_reason(state, now, rules)
            if why:
                log(f"No publico: {why}.")
                return 0
        limit = int(rules["test_private_posts"] if args.test_private else rules["max_per_run"])
        candidates = discover(session, rules, state, now, log)
        log(f"Candidatos a revisar en la ficha: {len(candidates)}")
        approved: list[dict] = []
        checks = 0
        for item in candidates:
            if len(approved) >= limit or checks >= int(rules["max_product_checks_per_run"]):
                break
            checks += 1
            product = amz.fetch_product(session, item["asin"])
            why = evaluate(product, rules)
            if not why and recently_posted(state, item["asin"], product["price"], now, rules):
                why = "ya publicado hace poco y no ha bajado más"
            if not args.test_private:
                state.setdefault("seen", {})[item["asin"]] = {"t": int(now.timestamp()),
                                                              "price": product.get("price"), "why": why}
            label = clean_title(product.get("title") or item.get("title") or "", 60)
            if why:
                log(f"  ✗ {item['asin']} {label}: {why}")
                continue
            pct = discount_pct(product["price"], product["lowest_30"])
            log(f"  ✓ {item['asin']} {label}: {euro(product['price'])} (-{pct:.0f}% vs {euro(product['lowest_30'])})")
            approved.append(product)
        approved.sort(key=lambda p: discount_pct(p["price"], p["lowest_30"]), reverse=True)
        sent = 0
        for first in approved:
            # Segunda lectura justo antes de publicar.
            second = amz.fetch_product(session, first["asin"])
            why = same_offer(first, second, rules)
            if why:
                log(f"  ✗ {first['asin']} descartado en la comprobación final: {why}")
                continue
            checked = datetime.fromtimestamp(second["checked_at"], timezone.utc)
            url = amz.canonical_url(second["asin"], rules["tag"])
            caption = build_caption(second, url, rules, checked)
            if dry:
                log("  [prueba, no se envía]\n" + caption)
                sent += 1
                continue
            card = make_card(second, rules)
            message = tg.send_photo(target, card, caption, {"reply_markup": buttons(url)})
            log(f"  Enviado a {target} (mensaje {message['message_id']}): {clean_title(second['title'], 70)}")
            sent += 1
            if not args.test_private:
                state.setdefault("posts", []).append({
                    "asin": second["asin"], "price": second["price"], "reference": second["lowest_30"],
                    "t": int(now.timestamp()), "url": url, "chat": target,
                    "message_id": int(message["message_id"]), "caption": caption,
                    "title": second["title"][:140],
                })
            time.sleep(2)
        if not sent:
            log("Nada que cumpla todas las reglas en esta pasada.")
    except amz.Blocked as exc:
        log(f"Amazon ha pedido captcha ({exc}). Paro esta pasada sin publicar nada.")
        state["blocked_at"] = int(now.timestamp())
        return 0
    return 0


def run_diagnose(asins: list[str]) -> int:
    """No envía nada: lee unas fichas y enseña lo que el lector saca de cada una."""
    rules = rules_from(load_json(CONFIG_PATH, {}))
    session = amz.Session(min_gap=float(rules["request_gap_seconds"]))
    try:
        if not asins:
            for url in (rules.get("discovery_urls") or [])[:2]:
                items = amz.parse_listing(session.get(url))
                asins += [i["asin"] for i in sorted(items, key=amz.listing_drop, reverse=True)[:3]]
        for asin in asins[:6]:
            page = session.get(f"{amz.BASE}/dp/{asin}?th=1&psc=1")
            print(amz.diagnose(page, asin), flush=True)
    except amz.Blocked as exc:
        print(f"Amazon ha pedido captcha ({exc}). Prueba de nuevo dentro de un rato.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Canal @cazachollos_com: solo Amazon con precio verificado")
    parser.add_argument("--dry-run", action="store_true", help="Lo revisa todo pero no envía nada")
    parser.add_argument("--test-private", action="store_true",
                        help="Envía hasta 3 ejemplos a tu chat privado, nunca al canal")
    parser.add_argument("--ignore-limits", action="store_true", help="Salta cupos y horario (pruebas)")
    parser.add_argument("--diagnose", nargs="*", metavar="ASIN",
                        help="Lee estas fichas (o las primeras de los listados) y enseña qué ve el lector")
    args = parser.parse_args()
    if args.diagnose is not None:
        return run_diagnose(args.diagnose)
    load_env()
    cfg = load_json(CONFIG_PATH, {})
    state = load_json(STATE_PATH, {"posts": [], "seen": {}})
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token and not args.dry_run:
        print("Falta TELEGRAM_BOT_TOKEN en .env", file=sys.stderr)
        return 2
    from scanner import Telegram
    tg = Telegram(token) if token else None
    lines: list[str] = []

    def log(text: str) -> None:
        print(text, flush=True)
        lines.append(text)

    now = datetime.now(timezone.utc)
    log(f"== {now.astimezone(MADRID):%Y-%m-%d %H:%M} ==")
    code = run(args, cfg, state, now, tg=tg, log=log)
    if not args.dry_run and not args.test_private:
        save_state(state)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    old = LOG_PATH.read_text(encoding="utf-8").splitlines()[-1500:] if LOG_PATH.exists() else []
    LOG_PATH.write_text("\n".join(old + lines) + "\n", encoding="utf-8")
    return code


if __name__ == "__main__":
    sys.exit(main())
