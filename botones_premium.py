"""Botones de los posts del premium @caza_errores: «🛒 Comprar en Amazon» y debajo el de unirse al canal free de
Telegram @cazachollos_com (25/11/2026, Enrique; antes era el de WhatsApp). Cuando un post pasa a AGOTADO se quita el
de Amazon y se queda el de Caza Chollos."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


DEFAULT_JOIN = {"text": "📢 Únete a Caza Chollos", "url": "https://t.me/cazachollos_com"}


def _whatsapp() -> dict | None:
    """El botón de debajo en el premium (config: amazon_channel.premium_join_button). Desde el 25/11/2026 lleva al
    canal free de Telegram @cazachollos_com para hacerlo crecer; el nombre se queda por compatibilidad."""
    try:
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cfg = {}
    spec = (cfg.get("amazon_channel") or {}).get("premium_join_button") or DEFAULT_JOIN
    if spec.get("text") and str(spec.get("url") or "").startswith("https://"):
        return {"text": str(spec["text"]), "url": str(spec["url"])}
    return None


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
