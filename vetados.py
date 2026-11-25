"""Productos vetados en todos los canales (free, premium, espejo de Kevin, a mano, AliExpress y X).

25/11/2026 (Enrique): «Descarta publicar los errores o chollos de funkopop de cualquier tipo, a mis
seguidores no les gusta». La lista vive en config.json («vetados_siempre»); si no se puede leer,
se usa la de aquí, para que nunca se cuele un Funko por un fallo de configuración.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

POR_DEFECTO = ["funko", "funkopop", "funko pop", "pop!"]
CONFIG = Path(__file__).with_name("config.json")


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text or "")
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn").lower()


def lista() -> list[str]:
    try:
        extra = json.loads(CONFIG.read_text(encoding="utf-8")).get("vetados_siempre") or []
    except (OSError, ValueError):
        extra = []
    return list(dict.fromkeys(POR_DEFECTO + [str(x) for x in extra]))


def vetado(*textos: str) -> str | None:
    """Primera palabra vetada que aparece en cualquiera de los textos (título, copy, post…), o None."""
    folded = " ".join(_fold(t) for t in textos if t)
    if not folded:
        return None
    for palabra in lista():
        needle = _fold(palabra).strip()
        if not needle:
            continue
        # «pop!» solo cuenta como «POP! Animation», «POP! TV»…, no «pop» suelto (música pop, popcorn).
        if needle == "pop!":
            if re.search(r"(?<![\w])pop!\s*(animation|tv|movies|games|television|rocks|marvel|disney|star wars|"
                         r"heroes|anime|vinyl|deluxe|ride|town|moment|album|keychain)", folded):
                return "Funko POP!"
            continue
        if re.search(rf"(?<![\w]){re.escape(needle)}", folded):  # «funkos», «funkopop» también
            return palabra
    return None
