"""Botones de los posts del premium @caza_errores (23/11/2026, como en el free): «🛒 Comprar en Amazon» y debajo
el de unirse al canal de WhatsApp. Cuando un post pasa a AGOTADO se quita el de Amazon y se queda el de WhatsApp."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _whatsapp() -> dict | None:
    try:
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    wa = (cfg.get("amazon_channel") or {}).get("whatsapp_button") or {}
    return {"text": wa["text"], "url": wa["url"]} if wa.get("text") and wa.get("url") else None


def teclado(link: str) -> dict:
    rows = [[{"text": "🛒 Comprar en Amazon", "url": link, "style": "success"}]]
    wa = _whatsapp()
    if wa:
        rows.append([wa])
    return {"inline_keyboard": rows}


def teclado_terminado() -> dict | None:
    wa = _whatsapp()
    return {"inline_keyboard": [[wa]]} if wa else None


def sin_amazon(markup: dict | None) -> dict | None:
    """El teclado de un post ya publicado sin los botones que llevan a Amazon (para el sello de AGOTADO)."""
    rows = []
    for row in (markup or {}).get("inline_keyboard") or []:
        keep = [b for b in row if "amazon." not in (b.get("url") or "") and "amzn." not in (b.get("url") or "")]
        if keep:
            rows.append(keep)
    return {"inline_keyboard": rows} if rows else None
