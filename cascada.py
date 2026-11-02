"""Cascada premium → canal normal (@cazachollos_com).

Lo que el escáner premium descarta porque no da para revender (poco margen en Wallapop, fuera de las
categorías de reventa, ahorro o importe pequeños…) puede ser un buen chollo para comprar y usar.
El premium lo apunta aquí y el canal normal lo revisa con TODAS sus reglas, releyendo la ficha.

Reglas que no se saltan:
- Solo productos de Amazon.es vistos en Jimmyleaks. Nada de Chollometro ni de otras tiendas.
- Solo descartes por motivos de reventa (lista blanca de motivos). Lo descartado por datos dudosos
  (precio que no cuadra, datos viejos, sin stock, tallas, descuento sospechoso, media inflada…) nunca baja.
- Nunca baja lo que el premium ha publicado o está esperando tu OK.

El premium sube la lista en cada pasada a la rama `cascada` del repositorio (un único commit que se
sobrescribe, así no ensucia el historial de main) y el canal normal la lee en cada pasada.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time

FILE_NAME = "cascada.json"
DEFAULT_BRANCH = "cascada"
ITEM_FIELDS = ("id", "title", "brand", "price", "was", "verdict", "ts", "rating", "reviews")

# Motivos de descarte del premium que solo dicen «no da para revender», no «el dato es dudoso».
SAFE_REASONS = [re.compile(p, re.I) for p in (
    r"^solo -\d+% bajo la referencia",
    r"^importe demasiado bajo",
    r"^error de precio pero importe demasiado bajo",
    r"^valoraciones flojas",
    r"^fuera de las categorías premium",
    r"^producto de poco valor",
    r"^bloqueado para reventa",
    r"^precio .* por debajo del mínimo de reventa",
    r"^ahorro de .* inferior al mínimo de reventa",
    r"^error de precio de algo que vale",
    r"^error de precio sin marca",
    r"^error de precio con pocas opiniones",
    r"^error de precio con valoración floja",
    r"^solo \d+ puntos de precio en españa",
    r"^el pvp .* supera",
    r"^sin margen de reventa",
    r"^listado: ",
)]


def reason_ok(reason: str | None) -> bool:
    text = (reason or "").strip()
    return bool(text) and any(p.search(text) for p in SAFE_REASONS)


def make_entry(item: dict, reason: str, now_ts: float) -> dict:
    """Solo los datos del listado: el canal normal vuelve a leer la ficha y decide con sus reglas."""
    data = {k: item.get(k) for k in ITEM_FIELDS if item.get(k) not in (None, "")}
    if item.get("listing_price") is not None:
        data["price"] = item["listing_price"]  # el del listado, que es el que compara el canal normal
    return {"t": int(now_ts), "reason": reason, "item": data}


class Collector:
    """Descartes de una ejecución del premium, por ID de Jimmyleaks (el más reciente gana)."""

    def __init__(self):
        self.entries: dict[str, dict] = {}

    def add(self, item: dict, reason: str, now_ts: float) -> bool:
        jl_id = str(item.get("id") or "")
        if not re.fullmatch(r"[A-Za-z0-9]{4,12}", jl_id) or not reason_ok(reason):
            return False
        if item.get("origin") in ("chollometro", "watchlist") or item.get("direct_url") and not item.get("series"):
            return False  # solo lo que viene de los listados de Amazon en Jimmyleaks
        if not item.get("ts") or not (item.get("listing_price") or item.get("price")):
            return False
        self.entries[jl_id] = make_entry(item, reason, now_ts)
        return True

    def merge(self, previous: list[dict], now_ts: float, keep_minutes: float, limit: int = 250) -> None:
        for entry in previous or []:
            jl_id = str((entry.get("item") or {}).get("id") or "")
            if not jl_id or now_ts - float(entry.get("t") or 0) > keep_minutes * 60:
                continue
            mine = self.entries.get(jl_id)
            if mine is None or float(mine.get("t") or 0) < float(entry.get("t") or 0):
                self.entries[jl_id] = entry
        fresh = {k: v for k, v in self.entries.items() if now_ts - float(v.get("t") or 0) <= keep_minutes * 60}
        newest = sorted(fresh.items(), key=lambda kv: kv[1].get("t") or 0, reverse=True)[:limit]
        self.entries = dict(newest)

    def drop(self, ids) -> None:
        for jl_id in ids:
            self.entries.pop(str(jl_id), None)

    def as_list(self) -> list[dict]:
        return sorted(self.entries.values(), key=lambda e: e.get("t") or 0, reverse=True)


# ------------------------------------------------------------------ subir y leer la lista

def _git(args: list[str], data: str | None = None, timeout: int = 40) -> str:
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", "github-actions[bot]")
    env.setdefault("GIT_AUTHOR_EMAIL", "41898282+github-actions[bot]@users.noreply.github.com")
    env.setdefault("GIT_COMMITTER_NAME", env["GIT_AUTHOR_NAME"])
    env.setdefault("GIT_COMMITTER_EMAIL", env["GIT_AUTHOR_EMAIL"])
    done = subprocess.run(["git", *args], input=data, capture_output=True, text=True, timeout=timeout, env=env)
    if done.returncode != 0:
        raise RuntimeError((done.stderr or done.stdout or "git ha fallado").strip()[:300])
    return done.stdout.strip()


def _enabled_here() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def push(entries: list[dict], branch: str = DEFAULT_BRANCH, log=print) -> bool:
    """Sube la lista a la rama `branch` como un único commit (se sobrescribe cada vez).
    No toca la carpeta de trabajo ni main. Fuera de GitHub Actions no hace nada."""
    path = os.environ.get("CASCADA_FILE")
    payload = json.dumps({"updated": int(time.time()), "entries": entries}, ensure_ascii=False, indent=1) + "\n"
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(payload)
        return True
    if not _enabled_here():
        return False
    try:
        blob = _git(["hash-object", "-w", "--stdin"], payload)
        tree = _git(["mktree"], f"100644 blob {blob}\t{FILE_NAME}\n")
        commit = _git(["commit-tree", tree, "-m", "Descartes del premium para el canal normal [skip ci]"])
        _git(["push", "-q", "-f", "origin", f"{commit}:refs/heads/{branch}"])
        return True
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        log(f"Aviso: no he podido subir la cascada al canal normal ({exc})")
        return False


def load(branch: str = DEFAULT_BRANCH, log=print) -> list[dict]:
    """Lee la lista que dejó el premium. Fuera de GitHub Actions devuelve [] (salvo CASCADA_FILE)."""
    path = os.environ.get("CASCADA_FILE")
    try:
        if path:
            with open(path, encoding="utf-8") as fh:
                raw = fh.read()
        elif _enabled_here():
            _git(["fetch", "-q", "--depth", "1", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}"])
            raw = _git(["show", f"origin/{branch}:{FILE_NAME}"])
        else:
            return []
        data = json.loads(raw or "{}")
    except (RuntimeError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        if "couldn't find remote ref" not in str(exc):
            log(f"  Cascada del premium no disponible ({exc})")
        return []
    entries = data.get("entries") if isinstance(data, dict) else None
    return [e for e in entries or [] if isinstance(e, dict) and isinstance(e.get("item"), dict)]
