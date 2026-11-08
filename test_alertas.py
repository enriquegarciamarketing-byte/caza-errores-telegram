import unittest

import alertas

RULE = {"id": "tv-98", "label": "ALERTA TV 98", "sizes": [97, 98, 100], "min_discount": 30,
        "min_discount_at_low": 15, "asins": []}
CFG = {"alerts": [RULE], "alerts_detail_every_passes": 1}


class TG:
    def __init__(self):
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        return {}


def detail_for(prices):
    def parse(page):
        return prices[page]
    def fetch(url):
        return url.rstrip("/").split("/")[-1]
    return fetch, parse


class MatchTest(unittest.TestCase):
    def test_teles_98(self):
        for title in ("TCL 98T8D TV 98 Inch QD-Mini LED 4K Smart TV",
                      'Hisense 98E7Q Smart TV 4K QLED de 98" (2,49 m)',
                      "Televisor Samsung 98 pulgadas Neo QLED",
                      "TV QLED 248cm (98\") Hisense 98E7Q"):
            self.assertTrue(alertas.matches(RULE, title), title)

    def test_no_teles_ni_accesorios(self):
        for title in ("Soporte de pared para TV de 32 a 98 pulgadas",
                      "Samsung 65 pulgadas QLED Smart TV",
                      "Pantalla de proyección 98 pulgadas",
                      "Funda para TV 98 pulgadas exterior",
                      "Cafetera Cecotec 98 cápsulas"):
            self.assertFalse(alertas.matches(RULE, title), title)


class CheckTest(unittest.TestCase):
    def test_avisa_chollazo_una_vez(self):
        fetch, parse = detail_for({"B1": {"name": "TCL 98T8D TV 98 Inch Smart TV", "price": 999.0,
                                          "avg90": 1749.0, "in_stock": True, "image": None}})
        listings = [{"id": "B1", "title": "TCL 98T8D TV 98 Inch Smart TV", "price": 999.0, "was": 1749.0}]
        tg, state = TG(), {"admin_chat_id": 7}
        sent = alertas.check(tg, CFG, state, listings, fetch=fetch, parse_detail=parse, now_ts=1000)
        self.assertEqual([c["id"] for c in sent], ["B1"])
        self.assertEqual(tg.calls[0][1]["chat_id"], 7)
        self.assertIn("amazon.es/dp/B1", tg.calls[0][1]["text"])
        self.assertNotIn("tag=", tg.calls[0][1]["text"])
        again = alertas.check(tg, CFG, state, listings, fetch=fetch, parse_detail=parse, now_ts=2000)
        self.assertEqual(again, [])

    def test_no_avisa_descuento_flojo(self):
        fetch, parse = detail_for({"B1": {"name": "TCL 98T8D TV 98 Inch", "price": 1399.0,
                                          "avg90": 1749.0, "in_stock": True}})
        listings = [{"id": "B1", "title": "TCL 98T8D TV 98 Inch", "price": 1399.0, "was": 1749.0}]
        tg = TG()
        self.assertEqual(alertas.check(tg, CFG, {"admin_chat_id": 7}, listings,
                                       fetch=fetch, parse_detail=parse), [])
        self.assertEqual(tg.calls, [])

    def test_prueba_manda_lo_mejor(self):
        fetch, parse = detail_for({"B1": {"name": "TCL 98T8D TV 98 Inch", "price": 1399.0,
                                          "avg90": 1749.0, "in_stock": True}})
        listings = [{"id": "B1", "title": "TCL 98T8D TV 98 Inch", "price": 1399.0}]
        tg = TG()
        sent = alertas.check(tg, CFG, {"admin_chat_id": 7}, listings, fetch=fetch,
                             parse_detail=parse, test=True)
        self.assertEqual(len(sent), 1)
        self.assertIn("PRUEBA", tg.calls[0][1]["text"])

    def test_vigila_asin_aunque_no_salga_en_listados(self):
        fetch, parse = detail_for({"B9": {"name": "Hisense 98E7Q Smart TV 98\"", "price": 900.0,
                                          "avg90": 1500.0, "in_stock": True}})
        cfg = {"alerts": [dict(RULE, asins=["B9"])], "alerts_detail_every_passes": 1}
        tg = TG()
        sent = alertas.check(tg, cfg, {"admin_chat_id": 7}, [], fetch=fetch, parse_detail=parse)
        self.assertEqual([c["id"] for c in sent], ["B9"])


if __name__ == "__main__":
    unittest.main()
