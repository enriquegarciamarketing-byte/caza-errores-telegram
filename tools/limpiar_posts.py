#!/usr/bin/env python3
"""Limpia posts ya publicados en el canal free (uso puntual, lo lanza el workflow «Limpiar posts del canal»).

Para cada mensaje indicado:
- Quita «Precio más bajo de su historia» y #MinimoHistorico del texto.
- Si el post salió con la tarjeta de la marca y la foto del producto aparte (dos mensajes), pone la foto
  del producto en el post (con su texto y su botón) y borra el mensaje suelto de la foto, para que quede
  como los posts nuevos: una sola foto del producto, grande, con el texto y el botón.

Uso: python tools/limpiar_posts.py 348 350 352 … [--dry-run]
"""

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import canal_nube as cn  # noqa: E402
import scanner  # noqa: E402


def biggest_photo(message: dict) -> str | None:
    sizes = message.get("photo") or []
    return max(sizes, key=lambda s: s.get("width", 0) * s.get("height", 0))["file_id"] if sizes else None


def formato_corto(caption: str, post: dict, rules: dict) -> str:
    """Pasa un post con el texto largo de antes (frente a su PVP, mínimo de 30 días, enlace en el texto) al
    formato corto de ahora, conservando su cabecera, la hora del precio y su hashtag."""
    if "frente a su" not in caption and "Ver en Amazon" not in caption:
        return caption
    lines = caption.split("\n")
    header = lines[0]
    hour = (re.search(r"Precio a las (\d{1,2}:\d{2})", caption) or [None, ""])[1]
    tag = next((t for t in re.findall(r"#\w+", lines[-1]) if t != cn.PUBLI), "#Chollo")
    price, reference = float(post["price"]), float(post["reference"])
    pct = cn.discount_pct(price, reference)
    e = html.escape
    out = [header, "", f"<b>{e(cn.clean_title(post.get('title') or '', 90))}</b>", "",
           f"💶 PRECIO: <b>{e(cn.price_tag(price))}</b>"]
    if reference > price:
        out.append(f"❌ (Antes: <s>{e(cn.price_tag(reference))}</s>)")
        out.append(f"🔥 ¡Te ahorras <b>{e(cn.price_tag(reference - price))}</b>! ({round(pct)} % dto.)")
    if hour:
        out += ["", f"🕒 {cn.PRICE_NOTE.format(hour=hour)}"]
    out += ["", f"Visto en {rules.get('chat_id') or '@cazachollos_com'} {cn.PUBLI} {tag}"]
    return "\n".join(out)


def con_enlace(caption: str, url: str, ended: bool) -> str:
    """Añade la línea «🛒 amazon.es/dp/…» (enlazada) antes de «Visto en…», si el post sigue activo."""
    if ended:
        return caption
    lines = caption.split("\n")
    if any(line.startswith("🛒 ") for line in lines):  # ya la lleva: se deja como la pone el bot ahora
        return "\n".join(cn.buy_line(url) if line.startswith("🛒 ") else line for line in lines)
    at = next((i for i, line in enumerate(lines) if line.startswith("Visto en")), len(lines))
    return "\n".join(lines[:at] + [cn.buy_line(url), ""] + lines[at:])


def limpiar(tg, state: dict, rules: dict, ids: set[int], dry: bool, log=print) -> int:
    chat = rules["chat_id"]
    admin = cn.admin_chat_id(state, rules, tg, log) if tg else None
    fallos = 0
    for post in state.get("posts") or []:
        if post.get("chat") != chat or post.get("message_id") not in ids:
            continue
        mid, photo_mid = int(post["message_id"]), post.get("photo_message_id")
        caption = formato_corto(cn.sin_historial(post.get("caption") or ""), post, rules)
        caption = con_enlace(caption, post["url"], bool(post.get("ended")))[:1024]
        markup = None if post.get("ended") else cn.buttons(post["url"], rules.get("button_style", "success"))
        log(f"Post {mid}{f' (foto suelta {photo_mid})' if photo_mid else ''}: {cn.clean_title(post.get('title') or '', 60)}")
        if dry or tg is None:
            log("  [prueba] texto nuevo:\n" + caption)
            continue
        try:
            if photo_mid:
                if not admin:
                    raise RuntimeError("no encuentro tu chat privado con el bot para sacar la foto")
                copia = tg.call("forwardMessage", {"chat_id": admin, "from_chat_id": chat, "message_id": int(photo_mid),
                                                   "disable_notification": True})
                file_id = biggest_photo(copia)
                if not file_id:
                    raise RuntimeError(f"el mensaje {photo_mid} no tiene foto")
                params = {"chat_id": chat, "message_id": mid,
                          "media": {"type": "photo", "media": file_id, "caption": caption, "parse_mode": "HTML"}}
                if markup:
                    params["reply_markup"] = markup
                tg.call("editMessageMedia", params)
                tg.call("deleteMessage", {"chat_id": chat, "message_id": int(photo_mid)})
                try:
                    tg.call("deleteMessage", {"chat_id": admin, "message_id": copia["message_id"]})
                except RuntimeError:
                    pass
                post["photo_message_id"] = None
                log("  ✓ foto del producto puesta, foto suelta borrada")
            elif caption != (post.get("caption") or ""):
                params = {"chat_id": chat, "message_id": mid, "caption": caption, "parse_mode": "HTML"}
                if markup:
                    params["reply_markup"] = markup
                tg.call("editMessageCaption", params)
                log("  ✓ texto editado")
            else:
                log("  sin cambios")
            post["caption"] = caption
        except RuntimeError as exc:
            if "message is not modified" in str(exc):
                post["caption"] = caption
                log("  ya estaba bien")
                continue
            fallos += 1
            log(f"  ✗ {exc}")
    return 1 if fallos else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("ids", nargs="+", help="Números de mensaje del canal (los del post con texto)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    ids = {int(x) for part in args.ids for x in part.replace(",", " ").split() if x.strip()}
    cfg = cn.load_json(cn.CONFIG_PATH, {}) if hasattr(cn, "CONFIG_PATH") else json.loads(Path("config.json").read_text())
    rules = cn.rules_from(cfg)
    state = cn.load_json(cn.STATE_PATH, {})
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    tg = scanner.Telegram(token) if token and not args.dry_run else None
    code = limpiar(tg, state, rules, ids, args.dry_run)
    if not args.dry_run:
        cn.save_state(state)
    return code


if __name__ == "__main__":
    sys.exit(main())
