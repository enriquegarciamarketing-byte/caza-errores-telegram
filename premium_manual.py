"""Post manual del premium @caza_errores: Enrique pasa el error, Claude prepara datos y copy, y el bot publica.

Lo lanza el workflow «Post manual premium @caza_errores» con un JSON:

  {"link": "https://link.amazon/…", "asin": "B0…", "image": "https://m.media-amazon.com/images/I/….jpg",
   "reference": 84.99, "current": 35.50, "when": "17/11 · 13:24", "copy": "💎 #Chollo · -58 %\n\n…"}

- reference / current: precio recomendado y precio actual de la ficha de Amazon (solo datos de Amazon).
- when: fecha y hora a la que se leyó el precio (sale en la tarjeta).
- copy: el texto del post tal cual; en la línea 💸 el último precio sale tachado.

Con --privado va solo a tu chat (ADMIN_CHAT_ID); sin él, al canal (TELEGRAM_CHAT_ID).
Para marcar uno como agotado: {"agotado": <número de mensaje>} → tarjeta en blanco y negro con el sello AGOTADO.
Para corregir uno ya publicado: {"editar": <número de mensaje>, "reference": …, "current": …, "when": …, "copy": …,
  "ref_label": "nuevo"} → rehace tarjeta y texto del mismo mensaje (lo que no venga se queda como estaba).
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import uuid
import urllib.request
from pathlib import Path

import privado
from scanner import Telegram, product_photo
from tarjeta_premium import crear_tarjeta

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state" / "premium_manual.json"
OUT = ROOT / "output" / "premium_manual"
TAG = "cazachollos0c-21"
PRICE = r"\d{1,3}(?:\.\d{3})*,\d{2}€"
JOIN = re.compile(r"(\d) +(€|%)")  # Enrique: el € y el % siempre pegados al número


def caption_html(copy: str, links: dict[str, str] | None = None) -> str:
    """El copy de Enrique en HTML de Telegram: título en negrita y el precio de antes tachado en la línea 💸.
    Con `links`, cada enlace se ve tal cual lo escribió y al pinchar lleva al enlace limpio con su tag."""
    lines = []
    texts = [i for i, line in enumerate(copy.strip().splitlines()) if line.strip()]
    title = texts[1] if len(texts) > 1 else -1  # la línea tras la cabecera (💎/❗️) es el título: en negrita
    for i, line in enumerate(copy.strip().splitlines()):
        line = JOIN.sub(r"\1\2", line)
        safe = html.escape(line, quote=False)
        if i == title:
            safe = f"<b>{safe.strip()}</b>"
        if line.lstrip().startswith("💸"):
            prices = list(re.finditer(PRICE, safe))
            if len(prices) >= 2:
                last = prices[-1]
                safe = f"{safe[:last.start()]}<s>{last.group(0)}</s>{safe[last.end():]}"
        for shown, target in (links or {}).items():
            seen = html.escape(shown, quote=False)
            if seen in safe and shown != target:
                safe = safe.replace(seen, f'<a href="{html.escape(target)}">{seen}</a>')
        lines.append(safe)
    return "\n".join(lines)


URL_IN_TEXT = re.compile(r"https?://[^\s<>\"']+")


def clean_link(link: str, asin: str | None = None, resolve=None) -> str:
    """Cualquier enlace de Amazon (corto o largo) → https://www.amazon.es/dp/ASIN?tag=TAG, sin subtags de nadie
    (18/11/2026: el corto de SiteStripe arrastraba el ascsubtag=ppr-es-… de Pepper). Si no es de Amazon, igual."""
    import affiliate
    link = (link or "").strip()
    if not (affiliate.is_short_link(link) or "amazon." in urllib.parse.urlparse(link).netloc.lower()):
        return link
    final = link
    if affiliate.is_short_link(link):
        try:
            final = (resolve or affiliate.resolve_redirects)(link)
        except (urllib.error.URLError, TimeoutError, ValueError):
            final = ""
    got = affiliate.extract_asin(final) or ""
    wanted = (asin or "").strip().upper()
    if wanted and got and got != wanted:
        raise ValueError(f"el enlace lleva al producto {got} y no a {wanted}")
    asin = got or wanted
    if not asin:
        raise ValueError(f"no saco el ASIN del enlace {link}")
    return f"https://www.amazon.es/dp/{asin}?tag={TAG}"


def clean_copy(copy: str, asin: str | None = None, resolve=None) -> str:
    """Los enlaces de Amazon que vayan dentro del copy salen limpios, solo con tu tag."""
    return URL_IN_TEXT.sub(lambda m: clean_link(m.group(0), asin, resolve), copy)


def copy_links(copy: str, asin: str | None = None, resolve=None) -> dict[str, str]:
    """Enlace visible del copy → enlace limpio al que lleva el clic (18/11/2026: Enrique quiere ver el corto
    link.amazon en el post, pero que al pinchar vaya a amazon.es/dp/ASIN?tag=TAG sin subtags)."""
    return {url: clean_link(url, asin, resolve) for url in dict.fromkeys(URL_IN_TEXT.findall(copy))}


def check_link(link: str) -> str | None:
    host = urllib.parse.urlparse(link).netloc.lower()
    if not host:
        return "enlace no válido"
    if host.endswith("link.amazon") or host in ("amzn.to", "amzn.eu"):
        return None  # enlace corto de Enrique: Claude comprueba el tag al abrirlo antes de lanzar esto
    if "amazon." in host and f"tag={TAG}" not in link:
        return f"el enlace de Amazon no lleva tu etiqueta {TAG}"
    return None


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"posts": []}


def save_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def edit_media(token: str, chat, message_id: int, card: Path, caption: str) -> None:
    boundary = "----premium" + uuid.uuid4().hex
    media = {"type": "photo", "media": "attach://photo", "caption": caption, "parse_mode": "HTML"}
    fields = {"chat_id": str(chat), "message_id": str(message_id), "media": json.dumps(media, ensure_ascii=False)}
    parts = [f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8")
             for k, v in fields.items()]
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"card.jpg\"\r\n"
                 "Content-Type: image/jpeg\r\n\r\n".encode("utf-8") + card.read_bytes() + b"\r\n")
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


def photo_for(spec: dict, name: str) -> Path:
    src = OUT / f"{name}_foto.jpg"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(product_photo(spec["image"]))
    return src


def publish(spec: dict, private: bool, token: str) -> int:
    for key in ("link", "image", "current", "when", "copy"):
        if not spec.get(key):
            print(f"Falta «{key}» en los datos.", file=sys.stderr)
            return 2
    try:
        spec = dict(spec, link=clean_link(spec["link"], spec.get("asin")))
        spec["asin"] = spec.get("asin") or (re.search(r"/dp/([A-Z0-9]{10})", spec["link"]) or [None, None])[1]
        links = copy_links(spec["copy"], spec.get("asin"))  # el copy no cambia: se ve el corto, se pincha el limpio
    except ValueError as exc:
        print(f"No publico: {exc}.", file=sys.stderr)
        return 2
    problem = check_link(spec["link"])
    if problem:
        print(f"No publico: {problem}.", file=sys.stderr)
        return 2
    # Sin «reference» (la ficha no da precio de referencia): tarjeta sin tachado ni %, solo el precio de hoy.
    reference = float(spec["reference"]) if spec.get("reference") else None
    current = float(spec["current"])
    if not (0 < current and (reference is None or current < reference)):
        print("No publico: el precio actual tiene que ser menor que el recomendado.", file=sys.stderr)
        return 2
    chat = privado.admin_id() if private else os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not chat:
        print("Falta ADMIN_CHAT_ID" if private else "Falta TELEGRAM_CHAT_ID (canal premium)", file=sys.stderr)
        return 2
    name = re.sub(r"[^A-Za-z0-9]", "", spec.get("asin") or "") or f"p{int(time.time())}"
    card = crear_tarjeta(photo_for(spec, name), reference, current, spec["when"], OUT / f"{name}.jpg",
                        ref_label=spec.get("ref_label", "recomendado"))
    caption = caption_html(spec["copy"], links)
    msg = Telegram(token).send_photo(chat, card, caption)
    where = "tu chat privado (prueba)" if private else "el canal premium"
    pct = f" · -{round((reference - current) / reference * 100)}%" if reference else " · sin precio de referencia"
    print(f"Post manual premium enviado a {where} (mensaje {msg['message_id']}){pct}")
    if not private:
        state = load_state()
        state["posts"].append({"message_id": msg["message_id"], "asin": spec.get("asin"), "link": spec["link"],
                               "image": spec["image"], "reference": reference, "current": current,
                               "when": spec["when"], "ref_label": spec.get("ref_label", "recomendado"),
                               "caption": caption, "t": int(time.time())})
        save_state(state)
    return 0


def sold_out(message_id: int, token: str) -> int:
    state = load_state()
    post = next((p for p in state["posts"] if p.get("message_id") == message_id), None)
    if not post:
        print(f"No tengo guardado el mensaje {message_id} del premium.", file=sys.stderr)
        return 2
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    name = re.sub(r"[^A-Za-z0-9]", "", post.get("asin") or "") or str(message_id)
    card = crear_tarjeta(photo_for(post, name), post.get("reference"), post["current"], post["when"],
                         OUT / f"{name}_agotado.jpg", agotado=True,
                         ref_label=post.get("ref_label", "recomendado"))
    edit_media(token, chat, message_id, card, post["caption"])
    post["agotado"] = int(time.time())
    save_state(state)
    print(f"Mensaje {message_id} del premium marcado como AGOTADO")
    return 0


def editar(spec: dict, token: str) -> int:
    """Corrige un post ya publicado (tarjeta y texto) sin borrarlo (22/11/2026: el Lefant de segunda mano salió
    con el precio nuevo)."""
    message_id = int(spec["editar"])
    state = load_state()
    post = next((p for p in state["posts"] if p.get("message_id") == message_id), None)
    if not post:
        print(f"No tengo guardado el mensaje {message_id} del premium.", file=sys.stderr)
        return 2
    for key in ("reference", "current", "when", "image", "ref_label"):
        if key in spec:
            post[key] = spec[key]
    reference = float(post["reference"]) if post.get("reference") else None
    current = float(post["current"])
    if not (0 < current and (reference is None or current < reference)):
        print("No edito: el precio actual tiene que ser menor que el de referencia.", file=sys.stderr)
        return 2
    if spec.get("copy"):
        links = copy_links(spec["copy"], post.get("asin"))
        m = re.search(r"amazon\.es/dp/[A-Z0-9]{10}", spec["copy"])
        if m and m.group(0) not in links:
            links[m.group(0)] = post["link"]
        post["caption"] = caption_html(spec["copy"], links)
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    name = re.sub(r"[^A-Za-z0-9]", "", post.get("asin") or "") or str(message_id)
    card = crear_tarjeta(photo_for(post, name), reference, current, post["when"], OUT / f"{name}_editado.jpg",
                         ref_label=post.get("ref_label", "recomendado"))
    edit_media(token, chat, message_id, card, post["caption"])
    post["editado"] = int(time.time())
    save_state(state)
    pct = f" · -{round((reference - current) / reference * 100)}%" if reference else ""
    print(f"Mensaje {message_id} del premium corregido{pct}")
    return 0


def consultar(asin: str) -> int:
    """Solo lee la ficha en la API oficial (precio, precio de referencia de Amazon y stock); no publica nada."""
    from amazon_api import CreatorsAPI
    api = CreatorsAPI.from_env(TAG)
    if api is None:
        print("Faltan las credenciales de la Creators API", file=sys.stderr)
        return 2
    print("API Amazon:", json.dumps(api.get_item(asin.strip().upper()), ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("datos", help="JSON del post (ver la cabecera del fichero)")
    parser.add_argument("--privado", action="store_true", help="Solo a tu chat privado, nunca al canal")
    args = parser.parse_args()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Falta TELEGRAM_BOT_TOKEN", file=sys.stderr)
        return 2
    spec = json.loads(args.datos)
    if spec.get("consultar"):
        return consultar(str(spec["consultar"]))
    if spec.get("agotado"):
        return sold_out(int(spec["agotado"]), token)
    if spec.get("editar"):
        return editar(spec, token)
    return publish(spec, args.privado, token)


if __name__ == "__main__":
    sys.exit(main())
