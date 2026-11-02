#!/usr/bin/env python3
"""La web solo enseña lo que el canal publicó, con el mismo enlace de afiliado y sin fotos de Amazon."""

import unittest

import web_export

NOW = 1_793_636_000
URL = "https://www.amazon.es/dp/B07B8Y81NT?tag=cazadores_errores-21"


def post(**kw):
    base = {"asin": "B07B8Y81NT", "price": 14.99, "reference": 22.95, "t": NOW - 3600, "url": URL,
            "chat": "@cazachollos_com", "message_id": 126,
            "title": "Theo Klein Hot Wheels Maletín coches, garaje metal, a partir de 3 años"}
    base.update(kw)
    return base


class Export(unittest.TestCase):
    def test_campos_y_enlace_de_afiliado(self):
        deal = web_export.build({"posts": [post()]}, {}, NOW)["deals"][0]
        self.assertEqual(deal["url"], URL)
        self.assertEqual(deal["pct"], 35)
        self.assertEqual(deal["saving"], 7.96)
        self.assertTrue(deal["active"])
        self.assertEqual(deal["telegram"], "https://t.me/cazachollos_com/126")
        self.assertNotIn("image", deal)

    def test_marca_los_que_ya_no_estan(self):
        deal = web_export.build({"posts": [post(ended=NOW - 60, checked=NOW - 60)]}, {}, NOW)["deals"][0]
        self.assertFalse(deal["active"])
        self.assertEqual(deal["ended"], NOW - 60)

    def test_un_asin_una_vez_el_mas_reciente(self):
        data = web_export.build({"posts": [post(price=16.0, t=NOW - 7200), post(price=14.99)]}, {}, NOW)
        self.assertEqual(len(data["deals"]), 1)
        self.assertEqual(data["deals"][0]["price"], 14.99)

    def test_fuera_lo_antiguo_lo_de_otro_chat_y_sin_descuento(self):
        posts = [post(asin="A1", t=NOW - 3 * 86400), post(asin="A2", chat="@caza_errores"),
                 post(asin="A3", reference=10.0), post(asin="A4")]
        asins = [d["asin"] for d in web_export.build({"posts": posts}, {}, NOW)["deals"]]
        self.assertEqual(asins, ["A4"])

    def test_orden_mas_nuevo_primero(self):
        posts = [post(asin="VIEJO", t=NOW - 5000), post(asin="NUEVO", t=NOW - 10)]
        asins = [d["asin"] for d in web_export.build({"posts": posts}, {}, NOW)["deals"]]
        self.assertEqual(asins, ["NUEVO", "VIEJO"])

    def test_categoria_del_config(self):
        rules = web_export.load_rules()
        deal = web_export.build({"posts": [post(title="Cecotec Robot Aspirador Conga 2290")]}, rules, NOW)["deals"][0]
        self.assertEqual(deal["category"], "Aspiradoras")


if __name__ == "__main__":
    unittest.main()
