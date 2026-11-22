"""Pruebas del vigía de canales (espejo_canales.py) sin red: HTML de t.me/s, API y Telegram simulados."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import espejo_canales as ec

PAGE = """
<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message text_not_supported_wrap js-widget_message" data-post="erroresychollos/101" data-view="x">
<div class="tgme_widget_message_text js-message_text" dir="auto">⚡ <b>SUPEROFERTA</b><br/><br/>🍳 <b>Cecotec Freidora de Aire</b><br/>🅰️ Vendido por Amazon<br/><br/><i>Precio en <a href="http://Amazon.es/">Amazon.es</a> a las 19:42 del 20/11 (hora de Madrid). Puede cambiar.</i></div>
<div class="tgme_widget_message_inline_keyboard"><div class="tgme_widget_message_inline_row"><a class="tgme_widget_message_inline_button url_button" href="https://www.amazon.es/dp/B0HHMVKJ2C?tag=kevincrestt-21&amp;psc=1" target="_blank"><div class="tgme_widget_message_inline_button_text">Comprar en Amazon</div></a></div></div>
<a class="tgme_widget_message_date" href="https://t.me/erroresychollos/101"><time datetime="2026-11-20T18:42:00+00:00" class="time">18:42</time></a></div></div>
<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message js-widget_message" data-post="erroresychollos/102" data-view="x">
<div class="tgme_widget_message_text js-message_text" dir="auto">🔥 <b>PRECIAZO</b><br/><br/>📷 <b>GNCC Cámara Vigilancia Solar 2K</b><br/>🏪 Vendido por Kalado y enviado por Amazon</div>
<div class="tgme_widget_message_inline_keyboard"><a class="tgme_widget_message_inline_button url_button" href="https://www.amazon.es/dp/B0G4M3HMGJ?tag=kevincrestt-21"><div>Comprar en Amazon</div></a></div>
</div></div>
"""


class FakeTG:
    def __init__(self):
        self.sent, self.msgs = [], []

    def send_photo(self, chat, card, caption):
        self.sent.append((chat, caption))
        return {"message_id": 500 + len(self.sent)}

    def call(self, method, params):
        self.msgs.append(params["text"])
        return {}


class FakeAPI:
    def __init__(self, items):
        self.items = items

    def get_item(self, asin):
        return self.items.get(asin)


class Espejo(unittest.TestCase):
    def test_parse(self):
        posts = ec.parse_canal(PAGE)
        self.assertEqual([p["id"] for p in posts], [101, 102])
        self.assertIn("kevincrestt-21", ec.enlace_amazon(posts[0]))
        d = ec.datos_post(posts[1]["texto"])
        self.assertEqual(d["etiqueta"], "PRECIAZO")
        self.assertEqual(d["nombre"], "GNCC Cámara Vigilancia Solar 2K")
        self.assertEqual(d["vendedor"], "Vendido por Kalado y enviado por Amazon")

    def test_segunda_mano(self):
        texto = ("🆔 SEGUNDA MANO\n\n🛍️ INSTA360 ACE PRO\n\n📦 Estado: Como nuevo\n⚠️ El embalaje llegará dañado\n"
                 "🅰️ Vendido por Amazon Segunda mano\n\nPrecio en Amazon.es a las 23:06 del 21/11 (hora de Madrid).")
        d = ec.datos_post(texto)
        self.assertEqual(d["nombre"], "INSTA360 ACE PRO")
        copy = ec.hacer_copy(d["nombre"], {"price": 191.2, "reference": None}, d, "warehouse",
                             "https://www.amazon.es/dp/B0CNGQYF5Z?tag=cazachollos0c-21")
        self.assertIn("INSTA360 ACE PRO · segunda mano", copy)
        self.assertIn("estado como nuevo", copy)
        self.assertIn("⚠️ El embalaje llegará dañado", copy)
        self.assertNotIn("🏷️", copy)

        class API:  # sin stock nuevo: tira de la oferta usada
            def get_item(self, asin, condition=None):
                return {"price": 191.2, "in_stock": True} if condition == "Used" else {"price": None, "in_stock": False}
        self.assertEqual(ec.segunda_mano(API(), "B0CNGQYF5Z")["price"], 191.2)

        class API2:  # hay stock nuevo (899,99) y usado (214,58): sale SIEMPRE el usado, con el nuevo de referencia
            def get_item(self, asin, condition=None):
                if condition == "Used":
                    return {"price": 214.58, "in_stock": True, "condition": "Used"}
                return {"price": 899.99, "in_stock": True, "title": "Lefant M3 MAX", "image": "http://img/l.jpg"}
        live = ec.segunda_mano(API2(), "B0FXWLDNPQ")
        self.assertEqual(live["price"], 214.58)
        self.assertEqual(live["saving_basis"], 899.99)
        self.assertEqual(live["ref_label"], "nuevo")
        self.assertEqual(live["image"], "http://img/l.jpg")

        class API3:  # sin oferta usada: no se publica con el precio nuevo
            def get_item(self, asin, condition=None):
                return {"price": None, "in_stock": False} if condition == "Used" else {"price": 899.99, "in_stock": True}
        self.assertFalse(ec.segunda_mano(API3(), "X")["in_stock"])

    def test_copy(self):
        live = {"price": 27.92, "reference": 105.62}
        copy = ec.hacer_copy("Bolso X", live, {"vendedor": "Vendido por Kalado y enviado por Amazon"}, "general",
                             "https://www.amazon.es/dp/B0D2RYP973?tag=cazachollos0c-21")
        self.assertTrue(copy.startswith("❗️ #ErrorDePrecio · -74%"))
        self.assertIn("💸 Lo pillas a 27,92€ 105,62€", copy)
        self.assertIn("🏷️ Vendido por Kalado", copy)
        self.assertIn("🌟amazon.es/dp/B0D2RYP973", copy)
        self.assertNotIn("tag=", copy)
        copy2 = ec.hacer_copy("X", {"price": 60.0, "reference": 100.0}, {"vendedor": "Vendido por Amazon"},
                              "general", "L")
        self.assertTrue(copy2.startswith("💎 #Chollo · -40%"))
        self.assertNotIn("🏷️", copy2)
        ropa = ec.hacer_copy("Vaqueros", {"price": 15.9, "reference": 89.95}, {"talla": "38W / 36L"}, "ropa", "L")
        self.assertIn("en talla 38W / 36L 👀", ropa)

    def test_vuelta_publica_solo_lo_nuevo_con_tu_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with mock.patch.object(ec, "STATE", tmp / "espejo.json"), \
                 mock.patch("premium_manual.STATE", tmp / "manual.json"), \
                 mock.patch("premium_manual.OUT", tmp / "out"), \
                 mock.patch("premium_manual.photo_for", lambda spec, name: tmp / "foto.jpg"), \
                 mock.patch("tarjeta_premium.crear_tarjeta", lambda *a, **k: tmp / "card.jpg"), \
                 mock.patch.object(ec, "CANALES", {"erroresychollos": "general"}), \
                 mock.patch.dict(os.environ, {"ADMIN_CHAT_ID": "123"}):
                tg = FakeTG()
                api = FakeAPI({
                    "B0HHMVKJ2C": {"price": 39.99, "saving_basis": 89.99, "in_stock": True,
                                   "title": "Cecotec Freidora", "image": "http://img/a.jpg"},
                    "B0G4M3HMGJ": {"price": 20.0, "saving_basis": None, "in_stock": False,
                                   "title": "GNCC", "image": "http://img/b.jpg"},
                })
                state = {"ultimo": {"erroresychollos": 100}, "publicados": []}
                with mock.patch.object(ec, "leer_canal", lambda c: ec.parse_canal(PAGE)):
                    ec.vuelta(api, tg, state, False, False)
                    self.assertEqual(len(tg.sent), 1)  # el agotado no sale
                    chat, caption = tg.sent[0]
                    self.assertEqual(chat, ec.PREMIUM)
                    self.assertIn("tag=cazachollos0c-21", caption)
                    self.assertRegex(caption, r'🌟<a href="https://www\.amazon\.es/dp/\w{10}\?tag=cazachollos0c-21">amazon\.es/dp/\w{10}</a>')
                    self.assertNotIn("kevincrestt", caption)
                    self.assertIn("<b>Cecotec Freidora de Aire</b>", caption)
                    self.assertIn("<s>89,99€</s>", caption)
                    self.assertTrue(any("agotado" in m for m in tg.msgs))
                    self.assertEqual(state["ultimo"]["erroresychollos"], 102)
                    manual = json.loads((tmp / "manual.json").read_text())
                    self.assertEqual(manual["posts"][0]["asin"], "B0HHMVKJ2C")
                    # Otra vuelta: nada nuevo, nada repetido
                    ec.vuelta(api, tg, state, False, False)
                    self.assertEqual(len(tg.sent), 1)

    def test_primera_vez_no_republica_lo_antiguo(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ec, "STATE", Path(tmp) / "e.json"), \
             mock.patch.object(ec, "CANALES", {"erroresychollos": "general"}), \
             mock.patch.object(ec, "leer_canal", lambda c: ec.parse_canal(PAGE)):
            tg, state = FakeTG(), {"ultimo": {}, "publicados": []}
            ec.vuelta(FakeAPI({}), tg, state, False, False)
            self.assertEqual(tg.sent, [])
            self.assertEqual(state["ultimo"]["erroresychollos"], 102)


if __name__ == "__main__":
    unittest.main()
