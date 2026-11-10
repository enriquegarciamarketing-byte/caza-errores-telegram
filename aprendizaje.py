"""Lo que el bot aprende de ti (10/11/2026).

1. De tus OK y NO del premium: cada respuesta se apunta por marca, vendedor y búsqueda. Si rechazas varias
   veces la misma marca o el mismo vendedor y nunca le has dado OK, el bot deja de proponerlo (en los dos
   canales). Lo que apruebas sube de prioridad.
2. De lo que vende: el informe de pedidos de Amazon Afiliados (CSV) da peso a las búsquedas y categorías
   que convierten en la comunidad (tools/importar_ventas.py).

Todo se guarda en state/scanner.json → "learning" (lo escribe el premium) y lo leen los dos canales.
"""

from __future__ import annotations

import re
import unicodedata

BLOCK_AFTER_NO = 2  # rechazos sin ningún OK para dejar de proponer una marca o un vendedor


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", text.lower()).split())


def keyword_of(source: str) -> str:
    """«Amazon · robot aspirador» → «robot aspirador»."""
    return str(source or "").split("·", 1)[-1].strip() if "·" in str(source or "") else str(source or "").strip()


def record(state: dict, post: dict, verdict: str) -> list[str]:
    """Apunta tu OK o NO. Devuelve lo que acaba de quedar bloqueado (para decírtelo)."""
    learning = state.setdefault("learning", {})
    newly = []
    for kind, value in (("brand", post.get("brand")), ("seller", post.get("seller")),
                        ("keyword", keyword_of(post.get("source") or ""))):
        key = fold(value)
        if not key or (kind == "seller" and key == "amazon"):
            continue
        row = learning.setdefault(kind, {}).setdefault(key, {"ok": 0, "no": 0, "name": str(value)})
        was_blocked = _blocked(row)
        row["ok" if verdict == "ok" else "no"] += 1
        if kind in ("brand", "seller") and _blocked(row) and not was_blocked:
            newly.append(f"{'la marca' if kind == 'brand' else 'el vendedor'} {row['name']}")
    return newly


def _blocked(row: dict) -> bool:
    return int(row.get("no") or 0) >= BLOCK_AFTER_NO and int(row.get("ok") or 0) == 0


def blocked(learning: dict | None, cand: dict) -> str:
    """Motivo si has rechazado esa marca o ese vendedor varias veces sin ningún OK; "" si no."""
    learning = learning or {}
    for kind, value, label in (("brand", cand.get("brand"), "la marca"), ("seller", cand.get("seller"), "el vendedor")):
        row = (learning.get(kind) or {}).get(fold(value))
        if row and _blocked(row):
            return f"has rechazado {label} {row.get('name') or value} {row['no']} veces: no lo vuelvo a proponer"
    return ""


SALES_PATH = __import__("pathlib").Path(__file__).resolve().parent / "state" / "ventas.json"
_SALES_CACHE: dict = {}


def sales() -> dict:
    """Lo aprendido del informe de pedidos (state/ventas.json, lo escribe tools/importar_ventas.py)."""
    import json
    try:
        mtime = SALES_PATH.stat().st_mtime
    except OSError:
        return {}
    if _SALES_CACHE.get("mtime") != mtime:
        try:
            _SALES_CACHE.update(mtime=mtime, data=json.loads(SALES_PATH.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return {}
    return _SALES_CACHE.get("data") or {}


def keyword_weight(learning: dict | None, keyword: str) -> float:
    """Peso de una búsqueda: sube con tus OK y con las ventas del informe, baja con tus NO. 1 = normal."""
    learning = learning or {}
    row = (learning.get("keyword") or {}).get(fold(keyword)) or {}
    sold = (learning.get("sales") or sales()).get("keywords") or {}
    sales_count = float(sold.get(fold(keyword)) or 0)
    weight = 1.0 + 0.5 * int(row.get("ok") or 0) - 0.25 * int(row.get("no") or 0) + min(sales_count, 20) * 0.25
    return max(0.25, min(weight, 6.0))
