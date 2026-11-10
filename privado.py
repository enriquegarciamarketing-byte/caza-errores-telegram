"""Datos privados fuera del repositorio público.

El repo es público (así GitHub Actions y GitHub Pages salen gratis), así que tu chat privado con el bot no
debe quedar escrito en state/*.json. Con el secreto ADMIN_CHAT_ID en GitHub (Settings → Secrets and variables
→ Actions) el bot lo lee de ahí en cada pasada y lo quita de la memoria antes de guardarla.

Sin ese secreto todo sigue como antes: el chat se guarda en la memoria, para no romper nada.
"""
from __future__ import annotations

import os

PRIVATE_KEYS = ("admin_chat_id", "private_chats")


def admin_id() -> int | None:
    """Tu chat privado si está el secreto ADMIN_CHAT_ID; si no, None."""
    raw = os.environ.get("ADMIN_CHAT_ID", "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def fill(state: dict) -> dict:
    """Pone tu chat (del secreto) en la memoria recién cargada, para el código que lo lee de ahí."""
    admin = admin_id()
    if admin and isinstance(state, dict):
        state["admin_chat_id"] = admin
    return state


def strip(state: dict) -> dict:
    """Copia de la memoria sin los chats privados, solo si el secreto está puesto (si no, no se toca)."""
    if not admin_id() or not isinstance(state, dict):
        return state
    return {k: v for k, v in state.items() if k not in PRIVATE_KEYS}
