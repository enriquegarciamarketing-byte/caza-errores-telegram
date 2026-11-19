"""Texto para X (@AzvensLoL) con la voz de Enrique para trabajar su marca personal: plantillas distintas
(TEMPLATES) que no se repiten entre posts seguidos, gancho en la primera línea, frases cortas en vosotros y
cierre en 👇🏼 con el enlace debajo, para que X pinte la foto del producto en grande.

    Os chivo una cosa antes de que se entere todo el mundo 🤫

    Esta tv de @XiaomiEspana (Xiaomi TV Pro 32 Pulgadas 2026).

    De los descuentos más fuertes que le he visto.

    👇🏼

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
import math
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

# Posts completos con la voz de Enrique (marca personal: el que se montó un bot para no comprar nada a precio
# normal). Cada uno con un gancho distinto arriba, que es lo único que se ve antes del "Mostrar más", y siempre
# acaban en 👇🏼 con el enlace debajo para que X pinte la foto en grande. Algunos cierran con pregunta: en X las
# respuestas pesan mucho más que los likes. {What} = "Esta tv de @XiaomiEspana (Xiaomi TV Pro 32)",
# {a_kind} = "una tv", {why} y {caveat} salen de las listas de abajo. "when" filtra los de temporada u hora.
TEMPLATES = [
    {"id": "bot-aviso", "lines": ["Mi bot acaba de soltar un aviso que no me esperaba 👀", "{What}.", "{why}",
                                  "Os lo dejo aquí antes de que vuele 👇🏼"]},
    {"id": "regla", "lines": ["Regla que me aplico siempre: nada a precio normal.", "Y {what} ahora mismo no lo está.",
                              "{why}", "Aquí lo tenéis 👇🏼"]},
    {"id": "alguien", "lines": ["¿Alguien andaba detrás de {a_kind}?", "{What} acaba de caer.", "{why}",
                                "Luego no digáis que no avisé 👇🏼"], "needs": "kind"},
    {"id": "black-friday", "lines": ["Hay gente esperando al Black Friday para comprar esto.",
                                     "Yo no esperaría: {what} ya ha bajado.", "{why}", "👇🏼"], "when": "noviembre"},
    {"id": "no-dura", "lines": ["Esto no dura ni una tarde.", "{What}.", "{caveat}", "👇🏼"]},
    {"id": "filtro", "lines": ["El bot descarta casi todo lo que ve. Esto ha pasado el filtro:", "{What}.", "{why}",
                               "Enlace abajo 👇🏼"]},
    {"id": "chivatazo", "lines": ["Os chivo una cosa antes de que se entere todo el mundo 🤫", "{What}.", "{why}",
                                  "👇🏼"]},
    {"id": "telegram", "lines": ["Estas cosas me duran minutos en el canal de Telegram.",
                                 "Así que os lo pongo aquí también: {what}.", "{caveat}", "👇🏼"]},
    {"id": "momento", "lines": ["Si os hace falta {a_kind}, es el momento.", "{What}.", "{why}", "👇🏼"],
     "needs": "kind"},
    {"id": "rapido", "lines": ["Pocas veces comparto algo tan rápido.", "{What}.", "{why}", "Corred 👇🏼"]},
    {"id": "cartera", "lines": ["Mi cartera: este mes no compras nada más.", "Yo viendo {what}: 👀", "{why}", "👇🏼"]},
    {"id": "pregunta", "lines": ["{What} acaba de bajar de precio.", "{why}",
                                 "¿Lo pilláis ya o esperáis a ver si baja más? 👇🏼"]},
    {"id": "cabeza", "lines": ["Esto es lo que quiero decir cuando digo que hay que comprar con cabeza.", "{What}.",
                               "{why}", "👇🏼"]},
    {"id": "error", "lines": ["ALERTA 🚨", "Esto huele a error de precio.", "{What}.", "{caveat}", "👇🏼"],
     "badges": ["ERROR DE PRECIO"]},
    {"id": "manana", "lines": ["Café en mano y el bot ya ha cazado algo ☕", "{What}.", "{why}", "👇🏼"],
     "when": "manana"},
    {"id": "noche", "lines": ["Último aviso antes de irme a dormir 😴", "{What}.", "{caveat}", "👇🏼"], "when": "noche"},
    {"id": "comprado", "lines": ["Si no lo tuviera ya, lo pillaba ahora mismo.", "{What}.", "{why}",
                                 "¿Alguien más se lo lleva? 👇🏼"]},
    {"id": "guarda", "lines": ["Guardad este post, que esto no se ve todos los días.", "{What}.", "{why}", "👇🏼"]},
]
# Por qué merece la pena, sin cifras (Amazon sin API).
WHY = {
    "ERROR DE PRECIO": ["Error de precio de manual, nada que ver con lo que cuesta normalmente.",
                        "Tiene toda la pinta de error, no es un precio normal para esto.",
                        "Precio rarísimo para lo que es. Yo no me lo pensaría."],
    "CHOLLAZO": ["De los descuentos más fuertes que le he visto.",
                 "Muy por debajo de su precio habitual, de esos que no se ven cada día.",
                 "El bot lo tenía vigilado y no lo había visto así de bien.",
                 "Precio de los que hacen que te lo replantees aunque no lo necesites."],
    "CHOLLO": ["No es error de precio, pero está bastante mejor que de normal.",
               "Si lo estabais esperando, es buen momento.",
               "Buen precio para algo que se usa todos los días.",
               "De lo que más se vende, y ahora sale bastante más barato."],
}
# Con cifras (AliExpress, y Amazon cuando haya API: "x_prices": true).
WHY_NUMBERS = [
    "Está a {price} cuando a precio normal ronda los {ref}, un {pct}% menos.",
    "Ha bajado a {price} y su precio normal está en {ref} (un {pct}% menos).",
    "{price} cuando lo normal es pagar {ref}. Un {pct}% menos.",
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
                "Yo de vosotros no lo pensaría mucho, que estas vuelan.",
                "Cuando lo veáis ya puede estar agotado, avisados quedáis."],
}
ARTICLES = {"este": "un", "esta": "una", "estos": "unos", "estas": "unas"}
RECENT_KEEP = 8  # plantillas que no se repiten hasta pasados estos posts
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
    if kind and who and tagged:
        return f"{kind} de {who} ({name})"
    if kind:
        # "esta cafetera De'Longhi Magnifica S", sin repetir la palabra del tipo ("cafetera de Cafetera...")
        drop = {w.lower() for w in kind.split()[1:]} | {"robot", "aspirador", "aspiradora"} & set(kind.split())
        rest = [w for w in name.split() if w.lower().strip(",.") not in drop]
        while rest and rest[-1].lower() in {"de", "para", "con", "y", "e", "a", "en"}:
            rest.pop()
        return f"{kind} {' '.join(rest)}".strip()
    if who and tagged:
        return f"esto de {who} ({name})"
    return name or "esto"


def greeting(hour: int | None) -> str:
    if hour is None or 6 <= hour < 13:
        return "Buenos días"
    return "Buenas tardes" if hour < 21 else "Buenas noches"


def indefinite(kind: str) -> str:
    """'esta tv' → 'una tv'."""
    first, _, rest = kind.partition(" ")
    return f"{ARTICLES.get(first, first)} {rest}".strip()


def _fits(template: dict, badge: str, kind: str, hour: int | None, month: int | None, day: int | None) -> bool:
    if template.get("badges") and badge not in template["badges"]:
        return False
    if template.get("needs") == "kind" and not kind:
        return False
    when = template.get("when")
    if when == "noviembre":
        return month == 11 and (day or 0) <= 27
    if when == "manana":
        return hour is not None and 7 <= hour < 11
    if when == "noche":
        return hour is not None and (hour >= 22 or hour < 2)
    return True


def choose_template(seed: str, badge: str, kind: str, hour: int | None = None, month: int | None = None,
                    day: int | None = None, recent: list | None = None) -> dict:
    """Plantilla para este producto sin repetir las últimas usadas (recent se actualiza)."""
    pool = [t for t in TEMPLATES if _fits(t, badge, kind, hour, month, day)]
    fresh = [t for t in pool if t["id"] not in (recent or [])] or pool
    chosen = fresh[hashlib.sha256(f"tpl:{seed}".encode("utf-8")).digest()[0] % len(fresh)]
    if recent is not None:
        recent.append(chosen["id"])
        del recent[:-RECENT_KEEP]
    return chosen


def build_x_post(title: str, brand: str, link: str, seed: str = "", extra_handles: dict | None = None,
                 extra_line: str = "", badge: str = "CHOLLO", price: float | None = None,
                 reference: float | None = None, numbers: bool = False, hour: int | None = None,
                 month: int | None = None, day: int | None = None, recent: list | None = None) -> str:
    seed = seed or link
    badge = badge if badge in WHY else ("CHOLLAZO" if badge == "TOP VENTAS" else "CHOLLO")
    kind = product_kind(title)
    what = _what(title, brand, extra_handles)
    if numbers and price and reference and reference > price:
        pct = round((reference - price) / reference * 100)
        why = _pick(WHY_NUMBERS, seed, "why").format(price=_euro(price), ref=_euro(reference), pct=pct)
    elif numbers and price:
        why = f"Está a {_euro(price)}, de lo más vendido ahora mismo."
    else:
        why = _pick(WHY[badge], seed, "why")
    if kind in CONTEXT and not numbers:
        why = f"{why} {CONTEXT[kind]}"
    caveat = _pick(CAVEAT.get(badge) or CAVEAT["default"], seed, "caveat")
    template = choose_template(seed, badge, kind, hour, month, day, recent)
    values = {"What": what[:1].upper() + what[1:], "what": what, "a_kind": indefinite(kind), "why": why,
              "caveat": caveat}
    lines = [line.format(**values) for line in template["lines"]]
    if extra_line:
        lines.insert(-1, extra_line)
    optional = [i for i, line in enumerate(lines) if line in (why, caveat, extra_line)]
    while True:
        text = "\n\n".join([*lines, link])
        if x_length(text) <= X_LIMIT or not optional:
            return text
        lines.pop(optional.pop())  # si no cabe, cae la línea de contexto antes que el gancho o el cierre


# ------------------------------------------------------------------ estilo «alerta de bajada» (19/11/2026)
# Formato seco de cuenta de alertas, el que Enrique quiere ahora para X ("x_style": "alerta" en config):
#
#     ¡DYSON PENCILWASH FREGONA ELÉCTRICA BAJA DE 200 €!
#
#     Baja de 349 € a 199 €
#
#     Amazon: https://www.amazon.es/dp/B0GJT26L7Z?tag=cazachollos0c-21
#
#     Fregona eléctrica ultraligera con 30 minutos de autonomía y mango ultrafino y ligero
#
#     Precio solo para Prime        (solo si hay condición)
#
#     #ad
#
# En Amazon los precios solo salen si vienen de su API (normas de Afiliados).
ALERT_NAME_WORDS = 5
ALERT_NAME_CHARS = 42
ALERT_DESC_CHARS = 95
SMALL_WORDS = {"de", "del", "la", "el", "los", "las", "y", "e", "o", "u", "con", "sin", "para", "por", "en", "a", "al"}


def euros(amount: float) -> str:
    """169.99 → '169,99 €', 199.0 → '199 €'."""
    text = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return (text[:-3] if text.endswith(",00") else text) + " €"


def price_threshold(price: float) -> int:
    """Número redondo justo por encima del precio: 169,99 → 170; 199 → 200; 47,90 → 50; 9,99 → 10."""
    step = 1 if price < 20 else 5 if price < 50 else 10 if price < 300 else 50 if price < 1000 else 100
    value = math.ceil(price / step) * step
    return int(value + step if value <= price else value)


def alert_name(title: str) -> str:
    """Nombre corto del producto para el titular, sin cortar en una palabra de enlace."""
    head = re.split(r",| - | – |\(|\|", title or "")[0]
    words = re.sub(r"\s+", " ", head).strip().split()[:ALERT_NAME_WORDS]
    while words and len(" ".join(words)) > ALERT_NAME_CHARS:
        words.pop()
    while words and words[-1].lower() in SMALL_WORDS:
        words.pop()
    return " ".join(words) or (title or "").strip()[:ALERT_NAME_CHARS]


# Nombres propios que no se pasan a minúscula en la descripción.
KEEP_CAPS = {"google", "dolby", "vision", "atmos", "alexa", "android", "bluetooth", "wifi", "wi-fi", "apple",
             "windows", "intel", "amd", "nvidia", "ryzen", "core", "geforce", "radeon", "samsung", "sony", "lg",
             "philips", "bosch", "xiaomi", "dyson", "cecotec", "lego", "nintendo", "playstation", "xbox", "gopro",
             "magsafe", "airpods", "iphone", "ipad", "macbook", "galaxy", "pixel", "kindle", "fire", "echo",
             "chromecast", "netflix", "spotify", "thunderbolt", "hdmi", "usb", "gorilla", "glass"}


def _calm(word: str) -> str:
    """'Autonomía' → 'autonomía', pero deja siglas, modelos y marcas (4K60, USB-C, QLED, PencilWash, Google)."""
    letters = [c for c in word if c.isalpha()]
    if not letters or any(c.isdigit() for c in word) or word.isupper() or sum(c.isupper() for c in letters) > 1:
        return word
    if word.lower().strip(".,:") in KEEP_CAPS:
        return word
    return word.lower()


def _kind_words(name: str) -> str:
    """Tipo de producto al final del nombre: 'Dyson PencilWash Fregona Eléctrica' → 'fregona eléctrica'.
    Se queda con las palabras finales normales (sin cifras ni siglas) y nunca con la primera, que es la marca."""
    words = name.split()
    kind = []
    for word in reversed(words[1:]):
        letters = [c for c in word if c.isalpha()]
        if not letters or any(c.isdigit() for c in word) or sum(c.isupper() for c in letters) > 1 \
                or word.lower() in KEEP_CAPS:
            break
        kind.insert(0, word.lower())
    return " ".join(kind)


def alert_description(title: str) -> str:
    """Una línea con lo que es: el resto del título de Amazon, sin gritos ni segmentos de una palabra (colores)."""
    parts = [p.strip() for p in re.split(r",|\||·|;| - | – ", title or "")]
    name = parts[0] if parts else ""
    kept, total = [], 0
    for part in parts[1:]:
        part = re.sub(r"[\(\)\[\]]", "", part).strip()
        if len(part.split()) < 2:
            continue
        part = " ".join(_calm(w) for w in part.split())
        if total + len(part) + 2 > ALERT_DESC_CHARS or len(kept) == 3:
            break
        kept.append(part)
        total += len(part) + 2
    kind = _kind_words(name)
    body = ", ".join(kept)
    if kind and body:
        text = f"{kind} con {body}"
    else:
        text = kind or body
    if " y " not in text and text.count(", ") >= 1:
        head, _, tail = text.rpartition(", ")
        text = f"{head} y {tail}"
    return (text[:1].upper() + text[1:]) if text else ""


def build_alert_post(title: str, link: str, price: float, reference: float | None = None, store: str = "Amazon",
                     condition: str = "", description: str | None = None) -> str:
    """Post de X en formato alerta. Si no cabe en 280, primero cae la descripción y luego se acorta el nombre."""
    name = alert_name(title)
    desc = alert_description(title) if description is None else description
    drop = f"Baja de {euros(reference)} a {euros(price)}" if reference and reference > price + 0.009 \
        else f"Ahora a {euros(price)}"
    while True:
        blocks = [f"¡{name.upper()} BAJA DE {price_threshold(price)} €!", drop, f"{store}: {link}"]
        blocks += [b for b in (desc, condition) if b]
        blocks.append("#ad")
        text = "\n\n".join(blocks)
        if x_length(text) <= X_LIMIT:
            return text
        if desc:
            desc = ""
        elif len(name.split()) > 2:
            name = " ".join(name.split()[:-1])
        else:
            return text
