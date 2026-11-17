"""👍/👎 de la comunidad en el free (votos.py, 17/11/2026)."""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import canal_nube
import revision_semanal
import scanner
import votos

CHAT = {"id": -1001234, "username": "cazachollos_com", "type": "channel"}
BUY = [{"text": "🛒 Comprar en Amazon", "url": "https://www.amazon.es/dp/B0TEST1234?tag=x-21", "style": "success"}]
WA = [{"text": "📲 Únete en WhatsApp", "url": "https://whatsapp.com/channel/x"}]


class FakeTg:
    def __init__(self, updates=None):
        self.calls, self.updates = [], updates or []

    def call(self, method, params=None):
        self.calls.append((method, params))
        if method == "getUpdates":
            return self.updates
        if method == "answerCallbackQuery":
            raise RuntimeError("Telegram answerCallbackQuery: query is too old")
        return True


def cb(user, data, mid=655, markup=None, qid="q"):
    markup = markup or {"inline_keyboard": [BUY, votos.row(), WA]}
    return {"id": qid, "from": {"id": user}, "data": data,
            "message": {"message_id": mid, "chat": CHAT, "reply_markup": markup}}


class Botones(unittest.TestCase):
    def test_post_nuevo_lleva_votos_debajo_de_comprar_y_encima_de_whatsapp(self):
        rows = canal_nube.buttons("https://x", "success", WA[0])["inline_keyboard"]
        self.assertEqual(rows[0][0]["text"], "🛒 Comprar en Amazon")
        self.assertEqual([b["callback_data"] for b in rows[1]], [votos.UP, votos.DOWN])
        self.assertEqual([b["text"] for b in rows[1]], ["👍", "👎"])
        self.assertEqual(rows[2], WA)

    def test_sin_votos_si_se_pide(self):
        self.assertEqual(len(canal_nube.buttons("https://x", "success", None, None)["inline_keyboard"]), 1)

    def test_with_votes_sustituye_la_fila_y_respeta_el_resto(self):
        new = votos.with_votes({"inline_keyboard": [BUY, votos.row(1, 0), WA]}, 3, 1)
        self.assertEqual(new["inline_keyboard"][0], BUY)
        self.assertEqual([b["text"] for b in new["inline_keyboard"][1]], ["👍 3", "👎 1"])
        self.assertEqual(new["inline_keyboard"][2], WA)
        ended = votos.with_votes({"inline_keyboard": [votos.row(), WA]}, 2, 0)
        self.assertEqual(ended["inline_keyboard"][0][0]["text"], "👍 2")
        self.assertEqual(ended["inline_keyboard"][1], WA)

    def test_chollo_terminado_conserva_votos_y_whatsapp_sin_amazon(self):
        rules = {"whatsapp_button": {"text": WA[0]["text"], "url": WA[0]["url"]}}
        with mock.patch.object(votos, "load_store", return_value={"votos": {
                "@cazachollos_com:655": {"t": 1, "u": {"a": 1, "b": 1, "c": -1}}}}):
            markup = canal_nube.ended_markup(rules, {"chat": "@cazachollos_com", "message_id": 655})
        self.assertEqual([b["text"] for b in markup["inline_keyboard"][0]], ["👍 2", "👎 1"])
        self.assertEqual(markup["inline_keyboard"][1], WA)
        self.assertNotIn("Amazon", json.dumps(markup, ensure_ascii=False))


class Pulsaciones(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({"posts": [{"chat": "@cazachollos_com", "message_id": 655, "title": "Amoladora Bosch GWS 880",
                              "brand": "bosch", "asin": "B07BRS1KXS"}]}, tmp)
        tmp.close()
        patcher = mock.patch.object(votos, "FREE_STATE", Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.store_path = Path(tempfile.mkdtemp()) / "votos.json"
        store = mock.patch.object(votos, "STORE", self.store_path)
        store.start()
        self.addCleanup(store.stop)

    def test_un_voto_por_persona_cambiar_y_quitar(self):
        tg, state = FakeTg(), {}
        votos.handle(tg, state, [cb(1, votos.UP), cb(2, votos.UP), cb(3, votos.DOWN)], log=lambda *_: None)
        entry = state["votos"]["@cazachollos_com:655"]
        self.assertEqual(votos.counts(entry), (2, 1))
        self.assertEqual(entry["title"], "Amoladora Bosch GWS 880")
        votos.handle(tg, state, [cb(1, votos.UP), cb(1, votos.UP)], log=lambda *_: None)  # pulsa dos veces: quita y pone
        self.assertEqual(votos.counts(entry), (2, 1))
        votos.handle(tg, state, [cb(2, votos.DOWN)], log=lambda *_: None)  # cambia de opinión
        self.assertEqual(votos.counts(entry), (1, 2))
        votos.handle(tg, state, [cb(3, votos.DOWN)], log=lambda *_: None)  # quita su 👎
        self.assertEqual(votos.counts(entry), (1, 1))

    def test_no_guarda_el_id_de_telegram(self):
        state = {}
        votos.handle(FakeTg(), state, [cb(987654321, votos.UP)], log=lambda *_: None)
        self.assertNotIn("987654321", json.dumps(state))

    def test_actualiza_el_contador_una_vez_por_post(self):
        tg, state = FakeTg(), {}
        votos.handle(tg, state, [cb(1, votos.UP), cb(2, votos.UP)], log=lambda *_: None)
        edits = [p for m, p in tg.calls if m == "editMessageReplyMarkup"]
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]["chat_id"], -1001234)
        rows = edits[0]["reply_markup"]["inline_keyboard"]
        self.assertEqual(rows[0], BUY)
        self.assertEqual([b["text"] for b in rows[1]], ["👍 2", "👎"])
        self.assertEqual(rows[2], WA)

    def test_sin_teclado_en_el_mensaje_no_lo_toca(self):
        tg, state = FakeTg(), {}
        call = cb(1, votos.UP)
        call["message"].pop("reply_markup")
        votos.handle(tg, state, [call], log=lambda *_: None)
        self.assertFalse([m for m, _ in tg.calls if m == "editMessageReplyMarkup"])
        self.assertEqual(votos.counts(state["votos"]["@cazachollos_com:655"]), (1, 0))

    def test_el_escaner_recoge_los_votos_y_pide_callbacks(self):
        tg = FakeTg([{"update_id": 10, "callback_query": cb(1, votos.UP)},
                     {"update_id": 11, "callback_query": cb(2, votos.DOWN)}])
        state = {"tg_offset": 5}
        scanner.handle_updates(tg, {}, state, "@caza_errores", False)
        self.assertEqual(state["tg_offset"], 12)
        self.assertNotIn("votos", state)  # van a state/votos.json, no a la memoria del premium
        self.assertIn("callback_query", tg.calls[0][1]["allowed_updates"])
        self.assertEqual(votos.counts(votos.load_store()["votos"]["@cazachollos_com:655"]), (1, 1))

    def test_el_aviso_dice_que_el_voto_esta_apuntado_con_el_recuento(self):
        class Tg(FakeTg):
            def call(self, method, params=None):
                self.calls.append((method, params))
                return True
        tg = Tg()
        votos.handle(tg, {}, [cb(1, votos.UP, qid="a"), cb(2, votos.DOWN, qid="b")], log=lambda *_: None)
        notes = [p["text"] for m, p in tg.calls if m == "answerCallbackQuery"]
        self.assertIn("Apuntado", notes[0])
        self.assertTrue(notes[0].endswith("👍 1 · 👎 0"))
        self.assertTrue(notes[1].endswith("👍 1 · 👎 1"))

    def test_escucha_contesta_al_momento_y_guarda(self):
        updates = [[{"update_id": 1, "callback_query": cb(1, votos.UP)}], []]
        calls = []

        class Tg:
            def __init__(self, token):
                pass

            def call(self, method, params=None, timeout=30):
                calls.append((method, params))
                if method == "getUpdates":
                    return updates.pop(0) if updates else []
                return True
        clock = iter([0, 0, 0, 1, 2, 3, 99999, 99999, 99999])
        with mock.patch.object(votos, "premium_paused", return_value=True), \
                mock.patch.object(votos, "_Telegram", Tg), mock.patch.object(votos, "commit_store") as commit, \
                mock.patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "t"}), \
                mock.patch.object(votos.time, "time", side_effect=lambda: next(clock, 99999)):
            votos.listen(1, log=lambda *_: None)
        self.assertIn("answerCallbackQuery", [m for m, _ in calls])
        self.assertIn("editMessageReplyMarkup", [m for m, _ in calls])
        self.assertEqual(votos.counts(votos.load_store()["votos"]["@cazachollos_com:655"]), (1, 0))
        commit.assert_called()
        self.assertEqual(calls[-1][1]["offset"], 2)  # deja leído lo último

    def test_con_el_premium_en_marcha_no_escucha(self):
        with mock.patch.object(votos, "premium_paused", return_value=False), \
                mock.patch.object(votos, "_Telegram") as tg:
            self.assertEqual(votos.listen(1, log=lambda *_: None), 0)
        tg.assert_not_called()


class Aprendizaje(unittest.TestCase):
    NOW = datetime(2026, 11, 17, 16, 0, tzinfo=timezone.utc)

    def entry(self, up, down):
        return {"t": self.NOW.timestamp() - 3600, "u": {f"u{i}": 1 for i in range(up)} |
                {f"d{i}": -1 for i in range(down)}}

    def test_lo_que_gusta_sube_y_lo_que_no_baja(self):
        posts = [{"chat": "@cazachollos_com", "message_id": 1, "title": "Freidora de aire Cosori 5,5 L", "brand": "cosori"},
                 {"chat": "@cazachollos_com", "message_id": 2, "title": "Zapatillas Pepe Jeans Joe Basic", "brand": "pepe jeans"}]
        prem = {"votos": {"@cazachollos_com:1": self.entry(6, 0), "@cazachollos_com:2": self.entry(0, 5)}}
        rules = {"chat_id": "@cazachollos_com", "gustos": {"enabled": False}}
        with mock.patch.object(votos, "load_store", return_value=prem):
            tastes = canal_nube.taste_profile({"posts": posts}, rules, self.NOW)
        liked = {"title": "Freidora de aire Cosori Pro 6 L", "brand": "cosori", "discount": 50, "price": 60, "reference": 120}
        disliked = {"title": "Zapatillas Pepe Jeans Kenton", "brand": "pepe jeans", "discount": 50, "price": 60, "reference": 120}
        neutral = {"title": "Taladro percutor Einhell", "brand": "einhell", "discount": 50, "price": 60, "reference": 120}
        self.assertGreater(canal_nube.deal_rank(liked, tastes), canal_nube.deal_rank(neutral, tastes))
        self.assertLess(canal_nube.deal_rank(disliked, tastes), canal_nube.deal_rank(neutral, tastes))

    def test_pocos_votos_no_cuentan(self):
        self.assertEqual(votos.net_score([2, 0]), 0.0)
        self.assertGreater(votos.net_score([3, 0]), 0)

    def test_revision_semanal_cuenta_los_votos(self):
        prem = {"votos": {"@cazachollos_com:1": {**self.entry(4, 1), "last": self.NOW.timestamp()}}}
        free = {"posts": [{"chat": "@cazachollos_com", "message_id": 1, "title": "Freidora Cosori"}]}
        v = revision_semanal.weekly_votes(prem, free, self.NOW.timestamp() - 86400)
        self.assertEqual((v["up"], v["down"], v["posts"]), (4, 1, 1))
        self.assertEqual(v["best"][0][3], "Freidora Cosori")


if __name__ == "__main__":
    unittest.main()
