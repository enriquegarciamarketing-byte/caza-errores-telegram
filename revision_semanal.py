"""Revisión semanal (cada lunes por la mañana, a tu chat privado con el bot) — 10/11/2026.

1. Qué ha hecho la semana: posts del free y del premium, tus OK y NO, qué se ha quedado fuera y por qué
   (vendedores de terceros, marcas desconocidas, la trampa de subir y bajar el precio…).
2. Hasta 3 propuestas concretas de cambios, para que digas sí o no.
3. 2-3 borradores para X (@AzvensLoL) contando cómo trabajamos, con los números reales de la semana,
   con tu voz (la de marca_personal.py) y sin enlace de afiliado.

Uso: python revision_semanal.py [--dry-run]
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
MADRID = ZoneInfo("Europe/Madrid")
TELEGRAM = "t.me/cazachollos_com"
WEEK = 7 * 86400


def load(name: str) -> dict:
    try:
        return json.loads((ROOT / "state" / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def reason_kind(reason: str) -> str:
    r = (reason or "").lower()
    if r.startswith("lo vende"):
        return "vendedor"
    if "marca poco conocida" in r:
        return "marca"
    if "ninguna bajada" in r or "precio anterior inflado" in r:
        return "trampa"  # lo pilla el historial propio
    if "precio recomendado" in r or "pvp inflado" in r:
        return "pvp"
    if r.startswith("has rechazado"):
        return "aprendido"
    if r.startswith("solo -") or "solo categorías top" in r:
        return "poco"
    return "otro"


def gather(now: float) -> dict:
    prem, free, ventas = load("scanner.json"), load("canal_nube.json"), load("ventas.json")
    since = now - WEEK
    ppost = [p for p in prem.get("posts") or [] if (p.get("t") or 0) >= since]
    asks = [p for p in ppost if p.get("alert_id")]
    published = [p for p in ppost if p.get("message_id") and not p.get("pending") and not p.get("rejected")]
    fpost = [p for p in free.get("posts") or [] if (p.get("t") or 0) >= since]
    fast = [p for p in fpost if p.get("ended") and p["ended"] - p["t"] <= 3600]
    kinds: Counter = Counter()
    checked = 0
    for key, row in list((prem.get("seen") or {}).items()) + list((free.get("seen") or {}).items()):
        if (row.get("t") or 0) < since:
            continue
        checked += 1  # todo lo revisado a fondo esta semana (Amazon y Jimmyleaks), para comparar con lo publicado
        kinds[reason_kind(str(row.get("result") or row.get("why") or ""))] += 1
    learning = prem.get("learning") or {}
    blocked = [r.get("name") for kind in ("brand", "seller") for r in (learning.get(kind) or {}).values()
               if int(r.get("no") or 0) >= 2 and not int(r.get("ok") or 0)]
    hist = {**(free.get("price_history") or {}), **(prem.get("price_history") or {})}
    labels = Counter(p.get("label") for p in fpost if p.get("label"))
    return {
        "free_posts": len(fpost), "free_fast": len(fast), "free_labels": labels.most_common(3),
        "free_best": max(fpost, key=lambda p: (p["reference"] - p["price"]) / p["reference"], default=None)
        if all(p.get("reference") and p.get("price") for p in fpost) else None,
        "prem_published": len(published), "asks": len(asks),
        "ok": sum(1 for p in asks if p.get("approved")), "no": sum(1 for p in asks if p.get("rejected")),
        "expired": sum(1 for p in asks if p.get("expired") and not p.get("approved")),
        "checked": checked, "kinds": dict(kinds), "blocked": [b for b in blocked if b],
        "history": len(hist), "ventas": ventas,
    }


def proposals(s: dict, now: float) -> list[str]:
    out = []
    if s["expired"] > s["ok"] and s["expired"] >= 2:
        out.append(f"Se te caducaron {s['expired']} peticiones de OK del premium. ¿Alargo el plazo de 1 h a 2 h?")
    if s["free_posts"] < 14:
        out.append(f"El free solo ha publicado {s['free_posts']} chollos. Si quieres más volumen sin perder calidad, "
                   "puedo bajar el mínimo de -50 % a -45 % solo en categorías top.")
    ventas = s.get("ventas") or {}
    updated = ventas.get("updated")
    old = True
    if updated:
        try:
            old = (datetime.now(timezone.utc).date() - datetime.fromisoformat(updated).date()).days > 30
        except ValueError:
            pass
    if old:
        out.append("Pásame el informe de pedidos de Amazon Afiliados (Informes → Pedidos → descargar CSV) y el bot "
                   "aprende qué compra de verdad la comunidad para buscar más de eso.")
    if s["kinds"].get("pvp", 0) > 50:
        out.append(f"{s['kinds']['pvp']} productos venían con un «precio recomendado» que puede estar inflado. "
                   "Los dejo fuera en el premium; en el free solo pasan de marcas conocidas. ¿Lo mantengo?")
    return out[:3]


def summary_text(s: dict) -> str:
    e = html.escape
    k = s["kinds"]
    lines = ["🧠 <b>Revisión semanal de Caza Chollos</b>", ""]
    lines.append(f"📣 <b>Free</b>: {s['free_posts']} chollos publicados" +
                 (f", {s['free_fast']} se agotaron en menos de 1 h" if s["free_fast"] else ""))
    if s["free_labels"]:
        lines.append("   Lo que más ha salido: " + ", ".join(f"{e(str(l))} ({n})" for l, n in s["free_labels"]))
    lines.append(f"🚨 <b>Premium</b>: {s['prem_published']} errores publicados · te pedí OK {s['asks']} veces "
                 f"({s['ok']} OK, {s['no']} NO, {s['expired']} caducados)")
    lines.append("")
    lines.append(f"🔎 Productos revisados a fondo: <b>{s['checked']}</b>. Algunos motivos para dejarlos fuera:")
    for kind, label in (("vendedor", "los vendía un tercero, no Amazon ni la marca"),
                        ("marca", "marcas que nadie conoce"),
                        ("trampa", "la trampa de subir el precio y luego «rebajarlo» (historial)"),
                        ("pvp", "«precio recomendado» que puede estar inflado"),
                        ("aprendido", "marcas o vendedores que has rechazado tú"),
                        ("poco", "descuento real insuficiente")):
        if k.get(kind):
            lines.append(f"   • {k[kind]} · {label}")
    if s["blocked"]:
        lines.append(f"🙅 Ya no te propongo: {e(', '.join(s['blocked'][:8]))}")
    lines.append(f"📈 Historial propio: {s['history']} productos con precios guardados")
    return "\n".join(lines)


def x_drafts(s: dict) -> list[tuple[str, str]]:
    k = s["kinds"]
    drafts = []
    out_of = s["checked"]
    if out_of >= 50:
        parts = []
        if k.get("vendedor"):
            parts.append(f"{k['vendedor']} los vendía alguien que no era ni Amazon ni la marca")
        if k.get("marca"):
            parts.append(f"{k['marca']} eran marcas que no conoce nadie")
        if k.get("trampa"):
            parts.append(f"{k['trampa']} eran la trampa de siempre: subir el precio unos días y luego «rebajarlo»")
        reasons = ".\n\n".join(p[0].upper() + p[1:] for p in parts) if parts else "El resto no bajaba de verdad"
        drafts.append(("Los números de la semana",
                       f"Esta semana el bot ha revisado a fondo {out_of} productos con descuento grande.\n\n"
                       f"Al canal han llegado {s['free_posts']}.\n\n{reasons}.\n\n"
                       f"Prefiero publicar poco y bueno a llenaros el móvil de humo: {TELEGRAM}"))
    if k.get("trampa"):
        drafts.append(("Cómo pillo los falsos chollos",
                       "El truco más viejo de Amazon sigue funcionando.\n\nEl vendedor sube el precio una semana, "
                       "luego lo baja y Amazon le pone un -70% enorme. Los bots que solo miran el descuento caen "
                       f"siempre.\n\nEl mío guarda el precio de cada producto todos los días. Esta semana ha pillado "
                       f"{k['trampa']} así.\n\nSi antes estaba igual de barato, no es un chollo."))
    else:
        drafts.append(("Cómo pillo los falsos chollos",
                       "La mayoría de -70% que veis por ahí son mentira.\n\nEl vendedor sube el precio unos días y "
                       "luego lo «rebaja». Por eso mi bot guarda el precio de cada producto todos los días y lo "
                       "compara con lo que de verdad ha costado.\n\nSi no baja de verdad, no sale."))
    if s["asks"]:
        drafts.append(("El bot aprende de mí",
                       "Le he enseñado al bot a aprender de mí.\n\nCada error de precio que encuentra me llega antes "
                       f"al móvil y yo digo OK o NO. Esta semana han sido {s['asks']}: {s['ok']} OK y {s['no']} NO."
                       "\n\nCada NO le enseña qué marcas y vendedores no se merecen salir. Una IA que no aprende de "
                       "quien la usa no sirve de mucho."))
    else:
        drafts.append(("Cómo trabajamos",
                       "Así trabaja el bot que hay detrás del canal.\n\nBusca en Amazon cada minuto, descarta lo que "
                       "no vende Amazon o la marca oficial, mira el historial de precios y, si parece un error, me lo "
                       "pasa a mí antes de publicar.\n\nYo doy el OK o el NO. Lo que llega a vosotros ya ha pasado "
                       f"por dos filtros: {TELEGRAM}"))
    return drafts[:3]


def draft_message(label: str, text: str) -> str:
    return (f"✍️ <b>Para X</b> · {html.escape(label)}\nMantén pulsado el texto para copiarlo. Sin enlace de "
            f"afiliado, no hace falta Paid partnership.\n\n<pre>{html.escape(text)}</pre>")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    stats = gather(time.time())
    messages = [summary_text(stats)]
    props = proposals(stats, time.time())
    if props:
        messages[0] += "\n\n💡 <b>Propuestas</b> (dime sí o no y lo cambio):\n" + "\n".join(f"{i}. {html.escape(p)}"
                                                                                      for i, p in enumerate(props, 1))
    messages += [draft_message(label, text) for label, text in x_drafts(stats)]
    for m in messages:
        print(m, "\n---")
    if args.dry_run:
        return 0
    admin = os.environ.get("ADMIN_CHAT_ID", "").strip()
    if not admin:
        print("Falta ADMIN_CHAT_ID", file=sys.stderr)
        return 2
    import scanner
    tg = scanner.Telegram(os.environ["TELEGRAM_BOT_TOKEN"])
    for m in messages:
        tg.call("sendMessage", {"chat_id": admin, "text": m, "parse_mode": "HTML", "disable_web_page_preview": True})
        time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
