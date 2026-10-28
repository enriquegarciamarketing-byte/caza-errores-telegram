#!/usr/bin/env python3
"""Aplica la descripción del canal y el mensaje fijado definidos en channel_info.json.

Si el fijado lo publicó una persona y el bot no puede editarlo, publica uno nuevo y lo fija."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from scanner import Telegram

ROOT = Path(__file__).resolve().parent


def main() -> int:
    info = json.loads((ROOT / "channel_info.json").read_text(encoding="utf-8"))
    tg = Telegram(os.environ["TELEGRAM_BOT_TOKEN"].strip())
    channel = os.environ["TELEGRAM_CHAT_ID"].strip()
    status = 0

    try:
        tg.call("setChatDescription", {"chat_id": channel, "description": info["description"]})
        print("Descripción actualizada")
    except RuntimeError as exc:
        if "not modified" in str(exc):
            print("La descripción ya estaba al día")
        else:
            print(f"No se pudo cambiar la descripción: {exc}", file=sys.stderr)
            status = 1

    params = {"chat_id": channel, "text": info["pinned_html"], "parse_mode": "HTML",
              "link_preview_options": {"is_disabled": True}}
    try:
        tg.call("editMessageText", {**params, "message_id": info["pinned_message_id"]})
        print(f"Mensaje fijado {info['pinned_message_id']} editado")
    except RuntimeError as exc:
        if "not modified" in str(exc):
            print("El fijado ya estaba al día")
        else:
            print(f"No se pudo editar el fijado ({exc}); publico uno nuevo")
            msg = tg.call("sendMessage", {**params, "disable_notification": True})
            tg.call("pinChatMessage", {"chat_id": channel, "message_id": msg["message_id"],
                                       "disable_notification": True})
            print(f"Nuevo fijado publicado y fijado: mensaje {msg['message_id']}")
            info["pinned_message_id"] = msg["message_id"]
            (ROOT / "channel_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=1) + "\n",
                                                    encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
