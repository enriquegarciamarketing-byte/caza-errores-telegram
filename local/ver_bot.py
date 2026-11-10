"""Vista en directo del bot de errores del Mac, con colores, al estilo:

──── Caza Chollos · hogar y cocina ──── 17:42:05
📦 Bosch, Placa de inducción PUE611BB5E
💶 Antes 261,77 € → Ahora 82,95 € · -68%
🏷️ Marca: Bosch ✅
⏱️ Bajada vista hace 3 min · revisado en 2 s
✅ ERROR DE PRECIO (-68% frente a su precio medio)

Lee state/local_logs/eventos-AAAA-MM-DD.jsonl (lo escribe el escáner) y cambia de fichero al cambiar el día.
Cada producto descartado en el listado sale una sola vez por día y precio, para que no se repita cada minuto.
Uso: python local/ver_bot.py [--solo-buenos]   (Ctrl+C para salir; el bot sigue funcionando)
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

LOGS = Path(__file__).resolve().parent.parent / "state" / "local_logs"

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
RED, GREEN, YELLOW, CYAN, ORANGE = "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[38;5;208m"
ONLY_GOOD = "--solo-buenos" in sys.argv


def eur(value) -> str:
    try:
        return f"{float(value):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "?"


def clock(ts) -> str:
    return datetime.fromtimestamp(float(ts or time.time())).strftime("%H:%M:%S")


def ago(seconds) -> str:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return ""
    if s < 90:
        return f"{s} s"
    if s < 5400:
        return f"{round(s / 60)} min"
    return f"{s / 3600:.1f} h"


def product(e: dict) -> str:
    verdict = e.get("veredicto") or "DESCARTADO"
    good = verdict != "DESCARTADO"
    head_color = ORANGE if good else DIM
    source = (e.get("fuente") or "Caza Chollos").replace("Jimmyleaks", "Caza Chollos")
    lines = [f"{head_color}──── {source} ──── {clock(e.get('t'))}{RESET}",
             f"📦 {BOLD if good else ''}{e.get('titulo') or e.get('id')}{RESET}"]
    if e.get("precio") is not None:
        price = f"💶 Ahora {eur(e['precio'])}"
        if e.get("antes"):
            price = f"💶 Antes {eur(e['antes'])} → Ahora {eur(e['precio'])}"
        if e.get("descuento") is not None:
            price += f" · -{e['descuento']}%"
        lines.append(price)
    if e.get("marca"):
        lines.append(f"🏷️ Marca: {e['marca']} {'✅' if e.get('marca_ok') else '❔'}")
    timing = []
    if e.get("hace") is not None:
        timing.append(f"bajada vista hace {ago(e['hace'])}")
    if e.get("segundos") is not None:
        timing.append(f"revisado en {ago(e['segundos'])}")
    if timing:
        lines.append("⏱️ " + " · ".join(timing).capitalize())
    reason = e.get("motivo") or ""
    if good:
        extra = " · te pido OK por privado" if e.get("pedir_ok") else ""
        lines.append(f"{GREEN}{BOLD}✅ {verdict}{RESET}{GREEN} ({reason}){extra}{RESET}")
    else:
        lines.append(f"{RED}❌ DESCARTADO: {reason}{RESET}")
    return "\n".join(lines)


def publication(e: dict) -> str:
    state = e.get("estado") or ""
    if state == "PUBLICADO":
        return f"{GREEN}{BOLD}📢 PUBLICADO en el premium: {e.get('titulo')} · -{e.get('descuento')}% · {eur(e.get('precio'))}{RESET}"
    if state == "TE PIDO OK":
        return f"{YELLOW}{BOLD}✋ TE HE PEDIDO OK por privado: {e.get('titulo')} (responde OK al bot){RESET}"
    return f"{YELLOW}⛔ NO PUBLICADO: {e.get('titulo')} · {e.get('motivo')}{RESET}"


def render(e: dict, shown: set) -> str | None:
    kind = e.get("kind")
    if kind == "pasada":
        if ONLY_GOOD:
            return None
        if not e.get("listados") and e.get("fuente") != "Amazon":
            return None  # Jimmyleaks sin productos (bloqueado o en pausa): nada que ver
        where = "Amazon" if e.get("fuente") == "Amazon" else "Jimmyleaks"
        return (f"{DIM}· {clock(e.get('t'))} · pasada {where} · {e.get('listados', 0)} productos mirados · "
                f"{e.get('candidatos', 0)} con pinta de error{RESET}")
    if kind == "producto":
        verdict = e.get("veredicto") or "DESCARTADO"
        if ONLY_GOOD and verdict == "DESCARTADO":
            return None
        if e.get("fase") == "listado" or (verdict == "DESCARTADO" and str(e.get("fuente") or "").startswith("Amazon")):
            key = (e.get("id"), e.get("precio"))
            if key in shown:
                return None
            shown.add(key)
        return "\n" + product(e)
    if kind == "publicacion":
        return "\n" + publication(e)
    if kind == "aviso":
        return f"{YELLOW}⚠️ {e.get('texto')}{RESET}"
    return None


def today_file() -> Path:
    return LOGS / f"eventos-{datetime.now():%Y-%m-%d}.jsonl"


def follow() -> None:
    print(f"{CYAN}{BOLD}🔎 Bot de errores de Amazon en directo{RESET}"
          f"{CYAN}  ·  Ctrl+C o cerrar la ventana para salir (el bot sigue){RESET}")
    if ONLY_GOOD:
        print(f"{CYAN}Solo errores y publicaciones.{RESET}")
    shown: set = set()
    path, handle, waited = None, None, False
    while True:
        if path != today_file():
            if handle:
                handle.close()
            path, handle, shown = today_file(), None, set()
        if handle is None:
            if not path.exists():
                if not waited:
                    print(f"{DIM}Esperando a la primera pasada del bot…{RESET}")
                    waited = True
                time.sleep(2)
                continue
            handle = path.open(encoding="utf-8")
            backlog = handle.readlines()[-400:]  # lo último, para no empezar en blanco
            for line in backlog:
                show(line, shown)
        line = handle.readline()
        if not line:
            time.sleep(1)
            continue
        show(line, shown)


def show(line: str, shown: set) -> None:
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return
    text = render(event, shown)
    if text:
        print(text, flush=True)


if __name__ == "__main__":
    try:
        follow()
    except KeyboardInterrupt:
        print(f"\n{DIM}Vista cerrada. El bot sigue funcionando.{RESET}")
