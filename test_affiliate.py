#!/usr/bin/env python3
"""La etiqueta de afiliado del canal va en todos los enlaces de Amazon."""

from __future__ import annotations

import unittest
from urllib.parse import parse_qs, urlsplit

import affiliate

TAG = "cazadores_errores-21"


def tags(url: str) -> list[str]:
    return parse_qs(urlsplit(url).query).get("tag", [])


class AmazonEsTagTest(unittest.TestCase):
    def test_anade_la_etiqueta_si_falta(self):
        url, warnings = affiliate.prepare_amazon_link("https://www.amazon.es/dp/B0TEST1234", TAG)
        self.assertEqual(warnings, [])
        self.assertEqual(tags(url), [TAG])
        self.assertIn("/dp/B0TEST1234", url)

    def test_sustituye_la_etiqueta_de_otro_y_no_deja_duplicados(self):
        raw = "https://www.amazon.es/s?k=4548736132579&tag=otro-21&tag=cazadores_errores-21&ref=sr"
        url, warnings = affiliate.prepare_amazon_link(raw, TAG)
        self.assertEqual(warnings, [])
        self.assertEqual(tags(url), [TAG])
        self.assertEqual(parse_qs(urlsplit(url).query)["k"], ["4548736132579"])
        self.assertEqual(parse_qs(urlsplit(url).query)["ref"], ["sr"])

    def test_un_enlace_que_no_es_de_amazon_no_se_toca(self):
        raw = "https://jimmyleaks.com/es/dp/abc/"
        url, warnings = affiliate.prepare_amazon_link(raw, TAG)
        self.assertEqual(url, raw)
        self.assertEqual(warnings, [])


class ShortLinkTest(unittest.TestCase):
    def test_si_el_destino_lleva_la_etiqueta_se_publica_ese_amazon_es(self):
        final = f"https://www.amazon.es/dp/B0GOODASIN?tag=otro-21&tag={TAG}&linkCode=sl1"

        def resolve(_url):
            return final

        url, warnings = affiliate.prepare_amazon_link(
            "https://amzn.to/abc", TAG, asin="B0GOODASIN", resolve=resolve,
        )
        self.assertEqual(warnings, [])
        self.assertEqual(tags(url), [TAG])
        self.assertIn("/dp/B0GOODASIN", url)
        self.assertTrue(url.startswith("https://www.amazon.es/"))

    def test_sin_etiqueta_no_se_usa_el_corto_y_hay_enlace_directo(self):
        def resolve(_url):
            return "https://www.amazon.es/dp/B0TEST1234?tag=otro-21"

        url, warnings = affiliate.prepare_amazon_link(
            "https://link.amazon/xyz", TAG, asin="B0TEST1234", gtin="1234567890123", resolve=resolve,
        )
        self.assertTrue(warnings)
        self.assertIn("etiqueta", warnings[0])
        self.assertEqual(tags(url), [TAG])
        self.assertIn("/dp/B0TEST1234", url)
        self.assertNotIn("link.amazon", url)
        self.assertNotIn("otro-21", url)

    def test_amzlinks_sin_etiqueta_cae_al_ean(self):
        def resolve(_url):
            return "https://www.amazon.es/s?k=cosa"

        url, warnings = affiliate.prepare_amazon_link(
            "https://amzlinks.in/abc", TAG, gtin="4548736132579", resolve=resolve,
        )
        self.assertTrue(warnings)
        self.assertEqual(tags(url), [TAG])
        self.assertIn("4548736132579", url)
        self.assertTrue(url.startswith("https://www.amazon.es/s?"))

    def test_asin_distinto_avisa_y_no_usa_el_producto_ajeno(self):
        def resolve(_url):
            return f"https://www.amazon.es/dp/B0OTROPROD?tag={TAG}"

        url, warnings = affiliate.prepare_amazon_link(
            "https://amzn.to/mal", TAG, asin="B0MIPROD99", resolve=resolve,
        )
        self.assertTrue(any("B0OTROPROD" in warning and "B0MIPROD99" in warning for warning in warnings))
        self.assertIn("/dp/B0MIPROD99", url)
        self.assertNotIn("B0OTROPROD", url)
        self.assertEqual(tags(url), [TAG])

    def test_si_el_corto_no_abre_se_usa_el_dp(self):
        def resolve(_url):
            raise TimeoutError("timeout")

        url, warnings = affiliate.prepare_amazon_link(
            "https://amzn.eu/d/zzz", TAG, asin="B0TEST1234", resolve=resolve,
        )
        self.assertTrue(warnings)
        self.assertIn("/dp/B0TEST1234", url)
        self.assertEqual(tags(url), [TAG])

    def test_sin_alternativa_no_hay_enlace(self):
        def resolve(_url):
            return "https://www.amazon.es/s?k=nada"

        url, warnings = affiliate.prepare_amazon_link("https://amzn.to/x", TAG, resolve=resolve)
        self.assertIsNone(url)
        self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()
