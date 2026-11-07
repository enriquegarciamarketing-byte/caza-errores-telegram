#!/usr/bin/env python3
"""Canal @cazachollos_com en la nube (GitHub Actions): solo Amazon.es, solo chollos de verdad.

Amazon bloquea las lecturas desde GitHub, así que los datos salen de Jimmyleaks, que sigue
el precio de Amazon.es producto a producto. Reglas que no se saltan:

- Enlace al producto EXACTO: el ASIN sale del botón de compra de Jimmyleaks (/p/ID/ → amazon.es/dp/ASIN)
  y se publica como https://www.amazon.es/dp/ASIN?tag=<tu etiqueta>. Nunca una búsqueda por EAN.
- El precio tiene que haberse visto en Amazon hace muy poco (max_price_age_minutes) y coincidir
  en el listado y en la ficha. Justo antes de enviar se vuelve a leer la ficha: si cambia, no sale.
- Desde el 3/11/2026 el titular puede ser el PVP recomendado (precio tachado de Amazon), solo si es
  coherente con la media de 90 días y siempre con una bajada real frente al mínimo de 30 días, que
  también sale en el post. Sin PVP coherente, el descuento real de siempre (mínimo de 30 o media de 90).
- Los posts de las últimas 48 h se vuelven a mirar; si sube el precio o se agota, se marca el post.
"""

from __future__ import annotations

import argparse
import difflib
import html
import json
import os
import re
import statistics
import sys
import time
import uuid
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import cascada
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
BACKLOG = 0  # chollos aprobados en la última pasada que no cupieron: la siguiente se adelanta

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
    "wake_before_minutes": 60,
    "max_details_per_run": 15,
    "max_tracking_checks_per_run": 4,
    "recheck_rejected_hours": 6,
    "repost_after_days": 14,
    "repost_min_extra_drop_pct": 10,
    "track_hours": 48,
    "block_keywords": [],
    "cascade_enabled": True,          # revisar también lo que el premium descarta por no dar para revender
    "cascade_max_age_minutes": 75,    # descartes del premium de hace más de esto ya no se miran
    "cascade_max_details": 10,        # fichas extra por pasada solo para esos descartes
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
    # El canal free puede llevar su propio ID de afiliado ("affiliate_tag" dentro de amazon_channel);
    # si no, usa el general de config.json (el del premium).
    rules["tag"] = (str(rules.get("affiliate_tag") or "").strip()
                    or ((cfg or {}).get("affiliate_tag") or "").strip())
    return rules


def save_state(state: dict) -> None:
    state["posts"] = sorted(state.get("posts") or [], key=lambda p: p.get("t") or 0)[-3000:]
    cutoff = time.time() - 30 * 86400
    state["seen"] = {k: v for k, v in (state.get("seen") or {}).items() if (v.get("t") or 0) >= cutoff}
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def merge_states(local: dict, remote: dict) -> dict:
    """Junta la memoria de esta ejecución con la que ya hay en GitHub, sin perder posts de ninguna.

    Si dos ejecuciones se solapan (o un post manual entra a la vez), cada una guarda lo suyo y aquí se suman:
    así ningún producto se vuelve a publicar por no constar que ya salió."""
    merged = dict(remote or {})
    merged.update({k: v for k, v in (local or {}).items() if k not in ("posts", "seen", "rotation", "summary_sent")})
    merged["x_drafts"] = sorted(set((remote or {}).get("x_drafts") or []) | set((local or {}).get("x_drafts") or []))[-50:]

    def key(post: dict):
        return (str(post.get("chat")), post.get("message_id")) if post.get("message_id") else \
            ("sin-mensaje", post.get("asin"), post.get("t"))

    posts: dict = {}
    for post in list((remote or {}).get("posts") or []) + list((local or {}).get("posts") or []):
        old = posts.get(key(post))
        if old is None:
            posts[key(post)] = dict(post)
            continue
        combined = {**old, **post}
        for field in ("ended", "checked"):  # lo que una de las dos ya sabe no se olvida
            values = [x.get(field) for x in (old, post) if x.get(field)]
            if values:
                combined[field] = max(values)
        posts[key(post)] = combined
    merged["posts"] = sorted(posts.values(), key=lambda post: post.get("t") or 0)
    seen = dict((remote or {}).get("seen") or {})
    for item_id, entry in ((local or {}).get("seen") or {}).items():
        if (entry.get("t") or 0) >= ((seen.get(item_id) or {}).get("t") or 0):
            seen[item_id] = entry
    merged["seen"] = seen
    merged["rotation"] = max(int((local or {}).get("rotation") or 0), int((remote or {}).get("rotation") or 0))
    sent = [x for x in ((local or {}).get("summary_sent"), (remote or {}).get("summary_sent")) if x]
    if sent:
        merged["summary_sent"] = max(sent)
    return merged


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


def title_head(title: str) -> str:
    """Marca, modelo y tipo de producto: el título hasta la primera coma (o barra) tras 25 caracteres."""
    cut = len(title)
    for mark in (",", " | ", " – ", " — "):
        at = title.find(mark, 25)
        if at != -1:
            cut = min(cut, at)
    return title[:min(cut, 90)]


# Productos que Amazon Afiliados excluye en los sitios de la UE (Políticas del Programa, Lista de Productos,
# 3(c)): leche de fórmula, bebidas alcohólicas, tabaco y cigarrillos electrónicos (y productos relacionados).
# Nunca salen en el canal, ni con "relajado" ni a mano. Las excepciones evitan falsos positivos
# (copas de vino, sacacorchos, una nevera para cervezas...).
EXCLUIDOS_UE = [
    # alcohol
    "cerveza", "cervezas", "vino", "vinos", "vino tinto", "vino blanco", "cava", "champagne", "champán",
    "champan", "sidra", "vermut", "vermouth", "whisky", "whiskey", "bourbon", "ginebra", "gin", "ron",
    "vodka", "tequila", "mezcal", "brandy", "coñac", "cognac", "licor", "licores", "orujo", "pacharán",
    "pacharan", "sake", "sangría", "sangria", "aguardiente", "absenta", "jägermeister",
    "jagermeister", "baileys", "bebida alcohólica", "bebidas alcohólicas", "lambrusco",
    "albariño", "verdejo", "moscatel", "oporto", "manzanilla de sanlúcar", "hard seltzer",
    # leche de fórmula
    "leche de fórmula", "leche de formula", "fórmula infantil", "formula infantil", "leche infantil",
    "leche de inicio", "leche de continuación", "leche de continuacion", "leche de crecimiento",
    "preparado lácteo infantil", "leche en polvo para bebés", "leche en polvo bebé",
    # tabaco y cigarrillos electrónicos
    "tabaco", "cigarrillo", "cigarrillos", "cigarro", "cigarros", "cigarrillo electrónico",
    "cigarrillos electrónicos", "vaper", "vapers", "vape", "vapeo", "e-liquid", "eliquid", "e-líquido",
    "líquido para vapear", "liquido para vapear", "pod desechable", "pods desechables", "shisha", "cachimba",
    "narguile", "hookah", "papel de liar", "papelillos", "boquillas de liar", "picadura", "nicotina",
    "iqos", "heets", "terea",
]
EXCLUIDOS_UE_EXCEPCIONES = [
    "copa", "copas", "vaso", "vasos", "jarra", "jarras", "decantador", "sacacorchos", "abridor",
    "abrebotellas", "descorchador", "vinoteca", "enfriador", "cubitera", "aireador", "tapón", "tapones",
    "botellero", "nevera", "frigorífico", "dispensador", "grifo", "barril vacío", "kit de elaboración",
    "cava de vino", "cava para vinos", "armario", "vinagre", "camiseta", "sudadera", "taza", "libro", "puzzle", "juego de mesa", "vinilo",
]


def excluido_amazon(title: str) -> str:
    """La palabra que lo hace un Producto Excluido de Amazon Afiliados en la UE, o ''."""
    folded = fold(title)
    has = lambda word: re.search(rf"\b{re.escape(fold(word))}\b", folded) is not None
    if any(has(word) for word in EXCLUIDOS_UE_EXCEPCIONES):
        return ""
    return next((word for word in EXCLUIDOS_UE if has(word)), "")


def interest(title: str, rules: dict) -> dict:
    """Interés del producto para el público general: {'score', 'label', 'blocked'}.

    Lo bloqueado (consumibles, tornillería, papelería, ropa interior…) nunca sale. Lo que más se compra
    online (móviles, aspiradoras, cafeteras, electrodomésticos, muebles…) puntúa más y sale antes.
    La categoría se decide por el arranque del título (qué es el producto). Si la palabra clave solo
    aparece en la descripción ('apto para lavavajillas', 'carga tu móvil'), cuenta como categoría normal
    y nunca como estrella: así una cubertería no sale con los cortes de un electrodoméstico."""
    conf = rules.get("interest") or {}

    def matcher(text: str):
        folded = fold(text)
        return lambda word: re.search(rf"\b{re.escape(fold(word))}\b", folded) is not None

    has = matcher(title)
    excluded = excluido_amazon(title)
    if excluded:
        return {"score": 0, "label": "", "blocked": f"excluido por Amazon: {excluded}"}
    for word in list(conf.get("block") or []) + list(rules.get("block_keywords") or []):
        if has(word):
            return {"score": 0, "label": "", "blocked": word}

    def best_in(check) -> dict:
        best = {"score": 0, "label": "", "blocked": ""}
        for tier in conf.get("tiers") or []:
            # 'not_if': palabras que sacan el producto de esa categoría (detergente para lavadora ≠ lavadora).
            if any(check(word) for word in tier.get("not_if") or []):
                continue
            if tier.get("score", 0) > best["score"] and any(check(word) for word in tier.get("keywords") or []):
                best = {"score": int(tier["score"]), "label": tier.get("label") or "", "blocked": "",
                        "min_discount": tier.get("min_discount")}
        return best

    head = best_in(matcher(title_head(title)))
    if head["score"]:
        return head
    full = best_in(has)
    if full["score"]:
        full["score"] = min(full["score"], int(conf.get("description_max_score", 85)))
        full["min_discount"] = None
    return full


def deal_rank(deal: dict) -> float:
    """Orden de publicación: sobre todo el descuento, luego el interés y los euros ahorrados (con tope)."""
    saved = max(0.0, float(deal.get("reference") or 0) - float(deal.get("price") or 0))
    return 0.25 * float(deal.get("interest") or 0) + 2 * float(deal.get("discount") or 0) + min(saved, 200.0) / 10


def evaluate(item: dict, detail: dict, rules: dict, now: datetime, relaxed: bool = False) -> tuple[str, dict]:
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
    drop_30 = discount_pct(float(price), reference)
    pct, ref_kind = drop_30, ""
    median_90 = hist.get("reference")
    if rules.get("use_media90") and median_90:
        # El mejor descuento real: frente al mínimo de 30 días o frente a la media de 90 días. La media solo
        # cuenta si además ha bajado de verdad ahora (min_real_drop_pct frente al mínimo de 30 días).
        drop_90 = discount_pct(float(price), float(median_90))
        # Y solo si en los 30 días anteriores estuvo cerca de esa media: si ya estuvo mucho más barato
        # (como el Lefant a 799,99 € tras meses a 1.299,99 €), la media exageraría y se queda el mínimo de 30.
        gap = discount_pct(float(reference), float(median_90))
        if (drop_90 > drop_30 + 1e-9 and drop_30 + 1e-9 >= float(rules.get("min_real_drop_pct") or 0)
                and gap <= float(rules.get("media90_max_gap_pct", 15)) + 1e-9):
            pct, ref_kind, reference = drop_90, "media90", float(median_90)
    ref_text = "su media de los 90 días" if ref_kind else "su mínimo de los 30 días anteriores"
    taste = interest(title, rules)
    if taste["blocked"]:
        return f"poco interés («{taste['blocked']}»)", {}
    low = detail.get("low")
    pvp_conf = rules.get("pvp") or {}
    pvp = float(item.get("was") or 0)
    conf = rules.get("interest") or {}
    # PVP recomendado (el precio tachado del listado) como titular, si es coherente con lo que se ha pagado
    # de verdad (no más de max_ratio_median90 veces la media de 90 días) y si ahora hay una bajada real.
    use_pvp = bool(pvp_conf.get("enabled") and pvp > float(price) + 0.009 and median_90
                   and pvp <= float(pvp_conf.get("max_ratio_median90", 2.5)) * float(median_90) + 1e-9)
    if use_pvp:
        floor = float(pvp_conf.get("min_real_drop_relaxed" if relaxed else "min_real_drop", 10))
        if drop_30 + 1e-9 < floor:
            return (f"solo -{drop_30:.0f}% de bajada real frente a su mínimo de los 30 días anteriores "
                    f"({euro(hist['min_30'])})"), {}
        kind = "top" if taste["score"] > 0 and taste.get("min_discount") else ("tier" if taste["score"] > 0 else "any")
        needed = float(pvp_conf.get(("relaxed_" if relaxed else "") + kind, 101))
        pct, ref_kind, reference = discount_pct(float(price), pvp), "pvp", pvp
        if pct + 1e-9 < needed:
            return f"solo -{pct:.0f}% frente a su PVP recomendado ({euro(pvp)})", {}
        any_price = float(conf.get("any_category_min_price_eur", 0))
        if kind == "any" and price < any_price:
            return f"categoría de poco interés (fuera de las top solo desde {any_price:.0f} €)", {}
    else:
        needed = float(taste.get("min_discount") or rules["min_discount_pct"])
        if relaxed and taste["score"] > 0:
            # Sin publicar desde hace rato: se admite la mejor rebaja real de las categorías top, algo menor.
            top = taste["score"] >= 90
            needed = min(needed, float(rules.get("fallback_min_discount_top" if top else "fallback_min_discount") or needed))
        at_low = bool(low and float(price) <= float(low) + 0.009)
        if at_low and taste["score"] >= 90 and rules.get("historical_low_min_discount"):
            # En su precio más bajo de siempre y de lo que más se compra: vale con una rebaja real algo menor.
            needed = min(needed, float(rules["historical_low_min_discount"]))
        if pct + 1e-9 < needed:
            return f"solo -{pct:.0f}% frente a {ref_text} ({euro(reference)})", {}
    if (drop_30 if ref_kind == "pvp" else pct) > float(rules["max_discount_pct"]):
        return f"descuento sospechoso (-{(drop_30 if ref_kind == 'pvp' else pct):.0f}%)", {}
    if hist["drop_age_days"] > int(rules["max_drop_age_days"]):
        return f"lleva {hist['drop_age_days']} días a este precio", {}
    rating, reviews = detail.get("rating"), detail.get("reviews")
    if rating is None or reviews is None:
        return "sin valoraciones", {}
    if rating + 1e-9 < float(rules["min_rating"]):
        return f"valoración baja ({rating})", {}
    if reviews < int(rules["min_reviews"]):
        return f"pocas opiniones ({reviews})", {}
    if taste["score"] <= 0 and conf.get("tiers") and ref_kind != "pvp":
        any_pct = float(conf.get("any_category_min_discount", 101))
        if relaxed and conf.get("any_category_fallback_min_discount") is not None:
            any_pct = min(any_pct, float(conf["any_category_fallback_min_discount"]))
        any_price = float(conf.get("any_category_min_price_eur", 0))
        if pct + 1e-9 < any_pct or price < any_price:
            return (f"categoría de poco interés (fuera de las top solo sale con -{any_pct:.0f}% "
                    f"y desde {any_price:.0f} €)"), {}
    if not detail.get("image"):
        return "sin foto", {}
    return "", {
        "jl_id": item["id"], "title": title, "price": float(price), "reference": reference,
        "median_90": hist["reference"],
        "discount": pct, "ref_kind": ref_kind, "drop_30": drop_30, "min_30": hist["min_30"], "historical_low": bool(low and price <= low + 0.009), "rating": rating,
        "reviews": reviews, "image": detail["image"], "seen_ts": int(item["ts"]), "brand": item.get("brand") or "",
        "interest": taste["score"], "interest_label": taste["label"],
    }


# ------------------------------------------------------------------ cupos

def in_quiet_hours(now: datetime, rules: dict) -> bool:
    start, end = rules.get("quiet_hours") or [1, 8]
    return start <= now.astimezone(MADRID).hour < end


def seconds_until_quiet_end(now: datetime, rules: dict) -> float:
    """Segundos que faltan para que acabe el silencio de hoy (0 si no estamos en silencio)."""
    if not in_quiet_hours(now, rules):
        return 0.0
    _, end = rules.get("quiet_hours") or [1, 8]
    local = now.astimezone(MADRID)
    wake = local.replace(hour=int(end), minute=0, second=0, microsecond=0)
    return max(0.0, (wake - local).total_seconds())


def day_closed(state: dict, now: datetime, rules: dict) -> bool:
    """El día se cierra con el resumen: desde close_time, o en cuanto se ha enviado, no salen más productos."""
    local = now.astimezone(MADRID)
    if state.get("summary_sent") == local.date().isoformat():
        return True
    close = str(rules.get("close_time") or "")
    if close:
        hour, minute = (int(x) for x in close.split(":"))
        if (local.hour, local.minute) >= (hour, minute):
            return True
    return False


def quota_reason(state: dict, now: datetime, rules: dict, already: int = 0) -> str:
    if in_quiet_hours(now, rules):
        return "horario de silencio"
    if day_closed(state, now, rules):
        return "día cerrado con el resumen"
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


def same_product(title_a: str, title_b: str) -> bool:
    """Misma ficha con otro ASIN (otro color, pack o vendedor): el principio del título casi idéntico.

    Se compara el arranque del título, que es donde Amazon pone marca y modelo; así 'Lefant M3 MAX' y
    'Lefant M5 Pro' siguen siendo productos distintos y 'Qrevo S Pro Set (QV 35A)' en dos colores no."""
    a, b = fold(title_a)[:60], fold(title_b)[:60]
    if len(a) < 20 or len(b) < 20:
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.93


def recently_posted(state: dict, asin: str, price: float, now: datetime, rules: dict, title: str = "") -> bool:
    """Ya salió hace poco (mismo ASIN, o el mismo producto con otra ficha) y no ha bajado lo bastante más."""
    window = float(rules["repost_after_days"]) * 86400
    for post in reversed(state.get("posts") or []):
        if now.timestamp() - (post.get("t") or 0) > window:
            break
        if post.get("asin") != asin and not (title and same_product(title, post.get("title") or "")):
            continue
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


def real_drop(deal: dict) -> float | None:
    """Bajada frente al mínimo de 30 días cuando el porcentaje del post es contra la media de 90 días."""
    return deal.get("drop_30") if deal.get("ref_kind") in ("media90", "pvp") else None


def badge_for(pct: float, rules: dict, drop_30: float | None = None) -> str:
    """ERROR DE PRECIO solo si la bajada frente al mínimo de 30 días lo es; contra la media de 90 días, como mucho CHOLLAZO."""
    real = pct if drop_30 is None else drop_30
    if real + 1e-9 >= float(rules["error_discount_pct"]):
        return "ERROR DE PRECIO"
    return "CHOLLAZO" if pct >= 55 else "CHOLLO"


HEADERS = {
    "ERROR DE PRECIO": "🚨 <b>ERROR DE PRECIO EN AMAZON</b> 🚨",
    "CHOLLAZO": "🔥 <b>CHOLLAZO EN AMAZON</b>",
    "CHOLLO": "💥 <b>CHOLLO EN AMAZON</b>",
}


def build_caption(deal: dict, url: str, rules: dict) -> str:
    """Por defecto texto corto y llamativo ("caption_style": "corto"): el detalle del precio (frente a qué
    referencia, mínimo de 30 días, ahorro) ya va en la tarjeta. "completo" vuelve al texto largo de antes."""
    if rules.get("caption_style", "corto") == "corto":
        return build_caption_short(deal, url, rules)
    e = html.escape
    pct = deal["discount"]
    seen = datetime.fromtimestamp(deal["seen_ts"], timezone.utc).astimezone(MADRID)
    lines = [HEADERS[badge_for(pct, rules, real_drop(deal))], "", f"<b>{e(clean_title(deal['title'], 140))}</b>", ""]
    lines.append(f"💰 <b>{e(euro(deal['price']))}</b>   <s>{e(euro(deal['reference']))}</s>")
    # Desde el 7/11/2026 sin comparativas con el historial (mínimo de 30 días, media de 90, mínimo
    # histórico): son datos de terceros y acercan el canal a una alerta de precios, que Amazon no permite.
    lines.append(f"📉 <b>-{round(pct)} %</b> de descuento")
    lines.append(f"🤑 Te ahorras <b>{e(euro(deal['reference'] - deal['price']))}</b>")
    # Sin estrellas ni número de opiniones: Amazon solo deja mostrarlas si salen de su API oficial.
    for extra in deal.get("extra_lines") or []:
        lines.append(e(str(extra)))
    lines.append("")
    hour = deal.get("seen_hhmm") or f"{seen:%H:%M}"
    lines.append(f"🕒 {PRICE_NOTE.format(hour=hour)}")
    lines.append("")
    lines.append(f'🔗 <b><a href="{e(url, quote=True)}">Ver en Amazon</a></b>')
    lines.append("")
    lines.append(f"{PUBLI} {hashtags(deal, rules)}")
    return "\n".join(lines)


def build_caption_short(deal: dict, url: str, rules: dict) -> str:
    e = html.escape
    seen = datetime.fromtimestamp(deal.get("seen_ts") or time.time(), timezone.utc).astimezone(MADRID)
    lines = [HEADERS[badge_for(deal["discount"], rules, real_drop(deal))], "",
             f"<b>{e(clean_title(deal['title'], 90))}</b>", "",
             f"💶 PRECIO: <b>{e(price_tag(deal['price']))}</b>"]
    if deal.get("reference") and float(deal["reference"]) > float(deal["price"]):
        lines.append(f"❌ (Antes: <s>{e(price_tag(deal['reference']))}</s>)")
        lines.append(f"🔥 ¡Te ahorras <b>{e(price_tag(float(deal['reference']) - float(deal['price'])))}</b>! "
                     f"({round(deal['discount'])} % dto.)")
    for extra in deal.get("extra_lines") or []:
        lines.append(e(str(extra)))
    hour = deal.get("seen_hhmm") or f"{seen:%H:%M}"
    lines += ["", f"🕒 {PRICE_NOTE.format(hour=hour)}"]
    if rules.get("post_style", "foto") == "album":  # el álbum no admite botón: el enlace va en el texto
        lines.append(f'🔗 <b><a href="{e(url, quote=True)}">Comprar en Amazon</a></b>')
    lines += ["", f"Visto en {rules.get('chat_id') or '@cazachollos_com'} {PUBLI} {hashtags(deal, rules)}"]
    return "\n".join(lines)


def price_tag(amount: float) -> str:
    """84,99€ y 120€ (sin ,00), como en la tarjeta."""
    return euro(float(amount)).replace(",00 €", "€").replace(" €", "€")


# Hora del precio y aviso corto; la exención completa de Amazon va en el mensaje fijado del canal.
PRICE_NOTE = "Precio a las {hour} · puede cambiar"
PUBLI = "#Publicidad"
TAGS = {"ERROR DE PRECIO": "#ErrorDePrecio", "CHOLLAZO": "#Chollazo", "CHOLLO": "#Chollo"}


def hashtags(deal: dict, rules: dict) -> str:
    """Etiqueta según el descuento, para buscar dentro del canal. Sin #MinimoHistorico desde el 7/11/2026."""
    return TAGS[badge_for(deal["discount"], rules, real_drop(deal))]


def buttons(url: str, style: str = "success") -> dict:
    """Botón del post. Telegram solo admite tres colores ("success" verde, "danger" rojo, "primary" azul); no hay
    amarillo, así que va en verde, el de comprar. Cámbialo con "button_style" en config.json."""
    button = {"text": "🛒 Comprar en Amazon", "url": url}
    if style:
        button["style"] = style
    return {"inline_keyboard": [[button]]}


def x_text(deal: dict, url: str, rules: dict, state: dict | None = None) -> str:
    """Post para X con la voz de x_post.py: sin la palabra Amazon y, hasta tener la API, sin precio ni %."""
    from x_post import build_x_post
    now = datetime.now(MADRID)
    # El ID de la cuenta nueva de afiliados solo va en X (único sitio dado de alta); el canal sigue con el suyo.
    if rules.get("x_affiliate_tag") and deal.get("asin"):
        url = f"https://www.amazon.es/dp/{deal['asin']}?tag={rules['x_affiliate_tag']}"
    badge = badge_for(deal["discount"], rules, real_drop(deal)) if deal.get("discount") is not None else "CHOLLO"
    # Con la API de Amazon ("x_prices": true en config) ya se pueden poner precio y %.
    return build_x_post(deal.get("title") or "", deal.get("brand") or "", url, seed=deal.get("asin") or url,
                        extra_handles=rules.get("x_brand_handles"), badge=badge, price=deal.get("price"),
                        reference=deal.get("reference"), numbers=bool(rules.get("x_prices")),
                        hour=now.hour, month=now.month, day=now.day,
                        recent=state.setdefault("x_recent", []) if state is not None else None)


X_FILTER = {
    "min_interest": 85,          # categorías top: móviles, aspiradoras, cafeteras, electrodomésticos, muebles,
                                 # TV y sonido, informática, consolas, súper, bebé, relojes y droguería
    "min_discount": 40,          # o bien CHOLLAZO / ERROR DE PRECIO
    "historical_low_discount": 30,
    "min_saving_eur": 15,        # nada de productos de 5 € aunque el % sea alto
    "max_per_day": 6,
    "min_minutes_between": 45,   # los errores de precio se saltan la espera, no el tope diario
}


def x_worthy(deal: dict, rules: dict, state: dict, now: datetime) -> str:
    """Devuelve "" si el chollo merece post en X, o el motivo por el que no. X no es el canal: solo lo que
    de verdad interesa a cualquiera (categoría top, descuento fuerte, ahorro que se note) y sin saturar."""
    conf = {**X_FILTER, **(rules.get("x_filter") or {})}
    pct = float(deal.get("discount") or 0)
    badge = badge_for(pct, rules, real_drop(deal)) if deal.get("discount") is not None else "CHOLLO"
    if float(deal.get("interest") or 0) < conf["min_interest"]:
        return f"categoría poco interesante para X ({deal.get('interest_label') or 'sin categoría top'})"
    strong = badge != "CHOLLO" or pct >= conf["min_discount"] or \
        (deal.get("historical_low") and pct >= conf["historical_low_discount"])
    if not strong:
        return f"descuento flojo para X (-{pct:.0f} %)"
    saving = float(deal.get("reference") or 0) - float(deal.get("price") or 0)
    if saving < conf["min_saving_eur"]:
        return f"ahorro pequeño para X ({saving:.0f} €)"
    day = now.astimezone(MADRID).date()
    sent = [t for t in state.get("x_drafts") or [] if datetime.fromtimestamp(t, MADRID).date() == day]
    if len(sent) >= conf["max_per_day"]:
        return f"ya van {len(sent)} posts de X hoy"
    if badge != "ERROR DE PRECIO" and sent and now.timestamp() - max(sent) < conf["min_minutes_between"] * 60:
        return "muy seguido del anterior post de X"
    return ""


def send_x_draft(tg, state: dict, rules: dict, deal: dict, url: str, log=print, test: bool = False,
                 manual: bool = False) -> None:
    """Te manda por privado el texto listo para pegar en X. La vista previa del enlace es la misma
    tarjeta que pondrá X al publicarlo. Nunca va al canal."""
    if rules.get("x_drafts") is False:
        return
    if not manual:
        why = x_worthy(deal, rules, state, datetime.now(timezone.utc))
        if why:
            log(f"  X: no te lo paso ({why})")
            return
    admin = admin_chat_id(state, rules, tg, log)
    if not admin:
        return
    head = "🧪 PRUEBA · " if test else ""
    text = (f"{head}🐦 <b>Para X</b> · mantén pulsado el texto para copiarlo y activa la bandera «Paid partnership» antes de publicar\n\n"
            f"<pre>{html.escape(x_text(deal, url, rules, state))}</pre>")
    try:
        tg.call("sendMessage", {"chat_id": admin, "text": text, "parse_mode": "HTML",
                                "link_preview_options": {"url": url, "prefer_large_media": True}})
        if not test:
            state.setdefault("x_drafts", []).append(int(time.time()))
            state["x_drafts"] = state["x_drafts"][-50:]
    except Exception as exc:  # el post del canal ya ha salido; esto nunca debe tumbar la pasada
        log(f"  No he podido mandarte el texto de X ({exc})")


def send_x_text(tg, cfg: dict, state: dict, text: str, url: str = "", log=print) -> int:
    """Post de X escrito a mano (skill post-x-caza-chollos): solo a tu chat privado, nunca al canal."""
    admin = admin_chat_id(state, rules_from(cfg), tg, log)
    if not admin:
        log("No encuentro tu chat privado con el bot: escríbele algo y vuelve a lanzarlo")
        return 1
    body = (f"🐦 <b>Para X</b> · mantén pulsado el texto para copiarlo y activa la bandera «Paid partnership» antes de publicar\n\n"
            f"<pre>{html.escape(text.strip())}</pre>")
    payload = {"chat_id": admin, "text": body, "parse_mode": "HTML"}
    if url:
        payload["link_preview_options"] = {"url": url, "prefer_large_media": True}
    message = tg.call("sendMessage", payload)
    log(f"Texto de X enviado a tu chat (mensaje {message.get('message_id')})")
    return 0


BAR_LINES = {
    "pvp": ("frente a su", "", "PVP recomendado", ""),
    "media90": ("frente a su precio medio", "de los", "90 días", "anteriores"),
}


def make_card(deal: dict, rules: dict) -> Path:
    """Tarjeta del post. Por defecto la de estilo AliExpress con los colores de Amazon y sin la foto dentro:
    la foto del producto va aparte y tal cual en el álbum (las normas no dejan retocar las imágenes de Amazon).
    "card_style": "clasica" en config vuelve a la tarjeta naranja antigua."""
    if rules.get("card_style", "amazon") != "amazon":
        return make_card_clasica(deal, rules)
    import aliexpress_card

    seen = datetime.fromtimestamp(deal.get("seen_ts") or time.time(), timezone.utc).astimezone(MADRID)
    return aliexpress_card.create_card({
        "id": deal["asin"],
        "title": clean_title(deal["title"], 140),
        "price": deal["price"],
        "reference": deal["reference"],
        "badge": badge_for(deal["discount"], rules, real_drop(deal)),
        "ref_label": {"media90": "MEDIA 90 DÍAS", "pvp": "PVP RECOMENDADO"}.get(deal.get("ref_kind") or "",
                                                                             "MÍNIMO 30 DÍAS ANTES"),
        "bar_lines": BAR_LINES.get(deal.get("ref_kind") or ""),
        "seen_hhmm": deal.get("seen_hhmm") or f"{seen:%H:%M}",
    }, theme="amazon")


def _media_group(tg, chat_id, media: list, files: dict) -> list:
    boundary = "----caza" + uuid.uuid4().hex
    parts = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8")
             for k, v in (("chat_id", str(chat_id)), ("media", json.dumps(media, ensure_ascii=False)))]
    for key, (name, data) in files.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; filename=\"{name}\"\r\n"
                     "Content-Type: image/jpeg\r\n\r\n".encode("utf-8") + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    req = urllib.request.Request(tg.base + "sendMediaGroup", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            result = json.loads(exc.read().decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            result = {"ok": False, "description": f"HTTP {exc.code}"}
    if not result.get("ok"):
        raise RuntimeError(f"Telegram sendMediaGroup: {result.get('description')}")
    return result["result"]


def full_size(image: str) -> str:
    """Foto de Amazon en grande: cambia el sufijo de tamaño (._AC_US100_, ._SL160_…) por ._AC_SL1500_.
    Es la misma foto, solo a más resolución (redimensionar sin deformar sí está permitido)."""
    if re.search(r"(media-amazon|images-amazon|ssl-images-amazon)\.com/images/I/", image):
        return re.sub(r"\._[A-Za-z0-9_,]+_\.(jpg|jpeg|png|webp)$", r"._AC_SL1500_.\1", image)
    return image


def send_product_photo(tg, target, image: str) -> dict:
    """Foto del producto tal cual y en silencio (la notificación la da la tarjeta con el texto que va justo detrás).
    Si es una URL de Amazon, Telegram la baja directamente: no se guarda ni se retoca."""
    if image.startswith("http"):
        return tg.call("sendPhoto", {"chat_id": target, "photo": full_size(image), "disable_notification": True})
    local = ROOT / image
    if not local.is_file():
        raise RuntimeError(f"no encuentro la foto {image}")
    return tg.send_photo(target, local, "", {"disable_notification": True})


def publish(tg, target, deal: dict, rules: dict, caption: str, url: str, log=print) -> dict:
    """Por defecto ("post_style": "foto") un solo mensaje: la foto del producto tal cual y en grande, con el texto
    y el botón "Comprar en Amazon". Si la foto falla, o el chollo no tiene, sale la tarjeta.
    Otros estilos en config: "separadas" (foto y tarjeta en dos mensajes), "album" o "tarjeta"."""
    card = make_card(deal, rules)
    image = str(deal.get("image") or "")
    style = rules.get("post_style", "foto")
    if style == "foto" and image:
        # Solo la foto del producto, a todo lo ancho, con el texto y el botón (como los canales grandes).
        try:
            if image.startswith("http"):
                return tg.call("sendPhoto", {"chat_id": target, "photo": full_size(image), "caption": caption,
                                             "parse_mode": "HTML", "reply_markup": buttons(url, rules.get("button_style", "success"))})
            local = ROOT / image
            if local.is_file():
                return tg.send_photo(target, local, caption, {"reply_markup": buttons(url, rules.get("button_style", "success"))})
        except (RuntimeError, OSError, urllib.error.URLError) as exc:
            log(f"  No he podido mandar la foto del producto ({exc}); mando la tarjeta")
    if style == "separadas" and image:
        try:
            photo = send_product_photo(tg, target, image)
            message = tg.send_photo(target, card, caption, {"reply_markup": buttons(url, rules.get("button_style", "success"))})
            message["photo_message_id"] = photo.get("message_id")
            return message
        except (RuntimeError, OSError, urllib.error.URLError) as exc:
            log(f"  No he podido mandar la foto del producto ({exc}); mando solo la tarjeta")
    if style == "album" and image:
        cap = {"caption": caption, "parse_mode": "HTML"}
        card_item = {"type": "photo", "media": "attach://card"}
        files = {"card": (card.name, card.read_bytes())}
        local = ROOT / image if not image.startswith("http") else None
        try:
            if local:
                if not local.is_file():
                    raise RuntimeError(f"no encuentro la foto {image}")
                media = [{"type": "photo", "media": "attach://photo", **cap}, card_item]
                sent = _media_group(tg, target, media, {"photo": (local.name, local.read_bytes()), **files})
            else:
                sent = _media_group(tg, target, [{"type": "photo", "media": image, **cap}, card_item], files)
            return sent[0]
        except (RuntimeError, OSError, urllib.error.URLError) as exc:
            log(f"  No he podido mandar el álbum ({exc}); mando solo la tarjeta")
    return tg.send_photo(target, card, caption, {"reply_markup": buttons(url, rules.get("button_style", "success"))})


def make_card_clasica(deal: dict, rules: dict) -> Path:
    import photos
    from publisher import DEAL_LOGO, create_price_card

    OUTPUT.mkdir(parents=True, exist_ok=True)
    image_path = None
    # Por defecto la tarjeta lleva el logo del canal y no la foto de Amazon: las normas de afiliados
    # no permiten guardar ni retocar sus imágenes. "amazon_photo": true en config solo cuando la foto venga de la API.
    if rules.get("amazon_photo"):
        image = str(deal.get("image") or "")
        local = ROOT / image if image and not image.startswith("http") else None
        raw = local.read_bytes() if local and local.is_file() else (photos.fetch_best(image) if image else None)
        if not raw:
            raise ValueError("no he podido descargar la foto")
        image_path = OUTPUT / f"{deal['asin']}.img"
        image_path.write_bytes(raw)
    return create_price_card({
        "id": f"amz-{deal['asin']}",
        "title": clean_title(deal["title"]),
        "image_path": image_path,
        "category": badge_for(deal["discount"], rules, real_drop(deal)),
        "current": deal["price"],
        "reference": deal["reference"],
        "ref_label": {"media90": "MEDIA 90 DÍAS", "pvp": "PVP RECOMENDADO"}.get(deal.get("ref_kind") or "",
                                                                             "MÍNIMO 30 DÍAS ANTES"),
        "logo_path": DEAL_LOGO,
        "store": "Amazon",
        "days": 90,
        "jpeg_quality": 95,
    })


# ------------------------------------------------------------------ seguimiento

ENDED = "⛔ <b>YA NO ESTÁ A ESTE PRECIO</b> (comprobado a las {hour})"


def sin_historial(caption: str) -> str:
    """Quita de un texto ya publicado lo que se dejó de poner el 7/11/2026: la línea del mínimo histórico y
    el hashtag #MinimoHistorico (así, al marcar un post como terminado, no vuelven)."""
    lines = [line for line in caption.split("\n") if "Precio más bajo de su historia" not in line]
    return "\n".join(lines).replace(" #MinimoHistorico", "").replace("#MinimoHistorico", "")


def ended_caption(caption: str) -> str:
    """Texto del post terminado: sin enlace a Amazon ni estrellas (los posts antiguos aún las llevan)."""
    kept = [line for line in sin_historial(caption).split("\n")
            if not line.startswith("🔗") and not line.startswith("⭐")]
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept)


def track_posts(tg, state: dict, now: datetime, rules: dict, log, dry: bool, fetch) -> None:
    horizon = now.timestamp() - float(rules["track_hours"]) * 3600
    live = [p for p in state.get("posts") or []
            if (p.get("t") or 0) >= horizon and not p.get("ended") and p.get("message_id") and p.get("jl_id")]
    live.sort(key=lambda p: p.get("checked") or p.get("t") or 0)
    for post in live[: int(rules["max_tracking_checks_per_run"])]:
        try:
            detail = scanner.parse_detail(fetch(f"{JL}/es/dp/{post['jl_id']}/"))
        except Exception as exc:
            post["checked"] = int(now.timestamp())
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
        caption = ENDED.format(hour=f"{now.astimezone(MADRID):%H:%M}") + "\n\n" + ended_caption(post["caption"])
        try:
            # Sin reply_markup Telegram quita el botón: un chollo terminado deja de enlazar a Amazon.
            tg.call("editMessageCaption", {"chat_id": post["chat"], "message_id": post["message_id"],
                                           "caption": caption[:1024], "parse_mode": "HTML"})
            post["ended"] = int(now.timestamp())
        except RuntimeError as exc:
            log(f"  No he podido marcar el post {post['message_id']}: {exc}")


def listing_priority(item: dict, rules: dict | None = None) -> tuple:
    """Qué fichas abrir antes: las grandes bajadas (por tramos de 10 %), luego lo que más interesa y los mínimos históricos."""
    verdict = fold(item.get("verdict") or "")
    price, was = item.get("price") or 0, item.get("was") or 0
    drop = (was - price) / was if was and was > price else 0
    taste = interest(f"{item.get('brand') or ''} {item.get('title') or ''}", rules or {})
    score = -1 if taste["blocked"] else taste["score"]
    if score < 0:
        return (-1, -1, False, 0)
    return (int(drop * 10), score, "minimo historico" in verdict, item.get("ts") or 0)


# ------------------------------------------------------------------ pasada

def live_rules(rules: dict, test: bool) -> dict:
    """Con "album_solo_pruebas": true el álbum nuevo solo sale en las pruebas privadas; el canal sigue igual
    hasta que des el visto bueno y se quite esa línea de config.json."""
    if rules.get("album_solo_pruebas") and not test:
        return {**rules, "card_style": "clasica", "post_style": "tarjeta"}
    return rules


def run(args, cfg: dict, state: dict, now: datetime, tg=None, fetch=None, resolve_asin=None, log=print,
        cascade_loader=None) -> int:
    rules = live_rules(rules_from(cfg), bool(args.test_private))
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
    relaxed = False
    silence = float(rules.get("silence_minutes") or 0) * 60
    if silence and not args.test_private:
        last = max([p.get("t") or 0 for p in state.get("posts") or []] or [0])
        relaxed = now.timestamp() - last >= silence
        if relaxed:
            log(f"Modo sin silencios: {int((now.timestamp() - last) // 60)} min sin publicar; "
                f"admito desde -{rules.get('fallback_min_discount_top')} % en categorías estrella, "
                f"-{(rules.get('interest') or {}).get('any_category_fallback_min_discount', '—')} % en cualquier categoría "
                f"y -{rules.get('fallback_min_discount')} % en el resto de las top.")
    cascade = cascade_items(cfg, rules, now, log, cascade_loader, test=bool(args.dry_run or args.test_private))
    approved = find_deals(rules, state, now, fetch, resolve_asin, log, remember=not args.test_private,
                          relaxed=relaxed, cascade=cascade)
    if args.test_private:
        approved.sort(key=lambda pair: not pair[0].get("cascada"))  # en la prueba, primero los del premium
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
            log("  [prueba, no se envía]\n" + caption + f"\n[botón] {url}")
            sent += 1
            continue
        try:
            message = publish(tg, target, deal, rules, caption, url, log)
        except (OSError, ValueError) as exc:
            log(f"  ✗ {deal['asin']} sin tarjeta: {exc}")
            continue
        origin = " (descarte del premium)" if item.get("cascada") else ""
        log(f"  Enviado a {target} (mensaje {message['message_id']}){origin}: {clean_title(deal['title'], 70)}")
        sent += 1
        send_x_draft(tg, state, rules, deal, url, log, test=bool(args.test_private))
        if not args.test_private:
            record = {
                "asin": deal["asin"], "jl_id": deal["jl_id"], "price": deal["price"],
                "reference": deal["reference"], "t": int(now.timestamp()), "url": url, "chat": target,
                "message_id": int(message["message_id"]), "caption": caption, "title": deal["title"][:140], "photo_message_id": message.get("photo_message_id"),
            }
            if item.get("cascada"):
                record["origen"] = "premium"  # para medir cuánto aporta la cascada
            state.setdefault("posts", []).append(record)
        time.sleep(2)
    global BACKLOG
    BACKLOG = max(0, len(approved) - sent) if sent >= limit else 0
    if not args.test_private:
        # Lo aprobado que no cupo se guarda para la siguiente pasada: el feed general cambia tan rápido que
        # ese producto ya no estaría en los listados. Se vuelve a evaluar entero y con segunda lectura.
        posted = {p.get("jl_id") for p in state.get("posts") or []}
        state["backlog"] = [item for item, _ in approved if item.get("id") not in posted][: int(rules.get("backlog_max", 20))]
    if not sent:
        log("Nada que cumpla todas las reglas en esta pasada.")
    return 0


def cascade_items(cfg: dict, rules: dict, now: datetime, log=print, loader=None, test: bool = False) -> list[dict]:
    """Productos de Amazon que el premium descartó por no dar para revender, como items de listado.

    Nunca lo que el premium ha publicado o tiene esperando tu OK."""
    enabled = rules.get("cascade_enabled", True) and ((cfg or {}).get("cascada") or {}).get("enabled", True)
    if not enabled and not test:
        return []  # apagada: en el canal no entra nada; las pruebas sí la pueden ver
    branch = ((cfg or {}).get("cascada") or {}).get("branch") or cascada.DEFAULT_BRANCH
    if loader:
        entries = loader(log)
    else:
        entries = cascada.load(branch, log)
        if test:
            # Las pruebas también ven lo que dejan las pruebas del premium (rama aparte, nunca el canal).
            entries = entries + cascada.load(f"{branch}-prueba", log)
    if not entries:
        return []
    premium_posts = {str(p.get("id")) for p in load_json(PREMIUM_STATE, {}).get("posts") or [] if p.get("id")}
    max_age = float(rules.get("cascade_max_age_minutes") or 75) * 60
    items = []
    for entry in entries:
        item = dict(entry.get("item") or {})
        jl_id = str(item.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9]{4,12}", jl_id) or jl_id in premium_posts:
            continue
        if now.timestamp() - float(entry.get("t") or 0) > max_age or not cascada.reason_ok(entry.get("reason")):
            continue
        item["cascada"] = str(entry.get("reason") or "")
        items.append(item)
    if items:
        log(f"Cascada del premium: {len(items)} descartes recientes por no dar para revender")
    return items


def sources_for_run(rules: dict, now: datetime, state: dict | None = None) -> list[str]:
    """Las fuentes principales en cada pasada y el resto por turnos, para no cargar la web de golpe."""
    sources = list(rules.get("sources") or [])
    limit = int(rules.get("max_sources_per_run") or 0)
    core = int(rules.get("core_sources") or 0)
    if not limit or len(sources) <= limit:
        return sources
    fixed, rest = sources[:core], sources[core:]
    take = max(0, limit - len(fixed))
    if not rest or not take:
        return fixed
    if state is not None:
        # Con pasadas cada pocos minutos se avanza por turno, no por reloj, para no repetir listados.
        turn = int(state.get("rotation") or 0)
        state["rotation"] = turn + 1
        start = (turn * take) % len(rest)
    else:
        start = (int(now.timestamp()) // 300 * take) % len(rest)
    return fixed + [rest[(start + i) % len(rest)] for i in range(min(take, len(rest)))]


def find_deals(rules: dict, state: dict, now: datetime, fetch, resolve_asin, log, remember: bool = True,
               relaxed: bool = False, cascade: list | None = None) -> list:
    """Busca en los listados y devuelve [(item, deal)] que cumplen todas las reglas, mejor descuento primero.

    `cascade` son productos que el premium descartó por no dar para revender: pasan exactamente
    por las mismas reglas, con la ficha releída aquí."""
    seen = state.setdefault("seen", {})
    recheck = float(rules["recheck_rejected_hours"]) * 3600
    max_age = float(rules["max_price_age_minutes"]) * 60
    pool: dict[str, dict] = {}

    def skip(item: dict) -> bool:
        last = seen.get(item["id"]) or {}
        same_price = last.get("price") is not None and abs(float(last["price"]) - float(item["price"])) < 0.01
        low_discount_only = str(last.get("why") or "").startswith("solo -")
        # ya descartado a este mismo precio; si baja más, se vuelve a mirar
        return same_price and now.timestamp() - (last.get("t") or 0) < recheck and not (relaxed and low_discount_only)

    for url in sources_for_run(rules, now, state if remember else None):
        try:
            items = scanner.parse_listing(fetch(url))
        except Exception as exc:
            log(f"  Listado {url}: {exc}")
            continue
        fresh = [i for i in items if i.get("ts") and now.timestamp() - i["ts"] <= max_age and i.get("price")]
        log(f"  Listado {url}: {len(items)} productos, {len(fresh)} vistos en la última hora")
        for item in fresh:
            if not skip(item):
                pool.setdefault(item["id"], item)
    for item in state.get("backlog") or []:
        if item.get("id") and item.get("ts") and now.timestamp() - item["ts"] <= max_age and item.get("price"):
            pool.setdefault(item["id"], dict(item))
    extra = 0
    for item in cascade or []:
        if not item.get("ts") or now.timestamp() - item["ts"] > max_age or not item.get("price") or skip(item):
            continue
        if not float(rules["min_price_eur"]) <= float(item["price"]) <= float(rules["max_price_eur"]):
            continue  # ni se abre la ficha: no saldría por precio
        if item["id"] in pool:
            pool[item["id"]]["cascada"] = item["cascada"]
        else:
            pool[item["id"]] = item
            extra += 1
    ordered = sorted(pool.values(), key=lambda item: listing_priority(item, rules), reverse=True)
    ordered = [item for item in ordered if listing_priority(item, rules)[0] >= 0]
    budget = int(rules["max_details_per_run"])
    chosen = ordered[:budget]
    # Los descartes del premium tienen fichas propias por pasada: no quitan sitio a los listados.
    chosen += [item for item in ordered[budget:] if item.get("cascada")][: int(rules.get("cascade_max_details") or 0)]
    from_premium = sum(1 for item in chosen if item.get("cascada"))
    log(f"Candidatos a revisar: {len(ordered)}" + (f" ({from_premium} descartes del premium, {extra} que no salían en mis listados)"
                                                   if from_premium else ""))
    approved = []
    for item in chosen:
        try:
            detail = scanner.parse_detail(fetch(f"{JL}/es/dp/{item['id']}/"))
        except Exception as exc:
            log(f"  Ficha {item['id']}: {exc}")
            continue
        why, deal = evaluate(item, detail, rules, now, relaxed=relaxed)
        if not why and item.get("cascada") and (scanner.has_size_variant(detail.get("name") or "")
                                                 or scanner.has_size_variant(item.get("title") or "")):
            why = "tiene tallas y no se puede comprobar el precio de cada una"
        if not why:
            asin = resolve_asin(item["id"])
            if not asin or not ASIN_RE.fullmatch(asin):
                why = "no he podido sacar el producto exacto de Amazon (ASIN)"
            else:
                deal["asin"] = asin
                if recently_posted(state, asin, deal["price"], now, rules, deal["title"]):
                    why = "ya publicado hace poco y no ha bajado más"
        if why and remember:
            # Solo se aparta lo descartado. Lo aprobado que no cabe en esta pasada sale en la siguiente.
            seen[item["id"]] = {"t": int(now.timestamp()), "why": why, "price": item.get("price")}
        label = clean_title(detail.get("name") or item.get("title") or "", 60)
        if why:
            log(f"  ✗ {item['id']} {label}: {why}")
            continue
        tag = " · descarte del premium" if item.get("cascada") else ""
        log(f"  ✓ {deal['asin']} {label}: {euro(deal['price'])} (-{deal['discount']:.0f}% vs {euro(deal['reference'])}){tag}")
        approved.append((item, deal))
    approved.sort(key=lambda pair: deal_rank(pair[1]), reverse=True)
    return approved


# ------------------------------------------------------------------ resumen de la noche

def closing_day(now: datetime, rules: dict):
    """El día que cierra el resumen: el de hoy, o el de ayer si GitHub lo lanza ya de madrugada."""
    local = now.astimezone(MADRID)
    hour = int(str(rules.get("summary_time") or "23:59").split(":")[0])
    return (local - timedelta(days=1)).date() if local.hour < 12 <= hour else local.date()


def summary_items(state: dict, now: datetime, rules: dict, fetch, log, limit: int = 10) -> list[dict]:
    """Los posts del día que siguen activos (vuelve a mirar el precio), mejor descuento primero."""
    today = closing_day(now, rules)
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
                      "image": detail.get("image") or "",
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
    lines += ["🌙 <b>CERRAMOS EL DÍA · LO MEJOR DE HOY EN AMAZON</b>", "",
              f"Los {len(items)} chollos más bestias de hoy que siguen activos ahora mismo 👇", ""]
    for index, item in enumerate(items):
        lines.append(f"{NUMBERS[index]} <b>{e(clean_title(item['title'], 70))}</b>")
        lines.append(f"💰 <b>{e(euro(item['price']))}</b>  <s>{e(euro(item['reference']))}</s>  "
                     f"📉 <b>-{round(item['discount'])} %</b>")
        lines.append(f'🔗 <a href="{e(item["url"], quote=True)}">Ver en Amazon</a>')
        lines.append("")
    lines.append(f"🕒 Precios a las {hour} · pueden cambiar")
    lines.append("😴 Mañana a las 8:00 volvemos con más chollos. Activa las notificaciones 🔔")
    lines.append("")
    lines.append(PUBLI)
    return "\n".join(lines)


def make_summary_collage(items: list[dict], download=None, max_products: int = 4) -> Path | None:
    """Imagen de cierre del resumen: los mejores chollos con precio en naranja, descuento y nombre, y el logo.

    Sin fotos de Amazon (las normas de afiliados no dejan retocarlas ni componerlas en un collage); las fotos
    tal cual ya salen en cada post. Devuelve None con menos de 2 chollos. `download` queda por compatibilidad."""
    from PIL import Image, ImageDraw
    from publisher import BRAND_ORANGE, DEAL_LOGO, _font

    picked = [item for item in items if item.get("price") is not None][:max_products]
    if len(picked) < 2:
        return None

    width, height, margin = 2160, 1080, 50
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    footer_top = 760
    column = (width - 2 * margin) // len(picked)
    tag_h = 120
    dark, grey = "#1A1A1A", "#8A8A8A"

    def fit(text: str, size: int, limit: int, bold: bool = True):
        font = _font(size, bold=bold)
        while draw.textbbox((0, 0), text, font=font)[2] > limit and size > 30:
            size -= 4
            font = _font(size, bold=bold)
        return font

    def centered(text: str, font, y: int, x0: int, fill: str) -> int:
        tb = draw.textbbox((0, 0), text, font=font)
        draw.text((x0 + (column - (tb[2] - tb[0])) // 2 - tb[0], y - tb[1]), text, font=font, fill=fill)
        return tb[3] - tb[1]

    for index, item in enumerate(picked):
        x0 = margin + index * column
        inner = column - 80
        if index:
            draw.line([(x0, margin + 20), (x0, footer_top - 40)], fill="#E6E6E6", width=4)
        # Precio en caja naranja, como las tarjetas de chollos
        text = euro(item["price"]).replace(" €", "€")
        font = fit(text, 92, inner - 56)
        tb = draw.textbbox((0, 0), text, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        bx, by = x0 + (column - tw - 56) // 2, margin + 10
        draw.rounded_rectangle([bx, by, bx + tw + 56, by + tag_h], radius=18, fill=BRAND_ORANGE)
        draw.text((bx + 28 - tb[0], by + (tag_h - th) // 2 - tb[1]), text, font=font, fill="white")
        y = by + tag_h + 45
        # Descuento grande y precio de antes tachado
        y += centered(f"-{round(item.get('discount') or 0)} %", _font(120, bold=True), y, x0, dark) + 35
        before = f"antes {euro(item['reference']).replace(' €', '€')}" if item.get("reference") else ""
        if before:
            bfont = fit(before, 50, inner, bold=False)
            bb = draw.textbbox((0, 0), before, font=bfont)
            bxl = x0 + (column - (bb[2] - bb[0])) // 2
            centered(before, bfont, y, x0, grey)
            mid = y + (bb[3] - bb[1]) // 2
            draw.line([(bxl + draw.textlength("antes ", font=bfont), mid), (bxl + bb[2] - bb[0], mid)],
                      fill=grey, width=4)
            y += bb[3] - bb[1] + 50
        # Nombre del producto, hasta 4 líneas
        tfont = _font(46, bold=True)
        words, lines, line = clean_title(item.get("title") or "", 90).split(), [], ""
        for word in words:
            trial = f"{line} {word}".strip()
            if draw.textbbox((0, 0), trial, font=tfont)[2] <= inner:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
        if len(lines) > 4:
            lines = lines[:4]
            lines[3] = lines[3].rstrip(".,") + "…"
        for text_line in lines:
            if y + 56 > footer_top - 40:
                break
            centered(text_line, tfont, y, x0, dark)
            y += 60

    # Pie: logo del canal y el nombre, a la derecha
    logo_size = 250
    logo = Image.open(DEAL_LOGO).convert("RGB").resize((logo_size, logo_size), Image.LANCZOS)
    name_font = _font(110, bold=True)
    sub_font = _font(46, bold=True)
    name, sub = "Caza Chollos", "t.me/cazachollos_com"
    nb = draw.textbbox((0, 0), name, font=name_font)
    sb = draw.textbbox((0, 0), sub, font=sub_font)
    text_w = max(nb[2] - nb[0], sb[2] - sb[0])
    block_w = logo_size + 40 + text_w
    lx = width - margin - block_w
    ly = height - margin - logo_size
    canvas.paste(logo, (lx, ly))
    tx = lx + logo_size + 40
    name_h, sub_h = nb[3] - nb[1], sb[3] - sb[1]
    ty = ly + (logo_size - (name_h + 24 + sub_h)) // 2
    draw.text((tx - nb[0], ty - nb[1]), name, font=name_font, fill="#1A1A1A")
    draw.text((tx - sb[0], ty + name_h + 24 - sb[1]), sub, font=sub_font, fill=BRAND_ORANGE)
    # A la izquierda del pie, el titular del cierre
    head_font = _font(64, bold=True)
    draw.text((margin, ly + 40), "LO MEJOR DE HOY", font=head_font, fill="#1A1A1A")
    draw.text((margin, ly + 130), "CERRAMOS EL DÍA", font=head_font, fill=BRAND_ORANGE)  # sin la marca Amazon

    OUTPUT.mkdir(parents=True, exist_ok=True)
    out = OUTPUT / "resumen.jpg"
    canvas.save(out, "JPEG", quality=92)
    return out


def run_summary(args, cfg: dict, state: dict, now: datetime, tg=None, fetch=None, resolve_asin=None, log=print) -> int:
    rules = rules_from(cfg)
    fetch = fetch or http_get
    local = now.astimezone(MADRID)
    hour, minute = (int(x) for x in str(rules.get("summary_time") or "23:59").split(":"))
    day = closing_day(now, rules)
    if not args.ignore_limits:
        target = datetime(day.year, day.month, day.day, hour, minute, tzinfo=MADRID)
        window = timedelta(minutes=int(rules.get("summary_window_minutes") or 100))
        if not (target <= local < target + window):
            log(f"Resumen: no es la hora ({local:%H:%M}); se manda a las {hour:02d}:{minute:02d}.")
            return 0
        if state.get("summary_sent") == day.isoformat():
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
                          "image": deal.get("image") or "",
                          "url": f"https://www.amazon.es/dp/{deal['asin']}?tag={rules['tag']}"})
        items.sort(key=lambda item: item["discount"], reverse=True)
    if len(items) < int(rules.get("summary_min_items") or 3) and not args.test_private:
        log(f"Resumen: solo {len(items)} chollos activos hoy; no mando lista.")
        state["summary_sent"] = day.isoformat()
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
    # Al final del todo, la imagen con los mejores del día y el logo. Si falla, el resumen ya ha salido.
    try:
        collage = make_summary_collage(items)
        if collage:
            tg.send_photo(target, collage, "🔔 Mañana a las 8:00 más chollos en @cazachollos_com")
            log("Resumen: imagen de cierre enviada.")
        else:
            log("Resumen: sin fotos suficientes para la imagen de cierre.")
    except Exception as exc:
        log(f"Resumen: no he podido mandar la imagen de cierre ({exc})")
    if not args.test_private:
        state["summary_sent"] = day.isoformat()
    return 0


def manual_deal(spec: dict, rules: dict, resolve=None) -> dict:
    """Chollo escrito a mano a partir de la ficha (captura). Comprueba que los datos tienen sentido.

    Acepta el ASIN, una URL amazon.es/dp/… o un enlace corto (link.amazon, amzn.eu, amzn.to), que se
    resuelve aquí mismo; si el enlace corto lleva a otro producto que el ASIN indicado, no se publica."""
    import affiliate
    asin = str(spec.get("asin") or "").strip().upper()
    url = str(spec.get("url") or "").strip()
    if url:
        final = url
        if affiliate.is_short_link(url):
            final = (resolve or affiliate.resolve_redirects)(url)
        got = affiliate.extract_asin(final) or ""
        if asin and got and got != asin:
            raise ValueError(f"el enlace lleva al producto {got} y no a {asin}")
        asin = asin or got
    if not ASIN_RE.fullmatch(asin):
        raise ValueError("falta un ASIN válido (10 caracteres) o una URL amazon.es/dp/…")
    title = str(spec.get("title") or "").strip()
    price = float(spec["price"])
    reference = float(spec["reference"])
    if not title:
        raise ValueError("falta el título")
    if excluido_amazon(title):
        raise ValueError(f"producto excluido de Amazon Afiliados en la UE ({excluido_amazon(title)})")
    if price <= 0 or reference <= price:
        raise ValueError("el precio de referencia tiene que ser mayor que el precio actual")
    pct = discount_pct(price, reference)
    if pct > float(rules.get("max_discount_pct") or 95):
        raise ValueError(f"descuento de -{pct:.0f} %: revisa los datos")
    ref_kind = spec.get("ref_kind") or ""
    min_30 = float(spec["min_30"]) if spec.get("min_30") else None
    # Contra el PVP nunca es ERROR DE PRECIO por sí solo: la cabecera la decide la bajada real frente al mínimo de 30 días.
    drop_30 = discount_pct(price, min_30) if min_30 else (0.0 if ref_kind == "pvp" else None)
    return {
        "min_30": min_30, "drop_30": drop_30,
        "asin": asin, "jl_id": "", "title": title, "price": price, "reference": reference,
        "median_90": float(spec.get("habitual") or 0), "discount": pct,
        "historical_low": bool(spec.get("historical_low")), "rating": spec.get("rating"),
        "reviews": spec.get("reviews"), "image": spec.get("image") or "", "seen_ts": int(time.time()),
        "seen_hhmm": spec.get("seen_at") or "", "extra_lines": list(spec.get("lines") or []),
        "interest": 0, "interest_label": "", "ref_kind": spec.get("ref_kind") or "",
    }


def spec_from_jl(spec: dict, rules: dict, now: datetime, fetch=None, resolve_asin=None, log=print) -> dict:
    """Completa un post manual con la ficha de Jimmyleaks: precio y stock de ahora, ASIN, foto, opiniones e historial.

    La referencia es el mínimo de los 30 días anteriores a la bajada si da una rebaja de al menos un 10 %;
    si no, el precio medio de los 90 días, y el post lo dice así. Si el precio ya no es el indicado, no se publica."""
    fetch = fetch or http_get
    jl_id = str(spec["jl_id"]).strip()
    detail = scanner.parse_detail(fetch(f"{JL}/es/dp/{jl_id}/"))
    price = detail.get("price")
    if price is None or not detail.get("in_stock"):
        raise ValueError("sin precio o sin stock en la ficha ahora mismo")
    if spec.get("price") is not None and abs(float(spec["price"]) - float(price)) > 0.009:
        raise ValueError(f"el precio ha cambiado ({spec['price']} → {price})")
    asin = spec.get("asin") or (resolve_asin or asin_from_jl)(jl_id)
    if not asin:
        raise ValueError("no he podido sacar el ASIN de Amazon")
    hist = history_reference(amazon_series(detail.get("series")), float(price), now.astimezone(MADRID).date())
    min30 = hist.get("min_30") if hist.get("ok") else None
    avg90 = (hist.get("reference") if hist.get("ok") else None) or detail.get("avg90")
    out = dict(spec, asin=asin, price=float(price), image=spec.get("image") or detail.get("image") or "",
               title=spec.get("title") or detail.get("name") or "")
    if min30 and discount_pct(float(price), min30) >= 10:
        out.update(reference=float(min30), habitual=float(avg90 or 0))
    elif avg90 and float(avg90) > float(price) and not min30:
        # Sin la línea del mínimo de 30 días (quitada el 7/11/2026), la media de 90 solo vale si no hay
        # precios recientes: si hace poco estuvo cerca de este precio, "Antes" engañaría y no se publica.
        out.update(reference=float(avg90), ref_kind="media90")
    else:
        raise ValueError(f"sin rebaja real (mínimo 30 días {min30}, media 90 días {avg90})")
    low = detail.get("low")
    out.setdefault("historical_low", bool(low and float(price) <= float(low) + 0.009))
    out.setdefault("rating", detail.get("rating"))
    out.setdefault("reviews", detail.get("reviews"))
    checked = None
    try:
        checked = datetime.fromisoformat(str(detail.get("modified")).replace("Z", "+00:00"))
        checked = checked if checked.tzinfo else checked.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    if checked is None:
        raise ValueError("la ficha no dice cuándo se comprobó el precio")
    age = (now - checked).total_seconds() / 60
    if age > float(rules.get("manual_max_price_age_minutes") or 180):
        raise ValueError(f"precio comprobado hace {age:.0f} min: demasiado viejo para publicarlo")
    if not out.get("seen_at"):
        out["seen_at"] = f"{checked.astimezone(MADRID):%H:%M}"
    log(f"Ficha {jl_id}: {price} € · mínimo 30 días {min30} · media 90 días {avg90} · ASIN {asin}")
    return out


def run_manual(args, cfg: dict, state: dict, now: datetime, tg=None, log=print) -> int:
    rules = live_rules(rules_from(cfg), bool(args.test_private))
    if not rules["tag"]:
        log("Falta affiliate_tag en config.json.")
        return 2
    try:
        spec = json.loads(args.manual)
        if spec.get("jl_id"):
            spec = spec_from_jl(spec, rules, now, log=log)
        deal = manual_deal(spec, rules)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, OSError) as exc:
        log(f"Post manual: datos no válidos ({exc}).")
        return 2
    url = f"https://www.amazon.es/dp/{deal['asin']}?tag={rules['tag']}"
    caption = build_caption(deal, url, rules)
    target = admin_chat_id(state, rules, tg, log) if args.test_private else rules["chat_id"]
    if not target:
        log("Post manual: no encuentro tu chat privado. Escribe /start al bot y repite.")
        return 2
    if args.dry_run or tg is None:
        log("[prueba, no se envía]\n" + caption + f"\n[botón] {url}")
        return 0
    message = publish(tg, target, deal, rules, caption, url, log)
    send_x_draft(tg, state, rules, deal, url, log, test=bool(args.test_private), manual=True)
    where = "tu chat (prueba)" if args.test_private else target
    log(f"Post manual enviado a {where} (mensaje {message['message_id']}): {clean_title(deal['title'], 70)}")
    if not args.test_private:
        state.setdefault("posts", []).append({
            "asin": deal["asin"], "jl_id": "", "price": deal["price"], "reference": deal["reference"],
            "t": int(now.timestamp()), "url": url, "chat": target, "message_id": int(message["message_id"]), "photo_message_id": message.get("photo_message_id"),
            "caption": caption, "title": deal["title"][:140], "manual": True,
        })
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Canal @cazachollos_com: solo Amazon, precio verificado")
    parser.add_argument("--dry-run", action="store_true", help="Lo revisa todo pero no envía nada")
    parser.add_argument("--test-private", action="store_true", help="Hasta 3 ejemplos a tu chat, nunca al canal")
    parser.add_argument("--ignore-limits", action="store_true", help="Salta cupos y horario (pruebas)")
    parser.add_argument("--resumen", action="store_true", help="Manda el resumen de la noche (a las 23:59)")
    parser.add_argument("--manual", default="", help="Post hecho a mano (JSON con asin, title, price, reference…)")
    parser.add_argument("--x-texto", default="", help="Solo te manda por privado este texto listo para X")
    parser.add_argument("--x-url", default="", help="Enlace para la vista previa del texto de X")
    parser.add_argument("--merge-state", default="", help="Junta la memoria local con la de este fichero y sale")
    parser.add_argument("--loop", type=int, default=1, help="Pasadas seguidas en esta ejecución")
    parser.add_argument("--every", type=int, default=300, help="Segundos entre pasadas con --loop")
    parser.add_argument("--busy-every", type=int, default=0,
                        help="Segundos hasta la siguiente pasada si quedaron chollos aprobados sin publicar")
    parser.add_argument("--minutes", type=float, default=0,
                        help="Repite pasadas durante estos minutos (en lugar de un número fijo con --loop)")
    args = parser.parse_args()
    cfg = load_json(CONFIG_PATH, {})
    state = load_json(STATE_PATH, {"posts": [], "seen": {}})
    if args.merge_state:
        remote = load_json(Path(args.merge_state), {})
        merged = merge_states(state, remote)
        save_state(merged)
        print(f"Memoria juntada: {len(merged['posts'])} posts ({len(state.get('posts') or [])} locales, "
              f"{len(remote.get('posts') or [])} en GitHub).")
        return 0
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token and not args.dry_run:
        print("Falta TELEGRAM_BOT_TOKEN", file=sys.stderr)
        return 2
    tg = scanner.Telegram(token) if token else None
    now = datetime.now(timezone.utc)
    print(f"== {now.astimezone(MADRID):%Y-%m-%d %H:%M} ==")
    if args.x_texto:
        code = send_x_text(tg, cfg, state, args.x_texto, args.x_url)
    elif args.manual:
        code = run_manual(args, cfg, state, now, tg=tg)
    elif args.resumen:
        code = run_summary(args, cfg, state, now, tg=tg)
    else:
        # GitHub retrasa mucho las tareas frecuentes: cada ejecución hace pasadas seguidas durante un rato.
        # Si quedan chollos aprobados sin publicar, la siguiente pasada se adelanta (--busy-every).
        rules = rules_from(cfg)
        code = 0
        deadline = time.time() + args.minutes * 60 if args.minutes else None
        index = 0
        while True:
            started = time.time()
            now = datetime.now(timezone.utc)
            if index:
                print(f"== pasada {index + 1} · {now.astimezone(MADRID):%H:%M} ==")
            code = run(args, cfg, state, now, tg=tg)
            index += 1
            if not args.dry_run and not args.test_private:
                save_state(state)
            why = quota_reason(state, now, rules)
            if "silencio" in why and deadline is not None and not args.test_private:
                # GitHub arranca el bot más o menos una vez por hora. Si toca poco antes de las 8,
                # espera despierto y publica a las 8 en punto en vez de cerrarse hasta la siguiente.
                left = seconds_until_quiet_end(datetime.now(timezone.utc), rules)
                if 0 < left <= float(rules.get("wake_before_minutes") or 0) * 60:
                    print(f"Silencio: espero {int(left // 60) + 1} min y publico desde las 08:00.")
                    time.sleep(left + 5)
                    deadline = time.time() + args.minutes * 60
                    continue
            if "silencio" in why or "cerrado" in why or args.test_private:
                break
            if deadline is None and index >= args.loop:
                break
            wait = args.busy_every if (BACKLOG and args.busy_every) else args.every
            pause = max(0, wait - (time.time() - started))
            if deadline is not None and time.time() + pause >= deadline:
                break
            time.sleep(pause)
    if not args.dry_run and not args.test_private:
        save_state(state)
    return code


if __name__ == "__main__":
    sys.exit(main())
