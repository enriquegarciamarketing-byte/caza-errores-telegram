#!/usr/bin/env bash
# Guarda la memoria del canal normal sin pisar la que otra ejecución haya subido mientras tanto.
# Uso: tools/guardar_memoria.sh "Mensaje del commit" state/canal_nube.json [otros ficheros de log…]
# La memoria (state/canal_nube.json) se junta post a post con la de GitHub; los logs se suben tal cual.
set -u
message="$1"; shift
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
for i in 1 2 3 4 5; do
  git fetch -q origin main || { sleep $((2 ** i)); continue; }
  if git cat-file -e origin/main:state/canal_nube.json 2>/dev/null; then
    git show origin/main:state/canal_nube.json > "$RUNNER_TEMP/memoria_github.json"
    python canal_nube.py --merge-state "$RUNNER_TEMP/memoria_github.json"
  fi
  # La web (GitHub Pages) lee docs/chollos.json: se rehace con la memoria ya juntada.
  web=()
  if [ -f web_export.py ] && printf '%s\n' "$@" | grep -qx "state/canal_nube.json"; then
    python web_export.py && web=(docs/chollos.json) || echo "Web: no se ha podido exportar (la memoria se guarda igual)."
  fi
  # El índice pasa a ser el de GitHub y solo se añaden estos ficheros: nunca se deshace código subido después.
  git reset -q --mixed origin/main
  git add -- "$@" "${web[@]}" 2>/dev/null || true
  if git diff --cached --quiet; then
    echo "Memoria: nada nuevo que guardar."
    exit 0
  fi
  git commit -qm "$message [skip ci]"
  if git push -q origin HEAD:main; then
    echo "Memoria guardada."
    exit 0
  fi
  sleep $((2 ** i))
done
echo "No he podido guardar la memoria tras 5 intentos." >&2
exit 1
