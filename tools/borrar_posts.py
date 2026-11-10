"""Borra posts concretos del canal free (@cazachollos_com) y los quita de la memoria del canal.

Uso: python tools/borrar_posts.py 460,461,462   (números de mensaje del canal)
Solo toca el canal free y solo los números que se le pasan.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import scanner  # noqa: E402

CHANNEL = "@cazachollos_com"
STATE = Path(__file__).resolve().parent.parent / "state" / "canal_nube.json"


def main() -> int:
    ids = sorted({int(x) for x in sys.argv[1].replace(" ", "").split(",") if x})
    tg = scanner.Telegram(os.environ["TELEGRAM_BOT_TOKEN"])
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    posts = state.get("posts") or []
    borrados = 0
    for mid in ids:
        extra = [int(p["photo_message_id"]) for p in posts
                 if int(p.get("message_id") or 0) == mid and p.get("photo_message_id")]
        for target in [mid] + extra:
            try:
                tg.call("deleteMessage", {"chat_id": CHANNEL, "message_id": target})
                print(f"Borrado el mensaje {target} de {CHANNEL}")
                borrados += 1
            except RuntimeError as exc:
                print(f"No he podido borrar el mensaje {target}: {exc}")
    state["posts"] = [p for p in posts if int(p.get("message_id") or 0) not in ids]
    if STATE.exists():
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Listo: {borrados} mensajes borrados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
