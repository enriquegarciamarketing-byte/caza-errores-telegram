"""Texto para X (@AzvensLoL) con la voz de @kevincrestt (pero con mayúscula al empezar cada frase): primera
persona, saluda como él ("Buenos días chavales"), cuenta lo que ha pillado el bot y por qué merece la pena,
avisa del riesgo sin vender humo y acaba en el enlace.

    A correr chavales, acaba de saltar esta tv de @XiaomiEspana (Xiaomi TV Pro 32 Pulgadas 2026).

    De los descuentos más fuertes que le he visto.

    Ojo, que estas suelen durar poco.

    https://link...

Reglas para Amazon Afiliados:
- Sin precio, sin % y sin valoraciones: Amazon solo deja mostrarlos si salen de su API. En AliExpress sí
  van (numbers=True), porque su programa lo permite.
- Sin la palabra Amazon ni capturas: la foto la pone la tarjeta automática del enlace.
- El aviso es la etiqueta Paid partnership de X, que Enrique activa en cada post.
- Solo se etiqueta a la marca si su cuenta oficial está en X_HANDLES o en config.json
  ("x_brand_handles"); si no, va el nombre en texto, para no etiquetar cuentas falsas.
"""
from __future__ import annotations

import hashlib
import re

# Cuentas oficiales verificadas. Añade más en config.json -> "x_brand_handles": {"marca": "@Cuenta"}.
X_HANDLES = {"xiaomi": "@XiaomiEspana"}

# Tipo de producto por palabras del título (de lo más concreto a lo más general) con su demostrativo.
KINDS = [
    (r"robot aspirador|aspirador robot|robot de limpieza", "este robot aspirador"),
    (r"\b(smart ?tv|televisor|qled|oled)\b|\btv\b", "esta tv"),
    (r"aspirador|aspiradora", "esta aspiradora"),
    (r"freidora", "esta freidora de aire"),
    (r"cafetera", "esta cafetera"),
    (r"auricular|earbuds|cascos", "estos auriculares"),
    (r"barra de sonido", "esta barra de sonido"),
    (r"altavoz", "este altavoz"),
    (r"smartwatch|reloj inteligente|forerunner|smart band|pulsera de actividad", "este reloj"),
    (r"port[aá]til|laptop|notebook|chromebook", "este portátil"),
    (r"tablet", "esta tablet"),
    (r"smartphone|m[oó]vil|tel[eé]fono|iphone", "este móvil"),
    (r"monitor", "este monitor"),
    (r"teclado", "este teclado"),
    (r"rat[oó]n", "este ratón"),
    (r"memoria ram|ddr[45]", "esta ram"),
    (r"\bssd\b|disco duro|nvme", "este ssd"),
    (r"router|repetidor|mesh", "este router"),
    (r"c[aá]mara", "esta cámara"),
    (r"patinete", "este patinete"),
    (r"bicicleta", "esta bici"),
    (r"zapatillas", "estas zapatillas"),
    (r"nevera|frigor[ií]fico", "esta nevera"),
    (r"lavadora", "esta lavadora"),
    (r"placa de inducci[oó]n|vitrocer", "esta placa de inducción"),
    (r"microondas", "este microondas"),
    (r"batidora|robot de cocina", "este robot de cocina"),
    (r"silla", "esta silla"),
    (r"colch[oó]n", "este colchón"),
    (r"mochila", "esta mochila"),
    (r"cepillo de dientes", "este cepillo eléctrico"),
    (r"afeitadora|maquinilla|cuchillas", "esta afeitadora"),
    (r"pañales", "estos pañales"),
    (r"aceite", "este aceite"),
    (r"consola|playstation|nintendo switch|xbox", "esta consola"),
]

# Aperturas como las de @kevincrestt. {hi} es el saludo según la hora ("Buenos días", "Buenas tardes"...).
OPENERS = [
    "{hi} chavales, el bot acaba de cazar {what}.",
    "{hi} jefes, os enseño lo que acaba de pillar el bot: {what}.",
    "El bot acaba de pillar {what}.",
    "Le acaba de saltar al bot {what}.",
]
OPENERS_URGENT = [  # errores de precio y chollazos
    "A correr chavales, acaba de saltar {what}.",
    "{hi} gente, el bot acaba de cazar {what}.",
    "El bot acaba de cazar {what}.",
]
# Por qué merece la pena, sin cifras (Amazon sin API).
WHY = {
    "ERROR DE PRECIO": ["Error de precio de manual, nada que ver con lo que cuesta normalmente.",
                        "Tiene toda la pinta de error, no es un precio normal para esto."],
    "CHOLLAZO": ["De los descuentos más fuertes que le he visto.",
                 "Muy por debajo de su precio habitual, de esos que no se ven cada día."],
    "CHOLLO": ["No es error de precio, pero está bastante mejor que de normal.",
               "Si lo estabais esperando, es buen momento."],
}
# Con cifras (AliExpress, y Amazon cuando haya API: "x_prices": true).
WHY_NUMBERS = [
    "Está a {price} cuando a precio normal ronda los {ref}, un {pct}% menos.",
    "Ha bajado a {price} y su precio normal está en {ref} (un {pct}% menos).",
]
# Una línea de contexto como las suyas, solo para algunos productos.
CONTEXT = {
    "esta ram": "Ya sabéis que con lo de la IA las ram están disparadas.",
    "este ssd": "Con lo que están subiendo los ssd por la IA, esto no va a durar.",
    "este robot aspirador": "De lo que más se pide, así que no creo que aguante mucho.",
    "esta freidora de aire": "De lo que más se pide, así que no creo que aguante mucho.",
}
# Riesgo o urgencia, contado tal cual.
CAVEAT = {
    "ERROR DE PRECIO": ["Probad, a lo mejor cancelan, pero no cuesta nada.",
                        "Aprovechad antes de que lo corten."],
    "default": ["Ojo, que estas suelen durar poco.",
                "Si se agota lo aviso en Telegram, pero yo no lo dejaría pasar.",
                "Yo de vosotros no lo pensaría mucho, que estas vuelan."],
}
X_LIMIT = 280


def product_kind(title: str) -> str:
    low = (title or "").lower()
    for pattern, kind in KINDS:
        if re.search(pattern, low):
            return kind
    return ""


def tidy(text: str) -> str:
    """Quita los gritos: XIAOMI → Xiaomi, pero deja siglas cortas como TV, QLED o SSD."""
    return " ".join(w.capitalize() if w.isupper() and len(w) > 4 and w.isalpha() else w for w in text.split())


def short_name(title: str, words: int = 6) -> str:
    """Nombre corto: lo que va antes de la primera coma o guion, recortado y sin mayúsculas gritonas."""
    head = re.split(r",| - | – |\(|\|", title or "")[0]
    head = re.sub(r"\s+", " ", head).strip()
    return tidy(" ".join(head.split()[:words]))


def brand_mention(brand: str, extra: dict | None = None) -> str:
    """@Cuenta oficial si la conocemos; si no, el nombre de la marca."""
    brand = re.sub(r"\s+", " ", (brand or "")).strip()
    if not brand or brand.lower() in {"amazon", "amazon basics", "generico", "genérico", "sin marca"}:
        return ""
    handles = {k.lower(): v for k, v in {**X_HANDLES, **(extra or {})}.items()}
    handle = handles.get(brand.lower())
    if handle:
        return handle if handle.startswith("@") else f"@{handle}"
    return tidy(brand) if not brand.islower() else brand.capitalize()


def x_length(text: str) -> int:
    """Longitud aproximada en X: los enlaces cuentan 23 y los emojis 2."""
    text = re.sub(r"https?://\S+", "x" * 23, text)
    return sum(2 if ord(ch) > 0x2000 else 1 for ch in text)


def _pick(options: list[str], seed: str, salt: str) -> str:
    """Siempre lo mismo para el mismo producto, pero rota entre productos (para que X no lo vea repetido)."""
    digest = hashlib.sha256(f"{salt}:{seed}".encode("utf-8")).digest()
    return options[digest[0] % len(options)]


def _euro(amount: float) -> str:
    text = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return (text[:-3] if text.endswith(",00") else text) + "€"


def _what(title: str, brand: str, extra_handles: dict | None) -> str:
    kind = product_kind(title)
    who = brand_mention(brand, extra_handles)
    name = short_name(title)
    tagged = who.startswith("@")
    if kind and who:
        return f"{kind} de {who} ({name})" if tagged else f"{kind} de {name}"
    if who and tagged:
        return f"esto de {who} ({name})"
    return name or "esto"


def greeting(hour: int | None) -> str:
    if hour is None or 6 <= hour < 13:
        return "Buenos días"
    return "Buenas tardes" if hour < 21 else "Buenas noches"


def build_x_post(title: str, brand: str, link: str, seed: str = "", extra_handles: dict | None = None,
                 extra_line: str = "", badge: str = "CHOLLO", price: float | None = None,
                 reference: float | None = None, numbers: bool = False, hour: int | None = None) -> str:
    seed = seed or link
    badge = badge if badge in WHY else ("CHOLLAZO" if badge == "TOP VENTAS" else "CHOLLO")
    kind = product_kind(title)
    pool = OPENERS_URGENT if badge in ("ERROR DE PRECIO", "CHOLLAZO") else OPENERS
    opener = _pick(pool, seed, "open").format(hi=greeting(hour), what=_what(title, brand, extra_handles))
    if numbers and price and reference and reference > price:
        pct = round((reference - price) / reference * 100)
        why = _pick(WHY_NUMBERS, seed, "why").format(price=_euro(price), ref=_euro(reference), pct=pct)
    elif numbers and price:
        why = f"Está a {_euro(price)}, de lo más vendido ahora mismo."
    else:
        why = _pick(WHY[badge], seed, "why")
    caveat = _pick(CAVEAT.get(badge) or CAVEAT["default"], seed, "caveat")
    middle = [why] + ([CONTEXT[kind]] if kind in CONTEXT else []) + ([extra_line] if extra_line else []) + [caveat]
    while True:
        text = "\n\n".join([opener, *middle, link])
        if x_length(text) <= X_LIMIT or len(middle) <= 1:
            return text
        middle.pop()  # si no cabe, cae primero la urgencia: el contexto es lo que más suena a él
