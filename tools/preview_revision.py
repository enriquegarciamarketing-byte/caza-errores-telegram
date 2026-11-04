#!/usr/bin/env python3
"""Prueba del modo revisión: manda a tu chat privado (nunca al canal) un post de ejemplo sin precios.

Usa la foto real del producto desde su ficha de Jimmyleaks y los datos de un post ya publicado.
Uso: TELEGRAM_BOT_TOKEN=... python tools/preview_revision.py JL_ID ASIN "Título" PRECIO REFERENCIA_30_DIAS
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import canal_nube as cn  # noqa: E402
import scanner  # noqa: E402


def main() -> int:
    jl_id, asin, title, price, reference = sys.argv[1:6]
    cfg = cn.load_json(cn.ROOT / "config.json", {})
    rules = dict(cn.rules_from(cfg))
    rules["revision_mode"] = rules.get("revision_mode") or "estricto"
    state = cn.load_json(cn.STATE_PATH, {})
    detail = scanner.parse_detail(cn.http_get(f"{cn.JL}/es/dp/{jl_id}/"))
    now = cn.datetime.now(cn.timezone.utc)
    deal = {
        "asin": asin, "jl_id": jl_id, "title": title, "price": float(price), "reference": float(reference),
        "discount": cn.discount_pct(float(price), float(reference)), "ref_kind": "",
        "image": detail.get("image") or "", "seen_ts": int(time.time()),
        "seen_hhmm": f"{now.astimezone(cn.MADRID):%H:%M}",
    }
    url = f"https://www.amazon.es/dp/{asin}?tag={rules['tag']}"
    caption = "🧪 <b>PRUEBA · MODO REVISIÓN ESTRICTO</b> (no es un post real)\n\n" + cn.build_caption(deal, url, rules)
    print(caption)
    tg = scanner.Telegram(os.environ["TELEGRAM_BOT_TOKEN"].strip())
    target = cn.admin_chat_id(state, rules, tg, print)
    if not target:
        print("No encuentro tu chat privado. Escribe /start al bot y repite.")
        return 2
    try:
        card = cn.make_card(deal, rules)
    except (OSError, ValueError) as exc:
        print(f"Sin foto ({exc}); tarjeta con el logo")
        card = cn.make_card(deal, dict(rules, amazon_photo=False))
    message = tg.send_photo(target, card, caption, {"reply_markup": cn.buttons(url, rules)})
    print(json.dumps({"enviado_a": target, "mensaje": message.get("message_id")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
