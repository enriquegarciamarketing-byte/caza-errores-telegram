"""Premium solo con errores de precio de Amazon (10/11/2026)."""

import os
import unittest
from unittest import mock

import cascada
import scanner
from test_premium_errores import ticket
from test_scanner import load_cfg


class ScopeTest(unittest.TestCase):
    def test_config_real_esta_en_modo_solo_errores(self):
        cfg = load_cfg(scope=True)
        self.assertTrue(scanner.amazon_errors_only(cfg))
        self.assertEqual(cfg["error_min_discount"], 70)

    def test_sin_scope_es_el_comportamiento_de_antes(self):
        self.assertFalse(scanner.amazon_errors_only({}))
        self.assertFalse(scanner.amazon_errors_only({"premium_scope": "todo"}))


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        self.cfg = {**load_cfg(scope=True), "resale": {"enabled": False}}

    def cand(self, price, avg):
        return {"price": price, "avg90": avg, "reviews": 200, "rating": 4.5, "brand": "Cecotec"}

    def test_una_ganga_ya_no_sale_y_baja_al_canal_normal(self):
        category, reason = scanner.classify(self.cfg, self.cand(50.0, 100.0))
        self.assertIsNone(category)
        self.assertTrue(reason.startswith("solo -50% bajo la referencia"))
        self.assertTrue(cascada.reason_ok(reason))

    def test_un_error_sigue_saliendo(self):
        category, _ = scanner.classify(self.cfg, self.cand(20.0, 100.0))
        self.assertEqual(category, "ERROR DE PRECIO")

    def test_sin_scope_la_ganga_sigue_como_antes(self):
        cfg = {**self.cfg}
        cfg.pop("premium_scope", None)
        category, _ = scanner.classify(cfg, self.cand(50.0, 100.0))
        self.assertIn(category, ("GANGA", "MÍNIMO HISTÓRICO"))


class FastFilterTest(unittest.TestCase):
    def run_scan(self, page, cfg):
        state, printed = {"seen": {}}, []
        scanner.CASCADA = cascada.Collector()
        with mock.patch.object(scanner, "fetch", return_value=page), \
             mock.patch.object(scanner.time, "sleep"), \
             mock.patch.object(scanner.feeds, "amazon_hot_titles", return_value=[]), \
             mock.patch.object(scanner.feeds, "external_candidates") as external, \
             mock.patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
            scanner.scan(cfg, state, scanner.now_utc(), with_external=True)
        return printed, external, scanner.CASCADA

    def test_solo_abre_fichas_de_posibles_errores_y_no_mira_otras_tiendas(self):
        page = (ticket("CONGA1", "Robot aspirador Conga 11090", "Cecotec", 23.0, 369.99)
                + ticket("TV1", "Smart TV 55 pulgadas", "Samsung", 140.0, 400.0)  # -65 %: dentro del margen
                + ticket("FRY2", "Freidora de aire 5,5 L", "Cosori", 60.0, 120.0)  # -50 %: ganga, no error
                + ticket("SOCK1", "6 pares calcetines deporte", "Generico", 7.26, 29.99))
        cfg = {**load_cfg(scope=True), "sources": ["x"], "rotating_sources": [], "max_detail_fetches_per_run": 0}
        printed, external, collector = self.run_scan(page, cfg)
        self.assertIn("Candidatos nuevos tras el filtro rápido: 2", printed)
        external.assert_not_called()
        self.assertIn("FRY2", collector.entries)  # la ganga baja al canal normal
        self.assertEqual(collector.entries["FRY2"]["reason"], "listado: no es error de precio")


class CascadePushTest(unittest.TestCase):
    def test_en_el_mac_sube_la_cascada_con_cascada_push(self):
        with mock.patch.dict(os.environ, {"CASCADA_PUSH": "1", "GITHUB_ACTIONS": ""}):
            self.assertTrue(cascada._enabled_here())
        with mock.patch.dict(os.environ, {"CASCADA_PUSH": "", "GITHUB_ACTIONS": ""}):
            self.assertFalse(cascada._enabled_here())


if __name__ == "__main__":
    unittest.main()
