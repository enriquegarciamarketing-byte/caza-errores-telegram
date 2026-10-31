"""Categorías premium, tiendas y enlaces sin afiliado de pago."""

from __future__ import annotations

import urllib.parse

import wallapop

# Host fragment, id de config, nombre visible en la tarjeta y el botón.
STORES = (
    ("amazon.", "amazon", "Amazon"),
    ("carrefour.", "carrefour", "Carrefour"),
    ("lidl.", "lidl", "Lidl"),
    ("game.es", "game", "GAME"),
    ("mediamarkt.", "mediamarkt", "MediaMarkt"),
    ("elcorteingles.", "elcorteingles", "El Corte Inglés"),
    ("fnac.", "fnac", "Fnac"),
    ("pccomponentes.", "pccomponentes", "PcComponentes"),
    ("toysrus.", "toysrus", "Toys R Us"),
    ("pokemoncenter.", "pokemoncenter", "Pokémon Center"),
    ("nintendo.", "nintendo", "Nintendo"),
    ("aliexpress.", "aliexpress", "AliExpress"),
    ("privalia.", "privalia", "Privalia"),
    ("zalando-prive.", "zalandoprive", "Zalando Privé"),
    ("zalando.", "zalando", "Zalando"),
    ("miravia.", "miravia", "Miravia"),
    ("decathlon.", "decathlon", "Decathlon"),
    ("primor.", "primor", "Primor"),
    ("druni.", "druni", "Druni"),
    ("worten.", "worten", "Worten"),
    ("ikea.", "ikea", "IKEA"),
    ("leroymerlin.", "leroymerlin", "Leroy Merlin"),
    ("aldi.", "aldi", "Aldi"),
    ("costco.", "costco", "Costco"),
    ("xbox.com", "xbox", "Xbox"),
    ("playstation.com", "playstation", "PlayStation Store"),
)


def store_of(url: str) -> tuple[str, str]:
    """Devuelve (id, nombre). Sin host conocido se queda en Amazon: es el caso del canal histórico."""
    host = (urllib.parse.urlparse(url or "").hostname or "").lower()
    for needle, store_id, label in STORES:
        if needle in host:
            return store_id, label
    if not host:
        return "amazon", "Amazon"
    return "tienda", store_name(host)


SUBDOMAINS = {"www", "es", "m", "s", "shop", "tienda", "store", "click", "go", "web", "app"}
SECOND_LEVEL = {"co", "com", "org", "net"}


def store_name(host: str) -> str:
    """es.aliexpress.com → Aliexpress, shop.atleticodemadrid.com → Atleticodemadrid, x.co.uk → X."""
    parts = [part for part in (host or "").lower().split(".") if part]
    if len(parts) >= 3 and parts[-2] in SECOND_LEVEL:
        parts = parts[:-2]
    elif len(parts) >= 2:
        parts = parts[:-1]
    while len(parts) > 1 and parts[0] in SUBDOMAINS:
        parts = parts[1:]
    name = parts[-1] if parts else "la tienda"
    return name[:1].upper() + name[1:]


def apply_store_template(url: str, cfg: dict) -> str:
    """Plantilla opcional por tienda (`{url}`). Vacía: se publica el enlace tal cual.

    Amazon no pasa por aquí: sigue forzando tag=cazadores_errores-21.
    """
    store_id, _label = store_of(url)
    hooks = ((cfg or {}).get("store_affiliates") or {})
    template = str((hooks.get(store_id) or {}).get("template") or "").strip()
    if not template or "{url}" not in template:
        return url
    return template.replace("{url}", urllib.parse.quote(url, safe=""))


def commodity_hit(cand: dict, rules: dict) -> str | None:
    """Piscinas, alfombrillas, ropa barata y accesorios. Una zapatilla no cuenta como camisa."""
    text = wallapop.fold_text(" ".join([
        cand.get("brand") or "", cand.get("name") or "", cand.get("title") or "",
    ]))
    if any(wallapop.keyword_in(text, word) for word in rules.get("commodity_exceptions") or []):
        return None
    for word in rules.get("commodity_keywords") or []:
        if wallapop.keyword_in(text, word):
            return word
    return None


def priority_info(cand: dict, rules: dict) -> dict:
    """Puntuación para ordenar y para exigir categoría premium. `hold` marca colección."""
    text = wallapop.fold_text(" ".join([
        cand.get("brand") or "", cand.get("name") or "", cand.get("title") or "",
    ]))
    brand = wallapop.fold_text(cand.get("brand") or "")
    best = {"score": 0, "id": "", "hold": False, "label": ""}
    for group in rules.get("priority") or []:
        brands = group.get("brands") or []
        if brands and not any(wallapop.keyword_in(brand, item) or wallapop.keyword_in(text, item) for item in brands):
            continue
        if not any(wallapop.keyword_in(text, word) for word in group.get("keywords") or []):
            continue
        # Un portátil que cita la gráfica no es una GPU suelta.
        if group.get("id") == "componentes" and any(
            wallapop.keyword_in(text, word) for word in ("portatil", "laptop", "notebook")
        ):
            continue
        score = int(group.get("score") or 0)
        if score > best["score"]:
            best = {"score": score, "id": group.get("id") or "", "hold": bool(group.get("hold")),
                    "label": group.get("label") or group.get("id") or ""}
    return best


def overlaps_hot(cand: dict, titles: list[str]) -> bool:
    """El producto comparte marca y otra palabra con un título de más vendidos o movers."""
    own = set(wallapop.tokens(f"{cand.get('brand') or ''} {cand.get('name') or ''} {cand.get('title') or ''}"))
    own = {token for token in own if len(token) >= 3}
    if len(own) < 2:
        return False
    for title in titles or []:
        other = {token for token in wallapop.tokens(title) if len(token) >= 3}
        if len(own & other) >= 2:
            return True
    return False


def product_key(cand: dict) -> str:
    """Misma ficha en dos tiendas: la watchlist manda; si no, marca + modelo."""
    if cand.get("watch_id"):
        return "watch:" + str(cand["watch_id"])
    raw = wallapop.tokens(f"{cand.get('brand') or ''} {cand.get('name') or cand.get('title') or ''}")
    kept = [token for token in raw if token not in wallapop.STOP and len(token) >= 3][:6]
    return "p:" + " ".join(kept)


def reserva_allowed(cand: dict) -> bool:
    """Solo la watchlist, con una justificación de edición limitada o aniversario."""
    if not cand.get("collector"):
        return False
    note = wallapop.fold_text(cand.get("justification") or "")
    if len(note) < 12:
        return False
    return any(word in note for word in ("limitad", "aniversario", "coleccion", "collector", "reserva"))
