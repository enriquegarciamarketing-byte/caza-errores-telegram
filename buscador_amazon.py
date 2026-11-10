"""Premium: errores de precio buscados directamente en Amazon con la API de creadores (10/11/2026).

Jimmyleaks bloquea al bot (HTTP 403), así que el premium busca en Amazon con la API oficial: en cada pasada
lanza unas pocas búsquedas de la lista de config.json (amazon_search.keywords), por turnos, pidiendo solo
productos con un ahorro grande (minSavingPercent). La API da hasta ~8.640 consultas al día (1 por segundo),
así que van pocas por pasada y la lista entera se recorre cada ~30-40 min.

Solo vale un error si Amazon compara con un precio honesto:
- WAS_PRICE: el precio mediano reciente del producto.
- LOWEST_PRICE / LOWEST_PRICE_STRIKETHROUGH: el más bajo de los últimos 30 días (lo que marca la ley en la UE).
El «precio recomendado» (LIST_PRICE) se descarta: muchos vendedores lo inflan para aparentar descuentos.
"""

from __future__ import annotations

import time
from datetime import datetime

from amazon_api import PRICE_RESOURCES, ApiError, _get

RESOURCES = PRICE_RESOURCES + ["itemInfo.byLineInfo", "itemInfo.externalIds", "offersV2.listings.merchantInfo",
                                "offersV2.listings.dealDetails", "offersV2.listings.isBuyBoxWinner",
                                "offersV2.listings.condition"]
AMAZON_SELLER_IDS = {"A1AT7YVPFBWXBL"}  # Amazon.es
HONEST = {
    "WAS_PRICE": "frente a su precio mediano en Amazon",
    "LOWEST_PRICE": "frente a su precio más bajo de los últimos 30 días",
    "LOWEST_PRICE_STRIKETHROUGH": "frente a su precio más bajo de los últimos 30 días",
}


def next_batch(conf: dict, state: dict) -> list[str]:
    keywords = [k for k in conf.get("keywords") or [] if str(k).strip()]
    if not keywords:
        return []
    per = max(1, int(conf.get("per_pass") or 4))
    start = int(state.get("amazon_search_index") or 0) % len(keywords)
    batch = [keywords[(start + i) % len(keywords)] for i in range(min(per, len(keywords)))]
    state["amazon_search_index"] = (start + len(batch)) % len(keywords)
    return batch


def to_candidate(item: dict, keyword: str, cfg: dict, now: datetime, tag: str) -> tuple[dict, str]:
    """(candidato, "") si pinta a error de precio; (datos para el log, motivo) si no."""
    asin = str(item.get("asin") or "").upper()
    title = _get(item, "itemInfo", "title", "displayValue", default="") or ""
    brand = (_get(item, "itemInfo", "byLineInfo", "brand", "displayValue", default="")
             or _get(item, "itemInfo", "byLineInfo", "manufacturer", "displayValue", default="") or "")
    listing = _get(item, "offersV2", "listings", 0, default={}) or {}
    price = _get(listing, "price", "money", "amount")
    basis = _get(listing, "price", "savingBasis", "money", "amount")
    basis_type = str(_get(listing, "price", "savingBasis", "savingBasisType", default="") or "").upper()
    avail = str(_get(listing, "availability", "type", default="") or "").upper()
    image = _get(item, "images", "primary", "large", "url")
    seller = str(_get(listing, "merchantInfo", "name", default="") or "")
    seller_id = str(_get(listing, "merchantInfo", "id", default="") or "")
    badge = str(_get(listing, "dealDetails", "badge", default="") or "").strip()
    deal_end = str(_get(listing, "dealDetails", "endTime", default="") or "")
    condition = str(_get(listing, "condition", "value", default="New") or "New")
    eans = _get(item, "itemInfo", "externalIds", "eans", "displayValues", default=[]) or []
    base = {"id": asin, "asin": asin, "title": title, "name": title, "brand": brand,
            "price": float(price) if price is not None else None, "source": f"Amazon · {keyword}",
            "ts": now.timestamp(), "image": image or "", "basis_type": basis_type, "seller": seller,
            "seller_id": seller_id, "deal_badge": badge, "deal_end": deal_end, "ean": eans[0] if eans else None,
            "sold_by_amazon": seller_id in AMAZON_SELLER_IDS or fold(seller) == "amazon",
            "official_store": bool(brand) and fold(brand) in fold(seller)}
    if not asin or price is None:
        return base, "sin precio en Amazon"
    if basis is None or float(basis) <= float(price):
        return base, "Amazon no marca precio anterior"
    disc = (float(basis) - float(price)) / float(basis) * 100
    base.update(was=float(basis), discount=disc)
    if condition.lower() != "new":
        return base, f"no es nuevo ({condition})"
    if not (base["sold_by_amazon"] or base["official_store"]):
        # Reglas de calidad (10/11/2026): los que inflan y luego «rebajan» son vendedores de terceros.
        return base, f"lo vende {seller or 'un tercero'}, no Amazon ni la tienda oficial de la marca"
    if basis_type not in HONEST:
        return base, f"-{disc:.0f}% frente al precio recomendado, que puede estar inflado"
    if avail and avail not in {"IN_STOCK", "INSTOCK", "AVAILABLE"}:
        return base, "sin stock"
    if not image:
        return base, "sin imagen"
    cand = {**base, "avg90": round(float(basis), 2), "reference_price": round(float(basis), 2),
            "ref_text": HONEST[basis_type], "basis_type": basis_type, "image": image, "in_stock": True,
            "listing_mode": True, "origin": "amazon_api",
            "direct_url": f"https://www.amazon.es/dp/{asin}?tag={tag}" if tag else f"https://www.amazon.es/dp/{asin}"}
    return cand, ""


def search(api, cfg: dict, state: dict, now: datetime, log=print) -> list[tuple[dict, str]]:
    """Una tanda de búsquedas. Devuelve (candidato o datos, motivo de descarte o "")."""
    conf = cfg.get("amazon_search") or {}
    if api is None or not conf.get("enabled"):
        return []
    tag = str(cfg.get("affiliate_tag") or "")
    min_saving = max(1, min(99, int(float(cfg.get("error_min_discount") or 70) - float(conf.get("slack_pct") or 0))))
    out: list[tuple[dict, str]] = []
    for keyword in next_batch(conf, state):
        try:
            data = api.call("searchItems", {"keywords": keyword, "searchIndex": conf.get("search_index") or "All",
                                            "minSavingPercent": min_saving, "itemCount": 10, "resources": RESOURCES})
        except ApiError as exc:
            log(f"Aviso: búsqueda «{keyword}» en Amazon sin respuesta ({str(exc)[:160]})")
            text = str(exc)
            if any(w in text for w in ("429", "TooManyRequests", "AssociateNotEligible", "HTTP 401", "HTTP 403")):
                state["api_error"] = text[:300]
            if "429" in text or "TooManyRequests" in text:
                break  # límite de la API: se sigue en la próxima pasada
            continue
        finally:
            time.sleep(float(conf.get("pause_seconds") or 1.1))
        calls = state.setdefault("api_calls", {})
        today = now.strftime("%Y-%m-%d")
        calls[today] = int(calls.get(today) or 0) + 1
        for day in [d for d in calls if d != today]:
            calls.pop(day, None)
        items = _get(data, "searchResult", "items", default=[]) or []
        for item in items:
            out.append(to_candidate(item, keyword, cfg, now, tag))
    return out


def fold(text: str) -> str:
    import unicodedata
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return " ".join(text.lower().replace("-", " ").split())


def trusted_brands(cfg: dict) -> set[str]:
    names = list(((cfg or {}).get("resale") or {}).get("brands") or [])
    names += list(((cfg or {}).get("amazon_search") or {}).get("trusted_brands") or [])
    names += list((((cfg or {}).get("amazon_channel") or {}).get("amazon_search") or {}).get("trusted_brands") or [])
    return {fold(n) for n in names if str(n).strip()}


def is_trusted(brand: str, cfg: dict) -> bool:
    """Solo marcas conocidas: los vendedores sin marca inflan el precio anterior (recomendado o «mediano»)."""
    b = fold(brand)
    return bool(b) and any(b == t or b.startswith(t + " ") for t in trusted_brands(cfg))


def deal_line(badge: str, end: str, now: datetime) -> str:
    """«⚡ Oferta flash · acaba hoy a las 23:59»: la oferta oficial de Amazon y cuándo termina (hora de Madrid).

    Solo si Amazon la marca. «Finaliza en» (sin nombre) sale como «Oferta por tiempo limitado»."""
    from zoneinfo import ZoneInfo
    badge = (badge or "").strip().rstrip(":").strip()
    if not badge:
        return ""
    if badge.lower().startswith("finaliza"):
        badge = "Oferta por tiempo limitado"
    text = f"⚡ {badge}"
    try:
        ends = datetime.fromisoformat(end.replace("Z", "+00:00")).astimezone(ZoneInfo("Europe/Madrid"))
    except (ValueError, AttributeError):
        return text
    local = now.astimezone(ZoneInfo("Europe/Madrid"))
    days = (ends.date() - local.date()).days
    if ends <= local or days > 14:
        return text
    when = "hoy" if days == 0 else "mañana" if days == 1 else f"el {ends:%d/%m}"
    return f"{text} · acaba {when} a las {ends:%H:%M}"


def problem_text(error: str) -> str:
    """Aviso claro para tu privado cuando la API de Amazon falla por algo que hay que saber."""
    if "AssociateNotEligible" in error:
        return ("Amazon no deja usar la API de afiliados (AssociateNotEligible): suele ser por no tener ventas "
                "en los últimos 30 días. Mientras tanto no busco en Amazon.")
    if "429" in error or "TooManyRequests" in error:
        return ("la API de Amazon ha llegado a su límite de consultas (unas 8.640 al día). Sigo en cuanto "
                "se libere; si pasa a menudo, bajo las búsquedas por pasada.")
    return f"la API de Amazon rechaza las consultas ({error[:160]}). Revisa las credenciales en el .env y en GitHub."

