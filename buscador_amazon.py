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

RESOURCES = PRICE_RESOURCES + ["itemInfo.byLineInfo"]
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
    base = {"id": asin, "asin": asin, "title": title, "name": title, "brand": brand,
            "price": float(price) if price is not None else None, "source": f"Amazon · {keyword}",
            "ts": now.timestamp()}
    if not asin or price is None:
        return base, "sin precio en Amazon"
    if basis is None or float(basis) <= float(price):
        return base, "Amazon no marca precio anterior"
    disc = (float(basis) - float(price)) / float(basis) * 100
    base.update(was=float(basis), discount=disc)
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
            if "429" in str(exc) or "TooManyRequests" in str(exc):
                break  # límite de la API: se sigue en la próxima pasada
            continue
        finally:
            time.sleep(float(conf.get("pause_seconds") or 1.1))
        items = _get(data, "searchResult", "items", default=[]) or []
        for item in items:
            out.append(to_candidate(item, keyword, cfg, now, tag))
    return out
