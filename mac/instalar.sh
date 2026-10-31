#!/bin/bash
# Instala el bot de @cazachollos_com en este Mac y hace una prueba privada.
# No publica nada en el canal: eso solo empieza cuando ejecutes mac/activar.sh.
set -euo pipefail
DIR="$HOME/CazaChollos"
REPO="https://github.com/enriquegarciamarketing-byte/caza-errores-telegram.git"

echo "== Caza Chollos: instalación en $DIR =="
if ! command -v python3 >/dev/null 2>&1; then
  echo "Falta Python 3. Ejecuta: xcode-select --install  y vuelve a lanzar este instalador."; exit 1
fi
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  git clone --depth 20 "$REPO" "$DIR"
fi
cd "$DIR"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q "Pillow>=10.0,<12"

if [ ! -s .env ] || ! grep -q '^TELEGRAM_BOT_TOKEN=.\+' .env; then
  echo
  echo "Pega el token del bot @cazaerroresAmazon_bot (el de BotFather; no se verá al escribir) y pulsa Enter:"
  read -rs TOKEN </dev/tty
  echo
  [ -n "$TOKEN" ] || { echo "Token vacío, cancelo."; exit 1; }
  printf 'TELEGRAM_BOT_TOKEN=%s\n' "$TOKEN" > .env
  chmod 600 .env
fi

echo
echo "== Prueba 1: ¿Amazon deja leer las fichas desde tu conexión? (no envía nada) =="
.venv/bin/python canal_amazon.py --dry-run --ignore-limits || true
echo
echo "== Prueba 2: hasta 3 chollos reales a tu chat privado de Telegram (nunca al canal) =="
.venv/bin/python canal_amazon.py --test-private --ignore-limits || true
echo
echo "Listo. Revisa tu chat privado con el bot y compara los precios con Amazon."
echo "Cuando quieras que publique en el canal cada 15 minutos:  bash $DIR/mac/activar.sh"
