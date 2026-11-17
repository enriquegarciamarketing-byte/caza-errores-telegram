#!/usr/bin/env python3
"""Canal de WhatsApp de Caza Chollos: lo mismo que sale en @cazachollos_com, también en WhatsApp.

Cada chollo (automático o manual) con su foto y el mismo copy, y cada noche el resumen con el top del día.

Meta no deja publicar en canales de WhatsApp con su API oficial, así que va por Whapi.Cloud. El plan
Sandbox es gratis pero tiene tope: 150 mensajes al día y 1.000 peticiones al mes. Como el canal de Telegram
saca 20-40 posts al día, aquí se reparte el cupo (config.json → amazon_channel.whatsapp_*): como mucho
whatsapp_daily_max chollos al día, separados al menos whatsapp_min_gap_minutes, y nunca más de
whatsapp_monthly_budget peticiones al mes, guardando siempre hueco para el resumen de cada noche.
Los posts manuales se saltan la separación (son los que molan) pero no el tope del mes.
Whapi va vinculado a un número SECUNDARIO de WhatsApp (nunca el personal) escaneando un QR, como
WhatsApp Web. Ese número tiene que ser propietario o administrador del canal.

Canal: https://whatsapp.com/channel/0029VbE063mEwEk5M7m9Xe17 (código en config.json → whatsapp_invite).

Secretos del repo:
- WHAPI_TOKEN: el token de Whapi. Sin él no se hace nada y el resumen de Telegram sale igual.
- WHATSAPP_CHANNEL_ID (opcional): el ID del canal (120363…@newsletter). Si falta, se saca del enlace.
- WHATSAPP_TEST_TO (opcional): número al que mandar las pruebas (34600111222), nunca al canal.

Si WhatsApp falla, solo se apunta en el log: Telegram es lo primero y nunca se bloquea por esto.

Uso a mano:
  python whatsapp.py --comprobar        conexión y canal, sin publicar nada
  python whatsapp.py --prueba           manda un resumen de ejemplo a WHATSAPP_TEST_TO (nunca al canal)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

GATE = "https://gate.whapi.cloud"
MADRID = ZoneInfo("Europe/Madrid")
TELEGRAM = "https://t.me/cazachollos_com"
DEFAULT_INVITE = "0029VbE063mEwEk5M7m9Xe17"
DEFAULT_TAG = "cazachollos0c-21"
NUMBERS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
MAX_ITEMS = 8  # con más, en el móvil se hace eterno
ASIN_RE = re.compile(r"/(?:dp|gp/product)/([A-Z0-9]{10})", re.I)


class WhapiError(RuntimeError):
    pass


def euro(amount: float) -> str:
    return f"{amount:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def short_title(title: str, limit: int = 70) -> str:
    # En WhatsApp *, _, ~ y ` dan formato: fuera del título para que no lo rompan.
    title = re.sub(r"[*_~`]", "", " ".join(str(title or "").split()))
    return title if len(title) <= limit else title[: limit - 1].rstrip(" ,.-·|") + "…"


def affiliate_url(item: dict, tag: str = DEFAULT_TAG) -> str:
    """Enlace limpio amazon.es/dp/ASIN?tag=… Siempre con el tag de afiliado, sea cual sea el enlace de origen."""
    asin = str(item.get("asin") or "").strip().upper()
    if not asin:
        found = ASIN_RE.search(str(item.get("url") or ""))
        asin = found.group(1).upper() if found else ""
    if asin:
        return f"https://www.amazon.es/dp/{asin}?tag={tag}"
    url = str(item.get("url") or "")
    parts = urllib.parse.urlsplit(url)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if k != "tag"] + [("tag", tag)]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def build_text(items: list[dict], now: datetime, tag: str = DEFAULT_TAG, test: bool = False) -> str:
    hour = now.astimezone(MADRID).strftime("%H:%M")
    items = items[:MAX_ITEMS]
    lines = []
    if test:
        lines += ["🧪 *PRUEBA* · así saldría en el canal", ""]
    lines += ["🌙 *CERRAMOS EL DÍA · LO MEJOR DE HOY EN AMAZON*", "",
              f"Los {len(items)} chollos más bestias de hoy que siguen activos ahora mismo 👇", ""]
    for index, item in enumerate(items):
        num = NUMBERS[index] if index < len(NUMBERS) else f"{index + 1}."
        discount = round(float(item.get("discount") or 0))
        lines.append(f"{num} *{short_title(item.get('title'))}*")
        lines.append(f"💰 *{euro(float(item['price']))}*  ~{euro(float(item['reference']))}~  📉 *-{discount} %*")
        lines.append(f"🛒 {affiliate_url(item, tag)}")
        lines.append("")
    lines.append(f"🕒 Precios a las {hour} · pueden cambiar")
    lines.append(f"📲 Cada día desde las 7:00 más chollos en Telegram 👉 {TELEGRAM}")
    lines.append("")
    lines.append("#Publicidad")
    return "\n".join(lines)


# ---------------------------------------------------------------- Whapi


def _request(method: str, path: str, token: str, body: bytes | None = None, ctype: str = "",
             timeout: int = 40) -> dict:
    req = urllib.request.Request(GATE + path, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise WhapiError(f"HTTP {exc.code} en {path}: {detail}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise WhapiError(f"sin conexión con Whapi ({exc})") from exc
    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError:
        return {}


def _json(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    return _request(method, path, token, body, "application/json" if body else "")


def channel_info(token: str, invite: str = DEFAULT_INVITE) -> dict:
    code = invite.rstrip("/").rsplit("/", 1)[-1]
    return _json("GET", f"/newsletters/link/{code}", token)


def own_role(token: str, channel: str) -> str:
    """Rol del número vinculado en el canal (owner/admin/subscriber). El enlace no lo trae; la lista sí."""
    data = _json("GET", "/newsletters?count=100", token)
    for item in data.get("newsletters") or []:
        if item.get("id") == channel:
            return str(item.get("role") or "")
    return ""


def resolve_channel(token: str, invite: str = DEFAULT_INVITE, log=print) -> str:
    fixed = (os.environ.get("WHATSAPP_CHANNEL_ID") or "").strip()
    if fixed:
        return fixed
    info = channel_info(token, invite)
    channel = str(info.get("id") or "")
    if not channel.endswith("@newsletter"):
        raise WhapiError(f"no encuentro el canal del enlace ({info})")
    role = str(info.get("role") or "")
    if role and role not in ("owner", "admin"):
        log(f"  WhatsApp: ojo, el número vinculado a Whapi es «{role}» del canal, no administrador; "
            "no podrá publicar")
    return channel


def send_text(token: str, to: str, text: str) -> dict:
    return _json("POST", "/messages/text", token, {"to": to, "body": text, "no_link_preview": True})


def send_image(token: str, to: str, image: Path, caption: str = "") -> dict:
    boundary = uuid.uuid4().hex
    parts = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"to\"\r\n\r\n{to}\r\n".encode()]
    if caption:
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n".encode()
                     + caption.encode() + b"\r\n")
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"media\"; filename=\"{image.name}\"\r\n"
                 f"Content-Type: image/jpeg\r\n\r\n".encode() + image.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return _request("POST", "/messages/image", token, b"".join(parts), f"multipart/form-data; boundary={boundary}")


def send_image_url(token: str, to: str, url: str, caption: str = "") -> dict:
    return _json("POST", "/messages/image", token, {"to": to, "media": url, "caption": caption})


# ---------------------------------------------------------------- cupo del plan gratis


def _wa(state: dict | None) -> dict:
    return (state if isinstance(state, dict) else {}).setdefault("whatsapp", {})


def _day(now: datetime) -> str:
    return now.astimezone(MADRID).date().isoformat()


def used_this_month(state: dict | None, now: datetime) -> int:
    month = _day(now)[:7]
    return sum(int(n) for d, n in (_wa(state).get("requests") or {}).items() if d.startswith(month))


def note_requests(state: dict | None, now: datetime, count: int) -> None:
    wa = _wa(state)
    days = wa.setdefault("requests", {})
    days[_day(now)] = int(days.get(_day(now)) or 0) + count
    keep = sorted(days)[-62:]  # dos meses de sobra
    wa["requests"] = {d: days[d] for d in keep}


def days_left(now: datetime) -> int:
    local = now.astimezone(MADRID).date()
    following = (local.replace(day=28) + timedelta(days=4)).replace(day=1)
    return (following - local).days  # hoy incluido


def deal_quota_reason(state: dict | None, now: datetime, rules: dict, manual: bool = False) -> str:
    """Por qué este chollo NO va a WhatsApp ("" si va). Guarda siempre hueco para el resumen de cada noche."""
    wa = _wa(state)
    budget = int(rules.get("whatsapp_monthly_budget") or 950)
    reserve = 3 * days_left(now)  # imagen + texto del resumen (+ margen) de hoy y de lo que queda de mes
    if used_this_month(state, now) + 1 + reserve > budget:
        return "cupo del mes de Whapi agotado (se guarda para los resúmenes)"
    today = _day(now)
    posted_today = int((wa.get("deals") or {}).get(today) or 0)
    if posted_today >= int(rules.get("whatsapp_daily_max") or 25):
        return "ya van los chollos de hoy en WhatsApp"
    gap = float(rules.get("whatsapp_min_gap_minutes") or 35) * 60
    if not manual and now.timestamp() - float(wa.get("last_deal") or 0) < gap:
        return "el último salió hace poco"
    return ""


def note_deal(state: dict | None, now: datetime) -> None:
    wa = _wa(state)
    deals = wa.setdefault("deals", {})
    deals[_day(now)] = int(deals.get(_day(now)) or 0) + 1
    wa["deals"] = {d: deals[d] for d in sorted(deals)[-14:]}
    wa["last_deal"] = int(now.timestamp())


def merge(local: dict | None, remote: dict | None) -> dict:
    """Junta el cupo de dos ejecuciones que se solapan: por día, el mayor de los dos."""
    local, remote = local or {}, remote or {}
    out = {**remote, **local}
    for key in ("requests", "deals"):
        days = dict(remote.get(key) or {})
        for d, n in (local.get(key) or {}).items():
            days[d] = max(int(n), int(days.get(d) or 0))
        if days:
            out[key] = days
    out["last_deal"] = max(int(local.get("last_deal") or 0), int(remote.get("last_deal") or 0))
    return out


def target(token: str, state: dict | None, now: datetime, invite: str, test: bool, log=print) -> str:
    """A dónde va: tu número de pruebas en las pruebas (nunca el canal) o el canal, con su ID guardado."""
    if test:
        to = (os.environ.get("WHATSAPP_TEST_TO") or "").strip()
        if not to:
            raise WhapiError("prueba sin WHATSAPP_TEST_TO; no la mando (nunca va al canal)")
        return to
    fixed = (os.environ.get("WHATSAPP_CHANNEL_ID") or "").strip()
    if fixed:
        return fixed
    wa = _wa(state)
    if wa.get("invite") == invite and str(wa.get("channel") or "").endswith("@newsletter"):
        return wa["channel"]
    channel = resolve_channel(token, invite, log)
    note_requests(state, now, 1)
    wa.update(channel=channel, invite=invite)
    return channel


# ---------------------------------------------------------------- formato


TELEGRAM_LINE = re.compile(r"^Visto en @cazachollos_com\s*", re.M)


def html_to_whatsapp(text: str) -> str:
    """El copy de Telegram (HTML) con el formato de WhatsApp: negrita *x*, tachado ~x~, enlaces a la vista."""
    import html as _html

    def link(match: re.Match) -> str:
        url, label = _html.unescape(match.group(1)), _html.unescape(re.sub(r"<[^>]+>", "", match.group(2))).strip()
        bare = re.sub(r"^https?://(www\.)?", "", url)
        return url if not label or bare.startswith(re.sub(r"^https?://(www\.)?", "", label)) else f"{label} {url}"

    out = re.sub(r'<a\s+href="([^"]+)"[^>]*>(.*?)</a>', link, text, flags=re.S | re.I)
    for tag, mark in (("b", "*"), ("strong", "*"), ("s", "~"), ("del", "~"), ("strike", "~"), ("i", "_"), ("em", "_")):
        out = re.sub(rf"<{tag}>\s*(.*?)\s*</{tag}>", lambda m: f"{mark}{m.group(1)}{mark}" if m.group(1) else "",
                     out, flags=re.S | re.I)
    out = re.sub(r"<[^>]+>", "", out)
    out = _html.unescape(out)
    # En WhatsApp el @ del canal no lleva a ningún sitio: va el enlace a Telegram.
    out = TELEGRAM_LINE.sub(f"📲 Más chollos en Telegram 👉 {TELEGRAM}\n", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def publish_deal(caption_html: str, image, state: dict | None, now: datetime, rules: dict,
                 test: bool = False, manual: bool = False, log=print) -> bool:
    """Un chollo en el canal de WhatsApp: la foto (ruta o URL) con el mismo copy. Nunca lanza excepciones."""
    token = (os.environ.get("WHAPI_TOKEN") or "").strip()
    if not token:
        return False
    try:
        why = "" if test else deal_quota_reason(state, now, rules, manual)
        if why:
            log(f"  WhatsApp: este no va ({why})")
            return False
        to = target(token, state, now, str(rules.get("whatsapp_invite") or DEFAULT_INVITE), test, log)
        caption = html_to_whatsapp(caption_html)
        if test:
            caption = "🧪 *PRUEBA* · así saldría en el canal de WhatsApp\n\n" + caption
        note_requests(state, now, 1)
        if image and isinstance(image, Path) and image.is_file():
            send_image(token, to, image, caption)
        elif image and str(image).startswith("http"):
            send_image_url(token, to, str(image), caption)
        else:
            send_text(token, to, caption)
        if not test:
            note_deal(state, now)
        log(f"  WhatsApp: enviado {'a tu número de pruebas' if test else 'al canal'}")
        return True
    except Exception as exc:
        log(f"  WhatsApp: no he podido publicarlo ({exc}); Telegram ya ha salido")
        return False


def publish_text(text_html: str, state: dict | None, now: datetime, rules: dict, test: bool = False,
                 log=print) -> bool:
    """Un mensaje de texto (p. ej. una recopilación hecha a mano). Nunca lanza excepciones."""
    token = (os.environ.get("WHAPI_TOKEN") or "").strip()
    if not token:
        return False
    try:
        budget = int(rules.get("whatsapp_monthly_budget") or 950)
        if not test and used_this_month(state, now) + 1 > budget:
            log("  WhatsApp: cupo del mes de Whapi agotado; no lo mando")
            return False
        to = target(token, state, now, str(rules.get("whatsapp_invite") or DEFAULT_INVITE), test, log)
        note_requests(state, now, 1)
        send_text(token, to, html_to_whatsapp(text_html))
        log(f"  WhatsApp: enviado {'a tu número de pruebas' if test else 'al canal'}")
        return True
    except Exception as exc:
        log(f"  WhatsApp: no he podido publicarlo ({exc}); Telegram ya ha salido")
        return False


def publish_summary(items: list[dict], collage: Path | None, now: datetime, test: bool = False,
                    tag: str = DEFAULT_TAG, invite: str = DEFAULT_INVITE, log=print, state: dict | None = None,
                    budget: int = 950) -> bool:
    """Manda la imagen de cierre y el top del día al canal (o a WHATSAPP_TEST_TO en pruebas).

    Nunca lanza excepciones: devuelve True si ha salido y False si no (y lo apunta en el log)."""
    token = (os.environ.get("WHAPI_TOKEN") or "").strip()
    if not token:
        log("  WhatsApp: sin WHAPI_TOKEN, no publico (Telegram sale igual)")
        return False
    if not items:
        return False
    try:
        if not test and used_this_month(state, now) + 2 > budget:
            log("  WhatsApp: cupo del mes de Whapi agotado; hoy no sale el resumen")
            return False
        to = target(token, state, now, invite, test, log)
        if collage and Path(collage).exists():
            note_requests(state, now, 1)
            send_image(token, to, Path(collage), "🔥 Lo mejor de hoy en Amazon 👇")
        note_requests(state, now, 1)
        send_text(token, to, build_text(items, now, tag, test=test))
        log(f"  WhatsApp: resumen enviado {'a tu número de pruebas' if test else 'al canal'} "
            f"con {min(len(items), MAX_ITEMS)} chollos")
        return True
    except Exception as exc:
        log(f"  WhatsApp: no he podido publicar ({exc}); Telegram ya ha salido")
        return False


# ---------------------------------------------------------------- uso a mano


def _invite_from_config() -> str:
    try:
        cfg = json.loads((Path(__file__).with_name("config.json")).read_text("utf-8"))
        return str((cfg.get("amazon_channel") or {}).get("whatsapp_invite") or DEFAULT_INVITE)
    except Exception:
        return DEFAULT_INVITE


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--comprobar", action="store_true", help="conexión y canal, sin publicar")
    parser.add_argument("--prueba", action="store_true", help="resumen de ejemplo a WHATSAPP_TEST_TO")
    args = parser.parse_args()
    token = (os.environ.get("WHAPI_TOKEN") or "").strip()
    if not token:
        print("Falta el secreto WHAPI_TOKEN en GitHub (Settings → Secrets and variables → Actions).")
        return 1
    invite = _invite_from_config()
    try:
        info = channel_info(token, invite)
    except WhapiError as exc:
        print(f"No conecto con el canal: {exc}")
        print("Revisa que el número esté vinculado en Whapi (QR) y que el token sea el de esa instancia.")
        return 1
    try:
        role = own_role(token, str(info.get("id") or "")) or info.get("role") or "?"
    except WhapiError:
        role = info.get("role") or "?"
    print(f"Canal: {info.get('name')} · {info.get('id')} · seguidores: {info.get('subscribers_count', '?')}")
    print(f"El número vinculado es «{role}» del canal: "
          + ("puede publicar ✅" if role in ("owner", "admin") else "NO puede publicar ❌ (hazlo administrador)"))
    if args.prueba:
        sample = [
            {"asin": "B0EXAMPLE1", "title": "Robot aspirador de ejemplo", "price": 129.99, "reference": 299.99, "discount": 57},
            {"asin": "B0EXAMPLE2", "title": "Cafetera superautomática de ejemplo", "price": 249.0, "reference": 499.0, "discount": 50},
            {"asin": "B0EXAMPLE3", "title": "Auriculares de ejemplo", "price": 39.9, "reference": 79.9, "discount": 50},
        ]
        ok = publish_summary(sample, None, datetime.now(MADRID), test=True, invite=invite)
        return 0 if ok else 1
    return 0 if role in ("owner", "admin") else 1


if __name__ == "__main__":
    raise SystemExit(main())
