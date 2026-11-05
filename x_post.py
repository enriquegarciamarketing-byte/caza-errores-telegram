"""Texto para X (@AzvensLoL) con el formato de la tele Xiaomi del 3 nov 2026.

    🚨 Una buena OFERTA FLASH

    TV de la marca @XiaomiEspana a súper buen precio

    🔗 <enlace de afiliado>

    #ad

Reglas que lo hacen apto para Amazon Afiliados (y vale igual para AliExpress):
- Sin precio, sin % y sin valoraciones: Amazon solo deja mostrarlos si salen de su API.
- Sin la palabra Amazon ni capturas: la foto la pone la tarjeta automática del enlace.
- #ad en cada post como aviso de publicidad.
- Solo se etiqueta a la marca si su cuenta oficial está en X_HANDLES o en config.json
  ("x_brand_handles"); si no, va el nombre en texto, para no etiquetar cuentas falsas.
"""
from __future__ import annotations

import hashlib
import re

# Cuentas oficiales verificadas. Añade más en config.json -> "x_brand_handles": {"marca": "@Cuenta"}.
X_HANDLES = {"xiaomi": "@XiaomiEspana"}

HOOKS = ["🚨 Una buena OFERTA FLASH", "🔥 Ojo a este chollo", "⚡ Oferta que vuela", "💥 Precio de locos"]
ENDINGS = ["a súper buen precio", "a precio de risa", "con un descuentazo", "más barato que nunca"]

# Tipo de producto por palabras del título, de lo más concreto a lo más general.
KINDS = [
    (r"\b(smart ?tv|televisor|qled|oled)\b|\btv\b", "TV"),
    (r"robot aspirador|aspirador robot|robot de limpieza", "Robot aspirador"),
    (r"aspirador|aspiradora", "Aspiradora"),
    (r"freidora", "Freidora de aire"),
    (r"cafetera", "Cafetera"),
    (r"auricular|earbuds|cascos", "Auriculares"),
    (r"altavoz", "Altavoz"),
    (r"smartwatch|reloj inteligente|smart band|pulsera de actividad", "Reloj inteligente"),
    (r"port[aá]til|laptop|notebook|chromebook", "Portátil"),
    (r"tablet", "Tablet"),
    (r"smartphone|m[oó]vil|tel[eé]fono", "Móvil"),
    (r"monitor", "Monitor"),
    (r"teclado", "Teclado"),
    (r"rat[oó]n", "Ratón"),
    (r"memoria ram|ddr[45]", "Memoria RAM"),
    (r"\bssd\b|disco duro|nvme", "Disco SSD"),
    (r"router|repetidor|mesh", "Router"),
    (r"c[aá]mara", "Cámara"),
    (r"patinete", "Patinete eléctrico"),
    (r"bicicleta", "Bicicleta"),
    (r"zapatillas", "Zapatillas"),
    (r"nevera|frigor[ií]fico", "Frigorífico"),
    (r"lavadora", "Lavadora"),
    (r"microondas", "Microondas"),
    (r"batidora|robot de cocina", "Robot de cocina"),
    (r"silla", "Silla"),
    (r"colch[oó]n", "Colchón"),
    (r"mochila", "Mochila"),
    (r"cepillo de dientes", "Cepillo eléctrico"),
    (r"afeitadora|maquinilla|cuchillas", "Afeitadora"),
    (r"pañales", "Pañales"),
    (r"aceite", "Aceite"),
    (r"consola|playstation|nintendo|xbox", "Consola"),
]


def product_kind(title: str) -> str:
    low = (title or "").lower()
    for pattern, kind in KINDS:
        if re.search(pattern, low):
            return kind
    return ""


def brand_mention(brand: str, extra: dict | None = None) -> str:
    """@Cuenta oficial si la conocemos; si no, el nombre de la marca tal cual."""
    brand = re.sub(r"\s+", " ", (brand or "")).strip()
    if not brand or brand.lower() in {"amazon", "amazon basics", "generico", "genérico", "sin marca"}:
        return ""
    handles = {k.lower(): v for k, v in {**X_HANDLES, **(extra or {})}.items()}
    handle = handles.get(brand.lower())
    if handle:
        return handle if handle.startswith("@") else f"@{handle}"
    return brand if not brand.isupper() or len(brand) <= 4 else brand.title()


def _pick(options: list[str], seed: str, salt: str) -> str:
    """Elige siempre lo mismo para el mismo producto, pero rota entre productos (para que X no lo vea repetido)."""
    digest = hashlib.sha256(f"{salt}:{seed}".encode("utf-8")).digest()
    return options[digest[0] % len(options)]


def build_x_post(title: str, brand: str, link: str, seed: str = "", extra_handles: dict | None = None,
                 extra_line: str = "") -> str:
    seed = seed or link
    kind = product_kind(title)
    who = brand_mention(brand, extra_handles)
    ending = _pick(ENDINGS, seed, "end")
    if kind and who:
        line = f"{kind} de la marca {who} {ending}"
    elif who:
        line = f"Chollo de la marca {who} {ending}"
    elif kind:
        line = f"{kind} {ending}"
    else:
        line = f"Chollo {ending}"
    parts = [_pick(HOOKS, seed, "hook"), line]
    if extra_line:
        parts.append(extra_line)
    parts += [f"🔗 {link}", "#ad"]
    return "\n\n".join(parts)
