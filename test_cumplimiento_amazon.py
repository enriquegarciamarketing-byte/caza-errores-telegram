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

    def test_hora_con_zona_y_exencion(self):
        text = cn.build_caption(deal_with_rating(), URL, RULES)
        self.assertIn("(hora peninsular)", text)
        self.assertIn("al comprar se aplica el que marque Amazon.es", text)

    def test_aviso_de_publicidad_al_final(self):
        text = cn.build_caption(deal_with_rating(), URL, RULES)
        self.assertTrue(text.rstrip().endswith(cn.PUBLI))
        self.assertIn("#publi", text)

    def test_enlace_directo_y_visible(self):
        text = cn.build_caption(deal_with_rating(), URL, RULES)
        self.assertIn("https://www.amazon.es/dp/B0G7YP6MXV?tag=cazadores_errores-21", text)

    def test_cabe_en_un_pie_de_foto(self):
        self.assertLessEqual(len(cn.build_caption(deal_with_rating(), URL, RULES)), 1024)


class Tarjeta(unittest.TestCase):
    def test_sin_foto_de_amazon_por_defecto(self):
        deal = deal_with_rating()
        deal["image"] = "https://m.media-amazon.com/images/I/no-se-descarga.jpg"
        called = []
        import photos
        original = photos.fetch_best
        photos.fetch_best = lambda url: called.append(url)
        try:
            card = cn.make_card(deal, dict(RULES))
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
        self.assertIn("(hora peninsular)", text)
        self.assertIn("#publi", text)
        self.assertNotIn("⭐", text)


if __name__ == "__main__":
    unittest.main()
