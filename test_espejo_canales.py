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

    def send_photo(self, chat, card, caption, extra=None):
        self.sent.append((chat, caption))
        self.markups = getattr(self, "markups", []) + [(extra or {}).get("reply_markup")]
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
        self.assertIn("\nINSTA360 ACE PRO\n", copy)
        self.assertIn("♻️ Segunda mano · Como nuevo", copy)
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
        self.assertIn("💸 27,92€ 105,62€", copy)
        self.assertIn("💰 Te ahorras 77,70€", copy)
        self.assertIn("🏷️ Vendido por Kalado", copy)
        self.assertIn("🛒 amazon.es/dp/B0D2RYP973", copy)
        self.assertNotIn("tag=", copy)
        copy2 = ec.hacer_copy("X", {"price": 60.0, "reference": 100.0}, {"vendedor": "Vendido por Amazon"},
                              "general", "L")
        self.assertTrue(copy2.startswith("💎 #Chollo · -40%"))
        self.assertNotIn("🏷️", copy2)
        ropa = ec.hacer_copy("Vaqueros", {"price": 15.9, "reference": 89.95}, {"talla": "38W / 36L"}, "ropa", "L")
        self.assertIn("👕 Talla 38W / 36L", ropa)
        largo = "Neutrogena T/Gel Champú Anticaspa para Cabello Graso 250 ml 2 uds | Con extracto de alquitrán"
        self.assertEqual(ec.titulo_corto(largo), "Neutrogena T/Gel Champú Anticaspa para Cabello Graso 250 ml 2 uds")

    def test_vuelta_publica_solo_lo_nuevo_con_tu_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            with mock.patch.object(ec, "STATE", tmp / "espejo.json"), \
                 mock.patch("premium_manual.STATE", tmp / "manual.json"), \
                 mock.patch("premium_manual.OUT", tmp / "out"), \
                 mock.patch("premium_manual.photo_for", lambda spec, name: tmp / "foto.jpg"), \
                 mock.patch("tarjeta_premium.crear_tarjeta", lambda *a, **k: tmp / "card.jpg"), \
                 mock.patch.object(ec, "CANALES", {"erroresychollos": "general"}), \
                 mock.patch.object(ec, "reventa", lambda *a, **k: None), \
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
                    self.assertRegex(caption, r'🛒 <a href="https://www\.amazon\.es/dp/\w{10}\?tag=cazachollos0c-21">amazon\.es/dp/\w{10}</a>')
                    botones = tg.markups[0]["inline_keyboard"]
                    self.assertEqual(botones[0][0]["text"], "🛒 Comprar en Amazon")
                    self.assertIn("tag=cazachollos0c-21", botones[0][0]["url"])
                    self.assertIn("whatsapp.com/channel/", botones[1][0]["url"])
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

    def test_precios_de_la_tarjeta_de_kevin(self):
        """23/11/2026: los precios del post son los de su tarjeta (no los de la API) y el tachado es «normal»."""
        foto = ('<a class="tgme_widget_message_photo_wrap 5 " href="https://t.me/erroresychollos/101" '
                'style="width:800px;background-image:url(\'https://cdn4.telesco.pe/file/abc.jpg\')"></a>')
        page = PAGE.replace('<div class="tgme_widget_message_text js-message_text" dir="auto">⚡', foto
                            + '<div class="tgme_widget_message_text js-message_text" dir="auto">⚡', 1)
        posts = ec.parse_canal(page)
        self.assertEqual(posts[0]["foto"], "https://cdn4.telesco.pe/file/abc.jpg")
        self.assertIsNone(posts[1]["foto"])
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            tarjetas = []
            with mock.patch.object(ec, "STATE", tmp / "espejo.json"), \
                 mock.patch("premium_manual.STATE", tmp / "manual.json"), \
                 mock.patch("premium_manual.OUT", tmp / "out"), \
                 mock.patch("premium_manual.photo_for", lambda spec, name: tmp / "foto.jpg"), \
                 mock.patch("tarjeta_premium.crear_tarjeta", lambda *a, **k: tarjetas.append((a, k)) or tmp / "c.jpg"), \
                 mock.patch.object(ec, "reventa", lambda *a, **k: None), \
                 mock.patch("precios_kevin.desde_post", lambda post: {"current": 55.0, "reference": 119.81,
                                                                      "ahorro": 64.81, "pct": 54}):
                tg = FakeTG()
                api = FakeAPI({"B0HHMVKJ2C": {"price": 55.0, "saving_basis": None, "in_stock": True,
                                              "title": "MSI", "image": "http://img/a.jpg"}})
                ec.procesar(posts[0], "general", api, tg, {"ultimo": {}, "publicados": []}, False, False)
                caption = tg.sent[0][1]
                self.assertIn("💎 #Chollo · -54%", caption)
                self.assertIn("💸 55,00€ <s>119,81€</s>", caption)
                self.assertIn("💰 Te ahorras 64,81€", caption)
                self.assertEqual(tarjetas[0][0][1:3], (119.81, 55.0))
                self.assertEqual(tarjetas[0][1]["ref_label"], "normal")

    def test_reventa_y_roi_en_el_copy(self):
        """23/11/2026: en erroresychollos y erroresycholloswarehouse el copy lleva reventa y ROI."""
        venta = {"precio": 77.0, "beneficio": 37.0, "roi": 93, "fuente": "x"}
        copy = ec.hacer_copy("MSI MPG VELOX", {"price": 40.0, "reference": 120.0}, {}, "general", "L", venta)
        self.assertIn("♻️ En segunda mano ronda los 77€\n📈 +37€ por unidad · ROI +93%", copy)
        wh = ec.hacer_copy("Lefant M3", {"price": 40.0, "reference": 120.0}, {}, "warehouse", "L", venta)
        self.assertIn("💶 Se revende por unos 77€", wh)
        par = ec.hacer_copy("Nike Zapatillas Air Max", {"price": 40.0, "reference": 120.0}, {}, "general", "L", venta)
        self.assertIn("por par", par)
        # Sin anuncios suficientes: precio normal × factor de la categoría (0,6 por defecto)
        with mock.patch("resale_market.lookup", side_effect=RuntimeError("Wallapop 403")):
            v = ec.reventa("MSI MPG VELOX 300R", "", 55.0, 119.81)
        self.assertEqual(v["precio"], 71.89)
        self.assertEqual(v["roi"], 31)
        with mock.patch("resale_market.lookup", return_value={"price": 50.0, "count": 6, "source_label": "WALLAPOP"}):
            self.assertIsNone(ec.reventa("X Y Z", "", 55.0, 119.81))  # sin beneficio no se pone

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


class LectorCuentaTest(unittest.TestCase):
    """23/11/2026: ropa y básicos no tienen vista web; se leen con la cuenta de Telegram."""

    def test_sin_vista_web_usa_la_cuenta(self):
        class Lector:
            def leer(self, canal, limite=20):
                return [{"canal": canal, "id": 50, "texto": "SEGUNDA MANO",
                         "enlaces": ["https://www.amazon.es/dp/B0HHMVKJ2C?tag=kevincrestt-21"]}]
        state = {"ultimo": {}, "publicados": []}
        with mock.patch.object(ec, "leer_canal", return_value=[]):
            posts = ec.leer_posts("erroresychollosropa", Lector(), state)
            self.assertEqual(posts[0]["id"], 50)
            self.assertIn("erroresychollosropa", state["por_cuenta"])
        with mock.patch.object(ec, "leer_canal", side_effect=AssertionError("no debe ir a la web")):
            self.assertEqual(ec.leer_posts("erroresychollosropa", Lector(), state)[0]["id"], 50)

    def test_sin_cuenta_sigue_con_la_web(self):
        with mock.patch.object(ec, "leer_canal", return_value=[]):
            self.assertEqual(ec.leer_posts("erroresychollosropa", None, {}), [])
        with mock.patch.dict(os.environ, {"TG_API_ID": "", "TG_API_HASH": "", "TG_SESSION": ""}):
            self.assertIsNone(ec.LectorCuenta.from_env())

    def test_enlaces_de_botones_y_texto(self):
        from types import SimpleNamespace as NS
        msg = NS(id=7, message="Chollo", reply_markup=NS(rows=[NS(buttons=[NS(url="https://amzn.eu/d/abc"), NS(type=NS(url="https://amzn.eu/d/xyz"))])]),
                 get_entities_text=lambda: [(NS(url="https://www.amazon.es/dp/B0AAAAAAAA"), "aquí")])
        lector = ec.LectorCuenta.__new__(ec.LectorCuenta)
        lector.client = NS(get_messages=lambda canal, limit: [msg])
        post = lector.leer("erroresychollosbasicos")[0]
        self.assertEqual(post["enlaces"], ["https://www.amazon.es/dp/B0AAAAAAAA", "https://amzn.eu/d/abc", "https://amzn.eu/d/xyz"])
        self.assertTrue(ec.enlace_amazon(post))


class BotonesPremiumTest(unittest.TestCase):
    def test_agotado_quita_amazon_y_deja_whatsapp(self):
        import botones_premium as bp
        t = bp.teclado("https://www.amazon.es/dp/B0AAAAAAAA?tag=cazachollos0c-21")
        self.assertEqual(len(t["inline_keyboard"]), 2)
        fin = bp.sin_amazon(t)
        self.assertEqual(len(fin["inline_keyboard"]), 1)
        self.assertIn("whatsapp.com", fin["inline_keyboard"][0][0]["url"])
        self.assertEqual(bp.teclado_terminado(), fin)


class SeccionesTest(unittest.TestCase):
    def test_seccion_debajo_de_la_cabecera_y_titulo_en_negrita(self):
        import premium_manual as pm
        copy = ec.hacer_copy("Lefant M3 MAX Robot Aspirador", {"price": 214.58, "reference": 899.99},
                             {"estado": "Como nuevo"}, "warehouse", "https://www.amazon.es/dp/B0FXWLDNPQ?tag=cazachollos0c-21")
        self.assertTrue(copy.startswith("❗️ #ErrorDePrecio · -76%\n#Reacondicionado\n"))
        html = pm.caption_html(copy)
        self.assertIn("<b>Lefant M3 MAX Robot Aspirador</b>", html)
        self.assertNotIn("<b>#Reacondicionado</b>", html)

    def test_secciones(self):
        import secciones as s
        self.assertEqual(s.seccion("Hero Solo Bolsitas Yogur Desde 6 Meses", "basicos"), "#Bebé")
        self.assertEqual(s.seccion("Neutrogena T/Gel Champú Anticaspa", "basicos"), "#Belleza")
        self.assertEqual(s.seccion("Vaqueros 501", "ropa"), "#Moda")
        self.assertEqual(s.seccion("Papel de cocina Renova", "basicos"), "#DelDíaADía")
        self.assertIsNone(s.seccion("Cosa rara", "general"))


class TestErroresRutaYChollos(unittest.TestCase):
    """25/11/2026: ErroresRutaYChollos lleva los precios en el texto y sale con el formato de erroresychollos."""

    PLATOS = ("🔥 CHOLLAZO · -75% SOBRE PVP\n"
              "Juego de 6 Platos Grandes de Gres Ibiza - Elegantes Platos para Comida\n"
              "💶 19,95 € PVP 79,95 €\n🚚 Envío gratis\n"
              "🏪 Amazon España · Natureflow, enviado por Amazon · 94 % positivas, 89 valoraciones\n"
              "📦 Quedaba 1 unidad al verificar")
    MSI = ("🔥 CHOLLAZO · -69%\nMSI MAG 850GL PCIE 5 Blanca Fuente de alimentación 850W\n"
           "💶 43,50 € 141,58 €\n🚚 Envío gratis\n📉 Precio habitual: 141,58 € (mediana de 30 días)\n🏪 Amazon España")
    OBIRE = ("🔥 CHOLLAZO\nObire | Própolis Plus 400 mg | 90 Cápsulas | Pack 3 Unidades\n💶 9,44 €\n🚚 Envío gratis")

    def test_precios_del_texto(self):
        import precios_kevin as pk
        self.assertEqual(pk.desde_texto(self.PLATOS),
                         {"current": 19.95, "reference": 79.95, "pct": 75, "ref_label": "recomendado"})
        self.assertEqual(pk.desde_texto(self.MSI),
                         {"current": 43.5, "reference": 141.58, "pct": 69, "ref_label": "normal"})
        self.assertEqual(pk.desde_texto(self.OBIRE)["reference"], None)
        self.assertIsNone(pk.desde_texto("🔥 CHOLLAZO · -20%\nX\n💶 43,50 € 141,58 €"))  # el -% no cuadra
        self.assertIsNone(pk.desde_texto("sin precio"))

    def test_nombre_y_etiqueta(self):
        d = ec.datos_post(self.PLATOS)
        self.assertTrue(d["etiqueta"].startswith("CHOLLAZO"))
        self.assertEqual(d["nombre"], "Juego de 6 Platos Grandes de Gres Ibiza - Elegantes Platos para Comida")
        self.assertNotIn("€", ec.datos_post("🔥 CHOLLAZO\n💶 19,95 €\nCosa").get("nombre", ""))

    def _publicar(self, texto, api_item):
        post = {"canal": "ErroresRutaYChollos", "id": 300, "texto": texto,
                "enlaces": ["https://www.amazon.es/dp/B0CHS6D4BD?tag=otro-21"]}
        api = mock.Mock()
        api.get_item.return_value = api_item
        tg = mock.Mock()
        tg.send_photo.return_value = {"message_id": 1}
        tarjetas = []
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(ec, "STATE", Path(tmp) / "e.json"), \
             mock.patch("premium_manual.STATE", Path(tmp) / "m.json", create=True), \
             mock.patch("premium_manual.load_state", return_value={"posts": []}), \
             mock.patch("premium_manual.save_state"), \
             mock.patch("premium_manual.photo_for", return_value="foto"), \
             mock.patch("tarjeta_premium.crear_tarjeta", side_effect=lambda *a, **k: tarjetas.append((a, k)) or "t"), \
             mock.patch.object(ec, "subir_memoria"), \
             mock.patch.object(ec, "reventa", return_value={"precio": 45.0, "beneficio": 25.05, "roi": 126,
                                                             "fuente": "x"}) as rev:
            ec.procesar(post, "general", api, tg, {"publicados": []}, False, False)
        return tg.send_photo.call_args[0][2], tarjetas, rev

    def test_publica_con_tachado_ahorro_y_roi(self):
        item = {"price": 19.95, "saving_basis": None, "in_stock": True, "title": "Platos Ibiza", "image": "i"}
        caption, tarjetas, rev = self._publicar(self.PLATOS, item)
        self.assertIn("💸 19,95€ <s>79,95€</s>", caption)
        self.assertIn("💰 Te ahorras 60,00€", caption)
        self.assertIn("📈 +25€ por unidad · ROI +126%", caption)
        self.assertTrue(rev.called)
        self.assertEqual(tarjetas[0][0][1:3], (79.95, 19.95))

    def test_sin_tachado_usa_el_pvp_de_la_ficha(self):
        item = {"price": 9.44, "saving_basis": 30.30, "in_stock": True, "title": "Obire", "image": "i"}
        caption, tarjetas, _ = self._publicar(self.OBIRE, item)
        self.assertIn("💸 9,44€ <s>30,30€</s>", caption)
        self.assertEqual(tarjetas[0][1]["ref_label"], "recomendado")
