"""Vigía de canales: lo que salga en los canales de @kevincrestt sale al momento en el premium @caza_errores.

21/11/2026: Enrique quiere que los posts de
  t.me/erroresychollos · t.me/erroresycholloswarehouse · t.me/erroresychollosropa
se detecten al instante y se publiquen en su premium con su formato.

Cómo funciona
- Mira la vista pública de cada canal (t.me/s/<canal>) cada ~20 s. No hace falta cuenta ni sesión de Telegram.
  23/11/2026: los canales que tienen la vista web desactivada (erroresychollosropa, erroresychollosbasicos) se leen
  con una cuenta de Telegram (Telethon) si están los secretos TG_API_ID, TG_API_HASH y TG_SESSION
  (la sesión se saca una vez en el Mac con tools/sesion_telegram.py). Sin esos secretos, esos canales no se copian.
- De cada post nuevo saca el ASIN del botón «Comprar en Amazon» (le quita el tag kevincrestt-21).
- Precio, precio recomendado, stock y foto salen SIEMPRE de la API oficial de Amazon (nada de copiar su precio).
  En el canal warehouse el precio es SIEMPRE el de segunda mano y el nuevo va tachado de referencia.
- Monta la tarjeta del premium (tarjeta_premium.py) y el copy de Enrique, con su enlace cazachollos0c-21,
  y lo publica en el canal. Queda en state/premium_manual.json para que la vigilancia lo pase a AGOTADO.
- Si algo falla (sin ASIN, sin precio, agotado), no publica y avisa a Enrique en su privado con el enlace.
- La primera vez que ve un canal solo apunta por dónde va: no republica lo antiguo.

Uso:  python espejo_canales.py --minutos 345 [--privado] [--seco]
  --privado  manda los posts a tu chat (prueba) en vez de al canal
  --seco     solo lee los canales y dice qué publicaría
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state" / "espejo_canales.json"
TAG = "cazachollos0c-21"
MADRID = ZoneInfo("Europe/Madrid")
PREMIUM = os.environ.get("PREMIUM_CHAT_ID", "").strip() or "-1004494143183"  # Caza Errores | PREMIUM
CANALES = {
    "erroresychollos": "general",
    "erroresycholloswarehouse": "warehouse",
    "erroresychollosropa": "ropa",
    "ErroresRutaYChollos": "general",  # 22/11/2026: lo pidió Enrique
    "erroresychollosbasicos": "general",  # 23/11/2026: lo pidió Enrique (Errores y Chollos Básicos de Kevin)
}
CADA = 20          # segundos entre vueltas
REPETIDO_DIAS = 3  # un mismo ASIN no se vuelve a publicar en estos días
ERROR_PCT = 70     # desde -70% es #ErrorDePrecio (umbral del premium)
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def log(msg: str) -> None:
    print(f"[{datetime.now(MADRID):%H:%M:%S}] {msg}", flush=True)


# ------------------------------------------------------------------ leer los canales

POST_RE = re.compile(r'data-post="([A-Za-z0-9_]+)/(\d+)"')
HREF_RE = re.compile(r'href="([^"]+)"')
TEXT_RE = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)


def html_a_texto(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    return html.unescape(fragment).strip()


def parse_canal(page: str) -> list[dict]:
    """Posts de la vista pública t.me/s/<canal>: id, texto y enlaces (botones incluidos)."""
    marks = list(POST_RE.finditer(page))
    posts = []
    for i, m in enumerate(marks):
        chunk = page[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(page)]
        text = TEXT_RE.search(chunk)
        posts.append({
            "canal": m.group(1),
            "id": int(m.group(2)),
            "texto": html_a_texto(text.group(1)) if text else "",
            "enlaces": [html.unescape(h) for h in HREF_RE.findall(chunk)],
        })
    return posts


def leer_canal(canal: str) -> list[dict]:
    req = urllib.request.Request(f"https://t.me/s/{canal}", headers={"User-Agent": UA, "Accept-Language": "es-ES"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        page = resp.read().decode("utf-8", "replace")
    return [p for p in parse_canal(page) if p["canal"].lower() == canal.lower()]


class LectorCuenta:
    """Lee los canales sin vista web pública con una cuenta de Telegram (solo lectura, sesión en TG_SESSION)."""

    def __init__(self, api_id: int, api_hash: str, session: str):
        from telethon.sync import TelegramClient
        from telethon.sessions import StringSession
        self.client = TelegramClient(StringSession(session), api_id, api_hash)
        self.client.connect()
        if not self.client.is_user_authorized():
            raise RuntimeError("la sesión TG_SESSION ya no vale (hay que sacarla otra vez)")

    @classmethod
    def from_env(cls) -> "LectorCuenta | None":
        api_id = os.environ.get("TG_API_ID", "").strip()
        api_hash = os.environ.get("TG_API_HASH", "").strip()
        session = os.environ.get("TG_SESSION", "").strip()
        if not (api_id and api_hash and session):
            return None
        try:
            lector = cls(int(api_id), api_hash, session)
        except Exception as exc:  # sin cuenta el vigía sigue con la vista web
            log(f"Cuenta de Telegram no disponible ({exc})")
            return None
        log("Cuenta de Telegram lista para los canales sin vista web")
        return lector

    def leer(self, canal: str, limite: int = 20) -> list[dict]:
        posts = []
        for m in self.client.get_messages(canal, limit=limite):
            enlaces = []
            for ent, txt in (m.get_entities_text() or []):
                url = getattr(ent, "url", None) or (txt if type(ent).__name__ == "MessageEntityUrl" else None)
                if url:
                    enlaces.append(url)
            for row in getattr(m.reply_markup, "rows", None) or []:  # botón «Comprar en Amazon»
                for button in row.buttons:  # según la versión: button.url o button.type.url
                    url = getattr(button, "url", None) or getattr(getattr(button, "type", None), "url", None)
                    if url:
                        enlaces.append(url)
            posts.append({"canal": canal, "id": m.id, "texto": m.message or "", "enlaces": enlaces,
                          "fecha": m.date.timestamp() if getattr(m, "date", None) else None})
        return posts


def leer_posts(canal: str, lector: "LectorCuenta | None", state: dict) -> list[dict]:
    """Vista web t.me/s/ y, si el canal la tiene desactivada, la cuenta de Telegram."""
    if lector and canal in state.get("por_cuenta", []):
        return lector.leer(canal)
    posts = leer_canal(canal)
    if posts or not lector:
        return posts
    posts = lector.leer(canal)
    if posts:
        state.setdefault("por_cuenta", []).append(canal)
        log(f"{canal}: sin vista web, lo leo con la cuenta de Telegram")
    return posts


def enlace_amazon(post: dict) -> str | None:
    import affiliate
    for url in post["enlaces"]:
        host = urllib.parse.urlparse(url).netloc.lower()
        if ("amazon." in host and "/dp/" in url) or "/gp/product/" in url or affiliate.is_short_link(url):
            return url
    return None


# ------------------------------------------------------------------ datos que aporta su post

ETIQUETAS = re.compile(r"(SEGUNDA MANO|SUPER ?OFERTA|PRECIAZO|ERROR(?: DE PRECIO)?|CHOLLAZO|CHOLLO|OFERTA FLASH|MÍNIMO HISTÓRICO)", re.I)


def _sin_emoji_inicial(line: str) -> str:
    return re.sub(r"^[^\wÁÉÍÓÚÑáéíóúñ¡¿(]+", "", line).strip()


def datos_post(texto: str) -> dict:
    """Del texto del post saca la etiqueta (SUPEROFERTA…), el nombre corto, quién lo vende, estado y talla."""
    lines = [l.strip() for l in texto.splitlines() if l.strip()]
    out: dict = {}
    for line in lines:
        clean = _sin_emoji_inicial(line)
        low = clean.lower()
        if "etiqueta" not in out and ETIQUETAS.fullmatch(clean.upper().strip("!¡ ")):
            out["etiqueta"] = clean.upper()
            continue
        if low.startswith("precio en amazon") or "puede cambiar" in low or low.startswith("en calidad de"):
            continue
        if line.startswith("⚠") or "embalaje" in low:
            out.setdefault("aviso", clean)
        elif "vendido por" in low or "enviado por" in low:
            out.setdefault("vendedor", clean)
        elif re.match(r"(estado|condici[oó]n)\b", low) or "reacondicionado" in low or "como nuevo" in low:
            out.setdefault("estado", re.sub(r"^(estado|condici[oó]n)\s*:?\s*", "", clean, flags=re.I))
        elif re.match(r"tallas?\b", low):
            out.setdefault("talla", re.sub(r"^tallas?\s*:?\s*", "", clean, flags=re.I))
        elif "nombre" not in out and "etiqueta" in out and 3 <= len(clean) <= 120:
            out["nombre"] = clean
    return out


# ------------------------------------------------------------------ copy y publicación

def eur(value: float) -> str:
    whole, dec = f"{value:,.2f}".split(".")
    return f"{whole.replace(',', '.')},{dec}€"


def titulo_corto(title: str, limite: int = 70) -> str:
    """Nombre limpio para el móvil: corta en el primer separador de la ficha (| - , «(») y a palabra entera."""
    title = re.sub(r"\s+", " ", title or "").strip()
    for sep in (" | ", " - ", " – ", ", ", " ("):
        i = title.find(sep)
        if i >= 25:
            title = title[:i]
            break
    if len(title) <= limite:
        return title
    cut = title[:limite].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;-–|(")


def enlace_visible(link: str) -> str:
    """Lo que se ve en el copy: el enlace corto amazon.es/dp/ASIN, sin https ni tag (21/11/2026, Enrique).
    Al pinchar lleva al enlace largo con su tag (caption_html lo convierte en hipervínculo)."""
    m = re.search(r"/dp/([A-Z0-9]{10})", link or "")
    return f"amazon.es/dp/{m.group(1)}" if m else link


def hacer_copy(nombre: str, live: dict, extra: dict, tipo: str, link: str) -> str:
    """Copy pensado para el móvil (23/11/2026): líneas cortas, el precio solo una vez y el ahorro en euros.
    El botón «Comprar en Amazon» y el de WhatsApp van debajo (botones_premium.py)."""
    current, reference = live["price"], live.get("reference")
    pct = round((reference - current) / reference * 100) if reference else None
    error = (pct is not None and pct >= ERROR_PCT) or "ERROR" in (extra.get("etiqueta") or "")
    cabecera = "❗️ #ErrorDePrecio" if error else "💎 #Chollo"
    if pct:
        cabecera += f" · -{pct}%"

    lines = [cabecera, "", titulo_corto(nombre), ""]
    lines.append(f"💸 {eur(current)}" + (f" {eur(reference)}" if reference else ""))
    if reference:
        frente = " frente al nuevo" if tipo == "warehouse" else ""
        lines.append(f"💰 Te ahorras {eur(reference - current)}{frente}")

    detalles = []
    if tipo == "warehouse":
        estado = (extra.get("estado") or "").replace("Reacondicionado - ", "").strip()
        detalles.append("♻️ Segunda mano" + (f" · {estado[:1].upper()}{estado[1:]}" if estado else ""))
    if tipo == "ropa" and extra.get("talla"):
        detalles.append(f"👕 Talla {extra['talla']}")
    if extra.get("aviso"):
        detalles.append(f"⚠️ {extra['aviso']}")
    vendedor = extra.get("vendedor") or ""
    if vendedor and not re.search(r"vendido (y enviado )?por amazon\b", vendedor, re.I):
        detalles.append(f"🏷️ {vendedor}")
    if detalles:
        lines += [""] + detalles
    lines += ["", f"🛒 {enlace_visible(link)}"]
    return "\n".join(lines)


def cargar_estado() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"ultimo": {}, "publicados": []}


def guardar_estado(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    state["publicados"] = state["publicados"][-300:]
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def subir_memoria(msg: str) -> None:
    """Guarda la memoria en el repo tras cada publicación (si el job se corta, no repite posts)."""
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    script = ROOT / "tools" / "guardar_espejo.sh"
    subprocess.run(["bash", str(script), msg], cwd=ROOT, check=False)


def ya_publicado(asin: str, state: dict) -> bool:
    limite = time.time() - REPETIDO_DIAS * 86400
    if any(p["asin"] == asin and p["t"] > limite for p in state["publicados"]):
        return True
    import premium_manual  # también los que Enrique ha subido a mano
    return any(p.get("asin") == asin and p.get("t", 0) > limite and not p.get("agotado")
               for p in premium_manual.load_state().get("posts", []))


def avisar(tg, texto: str) -> None:
    import privado
    admin = privado.admin_id()
    if not admin:
        return
    try:
        tg.call("sendMessage", {"chat_id": admin, "text": texto, "disable_web_page_preview": True})
    except Exception as exc:  # el aviso nunca tumba el vigía
        log(f"  No he podido avisarte: {exc}")


def segunda_mano(api, asin: str) -> dict | None:
    """Canal warehouse: SIEMPRE el precio de segunda mano (22/11/2026, Enrique: «de ese canal siempre pilla los
    precios de segunda mano»). El precio nuevo de la ficha solo sirve de referencia tachada («Nuevo precio»),
    igual que en la tarjeta de @kevincrestt (p. ej. Lefant M3 MAX: 214,58€ como nuevo frente a 899,99€ nuevo).
    Antes se cogía la oferta nueva si había stock y salió a 899,99€."""
    from amazon_api import ApiError
    nuevo = api.get_item(asin)
    try:
        used = api.get_item(asin, condition="Used")
    except ApiError as exc:
        log(f"  {asin}: la API no me da la oferta de segunda mano ({exc})")
        used = None
    if not (used and used.get("in_stock") and used.get("price")):
        log(f"  {asin}: sin oferta de segunda mano en la API, no lo publico con el precio nuevo")
        return {**(used or {}), "price": None, "in_stock": False, "title": (nuevo or {}).get("title"),
                "image": (nuevo or {}).get("image")}
    out = dict(used)
    out.setdefault("title", (nuevo or {}).get("title"))
    out["title"] = out.get("title") or (nuevo or {}).get("title")
    out["image"] = out.get("image") or (nuevo or {}).get("image")
    precio_nuevo = (nuevo or {}).get("price")
    if precio_nuevo and precio_nuevo > used["price"]:
        out["saving_basis"] = precio_nuevo
        out["ref_label"] = "nuevo"
    log(f"  {asin}: segunda mano {used.get('condition') or '?'} a {used['price']} (nuevo {precio_nuevo})")
    return out


def procesar(post: dict, tipo: str, api, tg, state: dict, privado_: bool, seco: bool) -> None:
    from premium_manual import clean_link, caption_html, load_state, save_state, photo_for, OUT
    from tarjeta_premium import crear_tarjeta
    import premium_manual

    origen = f"https://t.me/{post['canal']}/{post['id']}"
    raw = enlace_amazon(post)
    if not raw:
        log(f"  {origen}: sin enlace de Amazon, lo salto")
        return
    try:
        link = clean_link(raw)  # https://www.amazon.es/dp/ASIN?tag=cazachollos0c-21, sin rastro de su tag
    except ValueError as exc:
        avisar(tg, f"⚠️ Vigía: no saco el producto de {origen} ({exc})")
        return
    asin = link.split("/dp/")[1][:10]
    if f"tag={TAG}" not in link or "kevincrestt" in link:
        avisar(tg, f"⚠️ Vigía: el enlace de {origen} no queda con tu tag, no lo publico")
        return
    if ya_publicado(asin, state) and not privado_:  # en prueba (privado) se enseña igual
        log(f"  {origen}: {asin} ya está en el premium, lo salto")
        return

    live = segunda_mano(api, asin) if (api and tipo == "warehouse") else (api.get_item(asin) if api else None)
    if not live or not live.get("price") or not live.get("in_stock"):
        motivo = "sin datos en la API" if not live else ("agotado" if not live.get("in_stock") else "sin precio")
        log(f"  {origen}: {asin} {motivo}, no lo publico")
        avisar(tg, f"⚠️ Vigía: {origen} ({asin}) {motivo} en Amazon, no lo he publicado.\n{link}")
        return
    basis = live.get("saving_basis")
    live["reference"] = basis if basis and basis > live["price"] else None

    extra = datos_post(post["texto"])
    nombre = extra.get("nombre") or titulo_corto(live.get("title") or "")
    copy = hacer_copy(nombre, live, extra, tipo, link)
    if seco:
        log(f"  [seco] {origen} → publicaría:\n{copy}")
        return

    when = f"{datetime.now(MADRID):%d/%m · %H:%M}"
    image = live.get("image")
    if not image:
        avisar(tg, f"⚠️ Vigía: {asin} sin foto en la API, no lo he publicado.\n{link}")
        return
    spec = {"asin": asin, "image": image}
    ref_label = live.get("ref_label") or "recomendado"
    card = crear_tarjeta(photo_for(spec, asin), live["reference"], live["price"], when, OUT / f"{asin}.jpg",
                         ref_label=ref_label)
    caption = caption_html(copy, {enlace_visible(link): link})
    import privado
    chat = privado.admin_id() if privado_ else PREMIUM
    import botones_premium
    msg = tg.send_photo(chat, card, caption, {"reply_markup": botones_premium.teclado(link)})
    pct = round((live["reference"] - live["price"]) / live["reference"] * 100) if live["reference"] else 0
    log(f"  PUBLICADO {asin} ({nombre}) · {eur(live['price'])} · -{pct}% → mensaje {msg['message_id']}"
        + (" [privado]" if privado_ else ""))
    if privado_:
        return
    state["publicados"].append({"asin": asin, "origen": origen, "message_id": msg["message_id"], "t": int(time.time())})
    guardar_estado(state)
    manual = load_state()  # así la vigilancia de cada hora y el sello AGOTADO lo tratan igual que los tuyos
    manual["posts"].append({"message_id": msg["message_id"], "asin": asin, "link": link, "image": image,
                            "reference": live["reference"], "current": live["price"], "when": when,
                            "ref_label": ref_label, "caption": caption, "t": int(time.time()),
                            "auto": origen})
    save_state(manual)
    subir_memoria(f"Vigía: {asin} publicado en el premium")


def vuelta(api, tg, state: dict, privado_: bool, seco: bool, lector: "LectorCuenta | None" = None) -> None:
    for canal, tipo in CANALES.items():
        try:
            posts = leer_posts(canal, lector, state)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log(f"{canal}: no responde ({exc})")
            continue
        except Exception as exc:  # p. ej. FloodWait de la cuenta: se reintenta en la siguiente vuelta
            log(f"{canal}: fallo leyendo con la cuenta ({exc})")
            continue
        if not posts:
            if canal not in state.setdefault("sin_vista", []):  # avisa una vez: la web t.me/s/ no enseña sus posts
                state["sin_vista"].append(canal)
                log(f"{canal}: la vista web t.me/s/{canal} no muestra posts, no puedo vigilarlo")
                avisar(tg, f"⚠️ Vigía: t.me/{canal} no tiene vista web pública y no hay cuenta de Telegram "
                           "(secretos TG_API_ID, TG_API_HASH y TG_SESSION), ese canal no se está copiando.")
                guardar_estado(state)
            continue
        if canal in state.get("sin_vista", []):
            state["sin_vista"].remove(canal)
        ultimo = state["ultimo"].get(canal)
        top = max(p["id"] for p in posts)
        if ultimo is None:  # primera vez: solo apunto por dónde va
            state["ultimo"][canal] = top
            log(f"{canal}: empiezo a vigilar desde el post {top}")
            guardar_estado(state)
            continue
        for post in sorted((p for p in posts if p["id"] > ultimo), key=lambda p: p["id"]):
            log(f"{canal}: post nuevo {post['id']}")
            try:
                procesar(post, tipo, api, tg, state, privado_, seco)
            except Exception as exc:  # un post raro nunca para el vigía
                log(f"  Error con {canal}/{post['id']}: {exc}")
                avisar(tg, f"⚠️ Vigía: fallo con https://t.me/{canal}/{post['id']} ({exc}). Súbelo a mano si vale.")
            state["ultimo"][canal] = post["id"]
            guardar_estado(state)


class Callado:
    """Bot de Telegram que publica pero no te manda avisos al privado (para repasar posts antiguos)."""

    def __init__(self, tg):
        self.tg = tg
        self.saltados = 0

    def call(self, method, params=None):
        if method == "sendMessage":
            self.saltados += 1
            return {}
        return self.tg.call(method, params)

    def send_photo(self, *args, **kwargs):
        return self.tg.send_photo(*args, **kwargs)


def repasar(canal: str, dias: float, api, tg, state: dict, privado_: bool, seco: bool,
            lector: "LectorCuenta | None") -> int:
    """23/11/2026: publica en el premium lo que un canal ya tenía y siga en stock (sin avisos de agotados)."""
    tipo = CANALES.get(canal, "general")
    posts = lector.leer(canal, limite=200) if lector else leer_canal(canal)
    desde = time.time() - dias * 86400
    posts = sorted((p for p in posts if (p.get("fecha") or time.time()) >= desde), key=lambda p: p["id"])
    log(f"Repaso {canal}: {len(posts)} posts de los últimos {dias:g} días")
    callado = Callado(tg)
    antes = len(state["publicados"])
    for post in posts:
        try:
            procesar(post, tipo, api, callado, state, privado_, seco)
        except Exception as exc:
            log(f"  Error con {canal}/{post['id']}: {exc}")
        if not seco:
            time.sleep(3)  # sin ráfagas en el canal
    nuevos = len(state["publicados"]) - antes
    log(f"Repaso {canal} terminado: {nuevos} publicados, {callado.saltados} descartados (agotados, sin precio o sin ASIN)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutos", type=float, default=345)
    parser.add_argument("--privado", action="store_true", help="Posts a tu chat privado, no al canal")
    parser.add_argument("--seco", action="store_true", help="Solo leer y decir qué publicaría")
    parser.add_argument("--repasar", help="Canal cuyos posts ya publicados repasar (publica lo que siga en stock)")
    parser.add_argument("--dias", type=float, default=30, help="Con --repasar: posts de los últimos N días")
    args = parser.parse_args()

    from scanner import Telegram
    from amazon_api import CreatorsAPI
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Falta TELEGRAM_BOT_TOKEN", file=sys.stderr)
        return 2
    tg = Telegram(token)
    api = CreatorsAPI.from_env(TAG)
    if api is None and not args.seco:
        print("Faltan las credenciales de la Creators API", file=sys.stderr)
        return 2

    state = cargar_estado()
    lector = LectorCuenta.from_env()
    if lector is None:
        state["por_cuenta"] = []
    if args.repasar:
        return repasar(args.repasar, args.dias, api, tg, state, args.privado, args.seco, lector)
    fin = time.time() + args.minutos * 60
    log(f"Vigía en marcha {args.minutos:.0f} min sobre {', '.join(CANALES)}")
    while time.time() < fin:
        start = time.time()
        vuelta(api, tg, state, args.privado, args.seco, lector)
        time.sleep(max(1.0, CADA - (time.time() - start)))
    log("Fin de la vigilancia, paso el relevo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
