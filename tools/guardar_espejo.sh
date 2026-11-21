#!/usr/bin/env bash
# Guarda la memoria del vigía de canales sin pisar lo que otros workflows hayan subido mientras tanto.
# state/espejo_canales.json solo lo escribe el vigía; state/premium_manual.json lo comparten el vigía y los
# posts a mano de Enrique, así que se juntan por número de mensaje (gana lo de GitHub, se añade lo nuevo).
# Uso: tools/guardar_espejo.sh "Mensaje del commit"
set -u
message="${1:-Memoria vigía}"
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
for i in 1 2 3 4 5; do
  git fetch -q origin main || { sleep $((2 ** i)); continue; }
  if git cat-file -e origin/main:state/premium_manual.json 2>/dev/null; then
    git show origin/main:state/premium_manual.json > "$RUNNER_TEMP/premium_github.json"
    python - "$RUNNER_TEMP/premium_github.json" <<'EOF'
import json, sys
remote = json.load(open(sys.argv[1], encoding="utf-8"))
try:
    local = json.load(open("state/premium_manual.json", encoding="utf-8"))
except (FileNotFoundError, json.JSONDecodeError):
    local = {"posts": []}
seen = {p.get("message_id") for p in remote.get("posts", [])}
remote.setdefault("posts", []).extend(p for p in local.get("posts", []) if p.get("message_id") not in seen)
remote["posts"].sort(key=lambda p: p.get("message_id") or 0)
with open("state/premium_manual.json", "w", encoding="utf-8") as f:
    f.write(json.dumps(remote, ensure_ascii=False, indent=1) + "\n")
EOF
  fi
  git reset -q --mixed origin/main
  git add -- state/espejo_canales.json state/premium_manual.json 2>/dev/null || true
  if git diff --cached --quiet; then
    echo "Memoria vigía: nada nuevo."
    exit 0
  fi
  git commit -qm "$message [skip ci]"
  if git push -q origin HEAD:main; then
    echo "Memoria vigía guardada."
    exit 0
  fi
  sleep $((2 ** i))
done
echo "No he podido guardar la memoria del vigía." >&2
exit 1
