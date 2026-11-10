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


class TagGuardTest(unittest.TestCase):
    TAG = "cazachollos0c-21"

    def test_amazon_sin_tag_o_con_otro_no_sale(self):
        import affiliate
        for url in ("https://www.amazon.es/dp/B0TEST1234",
                    "https://www.amazon.es/dp/B0TEST1234?tag=otro-21",
                    "https://www.amazon.es/dp/B0TEST1234?tag=otro-21&tag=cazachollos0c-21"):
            with self.assertRaises(affiliate.MissingTag):
                affiliate.require_tag(url, self.TAG)

    def test_con_tu_tag_enlaces_cortos_y_otras_tiendas_pasan(self):
        import affiliate
        affiliate.require_tag("https://www.amazon.es/dp/B0TEST1234?tag=cazachollos0c-21", self.TAG)
        affiliate.require_tag("https://link.amazon/B06HSXRm5", self.TAG)
        affiliate.require_tag("https://www.pccomponentes.com/x", self.TAG)

    def test_el_boton_del_premium_y_el_post_del_free_lo_comprueban(self):
        import affiliate
        import canal_nube
        with self.assertRaises(affiliate.MissingTag):
            scanner.buttons_for("https://www.amazon.es/dp/B0TEST1234")
        self.assertIn("inline_keyboard", scanner.buttons_for("https://www.amazon.es/dp/B0TEST1234?tag=cazachollos0c-21"))
        with self.assertRaises(affiliate.MissingTag):
            canal_nube.publish(None, "@c", {"asin": "B0TEST1234"}, {"tag": self.TAG}, "", "https://www.amazon.es/dp/B0TEST1234")


def api_item(asin, title, brand, price, basis, basis_type, avail="IN_STOCK", seller="Amazon", seller_id="A1AT7YVPFBWXBL"):
    return {"asin": asin, "itemInfo": {"title": {"displayValue": title}, "byLineInfo": {"brand": {"displayValue": brand}}},
            "images": {"primary": {"large": {"url": f"https://m.media-amazon.com/images/I/{asin}._SL500_.jpg"}}},
            "offersV2": {"listings": [{"availability": {"type": avail}, "merchantInfo": {"name": seller, "id": seller_id},
                                       "price": {"money": {"amount": price}, "savingBasis": {"money": {"amount": basis},
                                                                                             "savingBasisType": basis_type}}}]}}


class FakeAPI:
    def __init__(self, items):
        self.items, self.calls = items, []

    def call(self, op, body):
        self.calls.append((op, body))
        return {"searchResult": {"items": self.items}}

    def get_item(self, asin):
        return None


class AmazonSearchTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load_cfg(scope=True)
        self.now = scanner.now_utc()

    def test_precio_honesto_con_marca_es_error(self):
        import buscador_amazon as ba
        cand, why = ba.to_candidate(api_item("B0AAAAAAA1", "Robot aspirador Roborock S8", "Roborock", 99.0, 499.0, "WAS_PRICE"),
                                    "robot aspirador", self.cfg, self.now, "cazachollos0c-21")
        self.assertEqual(why, "")
        self.assertEqual(cand["direct_url"], "https://www.amazon.es/dp/B0AAAAAAA1?tag=cazachollos0c-21")
        self.assertEqual(scanner.classify(self.cfg, cand)[0], "ERROR DE PRECIO")

    def test_precio_recomendado_inflado_no_vale(self):
        import buscador_amazon as ba
        _, why = ba.to_candidate(api_item("B0AAAAAAA2", "Auriculares Bluetooth 5.4", "Ordtop", 15.99, 59.99, "LIST_PRICE"),
                                 "auriculares", self.cfg, self.now, "x")
        self.assertIn("precio recomendado", why)

    def test_la_busqueda_rota_y_publica_solo_lo_bueno(self):
        items = [api_item("B0AAAAAAA1", "Robot aspirador Roborock S8", "Roborock", 99.0, 499.0, "WAS_PRICE"),
                 api_item("B0AAAAAAA2", "Auriculares Bluetooth 5.4", "Ordtop", 15.99, 59.99, "LIST_PRICE"),
                 api_item("B0AAAAAAA3", "Freidora de aire Cosori", "Cosori", 60.0, 120.0, "LOWEST_PRICE_STRIKETHROUGH"),
                 api_item("B0AAAAAAA4", "Robot aspirador genérico", "Generico", 20.0, 200.0, "WAS_PRICE")]
        fake = FakeAPI(items)
        state = {"seen": {}}
        with mock.patch.object(scanner, "API", fake), mock.patch.object(scanner.time, "sleep"), \
             mock.patch("buscador_amazon.time.sleep"), mock.patch("builtins.print"):
            found = scanner.scan_amazon(self.cfg, state, self.now, state["seen"])
            again = scanner.scan_amazon(self.cfg, state, self.now, state["seen"])
        self.assertEqual([c["asin"] for c in found], ["B0AAAAAAA1"])
        self.assertEqual(again, [])  # mismo precio: no se repite
        self.assertEqual(len(fake.calls), 8)  # 4 búsquedas por pasada
        self.assertEqual(fake.calls[0][1]["minSavingPercent"], 70)
        self.assertEqual(state["amazon_search_index"], 8)


class BlockPauseTest(unittest.TestCase):
    def test_si_jimmyleaks_bloquea_se_pausa_30_min(self):
        import urllib.error
        cfg = {**load_cfg(scope=True), "sources": ["a", "b", "c"], "rotating_sources": [], "amazon_search": {"enabled": False}}
        state = {"seen": {}}
        err = urllib.error.HTTPError("u", 403, "Forbidden", None, None)
        with mock.patch.object(scanner, "fetch", side_effect=err) as fetch, mock.patch.object(scanner.time, "sleep"), \
             mock.patch.object(scanner.feeds, "amazon_hot_titles", return_value=[]), mock.patch("builtins.print"):
            now = scanner.now_utc()
            scanner.scan(cfg, state, now, with_external=False)
            self.assertEqual(fetch.call_count, 2)
            self.assertGreater(state["jl_paused_until"], now.timestamp())
            scanner.scan(cfg, state, now, with_external=False)
            self.assertEqual(fetch.call_count, 2)  # en pausa: ni lo intenta


class FreeAmazonTest(unittest.TestCase):
    def test_el_free_busca_en_amazon_y_aplica_sus_reglas(self):
        import canal_nube as cn
        cfg = load_cfg(scope=True)
        rules = cn.rules_from(cfg)
        rules["amazon_search"] = dict(rules["amazon_search"], enabled=True)
        items = [api_item("B0AAAAAAA1", "Robot aspirador Roborock Q7 Max", "Roborock", 149.0, 399.0, "WAS_PRICE"),
                 api_item("B0AAAAAAA2", "Auriculares Bluetooth 5.4 deportivos", "Ordtop", 15.99, 59.99, "LIST_PRICE"),
                 api_item("B0AAAAAAA3", "Robot aspirador Cecotec Conga", "Cecotec", 99.0, 120.0, "LIST_PRICE")]
        fake = FakeAPI(items)
        state = {"seen": {}, "posts": []}
        logs = []
        with mock.patch.object(cn, "API", fake), mock.patch("buscador_amazon.time.sleep"):
            approved = cn.find_deals(dict(rules, sources=[], rotating_sources=[]), state, scanner.now_utc(),
                                     fetch=lambda url: "", resolve_asin=lambda i: None, log=logs.append)
        asins = [deal["asin"] for _, deal in approved]
        self.assertIn("B0AAAAAAA1", asins)          # -63 % frente a su precio mediano, categoría top
        self.assertNotIn("B0AAAAAAA2", asins)       # precio recomendado de un vendedor sin marca
        self.assertNotIn("B0AAAAAAA3", asins)       # solo -18 %
        self.assertEqual(fake.calls[0][1]["minSavingPercent"], 50)


class AskAllTest(unittest.TestCase):
    def test_todo_error_pide_ok_antes(self):
        cfg = load_cfg(scope=True)
        self.assertTrue(cfg["premium_ask_all"])
        cand = {"id": "B0AAAAAAA1", "asin": "B0AAAAAAA1", "price": 99.0, "avg90": 499.0, "discount": 80.2,
                "origin": "amazon_api", "ref_text": "frente a su precio mediano en Amazon",
                "direct_url": "https://www.amazon.es/dp/B0AAAAAAA1?tag=cazachollos0c-21", "title": "Roborock S8"}
        category, _ = scanner.quality_checks(cand, scanner.now_utc(), "ERROR DE PRECIO", "-80%")
        self.assertEqual(category, "ERROR DE PRECIO")
        self.assertTrue(cand["needs_ok"])
        self.assertIn("-80 % frente a su precio mediano", cand["ask_reason"])

    def test_la_prueba_nunca_publica_en_el_canal(self):
        class API:
            def get_item(self, asin):
                return {"price": 50.0, "saving_basis": 100.0, "title": "Producto de prueba", "image": "u"}
        sent = []
        with mock.patch.object(scanner, "API", API()), \
             mock.patch.object(scanner, "publish", side_effect=lambda tg, cfg, st, cand, ch, dry: sent.append(cand) or True), \
             mock.patch.object(scanner, "save_state") as save, mock.patch("builtins.print"):
            code = scanner.test_ask(object(), load_cfg(scope=True), {"admin_chat_id": 1}, "@caza_errores", "B0AAAAAAA1", False)
        self.assertEqual(code, 0)
        self.assertTrue(sent[0]["needs_ok"])          # va a ask_admin, nunca al canal
        self.assertIn("PRUEBA", sent[0]["ask_reason"])
        save.assert_not_called()                     # tu OK no encuentra nada que publicar


class TrustedBrandTest(unittest.TestCase):
    def test_tablets_y_portatiles_sin_marca_conocida_no_salen_ni_con_precio_mediano(self):
        import canal_nube as cn
        rules = cn.rules_from(load_cfg(scope=True))
        rules["amazon_search"] = dict(rules["amazon_search"], enabled=True)
        items = [api_item("B0H9LQ788R", "Tablet Android 15 Tablet 10 Pulgadas", "UJJ", 99.99, 299.99, "WAS_PRICE"),
                 api_item("B0HKN8VJ1Y", "Ordenador Pc Portátil 15,6 pulgadas", "Teclast", 579.99, 1599.99, "WAS_PRICE"),
                 api_item("B0BTDT8V59", "Sony WH-CH720N Auriculares Inalámbricos", "Sony", 67.0, 149.99, "WAS_PRICE")]
        with mock.patch.object(cn, "API", FakeAPI(items)), mock.patch("buscador_amazon.time.sleep"):
            approved = cn.find_deals(dict(rules, sources=[], rotating_sources=[]), {"seen": {}, "posts": []},
                                     scanner.now_utc(), fetch=lambda u: "", resolve_asin=lambda i: None, log=lambda *a: None)
        self.assertEqual([d["asin"] for _, d in approved], ["B0BTDT8V59"])

    def test_el_premium_tampoco(self):
        import buscador_amazon as ba
        cfg = load_cfg(scope=True)
        self.assertFalse(ba.is_trusted("UJJ", cfg))
        self.assertTrue(ba.is_trusted("Roborock", cfg))
        self.assertTrue(ba.is_trusted("SONY", cfg))


class SellerRuleTest(unittest.TestCase):
    def test_solo_amazon_o_la_tienda_oficial(self):
        import buscador_amazon as ba
        cfg, now = load_cfg(scope=True), scanner.now_utc()
        tablet = api_item("B0GVYYTNQ8", "Tablet Android 10", "Teclast", 89.99, 299.99, "LOWEST_PRICE_STRIKETHROUGH",
                          seller="ZIIZI Store", seller_id="APCUF7N2BULEX")
        _, why = ba.to_candidate(tablet, "tablet", cfg, now, "x")
        self.assertIn("lo vende ZIIZI Store", why)
        robo = api_item("B0GZZM4CXF", "Roborock Qrevo 2 Pro", "roborock", 99.0, 689.0, "WAS_PRICE",
                        seller="Roborock Official EU", seller_id="AYQYOFE0SRACD")
        cand, why = ba.to_candidate(robo, "roborock", cfg, now, "x")
        self.assertEqual(why, "")
        self.assertTrue(cand["official_store"])


class HistoryTest(unittest.TestCase):
    def setUp(self):
        import historial
        from datetime import timedelta
        self.h, self.td = historial, timedelta
        self.now = scanner.now_utc()

    def hist(self, prices):
        """prices: precio por día, del más antiguo (hace len días) a ayer."""
        hist = {}
        for i, p in enumerate(prices):
            self.h.record(hist, "B0PLANCHA1", p, self.now - self.td(days=len(prices) - i))
        return hist

    def test_la_trampa_de_subir_y_bajar_no_pasa(self):
        # La plancha: 30 € de siempre, el vendedor la sube a 119 € tres días y ahora «-75 %» a 29,99 €.
        hist = self.hist([30, 30, 31, 29.5, 30, 119, 119, 119])
        honest, why, info = self.h.check("B0PLANCHA1", 29.99, 119.0, self.now, hist, min_drop_pct=70)
        self.assertIsNone(honest)
        self.assertTrue(why)

    def test_un_error_de_verdad_si_pasa(self):
        hist = self.hist([399, 399, 389, 399, 395, 399])
        honest, why, info = self.h.check("B0PLANCHA1", 89.0, 399.0, self.now, hist, min_drop_pct=70)
        self.assertEqual(why, "")
        self.assertAlmostEqual(honest, 399.0)

    def test_sin_historial_decide_cada_canal(self):
        honest, why, info = self.h.check("B0NUEVO000", 50.0, 200.0, self.now, {}, min_drop_pct=70)
        self.assertEqual((honest, why, info["days"]), (None, "", 0))

    def test_el_ok_lleva_boton_de_keepa(self):
        sent = []

        class TG:
            def send_photo(self, chat, card, caption, extra=None):
                sent.append(extra)
                return {"message_id": 1}

            def call(self, m, p):
                sent.append(p)
                return {"message_id": 2}

        cand = {"id": "B0AAAAAAA1", "asin": "B0AAAAAAA1", "price": 50.0, "category": "ERROR DE PRECIO",
                "image": "u", "title": "x", "history": {"days": 0}}
        with mock.patch.object(scanner, "caption_for", return_value="txt"), \
             mock.patch.object(scanner, "caption_data", return_value={}), mock.patch("builtins.print"):
            scanner.ask_admin(TG(), {"admin_chat_id": 1}, cand, "card.jpg",
                              "https://www.amazon.es/dp/B0AAAAAAA1?tag=x", "s",
                              {"title": "x", "category": "E", "current": 1, "reference": 2}, False)
        buttons = sent[0]["reply_markup"]["inline_keyboard"][0]
        self.assertIn("https://keepa.com/#!product/9-B0AAAAAAA1", [b["url"] for b in buttons])
        self.assertIn("Keepa", sent[1]["text"])


class ExtrasTest(unittest.TestCase):
    def test_linea_de_oferta_oficial(self):
        import buscador_amazon as ba
        from datetime import datetime, timezone
        now = datetime(2026, 11, 10, 20, 0, tzinfo=timezone.utc)
        self.assertEqual(ba.deal_line("Oferta flash", "2026-11-10T22:59:59Z", now), "⚡ Oferta flash · acaba hoy a las 23:59")
        self.assertEqual(ba.deal_line("Black Friday anticipado", "2026-11-11T22:45:00Z", now),
                         "⚡ Black Friday anticipado · acaba mañana a las 23:45")
        self.assertEqual(ba.deal_line("Finaliza en ", "2026-11-30T22:00:00Z", now), "⚡ Oferta por tiempo limitado")
        self.assertEqual(ba.deal_line("", "", now), "")

    def test_el_post_del_premium_la_muestra(self):
        cand = {"category": "ERROR DE PRECIO", "title": "Roborock Qrevo", "price": 99.0, "avg90": 499.0,
                "deal_line": "⚡ Oferta flash · acaba hoy a las 23:59"}
        text = scanner.caption_for("https://www.amazon.es/dp/B0X?tag=t", scanner.caption_data(cand))
        self.assertIn("⚡ Oferta flash · acaba hoy a las 23:59", text)

    def test_aviso_si_amazon_quita_la_api(self):
        import buscador_amazon as ba
        self.assertIn("30 días", ba.problem_text("HTTP 403 AssociateNotEligible"))
        self.assertIn("límite", ba.problem_text("HTTP 429 TooManyRequests"))


class LearningTest(unittest.TestCase):
    def test_dos_no_bloquean_la_marca_y_un_ok_la_salva(self):
        import aprendizaje as ap
        state = {}
        post = {"brand": "Faszin", "seller": "Faszin Store EU", "source": "Amazon · plancha de pelo"}
        self.assertEqual(ap.record(state, post, "no"), [])
        newly = ap.record(state, post, "no")
        self.assertIn("la marca Faszin", newly)
        self.assertIn("has rechazado la marca Faszin", ap.blocked(state["learning"], {"brand": "FASZIN"}))
        ap.record(state, {"brand": "Faszin"}, "ok")
        self.assertEqual(ap.blocked(state["learning"], {"brand": "Faszin"}), "")

    def test_responder_no_descarta_y_aprende(self):
        state = {"admin_chat_id": 1, "posts": [{"id": "B0X", "needs_ok": True, "pending": True, "alert_id": 50,
                                                "brand": "Faszin", "seller": "X", "source": "Amazon · plancha",
                                                "ask_until": 9e12}]}
        sent = []

        class TG:
            def call(self, method, params):
                if method == "getUpdates":
                    return [{"update_id": 1, "message": {"message_id": 9, "chat": {"id": 1, "type": "private"},
                                                         "from": {"id": 1}, "text": "no",
                                                         "reply_to_message": {"message_id": 50}}}]
                sent.append(params)
                return {}
        with mock.patch("builtins.print"):
            scanner.handle_updates(TG(), load_cfg(scope=True), state, "@c", False)
        self.assertTrue(state["posts"][0].get("rejected"))
        self.assertFalse(state["posts"][0]["pending"])
        self.assertEqual(state["learning"]["brand"]["faszin"]["no"], 1)
        self.assertIn("Descartado", sent[-1]["text"])

    def test_las_busquedas_que_venden_salen_mas(self):
        import buscador_amazon as ba
        learning = {"sales": {"keywords": {"robot aspirador": 4}}, "keyword": {"plancha de pelo": {"ok": 0, "no": 3}}}
        rot = ba.rotation({"keywords": ["robot aspirador", "plancha de pelo", "freidora de aire"]}, learning, lap=1)
        self.assertEqual(rot.count("robot aspirador"), 2)
        self.assertNotIn("plancha de pelo", rot)  # vuelta impar: las rechazadas descansan
        self.assertIn("freidora de aire", rot)
