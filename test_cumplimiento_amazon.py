#!/usr/bin/env python3
"""Normas de Amazon Afiliados en el canal normal: lo que nunca debe volver a salir."""

import unittest
from datetime import datetime, timezone

import canal_nube as cn
import scanner
from test_canal_nube import LEFANT, NOW, RULES, item_for

URL = "https://www.amazon.es/dp/B0G7YP6MXV?tag=cazadores_errores-21"


def deal_with_rating() -> dict:
    _, deal = cn.evaluate(item_for("R0ZG4Bv"), scanner.parse_detail(LEFANT), RULES, NOW)
    deal["asin"] = "B0G7YP6MXV"
    deal["rating"], deal["reviews"] = 4.6, 812
    return deal


class TextoDelPost(unittest.TestCase):
    def test_sin_estrellas_ni_opiniones(self):
        text = cn.build_caption(deal_with_rating(), URL, RULES)
        self.assertNotIn("⭐", text)
        self.assertNotIn("opiniones", text)

    def test_hora_del_precio_y_aviso(self):
        text = cn.build_caption(deal_with_rating(), URL, RULES)
        self.assertIn("🕒 Precio a las 16:52 · puede cambiar", text)

    def test_publicidad_primera_en_la_linea_de_hashtags(self):
        text = cn.build_caption(deal_with_rating(), URL, RULES)
        last = text.rstrip().split("\n")[-1]
        self.assertTrue(last.startswith("#Publicidad #"), last)

    def test_hashtag_segun_descuento(self):
        deal = deal_with_rating()
        for pct, tag in ((80, "#ErrorDePrecio"), (60, "#Chollazo"), (30, "#Chollo")):
            deal["discount"] = pct
            self.assertIn(tag, cn.build_caption(deal, URL, RULES))
        deal["historical_low"] = True
        text = cn.build_caption(deal, URL, RULES)
        self.assertNotIn("#MinimoHistorico", text)
        self.assertNotIn("más bajo de su historia", text)

    def test_sin_comparativas_de_historial(self):
        deal = deal_with_rating()
        deal["historical_low"] = True
        for style in ("corto", "completo"):
            text = cn.build_caption(deal, URL, dict(RULES, caption_style=style))
            self.assertNotIn("30 días", text)
            self.assertNotIn("90 días", text)
            self.assertNotIn("historia", text)
            self.assertNotIn("Historico", text)

    def test_enlace_directo_y_visible(self):
        text = cn.build_caption(deal_with_rating(), URL, RULES)
        self.assertIn("https://www.amazon.es/dp/B0G7YP6MXV?tag=cazadores_errores-21", text)

    def test_cabe_en_un_pie_de_foto(self):
        self.assertLessEqual(len(cn.build_caption(deal_with_rating(), URL, RULES)), 1024)


class Tarjeta(unittest.TestCase):
    def test_sin_foto_si_se_desactiva(self):
        deal = deal_with_rating()
        deal["image"] = "https://m.media-amazon.com/images/I/no-se-descarga.jpg"
        called = []
        import photos
        original = photos.fetch_best
        photos.fetch_best = lambda url: called.append(url)
        try:
            card = cn.make_card(deal, dict(RULES, amazon_photo=False))
        finally:
            photos.fetch_best = original
        self.assertTrue(card.exists())
        self.assertEqual(called, [], "la tarjeta no debe descargar la foto de Amazon")


class PostTerminado(unittest.TestCase):
    def test_quita_enlace_y_estrellas(self):
        old = "💥 <b>CHOLLO</b>\n\n⭐ 4,4 (406 opiniones)\n\n🕒 Precio visto\n\n🔗 <b><a href=\"x\">Ver en Amazon</a></b>"
        text = cn.ended_caption(old)
        self.assertNotIn("Ver en Amazon", text)
        self.assertNotIn("⭐", text)
        self.assertTrue(text.endswith("🕒 Precio visto"))

    def test_quita_el_boton(self):
        class TG:
            def __init__(self):
                self.calls = []

            def call(self, method, params):
                self.calls.append((method, params))
                return {}

        tg = TG()
        state = {"posts": [{"t": NOW.timestamp(), "message_id": 7, "jl_id": "R0ZG4Bv", "asin": "B0G7YP6MXV",
                            "price": 1.0, "chat": "@c", "url": URL, "caption": "💥 X\n\n🔗 enlace"}]}
        cn.track_posts(tg, state, NOW, RULES, lambda *_: None, False, lambda url: LEFANT)
        self.assertEqual(len(tg.calls), 1)
        method, params = tg.calls[0]
        self.assertEqual(method, "editMessageCaption")
        self.assertNotIn("reply_markup", params)
        self.assertNotIn("🔗", params["caption"])


class Resumen(unittest.TestCase):
    def test_resumen_con_aviso(self):
        items = [{"title": "Producto", "price": 10.0, "reference": 20.0, "discount": 50, "url": URL}]
        text = cn.build_summary(items, datetime(2026, 11, 2, 22, 59, tzinfo=timezone.utc))
        self.assertIn("pueden cambiar", text)
        self.assertEqual(text.rstrip().split("\n")[-1], "#Publicidad")
        self.assertNotIn("⭐", text)


if __name__ == "__main__":
    unittest.main()


class ProductosExcluidosUE(unittest.TestCase):
    def test_excluidos(self):
        for title in ("Mahou Cinco Estrellas Cerveza Lata 24 x 33 cl", "Vino tinto Ramón Bilbao Crianza",
                      "Ginebra Bombay Sapphire 70 cl", "Nutribén Innova 2 Leche de continuación 800 g",
                      "Vaper desechable 600 caladas", "Papel de liar OCB Premium", "Whisky Johnnie Walker Black Label"):
            self.assertTrue(cn.excluido_amazon(title), title)
            self.assertTrue(cn.interest(title, RULES)["blocked"], title)

    def test_no_excluidos(self):
        for title in ("Copas de vino de cristal, set de 6", "Sacacorchos eléctrico recargable",
                      "Nevera para cervezas 70 latas", "Monster Energy Ultra 24 latas", "Pañales Dodot Sensitive talla 4",
                      "Aceite de oliva virgen extra 5 L", "Vinagre de vino de Jerez", "Anís estrellado 100 g"):
            self.assertFalse(cn.excluido_amazon(title), title)

    def test_manual_rechaza_excluidos(self):
        with self.assertRaises(ValueError):
            cn.manual_deal({"asin": "B000000000", "title": "Cerveza Estrella Galicia pack 12", "price": 9.9,
                            "reference": 14.9}, RULES)
