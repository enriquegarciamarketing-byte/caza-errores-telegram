#!/usr/bin/env python3
"""Aplica las bios y los mensajes fijados de los canales definidos en channel_info.json (25/11/2026).

Telegram (Caza Chollos y Caza Errores): cambia la descripción y, si ya hay pinned_message_id, edita ese fijado;
si no (o si el bot no puede editarlo), publica uno nuevo en silencio y lo fija. unpin_old quita fijados viejos.
WhatsApp: manda la bienvenida una sola vez (welcome_sent) e intenta cambiar la descripción del canal vía Whapi."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

from scanner import Telegram

ROOT = Path(__file__).resolve().parent
FILE = ROOT / "channel_info.json"


def save(info: dict) -> None:
    FILE.write_text(json.dumps(info, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def telegram_channel(tg: Telegram, ch: dict) -> int:
    status, chat, name = 0, ch["chat_id"], ch.get("name") or ch["chat_id"]
    try:
        tg.call("setChatDescription", {"chat_id": chat, "description": ch["description"]})
        print(f"{name}: descripción actualizada")
    except RuntimeError as exc:
        if "not modified" in str(exc):
            print(f"{name}: la descripción ya estaba al día")
        else:
            print(f"{name}: no se pudo cambiar la descripción: {exc}", file=sys.stderr)
            status = 1

    params = {"chat_id": chat, "text": ch["pinned_html"], "parse_mode": "HTML",
              "link_preview_options": {"is_disabled": True}}
    if ch.get("pinned_message_id"):
        try:
            tg.call("editMessageText", {**params, "message_id": ch["pinned_message_id"]})
            print(f"{name}: fijado {ch['pinned_message_id']} editado")
            return status
        except RuntimeError as exc:
            if "not modified" in str(exc):
                print(f"{name}: el fijado ya estaba al día")
                return status
            print(f"{name}: no se pudo editar el fijado ({exc}); publico uno nuevo")
    try:
        msg = tg.call("sendMessage", {**params, "disable_notification": True})
    except RuntimeError as exc:
        print(f"{name}: no se pudo publicar el fijado: {exc}", file=sys.stderr)
        return 1
    ch["pinned_message_id"] = msg["message_id"]
    try:
        tg.call("pinChatMessage", {"chat_id": chat, "message_id": msg["message_id"], "disable_notification": True})
        print(f"{name}: nuevo fijado publicado y fijado (mensaje {msg['message_id']})")
    except RuntimeError as exc:
        print(f"{name}: publicado como mensaje {msg['message_id']}, pero no se pudo fijar ({exc})", file=sys.stderr)
        status = 1
    for old in ch.pop("unpin_old", None) or []:
        try:
            tg.call("unpinChatMessage", {"chat_id": chat, "message_id": old})
            print(f"{name}: desfijado el mensaje viejo {old}")
        except RuntimeError as exc:
            print(f"{name}: el mensaje viejo {old} no se pudo desfijar ({exc})")
    return status


def whatsapp_channel(wa_info: dict) -> int:
    token = (os.environ.get("WHAPI_TOKEN") or "").strip()
    if not token:
        print("WhatsApp: sin WHAPI_TOKEN, no hago nada")
        return 0
    import whatsapp as wa
    status = 0
    try:
        channel = wa.target(token, None, datetime.now(), wa.DEFAULT_INVITE, False)
    except Exception as exc:  # noqa: BLE001
        print(f"WhatsApp: no encuentro el canal ({exc})", file=sys.stderr)
        return 1
    if not wa_info.get("welcome_sent"):
        try:
            wa.send_text(token, channel, wa_info["welcome"])
            wa_info["welcome_sent"] = True
            print("WhatsApp: bienvenida publicada en el canal")
        except Exception as exc:  # noqa: BLE001
            print(f"WhatsApp: no se pudo publicar la bienvenida ({exc})", file=sys.stderr)
            status = 1
    if not wa_info.get("description_done") and wa_info.get("description"):
        try:
            wa._json("PATCH", f"/newsletters/{channel}", token, {"description": wa_info["description"]})
            wa_info["description_done"] = True
            print("WhatsApp: descripción del canal actualizada")
        except Exception as exc:  # noqa: BLE001
            print(f"WhatsApp: Whapi no deja cambiar la descripción ({exc}); hay que ponerla a mano")
    return status


def main() -> int:
    info = json.loads(FILE.read_text(encoding="utf-8"))
    tg = Telegram(os.environ["TELEGRAM_BOT_TOKEN"].strip())
    status = 0
    for ch in info.get("telegram") or []:
        status |= telegram_channel(tg, ch)
        save(info)
    if info.get("whatsapp"):
        status |= whatsapp_channel(info["whatsapp"])
        save(info)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
