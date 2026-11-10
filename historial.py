"""Historial propio de precios de Amazon (10/11/2026).

El truco de muchos vendedores: suben el precio unos días y luego lo «rebajan», y Amazon enseña un -70 % que
parece un error. Para no picar, cada precio que el bot ve en Amazon (API) se guarda por producto y día
(mínimo y máximo), y antes de dar algo por chollo o error se mira contra lo que hemos visto nosotros:

- Con al menos MIN_DAYS días de historial, la referencia honesta es la mediana de lo visto (sin hoy).
  Si el «precio anterior» que da Amazon está muy por encima de esa mediana, está inflado.
- Si en los últimos días ya estuvo a este precio (o casi), no es ninguna bajada.

Se guarda dentro del estado de cada canal (premium: state/scanner.json, free: state/canal_nube.json), y cada
uno lee también el del otro, así que comparten todo lo visto.
"""

from __future__ import annotations

import statistics
from datetime import datetime, timezone

KEEP_DAYS = 45
MAX_PRODUCTS = 8000
MIN_DAYS = 3
KEEPA = "https://keepa.com/#!product/9-{asin}"  # 9 = amazon.es en Keepa


def _day(now: datetime) -> int:
    return int(now.astimezone(timezone.utc).strftime("%Y%m%d"))


def record(hist: dict, asin: str, price, now: datetime) -> None:
    """Apunta un precio visto: por día se guarda [día, mínimo, máximo]."""
    if not asin or price is None:
        return
    price = round(float(price), 2)
    if price <= 0:
        return
    rows = hist.setdefault(asin, [])
    today = _day(now)
    if rows and rows[-1][0] == today:
        rows[-1][1] = min(rows[-1][1], price)
        rows[-1][2] = max(rows[-1][2], price)
    else:
        rows.append([today, price, price])


def prune(hist: dict, now: datetime) -> dict:
    """Solo los últimos KEEP_DAYS días y, como mucho, los MAX_PRODUCTS productos vistos más recientemente."""
    cutoff = _day(now) - 0  # se compara por fecha real abajo
    keep = {}
    for asin, rows in hist.items():
        recent = [r for r in rows if _age_days(r[0], now) <= KEEP_DAYS]
        if recent:
            keep[asin] = recent
    if len(keep) > MAX_PRODUCTS:
        newest = sorted(keep.items(), key=lambda kv: kv[1][-1][0], reverse=True)[:MAX_PRODUCTS]
        keep = dict(newest)
    del cutoff
    return keep


def _age_days(day: int, now: datetime) -> int:
    d = datetime.strptime(str(day), "%Y%m%d").replace(tzinfo=timezone.utc)
    return (now.astimezone(timezone.utc).date() - d.date()).days


def merged(asin: str, *hists: dict) -> list[list]:
    """Las filas de un producto juntando el historial de los dos canales (por día, mínimo y máximo)."""
    by_day: dict[int, list] = {}
    for hist in hists:
        for day, low, high in (hist or {}).get(asin) or []:
            row = by_day.setdefault(day, [day, low, high])
            row[1], row[2] = min(row[1], low), max(row[2], high)
    return [by_day[d] for d in sorted(by_day)]


def summary(asin: str, now: datetime, *hists: dict) -> dict:
    """Días vistos (sin contar hoy), mínimo, precio habitual (mediana de los mínimos diarios) y del día anterior."""
    today = _day(now)
    rows = [r for r in merged(asin, *hists) if r[0] != today and _age_days(r[0], now) <= 30]
    if not rows:
        return {"days": 0}
    lows = [r[1] for r in rows]
    recent = [r[1] for r in rows if _age_days(r[0], now) <= 7]
    return {"days": len(rows), "min": min(lows), "usual": round(statistics.median(lows), 2),
            "min_7": min(recent) if recent else None, "first_day": rows[0][0]}


def check(asin: str, price: float, claimed_ref: float | None, now: datetime, *hists: dict,
          min_drop_pct: float = 0) -> tuple[float | None, str, dict]:
    """(referencia honesta o None, motivo de descarte o "", resumen).

    Sin historial suficiente devuelve (None, "", resumen) y cada canal decide qué hacer."""
    info = summary(asin, now, *hists)
    if info.get("days", 0) < MIN_DAYS:
        return None, "", info
    usual, low7 = info["usual"], info.get("min_7")
    if low7 is not None and price >= low7 * 0.97:
        return None, (f"no es ninguna bajada: hace menos de una semana ya estaba a {low7:.2f} € "
                      f"(historial propio de {info['days']} días)"), info
    real_pct = (usual - price) / usual * 100 if usual > 0 else 0
    if claimed_ref and claimed_ref > usual * 1.3 and real_pct + 1e-9 < min_drop_pct:
        return None, (f"precio anterior inflado: lo ponen a {claimed_ref:.2f} € pero su precio habitual es "
                      f"{usual:.2f} € (solo -{max(real_pct, 0):.0f}%, historial de {info['days']} días)"), info
    if real_pct + 1e-9 < min_drop_pct:
        return None, (f"solo -{max(real_pct, 0):.0f}% frente a su precio habitual de {usual:.2f} € "
                      f"(historial de {info['days']} días)"), info
    return usual, "", info


def keepa_url(asin: str) -> str:
    return KEEPA.format(asin=asin)
