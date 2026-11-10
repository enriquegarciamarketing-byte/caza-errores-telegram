#!/bin/bash
# Instala el bot de errores de Amazon en este Mac para que corra 24/7.
# Uso (desde la carpeta del bot):  bash local/instalar_mac.sh            → instala y arranca
#                                  bash local/instalar_mac.sh --parar    → lo para y lo quita del arranque
#                                  bash local/instalar_mac.sh --estado   → dice si está vivo y la última línea del log
#                                  bash local/instalar_mac.sh --actualizar → baja lo nuevo de GitHub y reinicia el bot
set -u
cd "$(dirname "$0")/.." || exit 1
REPO="$(pwd)"
LABEL="com.cazachollos.errores"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"

ok()   { echo "✅ $*"; }
mal()  { echo "❌ $*"; }
nota() { echo "👉 $*"; }

if [ "${1:-}" = "--parar" ]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null && ok "Bot parado." || nota "No estaba en marcha."
  rm -f "$PLIST"
  exit 0
fi

hay_internet() {
  curl -sS -m 8 -o /dev/null https://api.telegram.org 2>/dev/null || curl -sS -m 8 -o /dev/null https://github.com 2>/dev/null
}

if [ "${1:-}" = "--actualizar" ] || [ -z "${1:-}" ]; then
  # Sin internet (wifi reconectando al abrir la tapa) no se toca nada: el bot que esté en marcha sigue en marcha.
  espera=0
  until hay_internet; do
    if [ "$espera" -ge 60 ]; then
      mal "El Mac no tiene internet. No he tocado el bot. Conecta la wifi y vuelve a darle a ▶️ Encender bot."
      exit 1
    fi
    [ "$espera" -eq 0 ] && nota "Esperando a que vuelva internet (la wifi tarda unos segundos al abrir la tapa)…"
    sleep 5; espera=$((espera + 5))
  done
fi

if [ "${1:-}" = "--actualizar" ]; then
  # Para el bot, guarda su memoria, se trae lo nuevo de GitHub (gana la memoria del Mac) y sigue instalando.
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  export GIT_AUTHOR_NAME="Caza Errores (Mac)" GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com"
  export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
  git add state/scanner.json state/latido_mac.json 2>/dev/null || true
  git diff --cached --quiet || git commit -qm "Memoria del premium desde el Mac [skip ci]"
  if git pull -q --rebase -X theirs origin main; then
    git push -q origin HEAD:main 2>/dev/null || true
    ok "Código actualizado desde GitHub."
  else
    git rebase --abort 2>/dev/null || true
    mal "No he podido actualizar desde GitHub (sigo con el código que había)."
  fi
fi

if [ "${1:-}" = "--estado" ]; then
  if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    ok "El bot está cargado en launchd."
    launchctl print "$DOMAIN/$LABEL" | grep -E "state =|pid =|last exit code" | sed 's/^/   /'
  else
    mal "El bot no está cargado."
  fi
  ultimo="$(ls -t state/local_logs/errores-*.log 2>/dev/null | head -1)"
  [ -n "$ultimo" ] && { echo "Últimas líneas de $ultimo:"; tail -5 "$ultimo"; }
  exit 0
fi

echo "== Instalando el bot de errores en $(scutil --get ComputerName 2>/dev/null || hostname) =="

# 1. Python 3.10 o más nuevo (el de Apple suele ser 3.9).
PYTHON=""
for cand in /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 \
            /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PYTHON="$(command -v "$cand")"; break
  fi
done
if [ -z "$PYTHON" ]; then
  mal "Falta Python 3.10 o más nuevo."
  nota "Instálalo con:  brew install python@3.12   (y vuelve a lanzar este script)"
  exit 1
fi
ok "Python: $("$PYTHON" --version)"

# 2. Entorno con las dependencias.
if [ ! -x .venv/bin/python ]; then
  "$PYTHON" -m venv .venv || { mal "No he podido crear el entorno .venv"; exit 1; }
fi
.venv/bin/python -m pip install -q --upgrade pip >/dev/null 2>&1
if .venv/bin/python -m pip install -q -r requirements.txt; then
  shasum requirements.txt | cut -d' ' -f1 > .venv/.requirements_hash
  ok "Dependencias instaladas."
else
  mal "Han fallado las dependencias (mira el error de arriba)."; exit 1
fi

# 3. Secretos.
if [ ! -f .env ]; then
  cp local/env.ejemplo .env
  mal "He creado .env: rellénalo con los mismos secretos que tienes en GitHub y vuelve a lanzar el script."
  nota "open -e \"$REPO/.env\""
  exit 1
fi
set -a; . ./.env; set +a
faltan=""
for var in TELEGRAM_BOT_TOKEN TELEGRAM_CHAT_ID ADMIN_CHAT_ID AMAZON_CREATORS_ID AMAZON_CREATORS_SECRET; do
  [ -n "${!var:-}" ] || faltan="$faltan $var"
done
if [ -n "$faltan" ]; then
  mal "Faltan en .env:$faltan"; exit 1
fi
ok "Secretos en .env. Publicará en: $TELEGRAM_CHAT_ID"
if [ "$TELEGRAM_CHAT_ID" != "@caza_errores" ]; then
  nota "Ojo: el premium es @caza_errores. Si $TELEGRAM_CHAT_ID no es ese canal (o su número), cámbialo en .env."
fi
respuesta="$(curl -sS -m 15 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe" 2>&1)"
if echo "$respuesta" | grep -q '"ok":true'; then
  ok "Telegram responde."
elif echo "$respuesta" | grep -q '"ok":false'; then
  mal "Telegram no acepta el TELEGRAM_BOT_TOKEN de .env."; exit 1
else
  mal "No llego a Telegram (¿sin internet?). Conecta la wifi y vuelve a darle a ▶️ Encender bot."; exit 1
fi

# 4. Permiso para subir a GitHub (memoria del premium, latido y cascada al canal normal).
if git push --dry-run -q origin HEAD:main >/dev/null 2>&1; then
  ok "El Mac puede subir a GitHub."
else
  mal "El Mac no puede subir a GitHub todavía."
  nota "Opción fácil:  brew install gh && gh auth login && gh auth setup-git   (y vuelve a lanzar este script)"
  exit 1
fi

# 5. Arranque automático con launchd.
mkdir -p "$HOME/Library/LaunchAgents" state/local_logs
chmod +x local/caza_errores.sh
sed "s#__REPO__#$REPO#g" local/com.cazachollos.errores.plist > "$PLIST"
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST" && launchctl enable "$DOMAIN/$LABEL"
sleep 3
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  ok "Bot en marcha. Te llegará un 🟢 por Telegram."
else
  mal "launchd no ha cargado el bot. Mira state/local_logs/launchd.log"; exit 1
fi

# 6. Que el Mac no se duerma enchufado y vuelva solo tras un corte de luz (pide tu contraseña).
echo
nota "Para que no se duerma con el cargador puesto y se encienda solo tras un corte de luz:"
echo "   sudo pmset -c sleep 0 disksleep 0 displaysleep 10 womp 1 autorestart 1"
nota "Si lo vas a tener con la TAPA CERRADA, además:"
echo "   sudo pmset -a disablesleep 1      (para deshacerlo: sudo pmset -a disablesleep 0)"
