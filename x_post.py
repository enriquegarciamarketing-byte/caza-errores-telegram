"""Texto para X (@AzvensLoL) con la voz de @kevincrestt: minúsculas, primera persona, cuenta lo que ha
pillado el bot y por qué merece la pena, avisa de los riesgos sin vender humo y cierra con "link afiliado."

    el bot acaba de pillar esta tv de @XiaomiEspana (xiaomi tv pro 32 pulgadas 2026).

    de los descuentos más fuertes que le he visto, así que la comparto a mano.

    estas cosas suelen durar poco, si os interesa no lo dejéis mucho.

    https://link...

    link afiliado.

Reglas para Amazon Afiliados:
- Sin precio, sin % y sin valoraciones: Amazon solo deja mostrarlos si salen de su API. En AliExpress sí
  van (numbers=True), porque su programa lo permite.
- Sin la palabra Amazon ni capturas: la foto la pone la tarjeta automática del enlace.
- El aviso es la etiqueta Paid partnership de X más el "link afiliado." del final, como hace @kevincrestt.
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

OPENERS = [
    "el bot acaba de pillar {what}.",
    "le acaba de saltar al bot {what}.",
    "esto lo ha cazado el bot hace un momento: {what}.",
    "acaba de entrar al bot {what}.",
]
# Por qué merece la pena, sin cifras (Amazon).
WHY = {
    "ERROR DE PRECIO": ["huele a error de precio, muy por debajo de lo que suele costar.",
                        "esto tiene pinta de error, no es un precio normal para este producto."],
    "CHOLLAZO": ["de los descuentos más fuertes que le he visto, por eso lo comparto aquí también.",
                 "está muy por debajo de su precio habitual, de esos que no duran."],
    "CHOLLO": ["buen precio para lo que suele costar, si lo estabais esperando es el momento.",
               "no es un error, pero está bastante mejor que de normal."],
}
# Riesgo o urgencia, contado tal cual.
CAVEAT = {
    "ERROR DE PRECIO": ["probad, a lo mejor cancelan, pero no cuesta nada.",
                        "puede que lo cancelen, así que pedidlo y si cuela, cuela."],
    "default": ["estas cosas suelen durar poco, si os interesa no lo dejéis mucho.",
                "si se agota lo aviso en telegram, pero yo no lo dejaría pasar.",
                "yo de vosotros no lo pensaría mucho, que estas vuelan."],
}
DISCLOSURE = "link afiliado."
X_LIMIT = 280


def product_kind(title: str) -> str:
    low = (title or "").lower()
    for pattern, kind in KINDS:
        if re.search(pattern, low):
            return kind
    return ""


def short_name(title: str, words: int = 6) -> str:
    """Nombre corto en minúsculas: lo que va antes de la primera coma o guion, recortado."""
    head = re.split(r",| - | – |\(|\|", title or "")[0]
    head = re.sub(r"\s+", " ", head).strip()
    return " ".join(head.split()[:words]).lower()


def brand_mention(brand: str, extra: dict | None = None) -> str:
    """@Cuenta oficial si la conocemos; si no, el nombre de la marca en minúsculas."""
    brand = re.sub(r"\s+", " ", (brand or "")).strip()
    if not brand or brand.lower() in {"amazon", "amazon basics", "generico", "genérico", "sin marca"}:
        return ""
    handles = {k.lower(): v for k, v in {**X_HANDLES, **(extra or {})}.items()}
    handle = handles.get(brand.lower())
    if handle:
        return handle if handle.startswith("@") else f"@{handle}"
    return brand.lower()


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


def build_x_post(title: str, brand: str, link: str, seed: str = "", extra_handles: dict | None = None,
                 extra_line: str = "", badge: str = "CHOLLO", price: float | None = None,
                 reference: float | None = None, numbers: bool = False) -> str:
    seed = seed or link
    badge = badge if badge in WHY else ("CHOLLAZO" if badge == "TOP VENTAS" else "CHOLLO")
    opener = _pick(OPENERS, seed, "open").format(what=_what(title, brand, extra_handles))
    if numbers and price:
        if reference and reference > price:
            pct = round((reference - price) / reference * 100)
            why = f"está a {_euro(price)} y lo normal es {_euro(reference)}, un {pct}% menos."
        else:
            why = f"está a {_euro(price)}, de lo más vendido ahora mismo."
    else:
        why = _pick(WHY[badge], seed, "why")
    caveat = _pick(CAVEAT.get(badge) or CAVEAT["default"], seed, "caveat")
    middle = [why] + ([extra_line] if extra_line else []) + [caveat]
    while True:
        text = "\n\n".join([opener, *middle, link, DISCLOSURE])
        if x_length(text) <= X_LIMIT or len(middle) <= 1:
            return text
        middle.pop()  # si no cabe, primero cae el aviso de urgencia
