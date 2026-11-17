#!/usr/bin/env bash
# Sube los votos 👍/👎 del canal free (state/votos.json) sin tocar nada más del repo.
# Lo llama votos.py --escuchar cada ~10 min y al terminar. Solo ese proceso escribe el fichero mientras el
# premium está en pausa, así que basta con colocarlo encima de lo último de GitHub.
set -u
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
for i in 1 2 3 4 5; do
  git fetch -q origin main || { sleep $((2 ** i)); continue; }
  # El índice pasa a ser el de GitHub y solo se añade este fichero: nunca se deshace código subido después.
  git reset -q --mixed origin/main
  git add -- state/votos.json 2>/dev/null || true
  if git diff --cached --quiet; then
    echo "Votos: nada nuevo que guardar."
    exit 0
  fi
  git commit -qm "Votos del canal free [skip ci]"
  if git push -q origin HEAD:main; then
    echo "Votos guardados."
    exit 0
  fi
  sleep $((2 ** i))
done
echo "No he podido guardar los votos tras 5 intentos." >&2
exit 1
