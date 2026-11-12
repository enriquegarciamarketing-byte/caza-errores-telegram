"""Cambia el enlace 🛒 del texto de posts ya publicados en el canal free por el enlace con tu etiqueta.

Uso: python tools/editar_enlace.py 552,553   (números de mensaje del canal)

Para los posts manuales que salieron con un enlace corto sin afiliado (link.amazon, amzn.eu… compartidos desde
la app de Amazon): la línea 🛒 pasa a amazon.es/dp/ASIN con tu tag por dentro, como en los posts automáticos.
El resto del post (fotos del carrusel, texto y botón de comprar) se queda igual.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import canal_nube  # noqa: E402
import scanner  # noqa: E402

CHANNEL = "@cazachollos_com"


def fixed_caption(caption: str, url: str) -> str:
    lines = caption.split("\n")
    return "\n".join(canal_nube.buy_line(url) if line.startswith("🛒") else line for line in lines)


def main() -> int:
    ids = sorted({int(x) for x in sys.argv[1].replace(" ", "").split(",") if x})
    cfg = canal_nube.load_json(canal_nube.CONFIG_PATH, {})
    rules = canal_nube.rules_from(cfg)
    tag = rules.get("tag") or ""
    if not tag:
        print("Falta affiliate_tag en config.json: no toco nada.")
        return 2
    tg = scanner.Telegram(os.environ["TELEGRAM_BOT_TOKEN"])
    state = canal_nube.load_json(canal_nube.STATE_PATH, {"posts": []})
    fallos = 0
    for mid in ids:
        post = next((p for p in state.get("posts") or [] if int(p.get("message_id") or 0) == mid), None)
        if not post or not post.get("caption") or not post.get("asin"):
            print(f"Mensaje {mid}: no está en la memoria del canal, no lo toco.")
            fallos += 1
            continue
        url = f"https://www.amazon.es/dp/{post['asin']}?tag={tag}"
        caption = fixed_caption(post["caption"], url)
        if caption == post["caption"]:
            print(f"Mensaje {mid}: el enlace ya lleva tu etiqueta.")
            continue
        markup = canal_nube.buttons(url, rules.get("button_style", "success"))
        try:
            if post.get("slides"):
                keys = [f"s{n}" for n in range(len(post["slides"]))]
                slides = "".join(f'<img src="tg://photo?id={k}"/>' for k in keys)
                tg.call("editMessageText", {"chat_id": post.get("chat") or CHANNEL, "message_id": mid,
                                            "rich_message": {
                                                "html": f"<tg-slideshow>{slides}</tg-slideshow>"
                                                        + canal_nube.caption_to_rich_html(caption),
                                                "media": [{"id": k, "media": {"type": "photo", "media": f}}
                                                          for k, f in zip(keys, post["slides"])]},
                                            "reply_markup": markup})
            else:
                tg.call("editMessageCaption", {"chat_id": post.get("chat") or CHANNEL, "message_id": mid,
                                               "caption": caption[:1024], "parse_mode": "HTML",
                                               "reply_markup": markup})
        except RuntimeError as exc:
            print(f"Mensaje {mid}: no he podido editarlo ({exc}).")
            fallos += 1
            continue
        post["caption"], post["url"] = caption, url
        print(f"Mensaje {mid} editado: 🛒 → amazon.es/dp/{post['asin']} con tu etiqueta ({tag}).")
    canal_nube.save_state(state)
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
