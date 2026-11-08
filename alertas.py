"""Alertas privadas de productos concretos (de momento, teles de 98 pulgadas).

Cada pasada del escáner mira todos los productos que ha leído de Jimmyleaks. Si alguno encaja
con una alerta de config.json ("alerts") y tiene un descuento muy fuerte, te llega SOLO a tu
chat privado con el bot (admin_chat_id), nunca al canal. Los productos que encajan se apuntan
para revisar su ficha cada pocas pasadas, así se pilla también una bajada aunque no salga en
los listados.

Prueba a mano:  python alertas.py --test   (te manda lo mejor que haya ahora, sin mínimo).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state" / "scanner.json"
JL_BASE = "https://jimmyleaks.com"

ACCESSORY_WORDS = ("soporte", "funda", "mueble", "cable", "mando", "protector", "pie ", "peana",
                   "montaje", "brazo", "pared", "cubierta", "lampara", "lámpara", "proyector",
                   "pantalla de proyeccion", "pantalla de proyección", "tela", "lona")


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return " " + re.sub(r"\s+", " ", text.lower()) + " "


def size_of(title: str) -> int | None:
    """Pulgadas que anuncia el título: 98", 98 pulgadas, 98'', 98-inch, 98T8D (modelo)…"""
    t = fold(title)
    m = re.search(r"(\d{2,3})\s*(?:\"|''|pulgadas|pulg\b|-?inch\b|in\b)", t)
    if m:
        return int(m.group(1))
    return None


def matches(rule: dict, title: str) -> bool:
    t = fold(title)
    keys = rule.get("keywords") or ["tv", "televisor", "televisores", "television", "smart tv", "qled", "oled", "mini led"]
    if not any(re.search(r"\b" + re.escape(fold(k).strip()) + r"\b", t) for k in keys):
        return False
    for word in rule.get("exclude") or ACCESSORY_WORDS:
        if re.search(r"\b" + re.escape(fold(word).strip()) + r"\b", t):
            return False
    sizes = set(int(s) for s in rule.get("sizes") or [])
    size = size_of(title)
    if size is None:
        # Modelos tipo "98T8D", "98U7" o "100E7Q": el número va pegado al modelo.
        m = re.search(r"\b(\d{2,3})[a-z]{1,3}\d", t)
        size = int(m.group(1)) if m else None
    return size in sizes


def evaluate(rule: dict, price: float | None, refs: dict) -> tuple[bool, float, float | None, str]:
    """¿Es un chollazo? Devuelve (sí/no, % de descuento, precio de referencia, texto de referencia)."""
    if not price:
        return False, 0.0, None, ""
    best = (0.0, None, "")
    for label, ref in refs.items():
        if ref and ref > price:
            pct = (ref - price) / ref * 100
            if pct > best[0]:
                best = (pct, ref, label)
    pct, ref, label = best
    max_price = rule.get("max_price_eur")
    low = refs.get("mínimo histórico")
    hot = pct >= float(rule.get("min_discount", 30))
    if max_price and price <= float(max_price):
        hot = True
    if low and price <= low * 1.001 and pct >= float(rule.get("min_discount_at_low", 15)):
        hot = True
        label = label or "mínimo histórico"
    return hot, pct, ref, label


def caption(rule: dict, cand: dict, pct: float, ref: float | None, label: str, test: bool) -> str:
    def euro(v: float) -> str:
        return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    head = "🧪 PRUEBA · " if test else ""
    lines = [f"{head}📺 <b>{rule.get('label', 'Alerta')}</b>", "", (cand.get("title") or "")[:180], ""]
    lines.append(f"💶 <b>{euro(cand['price'])}</b>")
    if ref:
        lines.append(f"❌ Antes {euro(ref)} ({label}) · <b>-{pct:.0f} %</b>")
    if cand.get("low"):
        lines.append(f"📉 Mínimo histórico {euro(cand['low'])}")
    # Enlace sin afiliado: es para ti, y Amazon no permite comprar con tu propio enlace.
    lines += ["", f"🛒 https://www.amazon.es/dp/{cand['id']}"]
    return "\n".join(lines)


def _send(tg, admin, cand: dict, text: str) -> None:
    image = cand.get("image")
    if image:
        try:
            tg.call("sendPhoto", {"chat_id": admin, "photo": image, "caption": text, "parse_mode": "HTML"})
            return
        except Exception as exc:  # foto no aceptada por Telegram: va el texto solo
            print(f"  Alerta: foto rechazada ({exc}), mando solo el texto")
    tg.call("sendMessage", {"chat_id": admin, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": False})


def check(tg, cfg: dict, state: dict, listings: list[dict], *, fetch, parse_detail,
          dry: bool = False, test: bool = False, now_ts: float | None = None) -> list[dict]:
    """Revisa las alertas. Devuelve lo que ha avisado (o avisaría en dry/test)."""
    rules = [r for r in (cfg.get("alerts") or []) if r.get("enabled", True)]
    if not rules:
        return []
    now_ts = now_ts or time.time()
    mem = state.setdefault("alerts", {})
    watch: dict = mem.setdefault("watch", {})
    sent: dict = mem.setdefault("sent", {})
    passes = mem["passes"] = int(mem.get("passes") or 0) + 1
    admin = state.get("admin_chat_id")

    pool: dict[str, dict] = {}
    for rule in rules:
        for asin in rule.get("asins") or []:
            watch.setdefault(asin, {"rule": rule["id"], "title": "", "t": now_ts})
        for item in listings:
            if matches(rule, item.get("title") or ""):
                watch[item["id"]] = {"rule": rule["id"], "title": item.get("title") or "", "t": now_ts}
                pool[item["id"]] = {**item, "rule": rule["id"]}

    # Fichas vigiladas: en cada pasada de prueba y, si no, cada N pasadas.
    every = max(1, int(cfg.get("alerts_detail_every_passes") or 4))
    if test or passes % every == 1 or every == 1:
        for asin, info in list(watch.items()):
            if now_ts - float(info.get("t") or now_ts) > 60 * 86400:
                watch.pop(asin, None)  # 60 días sin verlo en ningún listado
                continue
            pool.setdefault(asin, {"id": asin, "title": info.get("title") or "", "rule": info["rule"]})

    found = []
    for asin, cand in pool.items():
        rule = next((r for r in rules if r["id"] == cand["rule"]), None)
        if not rule:
            continue
        try:
            detail = parse_detail(fetch(f"{JL_BASE}/es/dp/{asin}/"))
            time.sleep(1)
        except Exception as exc:
            print(f"  Alerta {rule['id']}: ficha {asin} no disponible ({exc})")
            detail = {}
        cand = {**cand, **{k: v for k, v in detail.items() if v not in (None, "", [])}}
        cand["title"] = detail.get("name") or cand.get("title") or ""
        cand["price"] = detail.get("price") or cand.get("price")
        if not matches(rule, cand["title"]):
            continue
        if watch.get(asin) is not None and cand["title"]:
            watch[asin]["title"] = cand["title"]
        if detail and not detail.get("in_stock", True):
            continue
        refs = {"media 90 días": cand.get("avg90"), "precio anterior": cand.get("was"),
                "mínimo histórico": cand.get("low")}
        hot, pct, ref, label = evaluate(rule, cand.get("price"), refs)
        if label == "mínimo histórico" and ref == cand.get("low"):
            ref, label = None, ""  # no es "antes": es que está en el mínimo
        cand.update(pct=pct, ref=ref, ref_label=label, hot=hot)
        print(f"  Alerta {rule['id']}: {asin} · {cand.get('price')} € · -{pct:.0f}% · "
              f"{'CHOLLAZO' if hot else 'no llega'} · {cand['title'][:60]}")
        found.append(cand)

    if test:
        # Prueba: lo mejor que haya ahora, aunque no llegue al mínimo.
        picks = sorted([c for c in found if c.get("price")], key=lambda c: (-c["pct"], c["price"]))[:1]
    else:
        picks = []
        for cand in found:
            if not cand["hot"]:
                continue
            last = sent.get(cand["id"])
            # Mismo precio (o casi) ya avisado en los últimos 7 días: no se repite.
            if last and cand["price"] >= float(last["price"]) * 0.97 and now_ts - float(last["t"]) < 7 * 86400:
                continue
            picks.append(cand)

    for cand in picks:
        rule = next(r for r in rules if r["id"] == cand["rule"])
        text = caption(rule, cand, cand["pct"], cand["ref"], cand["ref_label"], test)
        if dry or not (tg and admin):
            print("  Alerta (no enviada" + (": sin bot o sin admin" if not dry else ", prueba en seco") + "):\n" + text)
            continue
        try:
            _send(tg, admin, cand, text)
            if not test:
                sent[cand["id"]] = {"price": cand["price"], "t": now_ts}
            print(f"  Alerta enviada a tu privado: {cand['id']}")
        except Exception as exc:
            print(f"  Alerta: no se pudo enviar {cand['id']} ({exc})")
    if test and not picks:
        msg = "🧪 PRUEBA · 📺 Ahora mismo no encuentro ninguna tele de 98\" en Jimmyleaks."
        if not dry and tg and admin:
            tg.call("sendMessage", {"chat_id": admin, "text": msg})
        print(msg)
    for key in [k for k, v in sent.items() if now_ts - float(v.get("t") or 0) > 30 * 86400]:
        sent.pop(key, None)
    return picks


def main() -> int:
    import scanner  # aquí y no arriba: scanner importa este módulo

    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Te manda lo mejor que haya ahora, sin mínimo")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    cfg = json.loads(CONFIG_PATH.read_text("utf-8"))
    state = json.loads(STATE_PATH.read_text("utf-8")) if STATE_PATH.exists() else {}
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg = scanner.Telegram(token) if token else None
    listings: dict[str, dict] = {}
    urls = list(cfg.get("sources") or []) + [u for u in cfg.get("rotating_sources") or [] if "/electronica/" in u]
    for url in urls:
        try:
            for item in scanner.parse_listing(scanner.fetch(url)):
                listings.setdefault(item["id"], item)
        except Exception as exc:
            print(f"Aviso: no se pudo leer {url} ({exc})")
        time.sleep(1)
    print(f"Listados: {len(listings)} productos")
    check(tg, cfg, state, list(listings.values()), fetch=scanner.fetch, parse_detail=scanner.parse_detail,
          dry=args.dry_run, test=args.test)
    return 0


if __name__ == "__main__":
    sys.exit(main())
