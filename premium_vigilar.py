"""Pasada de cada hora por el premium @caza_errores: ¿siguen vivos los errores y chollos publicados?

Pedido por Enrique el 17/11/2026. Para cada tarjeta del canal (foto con #ErrorDePrecio o #Chollo) mira en la
API oficial de Amazon si el producto sigue al precio publicado:
- sin stock / sin precio            → tarjeta en blanco y negro con el sello AGOTADO
- en stock pero más caro             → tarjeta en blanco y negro con el sello OFERTA TERMINADA
- sigue igual o más barato           → no se toca
El texto, los enlaces y los botones del post se quedan tal cual: solo cambia la imagen.

Cómo lee el canal: la Bot API no deja leer el historial, así que el bot reenvía cada post nuevo a tu chat
privado en silencio, lo lee (foto, texto, enlaces) y borra el reenvío al momento. Solo una vez por post.

Seguridad para no marcar nada por error:
- Un post que ya está en blanco y negro no se vuelve a sellar.
- Antes de sellar se repite la consulta a Amazon un minuto después; solo se sella si sigue igual.
- Si Amazon no devuelve el producto (API caída, ASIN raro) no se marca nada.
- Los posts con cupón, código o precio pagando con PayPal solo se marcan si se AGOTAN (el precio que da la API
  es sin cupón, así que «más caro» no significa que la oferta haya terminado).
- Los reenvíos del free no se pueden editar y se ignoran.

Uso: python premium_vigilar.py [--prueba] [--diagnostico]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image

import privado
from amazon_api import ApiError, CreatorsAPI
from scanner import Telegram
from tarjeta_premium import es_blanco_y_negro, sellar

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state" / "premium_vigilancia.json"
MADRID = ZoneInfo("Europe/Madrid")
TAG = "cazachollos0c-21"
PREMIUM = os.environ.get("PREMIUM_CHAT_ID", "").strip() or "-1004494143183"  # Caza Errores | PREMIUM
SEED_FROM = 150          # los posts de antes del 10/11 ya se borraron el 17/11
MISSES_SEED = 40         # huecos seguidos (mensajes borrados) antes de dar por acabado el canal
MISSES = 15
MAX_AGE_DAYS = 30        # un error de hace más de un mes ya no se vigila
RECHECK_WAIT = 60
CARD = re.compile(r"#(ErrorDePrecio|Chollo)\b", re.I)
EURO = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s?€")
COUPON = re.compile(r"cup[oó]n|c[oó]digo|paypal", re.I)
ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d)/([A-Z0-9]{10})", re.I)
SHORT_HOSTS = ("link.amazon", "amzn.to", "amzn.eu")


def log(msg: str) -> None:
    print(msg, flush=True)


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"ultimo": SEED_FROM - 1, "posts": {}}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def euro_to_float(text: str) -> float:
    return float(text.replace(".", "").replace(",", "."))


def posted_price(caption: str) -> float | None:
    """El precio al que se publicó: el primero de la línea 💸 / «Lo pillas a…»."""
    for line in caption.splitlines():
        if "💸" in line or re.search(r"pillas a", line, re.I):
            found = EURO.search(line)
            if found:
                return euro_to_float(found.group(1))
    found = EURO.search(caption)
    return euro_to_float(found.group(1)) if found else None


def links_of(msg: dict) -> list[str]:
    text = msg.get("caption") or ""
    urls = re.findall(r"https?://\S+", text)
    for ent in msg.get("caption_entities") or []:
        if ent.get("type") == "text_link":
            urls.append(ent["url"])
        elif ent.get("type") == "url":
            # Los offsets de Telegram van en UTF-16
            raw = text.encode("utf-16-le")
            urls.append(raw[ent["offset"] * 2:(ent["offset"] + ent["length"]) * 2].decode("utf-16-le"))
    for row in (msg.get("reply_markup") or {}).get("inline_keyboard") or []:
        urls += [b["url"] for b in row if b.get("url")]
    return [u.rstrip(").,") for u in dict.fromkeys(urls)]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def resolve_asin(url: str) -> str | None:
    found = ASIN_RE.search(url)
    if found:
        return found.group(1).upper()
    host = urllib.parse.urlparse(url).netloc.lower()
    if not any(host.endswith(h) for h in SHORT_HOSTS):
        return None
    opener = urllib.request.build_opener(_NoRedirect)
    for _ in range(4):  # el enlace corto puede encadenar un par de redirecciones
        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0"})
        try:
            with opener.open(req, timeout=20) as resp:
                found = ASIN_RE.search(resp.geturl())
                return found.group(1).upper() if found else None
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location")
            if exc.code not in (301, 302, 303, 307, 308) or not location:
                return None
            url = urllib.parse.urljoin(url, location)
            found = ASIN_RE.search(url)
            if found:
                return found.group(1).upper()
        except (urllib.error.URLError, OSError):
            return None
    return None


def title_of(caption: str) -> str:
    """El nombre del producto: la primera línea sin hashtags, enlaces ni las líneas de datos (💸 ♻️ 📈 👀 🌟)."""
    for line in caption.splitlines():
        line = line.strip()
        if line and "#" not in line and "http" not in line and not line.startswith(("💸", "♻️", "📈", "👀", "🌟", "🛒", "⛔", "🚫")):
            return line[:70]
    return ""


# ------------------------------------------------------------------ leer el canal

def call_retry(tg: Telegram, method: str, params: dict) -> dict:
    """Llamada a Telegram con hasta 3 reintentos si se corta la conexión o pide esperar."""
    for attempt in range(4):
        try:
            return tg.call(method, params)
        except RuntimeError as exc:
            text = str(exc).lower()
            wait = re.search(r"retry after (\d+)", text)
            if attempt == 3 or not ("sin conexión" in text or wait):
                raise
            time.sleep(int(wait.group(1)) + 1 if wait else 3 * (attempt + 1))
    raise RuntimeError("inalcanzable")


def read_post(tg: Telegram, admin: int, message_id: int) -> dict | None:
    """Reenvía el post a tu chat en silencio, lo lee y borra el reenvío. None si ese mensaje no existe."""
    try:
        fwd = call_retry(tg, "forwardMessage", {"chat_id": admin, "from_chat_id": PREMIUM, "message_id": message_id,
                                                "disable_notification": True})
    except RuntimeError as exc:
        text = str(exc).lower()
        if "not found" in text or "can't be forwarded" in text or "message to forward" in text:
            return None
        raise
    try:
        call_retry(tg, "deleteMessage", {"chat_id": admin, "message_id": fwd["message_id"]})
    except RuntimeError as exc:
        log(f"  (no he podido borrar el reenvío de prueba {fwd['message_id']}: {exc})")
    return fwd


def register(post_id: int, fwd: dict) -> dict | None:
    origin = fwd.get("forward_origin") or {}
    origin_chat = str((origin.get("chat") or {}).get("id", ""))
    if origin.get("type") != "channel" or origin_chat != str(PREMIUM):
        return {"tipo": "reenvio"}  # reenvío del free: no se puede editar
    caption = fwd.get("caption") or ""
    if not fwd.get("photo") or not CARD.search(caption):
        return {"tipo": "otro"}
    asin = None
    for url in links_of(fwd):
        asin = resolve_asin(url)
        if asin:
            break
    return {
        "tipo": "tarjeta",
        "asin": asin,
        "precio": posted_price(caption),
        "titulo": title_of(caption),
        "cupon": bool(COUPON.search(caption)),
        "segunda": bool(re.search(r"segunda mano", caption, re.I)),
        "fecha": int(origin.get("date") or fwd.get("date") or time.time()),
        "estado": "vivo",
    }


def discover(tg: Telegram, admin: int, state: dict) -> None:
    first = not state["posts"]
    limit = MISSES_SEED if first else MISSES
    mid, misses = int(state["ultimo"]) + 1, 0
    while misses < limit:
        try:
            fwd = read_post(tg, admin, mid)
        except RuntimeError as exc:
            log(f"  Telegram falla leyendo el post {mid} ({exc}); sigo en la próxima pasada")
            return
        if fwd is None:
            misses += 1
        else:
            misses = 0
            info = register(mid, fwd)
            state["posts"][str(mid)] = info
            state["ultimo"] = mid
            if info["tipo"] == "tarjeta":
                log(f"  Nuevo post {mid}: {info['titulo']} · {info['asin'] or 'sin ASIN'} · {info['precio']}€")
            time.sleep(0.4)
        mid += 1


# ------------------------------------------------------------------ editar la tarjeta

def edit_card(token: str, tg: Telegram, admin: int, message_id: int, motivo: str) -> bool:
    """Sella la tarjeta del post. False si ya estaba en blanco y negro (no se toca)."""
    fwd = read_post(tg, admin, message_id)
    if fwd is None or not fwd.get("photo"):
        raise RuntimeError("el post ya no existe o no tiene foto")
    big = max(fwd["photo"], key=lambda p: p.get("width", 0) * p.get("height", 0))
    path = tg.call("getFile", {"file_id": big["file_id"]})["file_path"]
    with urllib.request.urlopen(f"https://api.telegram.org/file/bot{token}/{path}", timeout=60) as resp:
        im = Image.open(BytesIO(resp.read()))
        im.load()
    if es_blanco_y_negro(im):
        return False
    buf = BytesIO()
    sellar(im, motivo).save(buf, "JPEG", quality=93)

    media = {"type": "photo", "media": "attach://photo", "caption": fwd.get("caption") or ""}
    if fwd.get("caption_entities"):
        media["caption_entities"] = fwd["caption_entities"]
    if fwd.get("show_caption_above_media"):
        media["show_caption_above_media"] = True
    fields = {"chat_id": PREMIUM, "message_id": str(message_id), "media": json.dumps(media, ensure_ascii=False)}
    if fwd.get("reply_markup"):
        fields["reply_markup"] = json.dumps(fwd["reply_markup"], ensure_ascii=False)
    boundary = "----vigila" + uuid.uuid4().hex
    parts = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8")
             for k, v in fields.items()]
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"card.jpg\"\r\n"
                 "Content-Type: image/jpeg\r\n\r\n".encode("utf-8") + buf.getvalue() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("ascii"))
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/editMessageMedia", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        result = json.loads(exc.read().decode("utf-8") or "{}")
    if not result.get("ok"):
        raise RuntimeError(f"Telegram editMessageMedia: {result.get('description')}")
    return True


# ------------------------------------------------------------------ comprobar en Amazon

def verdict(post: dict, live: dict | None) -> str | None:
    """None si sigue vivo o no se sabe; «agotado» o «terminada» si hay que sellarlo."""
    if live is None:
        return None  # Amazon no devuelve el producto: no se marca nada por si acaso
    price = live.get("price")
    avail = str(live.get("availability") or "").upper()
    # Solo es AGOTADO si Amazon no da precio o lo da como no disponible. «Envío en X días», reserva,
    # pocas unidades… con precio se pueden comprar (el 17/11 la API daba así el Citizen y el Garmin, activos).
    if price is None or any(k in avail for k in ("OUT_OF_STOCK", "UNAVAILABLE", "DISCONTINUED")):
        return "agotado"
    if post.get("cupon") or post.get("precio") is None:
        return None
    return "terminada" if price > float(post["precio"]) + 0.009 else None


def check(api: CreatorsAPI, posts: dict[str, dict]) -> dict[str, tuple[str | None, dict | None]]:
    asins = [p["asin"] for p in posts.values()]
    live = api.get_items(asins)
    out = {}
    for mid, p in posts.items():
        item = live.get(p["asin"].upper())
        result = verdict(p, item)
        # Segunda mano (21/11/2026): la oferta normal puede ser la nueva; antes de sellar, mira la usada.
        if result and (p.get("segunda") or "segunda mano" in (p.get("titulo") or "").lower()):
            try:
                used = api.get_item(p["asin"], condition="Used")
            except Exception as exc:  # sin oferta usada clara no se sella nada por si acaso
                log(f"  {p['asin']}: no compruebo la oferta de segunda mano ({exc}), no lo sello")
                used, result = None, None
            if used is not None:
                item, result = used, verdict(p, used)
        out[mid] = (result, item)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prueba", action="store_true", help="Lo mira todo pero no edita ninguna tarjeta")
    parser.add_argument("--diagnostico", action="store_true", help="Solo comprueba permisos del bot en el canal")
    args = parser.parse_args()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    admin = privado.admin_id()
    if not token or not admin:
        log("Falta TELEGRAM_BOT_TOKEN o ADMIN_CHAT_ID")
        return 2
    tg = Telegram(token)

    if args.diagnostico:
        me = tg.call("getMe")
        chat = tg.call("getChat", {"chat_id": PREMIUM})
        member = tg.call("getChatMember", {"chat_id": PREMIUM, "user_id": me["id"]})
        log(f"Bot @{me['username']} en «{chat.get('title')}» (@{chat.get('username') or '-'}, {chat['id']}): "
            f"{member.get('status')} · editar mensajes de otros: {member.get('can_edit_messages')} · "
            f"publicar: {member.get('can_post_messages')}")
        return 0

    api = CreatorsAPI.from_env(TAG)
    if api is None:
        log("Falta la API de Amazon (AMAZON_CREATORS_ID / AMAZON_CREATORS_SECRET)")
        return 2

    state = load_state()
    log("Buscando posts nuevos en el premium…")
    discover(tg, admin, state)
    save_state(state)

    now = time.time()
    alive = {mid: p for mid, p in state["posts"].items()
             if p.get("tipo") == "tarjeta" and p.get("estado") == "vivo" and p.get("asin")
             and now - p.get("fecha", now) < MAX_AGE_DAYS * 86400}
    log(f"Compruebo {len(alive)} tarjetas vivas en Amazon")
    if not alive:
        return 0
    try:
        first = check(api, alive)
    except ApiError as exc:
        log(f"La API de Amazon no responde ({exc}); lo vuelvo a intentar en la próxima pasada")
        return 0
    suspects = {mid: alive[mid] for mid, (v, _) in first.items() if v}
    for mid, (v, live) in first.items():
        p = alive[mid]
        p["comprobado"] = int(now)
        if live:
            p["ultimo_precio"] = live.get("price")
        if not v:
            log(f"  {mid} {p['titulo']}: sigue ({live.get('price') if live else 'sin datos'}€ vs {p['precio']}€, "
                f"{live.get('availability') if live else '-'})")

    if suspects:
        log(f"{len(suspects)} parecen terminadas; lo confirmo dentro de {RECHECK_WAIT}s")
        time.sleep(RECHECK_WAIT)
        try:
            second = check(api, suspects)
        except ApiError as exc:
            log(f"La API de Amazon no responde en la confirmación ({exc}); no marco nada")
            second = {}
        stamped = []
        for mid, p in suspects.items():
            v, live = second.get(mid, (None, None))
            if not v:
                log(f"  {mid} {p['titulo']}: en la segunda consulta sigue bien, no lo marco")
                continue
            sello = "AGOTADO" if v == "agotado" else "OFERTA TERMINADA"
            now_txt = datetime.now(timezone.utc).astimezone(MADRID).strftime("%H:%M")
            log(f"  {mid} {p['titulo']}: {sello} (ahora {live.get('price') if live else '-'}€, "
                f"disponibilidad {live.get('availability') if live else '-'}; publicado a {p['precio']}€)")
            if args.prueba:
                continue
            try:
                changed = edit_card(token, tg, admin, int(mid), v)
            except RuntimeError as exc:
                log(f"    No he podido editar el post {mid}: {exc}")
                continue
            p["estado"] = v
            p["sellado"] = int(time.time())
            if changed:
                stamped.append(f"{'🚫' if v == 'agotado' else '⛔'} {sello} · {p['titulo']} ({now_txt})")
            else:
                log("    ya estaba en blanco y negro, no lo toco")
        if stamped:
            try:
                tg.call("sendMessage", {"chat_id": admin, "disable_notification": True,
                                        "text": "Caza Errores PREMIUM · pasada de cada hora\n\n" + "\n".join(stamped)})
            except RuntimeError:
                pass
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
