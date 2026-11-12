"""Freno a la moda en el canal free (12/11/2026): demasiadas zapatillas, vaqueros y bolsos de marca."""

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

import canal_nube as cn

CFG = json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8"))
RULES = cn.rules_from(CFG)
NOW = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)


def state(*titles):
    """Posts de más antiguo a más reciente, uno cada 20 minutos y de marcas distintas."""
    n = len(titles)
    return {"posts": [{"t": int(NOW.timestamp()) - (n - i) * 20 * 60, "title": t} for i, t in enumerate(titles)]}


class EsModa(unittest.TestCase):
    def test_ropa_calzado_y_complementos(self):
        for title in ["Nike Air MAX SNDR Sneaker", "adidas Hombre Grand Court 3.0 Shoes, FTWR White",
                      "Levi's 555 Relaxed Straight Back On The Block, 32W / 32L",
                      "Tommy Hilfiger Bolso bandolera Mujer Daily con correa desmontable",
                      "Anillo Thomas Sabo de Plata de Ley 925 con Piedra Azul",
                      "Calvin Klein Reloj Analógico de Cuarzo Multifunción para Hombre",
                      "PUMA Zapatillas de Running Softride Enzo 5, Black-White-Black, 36 EU",
                      "Pantalón Corto Tommy Hilfiger Hombre Azul Marino"]:
            self.assertTrue(cn.es_moda(title, RULES), title)

    def test_tecnologia_y_hogar_no(self):
        for title in ["HUAWEI Watch GT Runner 2 Smartwatch con GPS de Running Azul",
                      "Xiaomi Smart Band 9 Pulsera de Actividad", "Samsonite Maleta de cabina",
                      'LG 65QNED82B6B - Smart TV QNED EVO AI 65" 4K', "Casio fx-991SP CW Calculadora Científica",
                      "Cecotec Conga Rockstar 8000 Aspirador de Colchones", "Ninja Luxe Pro, Cafetera 3 en 1"]:
            self.assertFalse(cn.es_moda(title, RULES), title)

    def test_sin_bloque_moda_nada_es_moda(self):
        self.assertFalse(cn.es_moda("Nike Air MAX SNDR Sneaker", {}))


class DescuentoModa(unittest.TestCase):
    def test_moda_necesita_menos_65(self):
        deal = {"title": "Nike Air MAX SNDR Sneaker", "price": 50.0, "reference": 110.0, "discount": 55}
        self.assertIn("moda", cn.value_reason(deal, RULES))
        deal.update(price=35.0, discount=68)
        self.assertEqual(cn.value_reason(deal, RULES), "")

    def test_tecnologia_sigue_igual(self):
        deal = {"title": "Lefant M330 Plus Robot Aspirador", "price": 100.0, "reference": 200.0, "discount": 50}
        self.assertEqual(cn.value_reason(deal, RULES), "")


class CupoModa(unittest.TestCase):
    def test_una_de_cada_cinco(self):
        s = state("Levi's 555 Relaxed Straight", "Lefant M330 Robot Aspirador", "JATA Freidora de Aire 5L",
                  "Sony WH-CH720N Auriculares")
        why = cn.variety_reason(s, {"title": "Nike Air MAX SNDR Sneaker"}, NOW, RULES)
        self.assertIn("moda", why)
        self.assertIn("moda", cn.variety_reason(s, {"title": "Nike Air MAX SNDR Sneaker"}, NOW, RULES, urgent=True))

    def test_tras_cuatro_posts_sin_moda_vuelve_a_valer(self):
        s = state("Levi's 555 Relaxed Straight", "Lefant M330 Robot Aspirador", "JATA Freidora de Aire 5L",
                  "Sony WH-CH720N Auriculares", 'LG 65QNED82B6B - Smart TV QNED EVO AI 65"')
        self.assertEqual(cn.variety_reason(s, {"title": "Nike Air MAX SNDR Sneaker"}, NOW, RULES), "")

    def test_lo_que_no_es_moda_no_cuenta(self):
        s = state("Nike Air MAX SNDR Sneaker")
        self.assertEqual(cn.variety_reason(s, {"title": "JATA Freidora de Aire 5L"}, NOW, RULES), "")


class FuentesYBusquedas(unittest.TestCase):
    def test_sin_listado_de_moda(self):
        self.assertFalse([s for s in RULES["sources"] if "/c/moda/" in s])

    def test_busquedas_de_ropa_fuera(self):
        kws = ["zapatillas nike", "bolso mujer", "reloj casio", "robot aspirador", "smart tv 55 pulgadas"]
        self.assertEqual([k for k in kws if not cn.es_moda(k, RULES)], ["robot aspirador", "smart tv 55 pulgadas"])


if __name__ == "__main__":
    unittest.main()
