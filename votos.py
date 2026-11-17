"""👍/👎 de la comunidad en los posts de @cazachollos_com (17/11/2026).

«Quiero dos botones, like y dislike, para que el bot sepa qué chollos le gustan más a la comunidad y vaya
aprendiendo»: cada post del free lleva una fila 👍 · 👎 debajo de «Comprar en Amazon».

- Quien pulsa genera un callback al bot. Con el premium en pausa (premium_pausado en config.json) los escucha
  sin parar la tarea de GitHub «Votos del canal free» (python votos.py --escuchar): contesta al momento con
  «voto apuntado» y pone el contador al día. Con el premium en marcha los recoge el escáner en cada pasada
  (scanner.handle_updates), porque Telegram solo deja a uno leer los mensajes del bot.
- Un voto por persona y post: pulsar el mismo botón otra vez lo quita, pulsar el otro lo cambia.
- No se guarda quién vota (el repo es público): solo una huella de 12 caracteres, firmada con el token del bot,
  que sirve para no contar dos veces a la misma persona.
- Todo va en state/votos.json → "votos", con la clave «@canal:mensaje». El canal free (canal_nube.py) lo lee
  para subir en el orden de publicación los tipos de producto y las marcas que gustan y bajar los que no
  (nunca se salta las reglas de calidad), y la revisión semanal te cuenta qué ha gustado más y menos.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PREFIX = "voto:"
UP, DOWN = PREFIX + "up", PREFIX + "down"
KEEP_DAYS = 180  # los votos más viejos se borran de la memoria
ROOT = Path(__file__).resolve().parent
FREE_STATE = ROOT / "state" / "canal_nube.json"
STORE = ROOT / "state" / "votos.json"
CONFIG = ROOT / "config.json"
ALLOWED_UPDATES = ["message", "callback_query"]  # igual que scanner.ALLOWED_UPDATES


def load_store(path: Path | None = None) -> dict:
    try:
        data = json.loads((path or STORE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"votos": {}}
    except (OSError, ValueError):
        return {"votos": {}}


def save_store(store: dict, path: Path | None = None) -> None:
    path = path or STORE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


# ------------------------------------------------------------------ botones
def row(up: int = 0, down: int = 0) -> list[dict]:
    """Fila de votos: «👍 3» y «👎 1» (sin número mientras esté a cero)."""
    return [{"text": "👍" + (f" {up}" if up else ""), "callback_data": UP},
            {"text": "👎" + (f" {down}" if down else ""), "callback_data": DOWN}]


def is_vote_row(buttons: list) -> bool:
    return any(str((b or {}).get("callback_data") or "").startswith(PREFIX) for b in buttons or [])


def with_votes(markup: dict | None, up: int, down: int) -> dict:
    """El teclado del post con la fila de votos puesta al día. Va justo debajo del botón de comprar
    (si lo hay) y encima del de WhatsApp; el resto de botones se quedan como estaban."""
    rows = [r for r in ((markup or {}).get("inline_keyboard") or []) if not is_vote_row(r)]
    at = 1 if rows and str((rows[0][0] or {}).get("text") or "").startswith("🛒") else 0
    return {"inline_keyboard": rows[:at] + [row(up, down)] + rows[at:]}


# ------------------------------------------------------------------ memoria
def key(chat) -> str:
    """«@cazachollos_com» o el id del chat. Vale con el chat de Telegram (dict) o con el de la memoria (str)."""
    if isinstance(chat, dict):
        return "@" + str(chat["username"]).lower() if chat.get("username") else str(chat.get("id"))
    chat = str(chat or "")
    return chat.lower() if chat.startswith("@") else chat


def entry_key(chat, message_id) -> str:
    return f"{key(chat)}:{int(message_id)}"


def counts(entry: dict | None) -> tuple[int, int]:
    votes = list(((entry or {}).get("u") or {}).values())
    return sum(1 for v in votes if v > 0), sum(1 for v in votes if v < 0)


def counts_for(votos: dict | None, chat, message_id) -> tuple[int, int]:
    try:
        return counts((votos or {}).get(entry_key(chat, message_id)))
    except (TypeError, ValueError):
        return 0, 0


def fingerprint(user_id) -> str:
    """Huella del usuario: no se puede volver al id sin el token del bot."""
    secret = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or "caza-chollos"
    return hmac.new(secret.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()[:12]


def _free_post(chat, message_id) -> dict | None:
    try:
        posts = json.loads(FREE_STATE.read_text(encoding="utf-8")).get("posts") or []
    except (OSError, ValueError):
        return None
    k = key(chat)
    return next((p for p in reversed(posts) if int(p.get("message_id") or 0) == int(message_id)
                 and key(p.get("chat")) in (k, "")), None)


def prune(votos: dict, now: float) -> None:
    for k in [k for k, e in votos.items() if now - float(e.get("t") or now) > KEEP_DAYS * 86400]:
        votos.pop(k, None)


# ------------------------------------------------------------------ pulsaciones
def handle(tg, state: dict, callbacks: list[dict], dry: bool = False, now: float | None = None,
           log=print) -> int:
    """Apunta los votos de esta tanda y deja cada post tocado con su contador al día. Devuelve cuántos votos."""
    now = now or time.time()
    votos = state.setdefault("votos", {})
    touched: dict[str, tuple] = {}
    done = 0
    for cq in callbacks:
        data = str(cq.get("data") or "")
        if data not in (UP, DOWN):
            continue
        msg = cq.get("message") or {}
        chat, mid, user = msg.get("chat") or {}, msg.get("message_id"), (cq.get("from") or {}).get("id")
        if not mid or user is None or not chat:
            _answer(tg, cq, "", dry, log)
            continue
        k = entry_key(chat, mid)
        entry = votos.setdefault(k, {"t": now, "u": {}})
        if not entry.get("title"):
            post = _free_post(chat, mid)
            if post:
                entry.update({kk: post[kk] for kk in ("title", "brand", "asin") if post.get(kk)})
        who, value = fingerprint(user), (1 if data == UP else -1)
        if entry["u"].get(who) == value:
            entry["u"].pop(who)
            note = "Voto quitado"
        else:
            entry["u"][who] = value
            note = "👍 ¡Apuntado! Así sabemos qué chollos os molan" if value > 0 else \
                "👎 Apuntado, gracias. Lo tendremos en cuenta"
        entry["last"] = now
        done += 1
        up, down = counts(entry)
        _answer(tg, cq, f"{note} · 👍 {up} · 👎 {down}", dry, log)
        touched[k] = (chat.get("id"), mid, msg.get("reply_markup"))
    for k, (chat_id, mid, markup) in touched.items():
        if not (markup or {}).get("inline_keyboard"):
            log(f"  Votos {k}: el mensaje no trae botones, no toco el teclado")
            continue
        new = with_votes(markup, *counts(votos.get(k)))
        if new == markup:
            continue
        if dry or tg is None:
            log(f"  [prueba] votos {k}: {counts(votos.get(k))}")
            continue
        try:
            tg.call("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": mid, "reply_markup": new})
        except RuntimeError as exc:
            if "not modified" not in str(exc):
                log(f"  Votos {k}: no he podido poner el contador al día ({exc})")
    if done:
        up, down = sum(counts(e)[0] for e in votos.values()), sum(counts(e)[1] for e in votos.values())
        log(f"Votos de la comunidad: {done} nuevos en {len(touched)} posts (en total 👍 {up} · 👎 {down})")
    prune(votos, now)
    return done


def _answer(tg, cq: dict, text: str, dry: bool, log) -> None:
    """Quita el «cargando» del botón. Si el bot tardó en verlo, Telegram ya no deja contestar: da igual."""
    if dry or tg is None or not cq.get("id"):
        return
    params = {"callback_query_id": cq["id"]}
    if text:
        params["text"] = text
    try:
        tg.call("answerCallbackQuery", params)
    except RuntimeError:
        pass


# ------------------------------------------------------------------ lo que aprende el canal free
def community_tastes(votos: dict | None, posts: list[dict], now: float, kind_of, brand_of,
                     days: float = 90, chat: str = "@cazachollos_com") -> dict:
    """Saldo de votos (👍 − 👎) por tipo de producto y por marca en los posts de los últimos «days» días.

    kind_of(title) y brand_of(post) los pone canal_nube.py (product_kind y la marca del post)."""
    by_mid = {int(p["message_id"]): p for p in posts or [] if p.get("message_id") and key(p.get("chat")) == key(chat)}
    kinds: dict[str, list[int]] = {}
    brands: dict[str, list[int]] = {}
    for k, entry in (votos or {}).items():
        if not k.startswith(key(chat) + ":") or now - float(entry.get("t") or 0) > days * 86400:
            continue
        up, down = counts(entry)
        if not up and not down:
            continue
        post = by_mid.get(int(k.rsplit(":", 1)[1])) or entry
        kind, brand = kind_of(post.get("title") or ""), brand_of(post)
        for bucket, name in ((kinds, kind), (brands, brand)):
            if name:
                tally = bucket.setdefault(name, [0, 0])
                tally[0] += up
                tally[1] += down
    return {"kinds": kinds, "brands": brands}


def net_score(tally: list[int] | None, min_votes: int = 3) -> float:
    """Saldo suavizado entre -1 y 1: (👍 − 👎) / (👍 + 👎 + 2). Con menos de min_votes votos, 0 (aún no dice nada)."""
    up, down = (tally or [0, 0])[:2]
    if up + down < min_votes:
        return 0.0
    return (up - down) / (up + down + 2)


# ------------------------------------------------------------------ escucha continua (GitHub, premium en pausa)
class _Telegram:
    """Cliente mínimo con long polling (el de scanner.py corta a los 30 s)."""

    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, params: dict | None = None, timeout: int = 30):
        req = urllib.request.Request(self.base + method, data=json.dumps(params or {}).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                result = json.loads(exc.read().decode("utf-8"))
            except ValueError:
                result = {"ok": False, "description": f"HTTP {exc.code}"}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            result = {"ok": False, "description": f"sin conexión ({exc})"}
        if not result.get("ok"):
            raise RuntimeError(f"Telegram {method}: {result.get('description')}")
        return result["result"]


def premium_paused() -> bool:
    try:
        return bool(json.loads(CONFIG.read_text(encoding="utf-8")).get("premium_pausado"))
    except (OSError, ValueError):
        return False


def commit_store(log=print) -> None:
    """Sube state/votos.json a GitHub (solo ese fichero; nunca deshace código subido después)."""
    script = ROOT / "tools" / "guardar_votos.sh"
    try:
        out = subprocess.run(["bash", str(script)], cwd=ROOT, capture_output=True, text=True, timeout=120)
        log((out.stdout + out.stderr).strip() or "Votos guardados.")
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"No he podido subir los votos ({exc}); lo intento en la próxima.")


def listen(minutes: float, save_every: float = 600, log=print) -> int:
    """Escucha los 👍/👎 sin parar durante «minutes» y contesta al momento. Solo con el premium en pausa:
    con el premium en marcha los lee el escáner y dos lectores a la vez se pisan (Telegram da «Conflict»).
    Con el premium en pausa nadie más necesita los mensajes privados al bot, así que también se dan por leídos."""
    if not premium_paused():
        log("El premium está en marcha: los votos los recoge el escáner. No escucho.")
        return 0
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        log("Falta TELEGRAM_BOT_TOKEN")
        return 2
    tg, store = _Telegram(token), load_store()
    deadline, last_save, dirty, offset = time.time() + minutes * 60, time.time(), False, None
    log(f"Escuchando votos durante {minutes:.0f} min")
    while time.time() < deadline:
        params = {"timeout": int(max(1, min(50, deadline - time.time()))), "allowed_updates": ALLOWED_UPDATES}
        if offset is not None:
            params["offset"] = offset
        try:
            updates = tg.call("getUpdates", params, timeout=params["timeout"] + 20)
        except RuntimeError as exc:
            log(f"Aviso: {exc}")
            time.sleep(15 if "Conflict" in str(exc) else 5)
            continue
        if updates:
            offset = updates[-1]["update_id"] + 1
        votes = [u["callback_query"] for u in updates if u.get("callback_query")]
        if votes and handle(tg, store, votes, log=log):
            dirty = True
            save_store(store)
        if dirty and time.time() - last_save >= save_every:
            commit_store(log)
            dirty, last_save = False, time.time()
    if offset is not None:
        try:  # da por leído lo último, para que la siguiente tanda no lo vuelva a contar
            tg.call("getUpdates", {"offset": offset, "timeout": 0, "allowed_updates": ALLOWED_UPDATES})
        except RuntimeError:
            pass
    if dirty:
        commit_store(log)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Votos 👍/👎 del canal free")
    parser.add_argument("--escuchar", action="store_true", help="escuchar los botones sin parar")
    parser.add_argument("--minutos", type=float, default=345)
    args = parser.parse_args()
    if args.escuchar:
        sys.exit(listen(args.minutos, log=lambda m: print(m, flush=True)))
    parser.print_help()
