"""Posts de marca personal para X (@AzvensLoL), con la voz de @kevincrestt y mayúscula al empezar.

Dos al día te llegan por privado al bot (workflow marca-personal.yml):
- Por la mañana: "El bot por dentro", con datos reales del canal del día anterior (qué salió, qué voló antes,
  cuánto filtra). Si no hay datos suficientes, uno de ahorro.
- Por la tarde: rota entre ahorro y promos, finanzas e inversión y tu día a día.

Los de "día a día" llevan [corchetes] para que pongas lo que de verdad has hecho: no me invento tu vida.
Ninguno lleva enlace de afiliado ni la palabra Amazon, así que no hace falta la etiqueta Paid partnership.
No se repite ninguno hasta haber usado todos los de su tema (memoria en state/marca_personal.json).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state" / "marca_personal.json"
CANAL = ROOT / "state" / "canal_nube.json"
MADRID = ZoneInfo("Europe/Madrid")
TELEGRAM = "t.me/cazachollos_com"

AHORRO = [
    "Antes de abrir una cuenta solo por la promo, mirad tres cosas.\n\nCuánto tiempo tenéis que mantener la "
    "nómina o el dinero, si hay comisión de mantenimiento cuando acabe y si os obliga a domiciliar recibos.\n\n"
    "Muchas promos de 200€ se quedan en 80€ cuando lees la letra pequeña.",
    "El truco más tonto que más dinero me ha ahorrado este año: pasar por una web de cashback antes de comprar "
    "lo que iba a comprar igualmente.\n\nNo es hacerse rico, pero a final de año son unos cuantos cientos de "
    "euros que antes regalaba.",
    "Un chollo no es comprar barato algo que no necesitabais.\n\nEso es gastar con descuento.\n\nYo me hago una "
    "pregunta antes de darle a comprar: ¿lo habría pagado a precio normal dentro de un mes? Si la respuesta es "
    "no, fuera.",
    "Os leo, que seguro que sabéis alguno que yo no.\n\n¿Cuál es el truco de ahorro que más os ha funcionado "
    "este año?",
    "La mayoría de descuentos del -70% que veis por ahí son mentira.\n\nEl vendedor sube el precio una semana "
    "antes y luego lo baja. Por eso el bot compara con el mínimo real de los últimos 30 días y no con el "
    "precio tachado.\n\nSi no baja de verdad, no sale.",
    "Las promos de bancos dan más dinero que muchos trabajos de fin de semana, pero hay que llevarlo "
    "ordenado.\n\nYo tengo una hoja con fecha de alta, requisito, cuándo cobro y cuándo puedo cerrar. Sin eso "
    "acabas pagando comisiones y perdiendo lo que ganaste.",
    "Black Friday está a la vuelta de la esquina y ya os aviso: los mejores precios no suelen ser ese día.\n\n"
    "Muchos productos bajan antes y otros suben la semana previa para vender el descuento. El bot va a estar "
    "fino estos días, os lo dejo en {telegram}",
    "Errores de precio hay todas las semanas, lo difícil es enterarse a tiempo.\n\nLa mayoría duran minutos y "
    "cuando llega el tuit viral ya no queda stock. Para eso monté el bot, para llegar antes que el resto.",
    "Pregunta seria: ¿cuánto pagáis de suscripciones al mes sin usarlas?\n\nYo hice limpieza el mes pasado y "
    "me sobraban tres. Haced la prueba, entrad en el banco y buscad cargos repetidos. Os vais a llevar alguna "
    "sorpresa.",
    "Comprar en Telegram con prisa es la mejor forma de comprar mal.\n\nPor eso el bot pone a qué hora vio el "
    "precio y frente a qué lo compara. Si no os cuadra, no compréis. Prefiero que me digáis que es caro a que "
    "os sintáis engañados.",
]

FINANZAS = [
    "El interés compuesto no es magia, es paciencia.\n\n100€ al mes durante 30 años al 7% anual son unos "
    "120.000€. De esos, solo 36.000€ los has puesto tú.\n\nEl resto lo hace el tiempo. Por eso empezar pronto "
    "importa más que empezar con mucho.",
    "La comisión de un fondo parece poca cosa hasta que la multiplicas por 20 años.\n\nUna diferencia de un "
    "1,5% anual se puede comer más de un cuarto de lo que habrías ganado. Antes de mirar la rentabilidad, mirad "
    "lo que os cobran.",
    "No necesitáis saber cuándo va a caer la bolsa.\n\nNadie lo sabe. Ni yo, ni el de YouTube, ni el banco.\n\n"
    "Aportar cada mes la misma cantidad pase lo que pase es aburrido, y precisamente por eso funciona.",
    "Lo primero no es invertir, es tener un colchón.\n\nEntre 3 y 6 meses de gastos en algo líquido. Si no lo "
    "tienes, a la primera avería vendes tus inversiones en el peor momento.",
    "Os leo: ¿invertís cada mes o lo hacéis cuando os sobra algo a final de mes?\n\nYo antes era de los "
    "segundos y nunca sobraba nada. Desde que lo programo el día que cobro, cambió todo.",
    "Una cosa que me repiten mucho: \"es que yo no tengo dinero para invertir\".\n\nCon 50€ al mes ya se puede "
    "empezar. Lo importante no es la cantidad, es el hábito. La cantidad sube sola cuando el hábito ya está.",
    "Cada vez que el mercado cae un 10% leo lo mismo: \"esto se hunde\".\n\nY cada vez quien vendió con pánico "
    "se arrepiente unos meses después. Si vuestra estrategia no aguanta una caída, el problema es la "
    "estrategia, no la caída.",
    "Diversificar no es tener 15 fondos que invierten en lo mismo.\n\nAntes de añadir otro, mirad qué lleva "
    "dentro. Muchas carteras que parecen variadas tienen las mismas 10 empresas repetidas cuatro veces.",
    "Hacienda también es parte de la rentabilidad.\n\nNo es lo mismo traspasar entre fondos que vender y "
    "volver a comprar. Lo primero no tributa hasta que sacas el dinero. Detalles así, a 20 años, son mucha "
    "pasta.",
    "Lo que más me ha enseñado preparar carteras para otros: casi nadie sabe qué riesgo puede aguantar hasta "
    "que lo ve en rojo.\n\nAntes de invertir, preguntaos cuánto podríais ver caer sin vender. Esa respuesta "
    "vale más que cualquier fondo.",
]

DIA = [
    "Buenos días chavales.\n\nHoy toca [gym / ruta por la montaña / día de curro] antes de ponerme con el bot. "
    "Si no muevo el cuerpo por la mañana, por la tarde no hay quien me centre.\n\n¿Vosotros sois de mañanas o "
    "de noches?",
    "Hoy le he metido [X horas] al bot para afinar los filtros.\n\nLo que más me cuesta no es encontrar "
    "chollos, es decidir qué NO publicar. Prefiero 10 buenos al día que 100 que no os sirven de nada.",
    "Me preguntáis mucho cómo me da tiempo a todo.\n\nLa respuesta es que no me da. Automatizo todo lo que "
    "puedo y lo que no, lo dejo en una lista. Hoy por ejemplo [lo que hayas hecho hoy].",
    "Domingo de [plan del domingo].\n\nEntre semana voy a tope, así que los findes intento desconectar del "
    "móvil un rato. El bot sigue trabajando por mí, que para eso lo monté.",
    "Un día normal mío: curro, [gym / entreno], un rato al bot y otro a las finanzas.\n\nNo es glamuroso, pero "
    "cada cosa que monto me ahorra horas el mes siguiente. Ese es el truco, construir cosas que trabajen solas.",
    "Hoy me he dado cuenta de [algo que hayas aprendido hoy].\n\nPequeñas cosas así son las que no te enseña "
    "nadie y te ahorran mucho dinero o mucho tiempo. Lo dejo por aquí por si a alguno le sirve.",
    "Llevo [X días / semanas] con el canal de chollos y ya somos [número] dentro.\n\nGracias de verdad. "
    "Cualquier mejora que se os ocurra, la leo toda. El canal está en {telegram}",
    "Objetivo de esta semana: [tu objetivo].\n\nLo pongo aquí para que me lo podáis echar en cara el domingo "
    "si no lo cumplo.",
]

TOPICS = {"ahorro": ("Ahorro y promos", AHORRO), "finanzas": ("Finanzas e inversión", FINANZAS),
          "dia": ("Tu día a día", DIA)}
EVENING = ["finanzas", "ahorro", "dia"]


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def short(title: str, words: int = 6) -> str:
    head = re.split(r",| - | – |\(|\|", title or "")[0].strip()
    return " ".join(w.capitalize() if w.isupper() and len(w) > 4 and w.isalpha() else w
                    for w in head.split()[:words])


def bot_post(posts: list, now: datetime, seed: int) -> str:
    """Post con datos reales del canal del día anterior. Vacío si no hay datos suficientes."""
    day = (now.astimezone(MADRID) - timedelta(days=1)).date()
    yday = [p for p in posts if p.get("t") and datetime.fromtimestamp(p["t"], MADRID).date() == day
            and p.get("reference") and p.get("price")]
    if len(yday) < 5:
        return ""
    fast = sorted((p for p in yday if p.get("ended") and p["ended"] > p["t"]), key=lambda p: p["ended"] - p["t"])
    best = max(yday, key=lambda p: (p["reference"] - p["price"]) / p["reference"])
    pct = round((best["reference"] - best["price"]) / best["reference"] * 100)
    options = []
    gone_hour = sum(1 for p in fast if p["ended"] - p["t"] <= 3600)
    if fast and gone_hour >= 2:  # solo si de verdad volaron: con uno suelto o en horas no tiene gracia
        f = fast[0]
        mins = max(1, round((f["ended"] - f["t"]) / 60))
        options.append(
            f"Ayer el chollo que menos duró fue {short(f['title'])}: {mins} minutos y fuera.\n\n"
            f"Y no fue el único, {gone_hour} de los {len(yday)} que publicó el bot se acabaron en menos de una "
            f"hora.\n\nPor eso el bot avisa en cuanto lo ve. Si estáis fuera, os lo estáis perdiendo: {TELEGRAM}")
    options.append(
        f"Ayer el bot publicó {len(yday)} chollos y el más bestia fue {short(best['title'])}, un {pct}% por "
        f"debajo de su precio de referencia.\n\nNo es un descuento inflado de esos de -80% que veis cada día, "
        f"el bot solo compara con lo que de verdad ha costado.\n\nTodo en {TELEGRAM}")
    options.append(
        f"El bot revisa un montón de productos cada día y ayer solo dejó pasar {len(yday)}.\n\nPrefiero publicar poco "
        f"y bueno a llenaros el móvil de notificaciones de relleno. Si un chollo no baja de verdad frente a su "
        f"mínimo, no sale.\n\nEl canal es gratis: {TELEGRAM}")
    return options[seed % len(options)]


def next_post(topic: str, state: dict) -> str:
    label, bank = TOPICS[topic]
    used = state.setdefault("used", {}).setdefault(topic, [])
    free = [i for i in range(len(bank)) if i not in used] or list(range(len(bank)))
    if len(free) == len(bank):
        used.clear()
    idx = free[0]
    used.append(idx)
    return bank[idx].format(telegram=TELEGRAM)


def choose(slot: str, now: datetime, state: dict) -> tuple[str, str]:
    """(tema, texto) para la franja de la mañana o de la tarde."""
    if slot == "manana":
        text = bot_post(load(CANAL, {}).get("posts") or [], now, now.timetuple().tm_yday)
        if text:
            return "El bot por dentro", text
        return TOPICS["ahorro"][0], next_post("ahorro", state)
    topic = EVENING[now.timetuple().tm_yday % len(EVENING)]
    return TOPICS[topic][0], next_post(topic, state)


def draft_message(label: str, text: str, test: bool = False) -> str:
    head = "🧪 PRUEBA · " if test else ""
    fill = "\nRellena lo que va entre [corchetes] antes de publicar." if "[" in text else ""
    return (f"{head}✍️ <b>Marca personal</b> · {html.escape(label)}\nMantén pulsado el texto para copiarlo. "
            f"Sin enlace de afiliado, no hace falta Paid partnership.{fill}\n\n<pre>{html.escape(text)}</pre>")


def main() -> int:
    parser = argparse.ArgumentParser(description="Posts de marca personal para X, al chat privado del bot")
    parser.add_argument("--slot", choices=["manana", "tarde", "auto"], default="auto")
    parser.add_argument("--test", action="store_true", help="No guarda memoria y marca el mensaje como prueba")
    parser.add_argument("--dry-run", action="store_true", help="Solo imprime")
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    slot = args.slot if args.slot != "auto" else ("manana" if now.astimezone(MADRID).hour < 14 else "tarde")
    state = load(STATE, {})
    label, text = choose(slot, now, state)
    print(f"[{slot}] {label}\n\n{text}\n")
    if args.dry_run:
        return 0
    import canal_nube
    import scanner

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Falta TELEGRAM_BOT_TOKEN.", file=sys.stderr)
        return 2
    tg = scanner.Telegram(token)
    cfg = load(ROOT / "config.json", {})
    canal_state = load(CANAL, {})
    admin = canal_nube.admin_chat_id(canal_state, canal_nube.rules_from(cfg), tg, print)
    if not admin:
        print("No encuentro tu chat privado con el bot. Escríbele /start y repite.", file=sys.stderr)
        return 2
    tg.call("sendMessage", {"chat_id": admin, "text": draft_message(label, text, args.test), "parse_mode": "HTML",
                            "disable_web_page_preview": True})
    print(f"Enviado a tu chat ({admin}).")
    if not args.test:
        state.setdefault("log", []).append({"t": int(now.timestamp()), "slot": slot, "topic": label})
        state["log"] = state["log"][-60:]
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
