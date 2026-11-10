"""Eventos del premium para la vista en directo del Mac (local/ver_bot.py).

Cada decisión del escáner (producto descartado, error de precio, publicado…) se apunta como una línea JSON en
el fichero de CAZA_EVENTOS, que pone local/caza_errores.sh (uno por día, en state/local_logs/). Sin esa
variable (GitHub Actions, tests) no se escribe nada. Un fallo al escribir nunca para el escáner.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse


def emit(kind: str, **data) -> None:
    path = os.environ.get("CAZA_EVENTOS", "").strip()
    if not path:
        return
    data = {"kind": kind, "t": round(time.time(), 1), **{k: v for k, v in data.items() if v not in (None, "")}}
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError):
        pass


def source_label(url: str) -> str:
    """https://jimmyleaks.com/es/?order=-drop → «Caza Chollos · bajadas de la última hora» (sin nombrar la fuente)."""
    parsed = urllib.parse.urlparse(url or "")
    query = urllib.parse.parse_qs(parsed.query)
    order = (query.get("order") or [""])[0]
    path = [part for part in parsed.path.split("/") if part and part != "es"]
    names = {"-drop": "bajadas de la última hora", "-updated": "actualizados", "-low": "mínimos de hoy",
             "-discount": "más descuento"}
    if path:
        what = path[-1].replace("-", " ")
    elif order:
        what = names.get(order, order.lstrip("-"))
    else:
        what = "portada"
    return f"Caza Chollos · {what}"
