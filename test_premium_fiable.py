"""Fiabilidad del canal premium: enlaces limpios de cualquier tienda, precio comprobado y posts marcados."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

import affiliate
import feeds
import premium
import scanner

CFG = {"affiliate_tag": "cazadores_errores-21", "store_affiliates": {}}


class Tiendas(unittest.TestCase):
    def test_nombre_de_tienda_legible(self):
        self.assertEqual(premium.store_of("https://es.aliexpress.com/item/1.html")[1], "AliExpress")
        self.assertEqual(premium.store_of("https://es.privalia.com/re-turn/p/1")[1], "Privalia")
        self.assertEqual(premium.store_of("https://shop.atleticodemadrid.com/es/polo")[1], "Atleticodemadrid")
        self.assertEqual(premium.store_name("www.tienda-ejemplo.co.uk"), "Tienda-ejemplo")

    def test_quita_el_afiliado_ajeno_de_aliexpress(self):
        wrapped = ("http://s.click.aliexpress.com/deep_link.htm?aff_short_key=_c3Mflefb&dl_target_url="
                   "https%3A%2F%2Fes.aliexpress.com%2Fitem%2F1005012105324220.html%3Faff_platform%3Dlink%26sk%3Dabc")
        clean = affiliate.clean_store_url(wrapped, CFG)
        self.assertEqual(clean, "https://es.aliexpress.com/item/1005012105324220.html")

    def test_envoltorio_que_no_se_puede_limpiar_no_se_publica(self):
        self.assertIsNone(affiliate.clean_store_url("https://s.click.aliexpress.com/e/_abc123", CFG))


class PrecioEnTienda(unittest.TestCase):
    PAGE = ('<html><head><meta property="product:price:amount" content="49.99"></head><body>'
            '<script type="application/ld+json">{"@type":"Product","offers":{"price":"49.99"}}</script>'
            '<button>Añadir a la cesta</button></body></html>')

    def test_precio_coincide(self):
        status, found = feeds.store_price_check("https://tienda.test/p", 49.99, fetch=lambda url: (200, self.PAGE))
        self.assertEqual((status, found), ("ok", 49.99))

    def test_precio_distinto(self):
        status, found = feeds.store_price_check("https://tienda.test/p", 39.99, fetch=lambda url: (200, self.PAGE))
        self.assertEqual((status, found), ("mismatch", 49.99))

    def test_pagina_sin_precio_o_bloqueada(self):
        self.assertEqual(feeds.store_price_check("https://t.test", 10, fetch=lambda u: (200, "<html>hola</html>"))[0],
                         "unknown")
        blocked = "<html><title>Access Denied</title></html>"
        self.assertEqual(feeds.store_price_check("https://t.test", 10, fetch=lambda u: (200, blocked))[0], "unknown")


class Estimacion(unittest.TestCase):
    RULES = None

    def rules(self):
        import json
        return json.loads(scanner.CONFIG_PATH.read_text(encoding="utf-8"))["resale"]

    def test_sin_anuncios_estima_con_el_precio_normal(self):
        import resale_market
        cand = {"name": "Robot aspirador Lefant M5 Pro", "title": "Robot aspirador Lefant M5 Pro", "brand": "Lefant",
                "price": 379.98, "min30_before": 799.99}
        result = resale_market.with_estimate(cand, self.rules(), {"ok": False, "count": 0, "prices": []})
        self.assertTrue(result["ok"])
        self.assertTrue(result["estimated"])
        self.assertEqual(result["source_label"], "ESTIMACIÓN")
        self.assertAlmostEqual(result["price"], round(799.99 * 0.65, 2))
        self.assertTrue(result["note"].startswith("Estimación: 65 % de 800 €"))

    def test_con_pocos_anuncios_usa_lo_mas_prudente(self):
        import resale_market
        cand = {"name": "Robot aspirador Lefant", "title": "Robot aspirador Lefant", "price": 300, "min30_before": 800}
        result = resale_market.with_estimate(cand, self.rules(), {"ok": False, "count": 2, "prices": [450, 470]})
        self.assertEqual(result["price"], 460)  # la mediana de los anuncios es menor que 800 × 0,65 = 520

    def test_si_el_mercado_dice_que_no_la_estimacion_no_lo_salva(self):
        import resale_market
        cand = {"name": "Robot aspirador Lefant", "price": 300, "min30_before": 800}
        verdict = {"ok": False, "count": 6, "prices": [310] * 6, "reason": "ROI bajo"}
        self.assertIs(resale_market.with_estimate(cand, self.rules(), verdict), verdict)

    def test_sin_precio_normal_no_se_inventa_nada(self):
        import resale_market
        verdict = {"ok": False, "count": 0, "prices": []}
        self.assertIs(resale_market.with_estimate({"name": "X", "price": 50}, self.rules(), verdict), verdict)

    def test_texto_dice_estimada(self):
        from publisher import build_caption
        text = build_caption(url="https://www.amazon.es/dp/B0TEST1234?tag=x", category="GANGA", title="Robot",
                             current=379.98, reference=799.99, resale_price=520, profit=140,
                             source_label="ESTIMACIÓN", store="Amazon")
        self.assertIn("Reventa estimada", text)
        self.assertNotIn("Reventa en", text)


class Seguimiento(unittest.TestCase):
    def test_marca_el_post_si_sube_el_precio(self):
        now = datetime(2026, 10, 31, 17, 0, tzinfo=timezone.utc)
        state = {"posts": [{"id": "R0ZG4Bv", "price": 379.98, "t": int(now.timestamp()) - 3600, "message_id": 77,
                            "url": "https://www.amazon.es/dp/B0G7YP6MXV?tag=cazadores_errores-21",
                            "cap": None}]}
        calls = []
        tg = SimpleNamespace(call=lambda method, params: calls.append((method, params)) or {})
        with mock.patch.object(scanner, "fetch", return_value="html"), \
             mock.patch.object(scanner, "parse_detail", return_value={"price": 449.0, "in_stock": True}):
            scanner.track_posts(tg, state, "@caza_errores", now, dry=False)
        self.assertEqual(calls[0][0], "editMessageCaption")
        self.assertIn("YA NO ESTÁ A ESTE PRECIO", calls[0][1]["caption"])
        self.assertTrue(state["posts"][0]["ended"])

    def test_no_marca_si_sigue_igual(self):
        now = datetime(2026, 10, 31, 17, 0, tzinfo=timezone.utc)
        state = {"posts": [{"id": "R0ZG4Bv", "price": 379.98, "t": int(now.timestamp()) - 3600, "message_id": 77,
                            "url": "https://www.amazon.es/dp/B0G7YP6MXV?tag=x", "cap": None}]}
        tg = SimpleNamespace(call=mock.Mock())
        with mock.patch.object(scanner, "fetch", return_value="html"), \
             mock.patch.object(scanner, "parse_detail", return_value={"price": 379.98, "in_stock": True}):
            scanner.track_posts(tg, state, "@caza_errores", now, dry=False)
        tg.call.assert_not_called()
        self.assertNotIn("ended", state["posts"][0])


if __name__ == "__main__":
    unittest.main()
