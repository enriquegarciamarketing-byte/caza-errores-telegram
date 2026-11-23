"""Saca la sesión de Telegram del vigía con un QR, sin Terminal (workflow «Sesión Telegram (QR)»).

1. Te manda al privado del bot un QR que cambia cada ~30 s (borra el anterior).
2. Lo escaneas desde el móvil con la cuenta que va a leer los canales:
   Telegram → Ajustes → Dispositivos → Vincular dispositivo de escritorio.
3. Si la cuenta tiene verificación en dos pasos, usa el secreto TG_2FA (si no está, te avisa y para).
4. Te manda la sesión al privado del bot: la pegas en el secreto TG_SESSION y borras el mensaje.

Necesita los secretos TG_API_ID, TG_API_HASH, TELEGRAM_BOT_TOKEN y ADMIN_CHAT_ID.
"""
from __future__ import annotations

import asyncio
import html
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MINUTOS = 6


def main() -> int:
    import privado
    from scanner import Telegram

    api_id = os.environ.get("TG_API_ID", "").strip()
    api_hash = os.environ.get("TG_API_HASH", "").strip()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = privado.admin_id()
    if not (api_id and api_hash and token and chat):
        print("Faltan TG_API_ID, TG_API_HASH, TELEGRAM_BOT_TOKEN o ADMIN_CHAT_ID", file=sys.stderr)
        return 2
    tg = Telegram(token)
    return asyncio.run(login(int(api_id), api_hash, tg, chat))


async def rematar(client, qr) -> bool:
    """Tras un timeout: si el QR ya se escaneó, completa el login (también si la cuenta vive en otro DC);
    si no, deja preparado un QR nuevo."""
    from telethon.tl import functions, types
    resp = await client(qr._request)
    if isinstance(resp, types.auth.LoginTokenMigrateTo):
        await client._switch_dc(resp.dc_id)
        resp = await client(functions.auth.ImportLoginTokenRequest(resp.token))
    if isinstance(resp, types.auth.LoginTokenSuccess):
        await client._on_login(resp.authorization.user)
        return True
    qr._resp = resp  # QR nuevo
    return False


async def login(api_id: int, api_hash: str, tg, chat: int) -> int:
    import qrcode
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
    from telethon.sessions import StringSession

    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.connect()
    qr = await client.qr_login()
    fin = time.time() + MINUTOS * 60
    anterior = None
    ok = False
    while time.time() < fin:
        img = Path("/tmp/qr_vigia.jpg")
        qrcode.make(qr.url).convert("RGB").save(img, "JPEG", quality=95)
        if anterior:
            try:
                tg.call("deleteMessage", {"chat_id": chat, "message_id": anterior})
            except RuntimeError:
                pass
        msg = tg.send_photo(chat, img, "🔑 <b>Vigía de canales</b>\nEscanéalo desde el móvil con la cuenta que va a leer "
                                        "los canales: Ajustes → Dispositivos → Vincular dispositivo de escritorio.\n"
                                        "Caduca en unos 30 s; si caduca te llega otro.")
        anterior = msg["message_id"]
        espera = max(5.0, (qr.expires - datetime.now(timezone.utc)).total_seconds() + 3)
        try:
            await qr.wait(timeout=espera)
            ok = True
            break
        except SessionPasswordNeededError:
            password = os.environ.get("TG_2FA", "").strip()
            if not password:
                tg.call("sendMessage", {"chat_id": chat, "text": "⚠️ Esa cuenta tiene verificación en dos pasos. "
                                        "Crea el secreto TG_2FA con esa contraseña y vuelve a lanzar el workflow."})
                return 1
            await client.sign_in(password=password)
            ok = True
            break
        except (asyncio.TimeoutError, TimeoutError):
            # A veces el aviso del escaneo no llega: se pregunta a Telegram si el QR ya se aceptó.
            if await rematar(client, qr):
                ok = True
                break
    if anterior:
        try:
            tg.call("deleteMessage", {"chat_id": chat, "message_id": anterior})
        except RuntimeError:
            pass
    if not ok:
        tg.call("sendMessage", {"chat_id": chat, "text": "⌛ No se escaneó el QR a tiempo. Vuelve a lanzar el workflow."})
        return 1
    me = await client.get_me()
    session = client.session.save()
    await client.disconnect()  # sin log_out: la sesión tiene que seguir viva para el vigía
    tg.call("sendMessage", {"chat_id": chat, "parse_mode": "HTML", "text": (
        f"✅ Sesión lista para {html.escape(me.first_name or '')} (@{html.escape(me.username or '-')}).\n\n"
        "Pégala entera en el secreto <b>TG_SESSION</b> de GitHub y luego <b>borra este mensaje</b>:\n\n"
        f"<code>{session}</code>")})
    print(f"Sesión creada para la cuenta @{me.username or me.id} y enviada a tu privado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
