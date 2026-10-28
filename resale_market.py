"""Precio de reventa con Wallapop, Vinted y Milanuncios. Si una fuente falla, se sigue con las demás."""

from __future__ import annotations

import time

import milanuncios
import vinted
import wallapop

NAMES = {"wallapop": "Wallapop", "vinted": "Vinted", "milanuncios": "Milanuncios"}
MODULES = {"wallapop": wallapop, "vinted": vinted, "milanuncios": milanuncios}


def is_fashion(cand: dict, rules: dict) -> bool:
    text = wallapop.fold_text(f"{cand.get('brand') or ''} {cand.get('name') or ''} {cand.get('title') or ''}")
    for word in rules.get("fashion_exceptions") or []:
        if wallapop.keyword_in(text, word):
            return False
    return any(wallapop.keyword_in(text, word) for word in rules.get("fashion_keywords") or [])


def source_order(cand: dict, rules: dict) -> list[str]:
    if is_fashion(cand, rules):
        return ["vinted", "wallapop", "milanuncios"]
    return ["wallapop", "milanuncios"]


def _label(parts: list[tuple[str, int]]) -> str:
    names = [name for name, count in parts if count]
    if not names:
        return "WALLAPOP"
    if len(names) == 1:
        return names[0].upper()
    return "+".join(name.upper() for name in names)


def _assemble(cand: dict, market: dict, route: list[str], prices: list[float],
              parts: list[tuple[str, int]], failures: list[str], any_transient: bool, query: str,
              reserved: int = 0, demand_known: bool = False) -> dict:
    tried = " + ".join(NAMES[source] for source in route)
    label = _label(parts) if parts else tried
    combined = wallapop.evaluate(cand, prices, market, label=label, reserved=reserved, demand_known=demand_known)
    used = int(combined.get("count") or 0)
    note = ""
    if parts:
        raw = sum(count for _, count in parts)
        if raw == used:
            detail = ", ".join(f"{name} {count}" for name, count in parts)
        else:
            detail = " + ".join(name for name, _count in parts)
        note = f"Mediana de {used} anuncios · {detail}"
        if combined.get("demand"):
            note = f"{note} · {combined['demand']}"
    # Un bloqueo solo explica la ficha cuando no llegamos al mínimo de anuncios.
    # Si ya hay mediana, el motivo es el ROI o el beneficio, y el bloqueo queda en el log.
    minimum = int(market.get("min_listings", 5))
    if not combined.get("ok") and failures and used < minimum:
        extra = "; ".join(failures)
        combined["reason"] = extra if not prices else f"{combined.get('reason') or ''} · {extra}".strip(" ·")
    if not combined.get("ok") and any_transient:
        combined["transient"] = True
    combined.update(source_label=_label(parts), note=note, sources=[name for name, count in parts if count],
                    prices=prices, query=query)
    return combined


def lookup(cand: dict, rules: dict, state: dict | None = None) -> dict:
    """Junta anuncios comparables. El mínimo de 5, el ROI y el beneficio se aplican al total."""
    rules = rules or {}
    market = rules.get("wallapop") or rules
    route = source_order(cand, rules)
    query = wallapop.query_keywords(cand, int(market.get("max_keywords", 3)))
    identity = wallapop.product_cache_key(cand, "+".join(route) + ":" + query)
    cache = {} if state is None else state.setdefault("resale_cache", {})
    ttl = float(market.get("cache_hours", 12)) * 3600
    hit = cache.get(identity)
    if isinstance(hit, dict) and time.time() - hit.get("t", 0) < ttl and "prices" in hit:
        combined = _assemble(cand, market, route, list(hit["prices"]), list(hit.get("parts") or []),
                             list(hit.get("failures") or []), bool(hit.get("transient")), query,
                             reserved=int(hit.get("reserved") or 0), demand_known=bool(hit.get("demand_known")))
        combined["cached"] = True
        return combined
    prices: list[float] = []
    parts: list[tuple[str, int]] = []
    failures: list[str] = []
    any_transient = False
    reserved_total = 0
    demand_known = False
    for source in route:
        name = NAMES[source]
        try:
            result = MODULES[source].lookup(cand, market, state)
        except Exception as exc:
            print(f"  {name}: error inesperado ({exc})")
            any_transient = True
            failures.append(f"{name}: error inesperado")
            continue
        got = list(result.get("prices") or [])
        if result.get("blocked") or (not got and (result.get("transient") or result.get("reason"))):
            any_transient = any_transient or bool(result.get("transient"))
            if result.get("reason"):
                failures.append(str(result["reason"]))
            print(f"  {name} no aporta datos: {result.get('reason')}")
        reserved_total += int(result.get("reserved") or 0)
        demand_known = demand_known or bool(result.get("demand_known"))
        if got:
            prices.extend(got)
            parts.append((name, len(got)))
    combined = _assemble(cand, market, route, prices, parts, failures, any_transient, query,
                         reserved=reserved_total, demand_known=demand_known)
    if parts:
        status = "publica" if combined.get("ok") else "no publica"
        print(f"  Reventa {combined.get('source_label')}: {combined.get('count')} anuncios, "
              f"~{float(combined.get('price') or 0):.0f} €, {status}")
    if state is not None and not any_transient:
        cache[identity] = {"t": time.time(), "prices": prices, "parts": parts,
                           "failures": failures, "transient": False,
                           "reserved": reserved_total, "demand_known": demand_known}
        if len(cache) > 200:
            oldest = sorted(cache, key=lambda item: cache[item].get("t") or 0)[: len(cache) - 200]
            for item in oldest:
                cache.pop(item, None)
    return combined


def probe(rules: dict) -> int:
    """Una consulta de electrónica y otra de moda. Un bloqueo se registra y no tumba el proceso."""
    print("Comprobación de Wallapop, Vinted y Milanuncios (si una fuente falla, se sigue):")
    samples = [
        {"brand": "Corsair", "name": "Vengeance LPX 16GB DDR4", "price": 60},
        {"brand": "Nike", "name": "Zapatillas Air Force 1", "price": 50},
        {"brand": "Casio", "name": "Reloj de pulsera", "price": 40},
    ]
    for cand in samples:
        try:
            result = lookup(cand, rules or {}, {})
        except Exception as exc:
            print(f"  {cand['brand']} {cand['name']}: error inesperado ({exc})")
            continue
        print(f"  {cand['brand']} {cand['name']}: {result.get('source_label')} "
              f"n={result.get('count')} ok={bool(result.get('ok'))} · {result.get('reason') or 'con datos'}")
    return 0
