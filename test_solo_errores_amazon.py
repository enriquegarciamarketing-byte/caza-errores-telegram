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


NEW_DETAIL = open("tests_fixtures/jl_detail_nueva_2026_11.html", encoding="utf-8").read()  # precio grande 12,34 €


def photo_ticket(jl_id, title, brand, price, was, verdict, age_min=3):
    html = ticket(jl_id, title, brand, price, was, verdict=verdict, age_min=age_min)
    return html.replace('<a href=', f'<a class="tk-photo" href="/es/dp/{jl_id}/"><img src="https://m.media-amazon.com/images/I/x._SL160_.jpg"></a><a href=', 1)


class ListingModeTest(unittest.TestCase):
    """Desde el 9/11/2026 la ficha de jimmyleaks solo trae el precio grande: el premium decide con el listado."""

    def setUp(self):
        self.cfg = {**load_cfg(scope=True), "sources": ["x"], "rotating_sources": [], "max_detail_fetches_per_run": 5}

    def run(self, *a, **k):
        scanner.API = None
        return super().run(*a, **k)

    def scan(self, page):
        def fake_fetch(url, binary=False, timeout=25):
            return NEW_DETAIL if "/dp/" in url else page
        scanner.CASCADA = cascada.Collector()
        with mock.patch.object(scanner, "fetch", side_effect=fake_fetch), \
             mock.patch.object(scanner.time, "sleep"), \
             mock.patch.object(scanner, "resolve_asin", return_value="B0TEST1234"), \
             mock.patch.object(scanner, "load_json", side_effect=lambda p, d: load_cfg(scope=True) if p == scanner.CONFIG_PATH else d), \
             mock.patch.object(scanner.feeds, "amazon_hot_titles", return_value=[]), \
             mock.patch("builtins.print"):
            return scanner.scan(self.cfg, {"seen": {}}, scanner.now_utc(), with_external=False)

    def test_error_frente_a_la_media_del_listado_entra(self):
        page = photo_ticket("ERR1", "Robot aspirador Conga 9090", "Cecotec", 12.34, 0, "80% por debajo de la media")
        found = self.scan(page)
        self.assertEqual([c["id"] for c in found], ["ERR1"])
        self.assertEqual(found[0]["category"], "ERROR DE PRECIO")
        self.assertAlmostEqual(found[0]["reference_price"], 61.7, places=1)
        self.assertTrue(found[0]["listing_mode"])

    def test_precio_de_la_ficha_distinto_no_entra(self):
        page = photo_ticket("ERR2", "Robot aspirador Conga 9090", "Cecotec", 15.0, 0, "80% por debajo de la media")
        self.assertEqual(self.scan(page), [])

    def test_sin_marca_no_entra(self):
        page = photo_ticket("ERR3", "Robot aspirador genérico", "Generico", 12.34, 0, "80% por debajo de la media")
        self.assertEqual(self.scan(page), [])

    def test_pvp_tachado_solo_si_es_minimo_historico(self):
        ok = photo_ticket("ERR4", "Placa de inducción PUE611", "Bosch", 12.34, 120.0, "Mínimo histórico")
        self.assertEqual(len(self.scan(ok)), 1)
        nope = photo_ticket("ERR5", "Placa de inducción PUE611", "Bosch", 12.34, 120.0, "Bajada reciente")
        self.assertEqual(self.scan(nope), [])


class EventsTest(unittest.TestCase):
    def test_el_escaner_apunta_las_decisiones_y_la_vista_las_pinta(self):
        import importlib.util
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "eventos.jsonl")
            with mock.patch.dict(os.environ, {"CAZA_EVENTOS": path}):
                page = (photo_ticket("ERR1", "Robot aspirador Conga 9090", "Cecotec", 12.34, 0, "80% por debajo de la media")
                        + ticket("FRY2", "Freidora de aire 5,5 L", "Cosori", 60.0, 120.0))
                case = ListingModeTest()
                case.setUp()
                scanner.API = None
                case.scan(page)
            events = [json.loads(line) for line in open(path, encoding="utf-8")]
        kinds = {(e["kind"], e.get("veredicto")) for e in events}
        self.assertIn(("pasada", None), kinds)
        self.assertIn(("producto", "ERROR DE PRECIO"), kinds)
        self.assertIn(("producto", "DESCARTADO"), kinds)
        spec = importlib.util.spec_from_file_location("ver_bot", "local/ver_bot.py")
        ver_bot = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ver_bot)
        shown = set()
        text = "\n".join(t for t in (ver_bot.render(e, shown) for e in events) if t)
        self.assertIn("ERROR DE PRECIO", text)
        self.assertIn("Robot aspirador Conga 9090", text)
        self.assertIn("DESCARTADO: descuento 50% (mín. 60%)", text)
        again = [ver_bot.render(e, shown) for e in events if e.get("fase") == "listado"]
        self.assertEqual([t for t in again if t], [])  # el mismo descarte no se repite


class NoResaleTest(unittest.TestCase):
    def test_publicar_no_mira_wallapop(self):
        cfg = load_cfg(scope=True)
        self.assertFalse(scanner.premium_resale(cfg))
        with mock.patch.object(scanner, "attach_wallapop") as wall, \
             mock.patch.object(scanner, "product_photo", side_effect=OSError("corta aquí")):
            with self.assertRaises(OSError):
                scanner.publish(None, cfg, {}, {"id": "X", "image": "u", "price": 1, "category": "ERROR DE PRECIO"},
                                "@c", dry=True)
        wall.assert_not_called()


class NetworkTest(unittest.TestCase):
    def test_un_corte_de_red_en_telegram_no_tumba_el_bot(self):
        import urllib.error
        tg = scanner.Telegram("token")
        with mock.patch.object(scanner.urllib.request, "urlopen", side_effect=urllib.error.URLError("sin wifi")):
            with self.assertRaises(RuntimeError):
                tg.call("getUpdates")
