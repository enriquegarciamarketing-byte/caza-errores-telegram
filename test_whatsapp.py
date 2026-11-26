import os
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import whatsapp

NOW = datetime(2026, 11, 16, 23, 59, tzinfo=ZoneInfo("Europe/Madrid"))
ITEMS = [
    {"asin": "B0AAAAAAA1", "title": "Robot *aspirador* Roborock", "price": 129.99, "reference": 299.99,
     "discount": 56.7, "url": "https://www.amazon.es/dp/B0AAAAAAA1?tag=otro-21&th=1"},
    {"asin": "", "title": "Cafetera", "price": 49.0, "reference": 99.0, "discount": 50.5,
     "url": "https://www.amazon.es/gp/product/B0BBBBBBB2"},
]


class TestWhatsApp(unittest.TestCase):
    def test_texto_lleva_tag_formato_y_publicidad(self):
        text = whatsapp.build_text(ITEMS, NOW)
        self.assertIn("https://www.amazon.es/dp/B0AAAAAAA1?tag=cazachollos0c-21", text)
        self.assertIn("https://www.amazon.es/dp/B0BBBBBBB2?tag=cazachollos0c-21", text)
        self.assertNotIn("otro-21", text)
        self.assertIn("*129,99 €*  ~299,99 €~  📉 *-57 %*", text)
        self.assertIn("*Robot aspirador Roborock*", text)
        self.assertIn("https://t.me/cazachollos_com", text)
        self.assertTrue(text.endswith("#Publicidad"))
        self.assertIn("23:59", text)

    def test_maximo_ocho(self):
        many = [dict(ITEMS[0], asin=f"B0AAAAAA{i:02d}") for i in range(12)]
        self.assertEqual(whatsapp.build_text(many, NOW).count("🛒"), 8)

    def test_sin_token_no_hace_nada(self):
        with mock.patch.dict(os.environ, {"WHAPI_TOKEN": ""}), mock.patch.object(whatsapp, "_request") as rq:
            self.assertFalse(whatsapp.publish_summary(ITEMS, None, NOW, log=lambda *_: None))
            rq.assert_not_called()

    def test_canal_desde_enlace(self):
        sent = []
        def fake(method, path, token, body=None, ctype="", **kw):
            if path.startswith("/newsletters/link/"):
                self.assertEqual(path, "/newsletters/link/0029VbE063mEwEk5M7m9Xe17")
                return {"id": "120363000000000001@newsletter", "role": "owner", "name": "Caza Chollos"}
            sent.append((path, body))
            return {"sent": True}
        with mock.patch.dict(os.environ, {"WHAPI_TOKEN": "x", "WHATSAPP_CHANNEL_ID": ""}), \
                mock.patch.object(whatsapp, "_request", fake):
            self.assertTrue(whatsapp.publish_summary(ITEMS, None, NOW, log=lambda *_: None))
        self.assertEqual(sent[0][0], "/messages/text")
        self.assertIn(b"120363000000000001@newsletter", sent[0][1])

    def test_prueba_nunca_va_al_canal(self):
        env = {"WHAPI_TOKEN": "x", "WHATSAPP_CHANNEL_ID": "1@newsletter", "WHATSAPP_TEST_TO": ""}
        with mock.patch.dict(os.environ, env), mock.patch.object(whatsapp, "_request") as rq:
            self.assertFalse(whatsapp.publish_summary(ITEMS, None, NOW, test=True, log=lambda *_: None))
            rq.assert_not_called()

    def test_prueba_va_a_tu_numero(self):
        seen = []
        env = {"WHAPI_TOKEN": "x", "WHATSAPP_CHANNEL_ID": "1@newsletter", "WHATSAPP_TEST_TO": "34600111222"}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(whatsapp, "_request", lambda m, p, t, b=None, c="", **k: seen.append(b) or {}):
            self.assertTrue(whatsapp.publish_summary(ITEMS, None, NOW, test=True, log=lambda *_: None))
        self.assertIn(b"34600111222", seen[0])
        self.assertNotIn(b"@newsletter", seen[0])

    def test_fallo_no_rompe(self):
        def boom(*a, **k):
            raise whatsapp.WhapiError("HTTP 402")
        with mock.patch.dict(os.environ, {"WHAPI_TOKEN": "x", "WHATSAPP_CHANNEL_ID": "1@newsletter"}), \
                mock.patch.object(whatsapp, "_request", boom):
            self.assertFalse(whatsapp.publish_summary(ITEMS, None, NOW, log=lambda *_: None))

    def test_imagen_multipart(self):
        seen = {}
        def fake(method, path, token, body=None, ctype="", **kw):
            seen.update(path=path, ctype=ctype, body=body)
            return {}
        img = Path(self.id() + ".jpg")
        img.write_bytes(b"\xff\xd8fake")
        try:
            with mock.patch.object(whatsapp, "_request", fake):
                whatsapp.send_image("x", "1@newsletter", img, "hola")
        finally:
            img.unlink()
        self.assertEqual(seen["path"], "/messages/image")
        self.assertIn("multipart/form-data", seen["ctype"])
        self.assertIn(b'name="media"', seen["body"])


CAPTION = """🔥 <b>CHOLLAZO EN AMAZON</b>

<b>Echo Dot (5.ª generación) &amp; Tapo</b>

💶 PRECIO: <b>44,99€</b>
❌ (Antes: <s>108,99€</s>)

🛒 <a href="https://www.amazon.es/dp/B0DXQ67BW4?tag=cazachollos0c-21">amazon.es/dp/B0DXQ67BW4</a>

Visto en @cazachollos_com #Publicidad #Chollazo"""
RULES = {"whatsapp_daily_max": 2, "whatsapp_min_gap_minutes": 35, "whatsapp_monthly_budget": 950}


class TestPostsSueltos(unittest.TestCase):
    def test_copy_de_telegram_a_whatsapp(self):
        text = whatsapp.html_to_whatsapp(CAPTION)
        self.assertIn("*CHOLLAZO EN AMAZON*", text)
        self.assertIn("*Echo Dot (5.ª generación) & Tapo*", text)
        self.assertIn("~108,99€~", text)
        self.assertIn("🛒 https://www.amazon.es/dp/B0DXQ67BW4?tag=cazachollos0c-21", text)
        self.assertIn("👉 https://t.me/cazachollos_com\n#Publicidad #Chollazo", text)
        self.assertNotIn("<", text)

    def test_cupo_separacion_y_maximo_diario(self):
        state = {}
        t0 = datetime(2026, 11, 17, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
        self.assertEqual(whatsapp.deal_quota_reason(state, t0, RULES), "")
        whatsapp.note_deal(state, t0)
        later = t0.replace(minute=20)
        self.assertIn("hace poco", whatsapp.deal_quota_reason(state, later, RULES))
        self.assertEqual(whatsapp.deal_quota_reason(state, later, RULES, manual=True), "")  # los manuales no esperan
        whatsapp.note_deal(state, later)
        self.assertIn("los chollos de hoy", whatsapp.deal_quota_reason(state, t0.replace(hour=20), RULES, manual=True))

    def test_guarda_hueco_para_los_resumenes(self):
        now = datetime(2026, 11, 20, 12, 0, tzinfo=ZoneInfo("Europe/Madrid"))  # quedan 11 días: 33 de reserva
        state = {"whatsapp": {"requests": {"2026-11-19": 950 - 33}}}
        self.assertIn("cupo del mes", whatsapp.deal_quota_reason(state, now, RULES))
        state["whatsapp"]["requests"]["2026-11-19"] = 950 - 34
        self.assertEqual(whatsapp.deal_quota_reason(state, now, RULES), "")
        state["whatsapp"]["requests"]["2026-10-30"] = 999  # el mes pasado no cuenta
        self.assertEqual(whatsapp.deal_quota_reason(state, now, RULES), "")

    def test_post_con_foto_y_canal_guardado(self):
        calls, bodies = [], []
        def fake(method, path, token, body=None, ctype="", **kw):
            calls.append(path)
            bodies.append(body or b"")
            if path.startswith("/newsletters/link/"):
                return {"id": "120363000000000001@newsletter", "role": "admin"}
            return {"sent": True}
        state, now = {}, datetime(2026, 11, 17, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
        with mock.patch.dict(os.environ, {"WHAPI_TOKEN": "x", "WHATSAPP_CHANNEL_ID": ""}), \
                mock.patch.object(whatsapp, "_request", fake):
            self.assertTrue(whatsapp.publish_deal(CAPTION, "https://m.media-amazon.com/x.jpg", state, now, RULES))
            self.assertTrue(whatsapp.publish_deal(CAPTION, "https://m.media-amazon.com/y.jpg", state,
                                                  now.replace(hour=11), RULES))
        self.assertEqual(calls.count("/messages/image"), 2)
        self.assertNotIn("con IA".encode(), bodies[-1])
        self.assertEqual(sum(c.startswith("/newsletters/link/") for c in calls), 1)  # el canal se busca una vez
        self.assertEqual(whatsapp.used_this_month(state, now), 3)
        self.assertEqual(state["whatsapp"]["deals"]["2026-11-17"], 2)

    def test_merge_no_descuenta_de_menos(self):
        a = {"requests": {"2026-11-17": 10, "2026-11-16": 3}, "deals": {"2026-11-17": 5}, "last_deal": 100}
        b = {"requests": {"2026-11-17": 12}, "deals": {"2026-11-17": 4}, "last_deal": 200, "channel": "1@newsletter"}
        m = whatsapp.merge(a, b)
        self.assertEqual(m["requests"], {"2026-11-17": 12, "2026-11-16": 3})
        self.assertEqual(m["deals"]["2026-11-17"], 5)
        self.assertEqual(m["last_deal"], 200)
        self.assertEqual(m["channel"], "1@newsletter")


class TestBotonWhatsApp(unittest.TestCase):
    def test_boton_debajo_de_comprar(self):
        import json
        import canal_nube
        rules = canal_nube.rules_from(json.loads(Path("config.json").read_text("utf-8")))
        markup = canal_nube.buttons("https://www.amazon.es/dp/B0TEST1234?tag=cazachollos0c-21", "success",
                                    canal_nube.whatsapp_button(rules))
        rows = markup["inline_keyboard"]
        self.assertEqual(rows[0][0]["text"], "🛒 Comprar en Amazon")
        self.assertEqual(rows[1][0]["url"], "https://whatsapp.com/channel/0029VbE063mEwEk5M7m9Xe17")
        self.assertIn("WhatsApp", rows[1][0]["text"])
        self.assertEqual([b["text"] for b in rows[2]], ["👍", "👎"])  # votos al final (26/11/2026)

    def test_sin_config_no_hay_boton(self):
        import canal_nube
        self.assertIsNone(canal_nube.whatsapp_button({}))
        self.assertEqual(len(canal_nube.buttons("https://x", "success", None, None)["inline_keyboard"]), 1)


if __name__ == "__main__":
    unittest.main()
