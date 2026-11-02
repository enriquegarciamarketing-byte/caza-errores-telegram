"""Premium: errores de precio tipo Conga, pasadas seguidas y OK del administrador."""

import argparse
import time
import unittest
from datetime import datetime, timezone
from unittest import mock

import scanner
from test_scanner import FakeTG, deal, load_cfg


def ticket(jl_id, title, brand, price, was, verdict="Mínimo histórico", age_min=5):
    ts = int(time.time() - age_min * 60)
    return (f'<article class="ticket"><a href="/es/dp/{jl_id}/"></a><h2 class="tk-title">{title}</h2>'
            f'<a class="tk-brand" href="#">{brand}</a><span class="now">{price:.2f} €</span>'
            f'<span class="was">{was:.2f} €</span><span class="verdict">{verdict}</span>'
            f'<div data-timestamp="{ts}"></div></article>')


class RotationTest(unittest.TestCase):
    def test_cada_pasada_lee_las_fijas_y_unas_pocas_rotativas(self):
        cfg = {"sources": ["a", "b"], "rotating_sources": ["r1", "r2", "r3"], "rotating_sources_per_pass": 2}
        state = {}
        self.assertEqual(scanner.pass_sources(cfg, state), ["a", "b", "r1", "r2"])
        self.assertEqual(scanner.pass_sources(cfg, state), ["a", "b", "r3", "r1"])
        self.assertEqual(scanner.pass_sources(cfg, state), ["a", "b", "r2", "r3"])

    def test_config_real_tiene_hogar_y_bajadas_de_la_ultima_hora(self):
        cfg = load_cfg()
        self.assertIn("https://jimmyleaks.com/es/?order=-drop", cfg["sources"])
        self.assertTrue(any("hogar-y-cocina" in url for url in cfg["rotating_sources"]))
        self.assertNotIn("https://jimmyleaks.com/es/?order=-discount", cfg["sources"])


class ErrorLaneTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load_cfg()

    def test_bajada_grande_de_algo_caro_entra(self):
        item = {"price": 23.0, "was": 369.99, "verdict": "Mínimo histórico"}
        self.assertTrue(scanner.listing_error_lane(self.cfg, item))

    def test_bajada_grande_de_algo_barato_no(self):
        item = {"price": 7.26, "was": 29.99, "verdict": "Mínimo histórico"}
        self.assertFalse(scanner.listing_error_lane(self.cfg, item))

    def test_veredicto_de_jimmyleaks_cuenta(self):
        item = {"price": 30.0, "was": None, "verdict": "80% por debajo de la media"}
        self.assertTrue(scanner.listing_error_lane(self.cfg, item))

    def test_el_filtro_rapido_deja_pasar_la_conga_y_no_los_calcetines(self):
        page = (ticket("CONGA1", "Robot aspirador Conga 11090", "Cecotec", 23.0, 369.99)
                + ticket("FRY1", "Freidora de aire XXL", "Philips", 24.0, 199.0)
                + ticket("SOCK1", "6 pares calcetines deporte", "Generico", 7.26, 29.99)
                + ticket("TOAST1", "Tostadora 2 ranuras", "Taurus", 21.0, 30.0, verdict="10% por debajo de la media"))
        cfg = {**self.cfg, "sources": ["x"], "rotating_sources": [], "max_detail_fetches_per_run": 0}
        state = {"seen": {}}
        printed = []
        with mock.patch.object(scanner, "fetch", return_value=page), \
             mock.patch.object(scanner.time, "sleep"), \
             mock.patch.object(scanner.feeds, "amazon_hot_titles", return_value=[]), \
             mock.patch("builtins.print", side_effect=lambda *a, **k: printed.append(" ".join(map(str, a)))):
            scanner.scan(cfg, state, scanner.now_utc(), with_external=False)
        self.assertIn("Candidatos nuevos tras el filtro rápido: 2", printed)


class AskAdminTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load_cfg()
        self.state = {"admin_chat_id": 7, "posts": [], "seen": {}}

    def _ask(self, **extra):
        cand = deal(id="cm-123", category="OPORTUNIDAD DE REVENTA", price=399.0, avg90=599.0,
                    store_label="PcComponentes", direct_url="https://www.pccomponentes.com/rtx-5070",
                    needs_ok=True, ask_hours=3, series=None, discount=33.4, **extra)
        tg = FakeTG()
        with mock.patch.object(scanner, "fetch", return_value=b"img"), \
             mock.patch.object(scanner, "create_price_card", return_value="/tmp/card.jpg"), \
             mock.patch.object(scanner, "attach_wallapop", return_value=True):
            ok = scanner.publish(tg, self.cfg, self.state, cand, "@caza_errores", False)
        return ok, tg

    def test_no_sale_al_canal_te_llega_a_ti(self):
        ok, tg = self._ask()
        self.assertTrue(ok)
        self.assertEqual([p["chat_id"] for p in tg.photos], [7])
        self.assertIn("respóndeme OK", tg.photos[0]["caption"])
        post = self.state["posts"][0]
        self.assertTrue(post["pending"] and post["needs_ok"])
        self.assertIn("cm-123", self.state["asked"])

    def _reply(self, text, tg=None):
        tg = tg or FakeTG()
        update = {"update_id": 1, "message": {"chat": {"type": "private", "id": 7}, "message_id": 99,
                                               "text": text, "reply_to_message": {"message_id": 4242}}}
        tg.call = lambda method, params=None: ([update] if method == "getUpdates" else {"message_id": 5})
        scanner.handle_updates(tg, self.cfg, self.state, "@caza_errores", False)
        return tg

    def test_con_ok_se_publica_en_el_canal(self):
        self._ask()
        self._reply("ok")
        self.assertTrue(self.state["posts"][0].get("approved"))
        tg = FakeTG()
        tg.call = lambda method, params=None: {"message_id": 1}
        with mock.patch.object(scanner, "fetch", return_value=b"img"), \
             mock.patch.object(scanner, "create_price_card", return_value="/tmp/card.jpg"):
            scanner.publish_pending_from_reply(tg, self.state, "@caza_errores")
        self.assertEqual(tg.photos[0]["chat_id"], "@caza_errores")
        self.assertIn("pccomponentes.com", tg.photos[0]["extra"]["reply_markup"]["inline_keyboard"][0][0]["url"])
        self.assertFalse(self.state["posts"][0].get("pending"))
        self.assertEqual(self.state["posts"][0]["message_id"], 4242)

    def test_sin_ok_no_se_publica(self):
        self._ask()
        self._reply("me lo pienso")
        tg = FakeTG()
        scanner.publish_pending_from_reply(tg, self.state, "@caza_errores")
        self.assertEqual(tg.photos, [])

    def test_ok_tarde_no_publica(self):
        self._ask()
        self.state["posts"][0]["ask_until"] = time.time() - 10
        scanner.expire_asks(self.state)
        self._reply("ok")
        self.assertTrue(self.state["posts"][0].get("expired"))
        tg = FakeTG()
        scanner.publish_pending_from_reply(tg, self.state, "@caza_errores")
        self.assertEqual(tg.photos, [])

    def test_lo_pendiente_no_gasta_cupo_de_gangas(self):
        self._ask()
        cfg = {**self.cfg, "max_bargains_per_day": 1, "bargain_quiet_hours": [0, 0]}
        ok, why = scanner.allowed_to_post(cfg, self.state, deal(id="otro", category="GANGA"), scanner.now_utc())
        self.assertTrue(ok, why)

    def test_amazon_con_ok_se_relee_antes_de_publicar(self):
        self._ask()
        post = self.state["posts"][0]
        post.update(id="CONGA1", approved=True, url="https://www.amazon.es/dp/B0TEST1234?tag=cazadores_errores-21")
        tg = FakeTG()
        tg.call = lambda method, params=None: {"message_id": 1}
        with mock.patch.object(scanner, "recheck_listing", return_value="el precio ha cambiado (23 → 299)"):
            scanner.publish_pending_from_reply(tg, self.state, "@caza_errores")
        self.assertEqual(tg.photos, [])
        self.assertTrue(post.get("expired"))


class ExternalUnknownTest(unittest.TestCase):
    def test_tienda_que_bloquea_pasa_a_pendiente_de_ok(self):
        cfg = {**load_cfg(), "sources": [], "rotating_sources": []}
        state = {"seen": {}, "admin_chat_id": 7}
        ext = {"id": "cm-9", "name": "PlayStation 5 Slim", "title": "PlayStation 5 Slim", "brand": "",
               "price": 299.0, "image": "https://x/i.jpg", "direct_url": "https://es.aliexpress.com/item/1.html",
               "store_label": "AliExpress", "origin": "chollometro", "category": "OPORTUNIDAD DE REVENTA"}
        with mock.patch.object(scanner.feeds, "external_candidates", return_value=[ext]), \
             mock.patch.object(scanner.feeds, "store_price_check", return_value=("unknown", None)), \
             mock.patch.object(scanner.feeds, "amazon_hot_titles", return_value=[]):
            found = scanner.scan(cfg, state, scanner.now_utc())
        self.assertEqual(len(found), 1)
        self.assertTrue(found[0]["needs_ok"])

    def test_ya_preguntado_no_se_repite(self):
        cfg = {**load_cfg(), "sources": [], "rotating_sources": []}
        state = {"seen": {}, "admin_chat_id": 7, "asked": {"cm-9": time.time()}}
        ext = {"id": "cm-9", "name": "PlayStation 5 Slim", "title": "PlayStation 5 Slim", "brand": "",
               "price": 299.0, "image": "https://x/i.jpg", "direct_url": "https://es.aliexpress.com/item/1.html",
               "store_label": "AliExpress", "origin": "chollometro"}
        with mock.patch.object(scanner.feeds, "external_candidates", return_value=[ext]), \
             mock.patch.object(scanner.feeds, "store_price_check", return_value=("unknown", None)), \
             mock.patch.object(scanner.feeds, "amazon_hot_titles", return_value=[]):
            found = scanner.scan(cfg, state, scanner.now_utc())
        self.assertEqual(found, [])


class LoopTest(unittest.TestCase):
    def test_pasadas_hasta_el_limite_y_fuentes_externas_por_turnos(self):
        calls = []

        def fake_run_scan(tg, cfg, state, channel, args, now, with_external=True):
            calls.append(with_external)
            return 0

        clock = {"t": 1000.0}
        args = argparse.Namespace(dry_run=True, test_private=False, minutes=10, every=150)
        with mock.patch.object(scanner, "run_scan", side_effect=fake_run_scan), \
             mock.patch.object(scanner.time, "time", side_effect=lambda: clock["t"]), \
             mock.patch.object(scanner.time, "sleep", side_effect=lambda s: clock.__setitem__("t", clock["t"] + s)):
            scanner.run_loop(None, {"external_every_passes": 2}, {"posts": []}, "@x", args)
        self.assertEqual(len(calls), 4)  # 0, 150, 300, 450 s dentro de 600 s
        self.assertEqual(calls, [True, False, True, False])

    def test_sin_minutos_hace_una_sola_pasada(self):
        args = argparse.Namespace(dry_run=True, test_private=False, minutes=0, every=150)
        with mock.patch.object(scanner, "run_scan", return_value=0) as run:
            scanner.run_loop(None, {}, {"posts": []}, "@x", args)
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
