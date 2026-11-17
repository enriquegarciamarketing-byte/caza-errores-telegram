#!/usr/bin/env bash
# Relevo del canal normal: al acabar una ejecución, lanza la siguiente.
# GitHub se salta a veces las tareas programadas durante horas (17/11/2026: ni una sola entre las 5:42 y las 13:20),
# así que el canal ya no depende del cron, que se queda solo de reserva.
#   - De día (6:30 a 23:45) lanza otra pasada del canal.
#   - De noche lanza "Relevo de noche", que duerme hasta las 6:30 y entonces arranca el canal.
# Uso: tools/relevo_canal.sh <estado del job: success|failure>
set -euo pipefail
estado="${1:-success}"
repo="repos/${GITHUB_REPOSITORY}/actions/workflows"
hm=$(TZ=Europe/Madrid date +%H%M); hm=$((10#$hm))

lanzar() {  # lanzar <workflow> [inputs...]
  local wf="$1"; shift
  for i in 1 2 3; do
    if gh api -X POST "$repo/$wf/dispatches" -f ref=main "$@" >/dev/null; then
      echo "Relevo: lanzado $wf."
      return 0
    fi
    sleep $((10 * i))
  done
  echo "Relevo: no he podido lanzar $wf (queda el cron de reserva)."
}

if [ "$hm" -ge 2345 ] || [ "$hm" -lt 630 ]; then
  lanzar relevo-noche.yml
  exit 0
fi

# Si la pasada ha fallado, deja 5 min antes de reintentar para no entrar en bucle de fallos.
if [ "$estado" != "success" ]; then
  echo "Relevo: la pasada ha fallado, espero 5 min."
  sleep 300
fi
lanzar scan-generic.yml -f 'inputs[dry_run]=false' -f 'inputs[test_private]=false' -f 'inputs[minutes]=55'
