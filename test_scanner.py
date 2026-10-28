#!/usr/bin/env python3
"""Pruebas locales del filtro de reventa y del modo de prueba privada. No llama a Telegram."""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import scanner


ROOT = Path(__file__).resolve().parent
WORKFLOW = ROOT / ".github" / "workflows" / "scan-deals.yml"
MADRID = ZoneInfo("Europe/Madrid")


def load_cfg() -> dict:
    return json.loads(scanner.CONFIG_PATH.read_text(encoding="utf-8"))


def deal(**overrides) -> dict:
    base = {
        "id": "abc",
        "name": "Sony WH-1000XM5",
        "title": "Auriculares Sony WH-1000XM5",
        "brand": "Sony",
        "price": 199.0,
        "avg90": 349.0,
        "rating": 4.6,
        "reviews": 800,
        "image": "https://example.test/a.jpg",
        "gtin": "4548736132579",
        "in_stock": True,
    }
    base.update(overrides)
    base.setdefault("listing_price", base["price"])
    return base


def cli(**kwargs) -> argparse.Namespace:
    base = dict(dry_run=True, ignore_limits=False, test_private=False, manual_id="",
                manual_link="", edit_message=0, custom="")
    base.update(kwargs)
    return argparse.Namespace(**base)


class FakeTG:
    def __init__(self):
        self.photos = []
        self.methods = []

    def send_photo(self, chat_id, image, caption, extra=None):
        self.photos.append({"chat_id": chat_id, "caption": caption, "extra": extra or {}, "image": image})
        return {"message_id": 4242}

    def call(self, method, params=None):
        self.methods.append(method)
        if method == "getMe":
            return {"username": "caza_bot"}
        raise AssertionError(method)


class ResaleRulesTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load_cfg()

    def test_config_has_editable_resale_rules(self):
        rules = self.cfg["resale"]
        self.assertTrue(rules["enabled"])
        self.assertEqual(rules["min_price_eur"], 40)
        self.assertEqual(rules["min_saving_eur"], 30)
        self.assertEqual(rules["resale_factor"], 0.85)
        self.assertEqual(rules["min_margin"], 0.25)
        for word in ("iphone", "auriculares", "lego", "taladro", "ssd"):
            self.assertIn(word, rules["category_keywords"])
        for brand in ("Apple", "Samsung", "Dyson", "LEGO", "DeWalt"):
            self.assertIn(brand, rules["brands"])
        for blocked in ("zapatillas", "perfume", "funda", "libro"):
            self.assertIn(blocked, rules["block_keywords"])

    def test_error_de_precio_de_marca_pasa(self):
        cand = deal(name="Apple iPhone 13 128 GB", title="Apple iPhone 13 128 GB", brand="Apple",
                    price=180, avg90=720, rating=3.0, reviews=2)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertEqual(category, "ERROR DE PRECIO")
        self.assertIn("reventa OK", reason)

    def test_error_barato_no_se_cuela(self):
        cand = deal(name="Apple iPhone SE", title="Apple iPhone SE", brand="Apple", price=35, avg90=200)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertIsNone(category)
        self.assertIn("mínimo de reventa", reason)

    def test_zapatillas_aunque_sean_error_de_precio(self):
        cand = deal(name="Skechers Og 85 Zapatillas", title="Skechers Mujer Zapatillas", brand="Skechers",
                    price=80, avg90=400)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertIsNone(category)
        self.assertIn("zapatillas", reason)

    def test_tallas_se_rechazan(self):
        cand = deal(name="Nike Air, 42 EU", title="Nike Air, 42 EU", brand="Nike", price=80, avg90=200)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertIsNone(category)
        self.assertIn("tallas", reason)

    def test_auriculares_genericos(self):
        cand = deal(name="Auriculares Bluetooth 5.3", title="Auriculares Bluetooth 5.3", brand="",
                    price=50, avg90=120)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertIsNone(category)
        self.assertIn("marca", reason)

    def test_marca_mencionada_no_vale_si_el_producto_es_otro(self):
        cand = deal(name="Google TV Proyector Portatil", title="LYNCAST Google TV Proyector Portatil",
                    brand="LYNCAST", price=209.99, avg90=400.58, rating=4.4, reviews=80)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertIsNone(category)
        self.assertIn("marca", reason)

    def test_frigorifico_de_marca_tecnologica_no_pasa(self):
        cand = deal(name="Frigorífico Samsung RB38", title="Frigorífico Samsung RB38", brand="Samsung",
                    price=400, avg90=800)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertIsNone(category)
        self.assertIn("categoría", reason)

    def test_dyson_fuera_de_tecnologia_si_pasa(self):
        cand = deal(name="Aspiradora sin cable V15", title="Aspiradora Dyson V15", brand="Dyson",
                    price=350, avg90=600)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertEqual(category, "GANGA")
        self.assertIn("reventa OK", reason)

    def test_portatil_que_menciona_el_cable_si_pasa(self):
        cand = deal(name="Portátil Lenovo IdeaPad 15 con cable USB", title="Portátil Lenovo IdeaPad 15",
                    brand="Lenovo", price=450, avg90=800)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertEqual(category, "GANGA")
        self.assertIn("reventa OK", reason)

    def test_el_cable_en_si_no_pasa_aunque_sea_apple(self):
        cand = deal(name="Cable USB-C Apple", title="Cable USB-C Apple", brand="Apple", price=49, avg90=90)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertIsNone(category)
        self.assertIn("cable", reason)

    def test_funda_no_pasa_aunque_mencione_el_movil(self):
        cand = deal(name="Funda Sony para auriculares", title="Funda Sony", brand="Sony", price=49, avg90=90)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertIsNone(category)
        self.assertIn("funda", reason)

    def test_camara_con_acentos(self):
        cand = deal(name="Cámara mirrorless Canon EOS R50", title="Cámara Canon EOS R50", brand="Canon",
                    price=700, avg90=1200)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertEqual(category, "GANGA")
        self.assertIn("reventa OK", reason)

    def test_kindle_de_verdad_si_ebook_no(self):
        device = deal(name="Kindle Paperwhite 16 GB", title="Kindle Paperwhite 16 GB", brand="Amazon",
                      price=89, avg90=149)
        category, reason = scanner.classify(self.cfg, device)
        self.assertEqual(category, "GANGA")
        self.assertIn("reventa OK", reason)
        ebook = deal(name="Harry Potter versión Kindle", title="Harry Potter versión Kindle", brand="Amazon",
                     price=49, avg90=90)
        category, reason = scanner.classify(self.cfg, ebook)
        self.assertIsNone(category)
        book = deal(name="Novela de bolsillo", title="Novela de bolsillo", brand="Penguin", price=40, avg90=80)
        category, reason = scanner.classify(self.cfg, book)
        self.assertIsNone(category)
        self.assertIn("novela", reason)

    def test_ahorro_minimo_y_margen(self):
        tight = deal(price=40, avg90=69)
        category, reason = scanner.classify(self.cfg, tight)
        self.assertIsNone(category)
        self.assertIn("ahorro", reason)

        cfg = copy.deepcopy(self.cfg)
        cfg["resale"]["min_margin"] = 0.90
        priced = deal(price=100, avg90=180)
        category, reason = scanner.classify(cfg, priced)
        self.assertIsNone(category)
        self.assertIn("margen de reventa", reason)
        # (180 * 0.85 - 100) / 100 = 0.53, por debajo del 90 % forzado arriba.
        self.assertAlmostEqual((180 * 0.85 - 100) / 100, 0.53)

        passing = scanner.resale_check(self.cfg, deal(price=100, avg90=200))
        self.assertTrue(passing[0])
        cfg["resale"]["min_margin"] = 0.70
        at_floor = scanner.resale_check(cfg, deal(price=100, avg90=200))
        self.assertTrue(at_floor[0])
        cfg["resale"]["min_margin"] = 0.71
        over = scanner.resale_check(cfg, deal(price=100, avg90=200))
        self.assertFalse(over[0])

    def test_minimo_historico_sigue_siendo_la_etiqueta(self):
        cand = deal(price=200, avg90=400, low=200)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertEqual(category, "MÍNIMO HISTÓRICO")
        self.assertIn("reventa OK", reason)

    def test_reglas_apagadas_dejan_el_comportamiento_anterior(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["resale"]["enabled"] = False
        cand = deal(name="Skechers Zapatillas", title="Zapatillas", brand="Skechers", price=80, avg90=400)
        category, reason = scanner.classify(cfg, cand)
        self.assertEqual(category, "ERROR DE PRECIO")
        self.assertNotIn("reventa", reason)
        bare = copy.deepcopy(self.cfg)
        bare.pop("resale")
        category, reason = scanner.classify(bare, cand)
        self.assertEqual(category, "ERROR DE PRECIO")

    def test_descuento_bajo_y_valoraciones_no_cambian_de_mensaje(self):
        low = deal(price=90, avg90=100)
        category, reason = scanner.classify(self.cfg, low)
        self.assertIsNone(category)
        self.assertIn("solo -10%", reason)
        weak = deal(price=50, avg90=100, rating=3.1, reviews=4)
        category, reason = scanner.classify(self.cfg, weak)
        self.assertIsNone(category)
        self.assertIn("valoraciones flojas", reason)

    def test_controles_de_calidad_siguen_aplicados(self):
        cand = deal(name="Apple iPhone 13", title="Apple iPhone 13", brand="Apple", price=180, avg90=720, gtin="")
        cand["modified"] = datetime.now(timezone.utc).isoformat()
        cand["series"] = []
        category, reason = scanner.classify(self.cfg, cand)
        self.assertEqual(category, "ERROR DE PRECIO")
        checked, why = scanner.quality_checks(cand, datetime.now(timezone.utc), category, reason)
        self.assertIsNone(checked)
        self.assertIn("EAN", why)

        absurd = deal(name="Apple iPhone 13", title="Apple iPhone 13", brand="Apple", price=40, avg90=800)
        absurd["modified"] = datetime.now(timezone.utc).isoformat()
        absurd["series"] = []
        category, reason = scanner.classify(self.cfg, absurd)
        self.assertEqual(category, "ERROR DE PRECIO")
        checked, why = scanner.quality_checks(absurd, datetime.now(timezone.utc), category, reason)
        self.assertIsNone(checked)
        self.assertIn("92", why)


class ScheduleTest(unittest.TestCase):
    def test_la_noche_se_puede_ignorar_sin_republicar(self):
        cfg = load_cfg()
        now = datetime(2026, 1, 15, 3, 0, tzinfo=MADRID).astimezone(timezone.utc)
        cand = {"id": "a", "category": "GANGA", "price": 100, "gtin": "12345670"}
        blocked, why = scanner.allowed_to_post(cfg, {"posts": []}, cand, now)
        self.assertFalse(blocked)
        self.assertIn("nocturno", why)
        allowed, why = scanner.allowed_to_post(cfg, {"posts": []}, cand, now, ignore_schedule=True)
        self.assertTrue(allowed)
        self.assertEqual(why, "")
        state = {"posts": [{"id": "a", "gtin": "12345670", "price": 100, "t": now.timestamp(), "category": "GANGA"}]}
        again, why = scanner.allowed_to_post(cfg, state, cand, now, ignore_schedule=True)
        self.assertFalse(again)
        self.assertIn("recientemente", why)
        error = {"id": "e", "category": "ERROR DE PRECIO", "price": 100, "gtin": "999"}
        ok, _why = scanner.allowed_to_post(cfg, {"posts": []}, error, now)
        self.assertTrue(ok)


class PrivateModeTest(unittest.TestCase):
    def test_parser_flag_and_manual_link_optional(self):
        self.assertFalse(scanner.build_parser().parse_args([]).test_private)
        self.assertTrue(scanner.build_parser().parse_args(["--test-private"]).test_private)
        args = scanner.build_parser().parse_args(["--manual-id", "abc"])
        self.assertEqual(args.manual_id, "abc")
        self.assertEqual(args.manual_link, "")
        with self.assertRaises(SystemExit):
            scanner.build_parser().parse_args(["--manual-link"])

    def test_caption_y_previews(self):
        cand = deal(category="GANGA", discount=43)
        text = scanner.private_caption("https://www.amazon.es/s?k=1&tag=cazadores_errores-21", cand, False)
        self.assertTrue(text.startswith("🧪 PRUEBA\n"))
        self.assertIn("Ver en Amazon", text)
        preview = scanner.private_caption("https://www.amazon.es/s?k=1&tag=x", {**cand, "reject": "marca <genérica>"}, True)
        self.assertTrue(preview.startswith("🧪 PRUEBA · vista previa"))
        self.assertIn("marca &lt;genérica&gt;", preview)

        pool = [
            deal(id="low", price=50, avg90=70, image="http://img"),
            deal(id="high", price=40, avg90=100, image="http://img"),
            deal(id="mid", price=80, avg90=140, image="http://img"),
            deal(id="noimg", price=30, avg90=90, image=None),
            deal(id="high", price=10, avg90=90, image="http://img"),
            deal(id="fourth", price=60, avg90=90, image="http://img"),
            deal(id="noref", price=40, avg90=40, was=None, image="http://img"),
        ]
        picked = scanner.select_previews(pool, 3)
        self.assertEqual([item["id"] for item in picked], ["high", "mid", "fourth"])
        prepared = scanner.prepare_preview({"id": "w", "price": 50, "was": 80, "image": "http://img", "name": "X"}, load_cfg())
        self.assertEqual(prepared["avg90"], 80)
        self.assertEqual(prepared["category"], "GANGA")
        self.assertIn("tachado", prepared["ref_text"])

    def test_publish_privado_no_toca_estado_ni_el_canal(self):
        cfg = load_cfg()
        state = {"admin_chat_id": 1880159117, "posts": [{"id": "old"}], "seen": {"keep": 1}}
        before = copy.deepcopy(state)
        cand = deal(category="GANGA", discount=43)
        tg = FakeTG()
        with mock.patch.object(scanner, "fetch", return_value=b"img"), \
             mock.patch.object(scanner, "create_price_card", return_value=Path("/tmp/card.jpg")):
            ok = scanner.publish(tg, cfg, state, cand, "@caza_errores", False, test_private=True)
        self.assertTrue(ok)
        self.assertEqual(len(tg.photos), 1)
        self.assertEqual(tg.photos[0]["chat_id"], 1880159117)
        self.assertNotEqual(tg.photos[0]["chat_id"], "@caza_errores")
        self.assertTrue(tg.photos[0]["caption"].startswith("🧪 PRUEBA\n"))
        self.assertIn("Ver en Amazon", tg.photos[0]["caption"])
        button = tg.photos[0]["extra"]["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual(button["text"], "🛒 Ver en Amazon")
        self.assertIn("tag=cazadores_errores-21", button["url"])
        self.assertIn(cand["gtin"], button["url"])
        self.assertNotIn("disable_notification", tg.photos[0]["extra"])
        self.assertEqual(state, before)
        self.assertEqual(tg.methods, [])

    def test_sin_ean_el_boton_sigue_siendo_de_afiliado(self):
        cfg = load_cfg()
        state = {"admin_chat_id": 7, "posts": [], "seen": {}}
        cand = deal(category="GANGA", discount=40, gtin=None, direct_url=None)
        tg = FakeTG()
        with mock.patch.object(scanner, "fetch", return_value=b"img"), \
             mock.patch.object(scanner, "create_price_card", return_value=Path("/tmp/card.jpg")):
            ok = scanner.publish(tg, cfg, state, cand, "@caza_errores", False, test_private=True, preview=True)
        self.assertTrue(ok)
        url = tg.photos[0]["extra"]["reply_markup"]["inline_keyboard"][0][0]["url"]
        self.assertIn("https://www.amazon.es/s?k=", url)
        self.assertIn("tag=cazadores_errores-21", url)
        self.assertTrue(tg.photos[0]["caption"].startswith("🧪 PRUEBA · vista previa"))

    def test_publicacion_normal_sigue_yendo_al_canal_y_se_recuerda(self):
        cfg = load_cfg()
        state = {"admin_chat_id": 1880159117, "posts": [], "seen": {}}
        cand = deal(category="ERROR DE PRECIO", discount=75)
        tg = FakeTG()
        with mock.patch.object(scanner, "fetch", return_value=b"img"), \
             mock.patch.object(scanner, "create_price_card", return_value=Path("/tmp/card.jpg")):
            ok = scanner.publish(tg, cfg, state, cand, "@caza_errores", False)
        self.assertTrue(ok)
        self.assertEqual(tg.photos[0]["chat_id"], "@caza_errores")
        self.assertFalse(tg.photos[0]["caption"].startswith("🧪"))
        self.assertEqual(tg.photos[1]["chat_id"], 1880159117)
        self.assertEqual(len(state["posts"]), 1)
        self.assertEqual(state["posts"][0]["id"], cand["id"])
        self.assertEqual(state["seen"], {})

    def test_run_scan_normal_no_pasa_el_saco_de_previas(self):
        calls = []

        def fake_scan(*args, **kwargs):
            calls.append((args, kwargs))
            return []

        with mock.patch.object(scanner, "scan", side_effect=fake_scan):
            code = scanner.run_scan(None, load_cfg(), {"seen": {}, "posts": []}, "@caza_errores",
                                    cli(test_private=False), scanner.now_utc())
        self.assertEqual(code, 0)
        self.assertEqual(len(calls[0][0]), 3)
        self.assertEqual(calls[0][1], {})

    def test_vista_previa_si_nadie_cumple_y_no_mancha_el_estado(self):
        cfg = load_cfg()
        state = {"admin_chat_id": 5, "seen": {"keep": {"price": 1, "t": 1, "result": "ya"}}, "posts": []}
        snapshot = copy.deepcopy(state)
        pool = [deal(id=f"p{i}", price=40 + i, avg90=100, image="http://img", reject="solo -10% bajo la media")
                for i in range(4)]

        def fake_scan(_cfg, st, _now, extras=None):
            st["seen"]["NEW"] = {"price": 1, "t": 1, "result": "no"}
            st["posts"].append({"id": "touched"})
            extras["pool"] = pool
            extras["listings"] = [{"id": "no-fetch", "price": 10, "was": 20}]
            return []

        sent = []

        def fake_publish(_tg, _cfg, _state, cand, channel, dry, link_override=None, test_private=False, preview=False):
            sent.append((cand["id"], channel, test_private, preview, dry))
            return True

        with mock.patch.object(scanner, "scan", side_effect=fake_scan), \
             mock.patch.object(scanner, "publish", side_effect=fake_publish), \
             mock.patch.object(scanner, "preview_details_from_listings") as fallback:
            code = scanner.run_private_test(None, cfg, state, "@caza_errores", cli(dry_run=True, test_private=True),
                                            scanner.now_utc())
        self.assertEqual(code, 0)
        fallback.assert_not_called()
        self.assertEqual(len(sent), 3)
        self.assertTrue(all(item[2] and item[3] and item[1] == "@caza_errores" for item in sent))
        self.assertEqual(state, snapshot)

    def test_de_noche_la_prueba_si_envia_la_ganga(self):
        cfg = load_cfg()
        cand = deal(category="GANGA", discount=45)
        now = datetime(2026, 1, 15, 3, 0, tzinfo=MADRID).astimezone(timezone.utc)

        def fake_scan(_cfg, _st, _now, extras=None):
            extras["pool"] = []
            extras["listings"] = []
            return [cand]

        with mock.patch.object(scanner, "scan", side_effect=fake_scan), \
             mock.patch.object(scanner, "publish", return_value=True) as pub:
            code = scanner.run_private_test(FakeTG(), cfg, {"admin_chat_id": 1, "posts": [], "seen": {}},
                                            "@caza_errores", cli(dry_run=False, test_private=True), now)
        self.assertEqual(code, 0)
        self.assertEqual(pub.call_count, 1)
        self.assertTrue(pub.call_args.kwargs["test_private"])
        self.assertFalse(pub.call_args.kwargs.get("preview", False))

    def test_main_no_guarda_ni_lee_updates(self):
        cfg = load_cfg()
        state = {"seen": {"keep": {"price": 3, "t": 1, "result": "ya"}}, "posts": [{"id": "old"}],
                 "tg_offset": 42, "admin_chat_id": 1880159117}
        snapshot = copy.deepcopy(state)

        def loader(path, default):
            if path == scanner.CONFIG_PATH:
                return cfg
            if path == scanner.STATE_PATH:
                return state
            return default

        def fake_scan(_cfg, st, _now, extras=None):
            st["seen"]["NEW"] = {"price": 1, "t": 1, "result": "no"}
            st["tg_offset"] = 999
            if extras is not None:
                extras["pool"] = []
                extras["listings"] = []
            return []

        tg = FakeTG()
        argv = ["scanner.py", "--test-private", "--dry-run"]
        with mock.patch.object(scanner, "load_json", side_effect=loader), \
             mock.patch.object(scanner, "save_state") as save, \
             mock.patch.object(scanner, "handle_updates") as updates, \
             mock.patch.object(scanner, "publish_pending_from_reply") as pending, \
             mock.patch.object(scanner, "scan", side_effect=fake_scan), \
             mock.patch.object(scanner, "Telegram", return_value=tg), \
             mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "@caza_errores"}), \
             mock.patch.object(sys, "argv", argv):
            code = scanner.main()
        self.assertEqual(code, 0)
        save.assert_not_called()
        updates.assert_not_called()
        pending.assert_not_called()
        self.assertEqual(tg.methods, ["getMe"])
        self.assertEqual(state, snapshot)

    def test_sin_token_o_sin_admin_no_hay_nada_que_guardar(self):
        cfg = load_cfg()
        state = {"seen": {}, "posts": [], "tg_offset": 0, "admin_chat_id": 5}

        def loader(path, default):
            return cfg if path == scanner.CONFIG_PATH else state if path == scanner.STATE_PATH else default

        with mock.patch.object(scanner, "load_json", side_effect=loader), \
             mock.patch.object(scanner, "save_state") as save, \
             mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}, clear=False), \
             mock.patch.object(sys, "argv", ["scanner.py", "--test-private"]):
            self.assertEqual(scanner.main(), 2)
        save.assert_not_called()

        no_admin = {"seen": {}, "posts": [], "tg_offset": 3}

        def loader_no_admin(path, default):
            return cfg if path == scanner.CONFIG_PATH else no_admin if path == scanner.STATE_PATH else default

        tg = FakeTG()
        with mock.patch.object(scanner, "load_json", side_effect=loader_no_admin), \
             mock.patch.object(scanner, "save_state") as save, \
             mock.patch.object(scanner, "Telegram", return_value=tg), \
             mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:abc"}, clear=False), \
             mock.patch.object(sys, "argv", ["scanner.py", "--test-private"]):
            self.assertEqual(scanner.main(), 2)
        save.assert_not_called()
        self.assertEqual(tg.methods, [])

    def test_manual_privado_no_guarda(self):
        cfg = load_cfg()
        state = {"admin_chat_id": 7, "posts": [], "seen": {}}
        detail = {"name": "Apple iPhone 13", "brand": "Apple", "price": 180, "avg90": 720,
                  "in_stock": True, "image": "http://x", "gtin": "1234567890123", "rating": 4.5, "reviews": 100}
        with mock.patch.object(scanner, "fetch", return_value="html"), \
             mock.patch.object(scanner, "parse_detail", return_value=detail), \
             mock.patch.object(scanner, "publish", return_value=True) as pub, \
             mock.patch.object(scanner, "save_state") as save:
            code = scanner.publish_manual(FakeTG(), cfg, state, "@caza_errores", "abc12",
                                          "https://amzn.eu/d/abc", False, True)
        self.assertEqual(code, 0)
        save.assert_not_called()
        self.assertTrue(pub.call_args.kwargs["test_private"])
        self.assertEqual(state["posts"], [])


class WorkflowTest(unittest.TestCase):
    def test_workflow_declara_el_modo_y_no_pasa_un_enlace_vacio(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("test_private:", text)
        self.assertRegex(
            text,
            r"test_private:\n\s+description:.*\n\s+required: false\n\s+type: boolean\n\s+default: false",
        )
        self.assertIn('if [ "${{ inputs.test_private }}" = "true" ]; then ARGS+=(--test-private); fi', text)
        self.assertIn('if [ -n "$MANUAL_ID" ]; then ARGS+=(--manual-id "$MANUAL_ID"); fi', text)
        self.assertIn('if [ -n "$MANUAL_LINK" ]; then ARGS+=(--manual-link "$MANUAL_LINK"); fi', text)
        self.assertNotIn("--manual-link $MANUAL_LINK", text)
        self.assertIn("inputs.test_private != true", text)
        self.assertIn("La prueba privada no admite un post custom", text)

    def test_bash_no_anade_manual_link_vacio(self):
        script = r"""
set -euo pipefail
build() {
  MANUAL_ID="$1"
  MANUAL_LINK="$2"
  ARGS=()
  if [ -n "$MANUAL_ID" ]; then ARGS+=(--manual-id "$MANUAL_ID"); fi
  if [ -n "$MANUAL_LINK" ]; then ARGS+=(--manual-link "$MANUAL_LINK"); fi
  printf '%s\n' "${ARGS[@]}"
}
build "abc" ""
echo "---"
build "abc" "https://amzn.eu/d/xyz"
"""
        result = subprocess.run(["bash", "-lc", script], check=True, capture_output=True, text=True)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "--manual-id")
        self.assertEqual(lines[1], "abc")
        self.assertNotIn("--manual-link", lines[:2])
        self.assertEqual(lines[3:], ["--manual-id", "abc", "--manual-link", "https://amzn.eu/d/xyz"])


if __name__ == "__main__":
    unittest.main()
