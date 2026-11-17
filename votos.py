"""👍/👎 de la comunidad en los posts de @cazachollos_com (17/11/2026).

«Quiero dos botones, like y dislike, para que el bot sepa qué chollos le gustan más a la comunidad y vaya
aprendiendo»: cada post del free lleva una fila 👍 · 👎 debajo de «Comprar en Amazon».

- Quien pulsa genera un callback al bot. Los recoge el escáner (scanner.handle_updates), que en el Mac pasa
  cada minuto: apunta el voto, contesta al botón y actualiza el contador del post.
- Un voto por persona y post: pulsar el mismo botón otra vez lo quita, pulsar el otro lo cambia.
- No se guarda quién vota (el repo es público): solo una huella de 12 caracteres, firmada con el token del bot,
  que sirve para no contar dos veces a la misma persona.
- Todo va en state/scanner.json → "votos", con la clave «@canal:mensaje». El canal free (canal_nube.py) lo lee
  para subir en el orden de publicación los tipos de producto y las marcas que gustan y bajar los que no
  (nunca se salta las reglas de calidad), y la revisión semanal te cuenta qué ha gustado más y menos.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path

PREFIX = "voto:"
UP, DOWN = PREFIX + "up", PREFIX + "down"
KEEP_DAYS = 180  # los votos más viejos se borran de la memoria
FREE_STATE = Path(__file__).resolve().parent / "state" / "canal_nube.json"


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
        _answer(tg, cq, note, dry, log)
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
