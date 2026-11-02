#!/usr/bin/env python3
"""Exporta los chollos publicados en @cazachollos_com a docs/chollos.json para la web (GitHub Pages).

La web lee ese fichero y pinta los chollos con el mismo enlace de afiliado del canal. Solo salen datos
que el bot ya publicó: título, precio, precio de referencia, hora y si sigue activo o ya no está a ese precio.
No se guarda ninguna foto de Amazon (las normas de afiliados solo lo permiten con la API).

Uso: python web_export.py [--state state/canal_nube.json] [--out docs/chollos.json] [--days 2]
Se ejecuta solo desde tools/guardar_memoria.sh cada vez que se guarda la memoria del canal normal.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import canal_nube as cn

ROOT = Path(__file__).resolve().parent
CHANNEL = "@cazachollos_com"


def load_rules() -> dict:
    try:
        return json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("amazon_channel") or {}
    except (OSError, ValueError):
        return {}


def build(state: dict, rules: dict, now: float, days: float | None = None, limit: int = 240) -> dict:
    # Solo lo que el bot sigue vigilando (track_hours, 48 h): de eso sabemos si sigue o no a ese precio.
    if days is None:
        days = float(rules.get("track_hours") or 48) / 24
    since = now - days * 86400
    latest: dict[str, dict] = {}
    for post in state.get("posts") or []:
        asin, t = post.get("asin"), post.get("t") or 0
        if not asin or t < since or post.get("chat") not in (None, CHANNEL):
            continue
        if asin not in latest or t >= (latest[asin].get("t") or 0):
            latest[asin] = post

    deals = []
    for post in latest.values():
        try:
            price, ref = float(post["price"]), float(post.get("reference") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        if price <= 0 or ref <= price:
            continue
        title = post.get("title") or ""
        try:
            label = cn.interest(title, rules).get("label") or ""
        except Exception:  # la web nunca debe romper el guardado de la memoria
            label = ""
        deals.append({
            "asin": post["asin"],
            "title": cn.clean_title(title, 110),
            "price": round(price, 2),
            "reference": round(ref, 2),
            "pct": round((ref - price) / ref * 100),
            "saving": round(ref - price, 2),
            "url": post.get("url") or f"https://www.amazon.es/dp/{post['asin']}",
            "category": label or "Otros",
            "posted": int(post.get("t") or 0),
            "checked": int(post.get("checked") or post.get("t") or 0),
            "active": not post.get("ended"),
            "ended": int(post["ended"]) if post.get("ended") else None,
            "telegram": f"https://t.me/{CHANNEL.lstrip('@')}/{post['message_id']}" if post.get("message_id") else None,
        })

    deals.sort(key=lambda d: d["posted"], reverse=True)
    return {"generated": int(now), "channel": CHANNEL, "deals": deals[:limit]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state", default=str(ROOT / "state" / "canal_nube.json"))
    parser.add_argument("--out", default=str(ROOT / "docs" / "chollos.json"))
    parser.add_argument("--days", type=float, default=None, help="por defecto, las horas de seguimiento del canal (48 h)")
    args = parser.parse_args()

    try:
        state = json.loads(Path(args.state).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Web: no he podido leer la memoria ({exc}); no toco la web.")
        return 0
    data = build(state, load_rules(), time.time(), days=args.days)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    active = sum(1 for d in data["deals"] if d["active"])
    print(f"Web: {len(data['deals'])} chollos exportados ({active} activos) a {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
