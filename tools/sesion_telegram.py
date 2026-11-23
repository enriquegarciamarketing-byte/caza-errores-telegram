"""Saca la sesión de Telegram que usa el vigía para leer los canales sin vista web (ropa y básicos de @kevincrestt).

Se ejecuta UNA sola vez en tu Mac, en la Terminal:

    pip3 install telethon
    python3 tools/sesion_telegram.py

1. Te pide el api_id y el api_hash (los sacas en https://my.telegram.org → API development tools).
2. Te pide el teléfono de la cuenta (mejor la secundaria, Darkness), el código que te llega a Telegram y,
   si la tienes, la contraseña de verificación en dos pasos. Todo lo escribes tú aquí, no sale de tu Mac.
3. Al final imprime una línea larga: esa es la sesión. Va en GitHub como secreto TG_SESSION
   (repo → Settings → Secrets and variables → Actions), junto con TG_API_ID y TG_API_HASH.

La sesión da acceso a esa cuenta de Telegram: no la pegues en ningún chat ni la subas al repo.
El vigía solo la usa para leer los mensajes de los canales, nunca escribe con ella.
"""
from telethon.sessions import StringSession
from telethon.sync import TelegramClient


def main() -> None:
    api_id = int(input("api_id: ").strip())
    api_hash = input("api_hash: ").strip()
    with TelegramClient(StringSession(), api_id, api_hash) as client:  # pide teléfono, código y 2FA
        me = client.get_me()
        print(f"\nConectado como {me.first_name} (@{me.username}).")
        print("\nCopia esta línea entera en el secreto TG_SESSION de GitHub:\n")
        print(client.session.save())


if __name__ == "__main__":
    main()
