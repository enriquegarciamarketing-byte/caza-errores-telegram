#!/bin/bash
# Bot de errores de precio de Amazon (premium @caza_errores) en el Mac, 24/7.
#
# Lo arranca launchd (local/com.cazachollos.errores.plist) al encender el Mac y lo vuelve a levantar si se cae.
# Cada ciclo:
#   1. Se trae de GitHub el código y la config nuevos (git pull).
#   2. Busca errores durante CICLO_MINUTOS, una pasada cada PASADA_SEGUNDOS.
#   3. Sube a GitHub la memoria (state/scanner.json) y el latido (state/latido_mac.json), para que el canal
#      normal sepa qué ha publicado el premium y el vigilante de GitHub te avise si el Mac deja de dar señales.
# La cascada al canal normal se sube en cada pasada (CASCADA_PUSH=1).
#
# Secretos en .env (no se sube nunca): TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ADMIN_CHAT_ID,
# AMAZON_CREATORS_ID, AMAZON_CREATORS_SECRET. Plantilla en local/env.ejemplo.

set -u
cd "$(dirname "$0")/.." || exit 1
REPO="$(pwd)"

if [ -f "$REPO/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$REPO/.env"
  set +a
fi

export CASCADA_PUSH=1
export PYTHONUNBUFFERED=1
export GIT_AUTHOR_NAME="Caza Errores (Mac)"
export GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

PY="$REPO/.venv/bin/python"
CICLO_MINUTOS="${CICLO_MINUTOS:-30}"
PASADA_SEGUNDOS="${PASADA_SEGUNDOS:-60}"
LOG_DIR="$REPO/state/local_logs"
mkdir -p "$LOG_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

aviso_telegram() {
  # Mensaje corto a tu chat privado con el bot. Nunca para el bucle si falla.
  [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${ADMIN_CHAT_ID:-}" ] || return 0
  curl -sS -m 20 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${ADMIN_CHAT_ID}" --data-urlencode "text=$1" >/dev/null 2>&1 || true
}

sincronizar() {
  # Código y config nuevos de GitHub. Si una ejecución a mano en GitHub tocó la memoria del premium,
  # gana la del Mac (-X theirs en un rebase = el commit del Mac).
  if ! git pull -q --rebase -X theirs --autostash origin main >/dev/null 2>&1; then
    git rebase --abort >/dev/null 2>&1 || true
    log "Aviso: no he podido traer cambios de GitHub (sigo con lo que hay)."
  fi
  local req_hash
  req_hash="$(shasum requirements.txt | cut -d' ' -f1)"
  if [ "$req_hash" != "$(cat .venv/.requirements_hash 2>/dev/null)" ]; then
    log "Dependencias nuevas: instalando…"
    "$PY" -m pip install -q -r requirements.txt && echo "$req_hash" > .venv/.requirements_hash
  fi
}

latido() {
  printf '{"t": %s, "hora": "%s", "equipo": "%s", "ultimo_codigo": %s}\n' \
    "$(date +%s)" "$(date '+%Y-%m-%d %H:%M')" "$(scutil --get ComputerName 2>/dev/null || hostname)" "$1" \
    > state/latido_mac.json
}

guardar_memoria() {
  git add state/scanner.json state/latido_mac.json 2>/dev/null || true
  if git diff --cached --quiet; then
    return 0
  fi
  git commit -qm "Memoria del premium desde el Mac [skip ci]" || return 0
  for i in 1 2 3; do
    if git push -q origin HEAD:main 2>/dev/null; then
      return 0
    fi
    git pull -q --rebase -X theirs --autostash origin main >/dev/null 2>&1 || git rebase --abort >/dev/null 2>&1
    sleep $((i * 5))
  done
  log "Aviso: no he podido subir la memoria a GitHub (lo reintento en el próximo ciclo)."
}

limpiar_logs() {
  find "$LOG_DIR" -name 'errores-*.log' -mtime +7 -delete 2>/dev/null || true
}

# Mientras el bot esté vivo, el Mac no se duerme (con el cargador puesto).
command -v caffeinate >/dev/null 2>&1 && caffeinate -s -i -w $$ &

log "Bot de errores en marcha en $(scutil --get ComputerName 2>/dev/null || hostname)."
aviso_telegram "🟢 Caza Errores: el bot de errores de Amazon está en marcha en el Mac."

# Latido nada más arrancar: así GitHub deja de buscar de reserva desde el primer minuto.
latido 0
guardar_memoria >> "$LOG_DIR/errores-$(date +%F).log" 2>&1

fallos=0
while true; do
  hoy_log="$LOG_DIR/errores-$(date +%F).log"
  inicio=$(date +%s)
  sincronizar >> "$hoy_log" 2>&1
  log "Ciclo de ${CICLO_MINUTOS} min, una pasada cada ${PASADA_SEGUNDOS} s" >> "$hoy_log"
  "$PY" -u scanner.py --minutes "$CICLO_MINUTOS" --every "$PASADA_SEGUNDOS" >> "$hoy_log" 2>&1
  codigo=$?
  latido "$codigo"
  guardar_memoria >> "$hoy_log" 2>&1
  limpiar_logs
  if [ "$codigo" -ne 0 ]; then
    fallos=$((fallos + 1))
    espera=$((fallos * 60))
    [ "$espera" -gt 600 ] && espera=600
    log "El escáner ha salido con código $codigo (fallo $fallos seguido). Reintento en ${espera} s." >> "$hoy_log"
    if [ "$fallos" -eq 3 ]; then
      aviso_telegram "⚠️ Caza Errores: el bot del Mac lleva 3 ciclos fallando. Mira state/local_logs/$(basename "$hoy_log")."
    fi
    sleep "$espera"
  else
    fallos=0
  fi
  # Un ciclo que acaba en segundos (fallo raro) no puede machacar GitHub ni Jimmyleaks: mínimo 1 min por ciclo.
  duro=$(( $(date +%s) - inicio ))
  [ "$duro" -lt 60 ] && sleep $((60 - duro))
done
