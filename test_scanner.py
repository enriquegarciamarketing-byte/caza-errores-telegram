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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import feeds
import milanuncios
import premium
import resale_market
import scanner
import vinted
import wallapop


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


def fake_wallapop(tg, cfg, state, cand, dry, test_private=False):
    cand["wallapop"] = {"ok": True, "price": 90.0, "count": 18, "roi": 0.40, "profit": 25.8}
    return True


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
        self.assertEqual(rules["min_price_eur"], 25)
        self.assertEqual(rules["min_saving_eur"], 30)
        self.assertEqual(rules["wallapop"]["min_listings"], 3)
        self.assertTrue(rules["estimate"]["enabled"])
        self.assertEqual(rules["wallapop"]["min_roi"], 0.25)
        self.assertEqual(rules["wallapop"]["min_roi_below"], 0.30)
        self.assertEqual(rules["wallapop"]["min_profit_eur"], 25)
        self.assertTrue(rules["require_priority"])
        self.assertIn("alfombrilla", rules["commodity_keywords"])
        self.assertIn("ps5", rules["priority"][1]["keywords"])
        self.assertEqual(rules["min_spain_points"], 15)
        self.assertEqual(rules["max_pvp_vs_avg"], 1.5)
        self.assertEqual(self.cfg["bargain_min_discount"], 30)
        self.assertEqual(self.cfg["bargain_min_reviews"], 20)
        self.assertEqual(self.cfg["error_min_discount"], 70)
        self.assertEqual(self.cfg["max_detail_fetches_per_run"], 25)
        self.assertTrue(any("/es/c/electronica/" in url for url in self.cfg["sources"]))
        self.assertTrue(any("/es/c/informatica/" in url for url in self.cfg["sources"]))
        self.assertIn("Amazon", rules["brands"])
        self.assertIn("Philips", rules["brands"])
        self.assertIn("Tineco", rules["brands"])
        self.assertNotIn("amazon", [item.lower() for item in rules["generic_brands"]])
        for banned in ("Lefant", "Cecotec", "Acclafit", "UJJ", "BVATE", "Haoyuyan", "Qecnato"):
            self.assertNotIn(banned, rules["brands"])
        self.assertIn("escritorio", rules["block_keywords"])
        self.assertIn("mesa", rules["block_keywords"])
        for word in ("iphone", "auriculares", "lego", "taladro", "ssd"):
            self.assertIn(word, rules["category_keywords"])
        for brand in ("Apple", "Samsung", "Dyson", "LEGO", "DeWalt"):
            self.assertIn(brand, rules["brands"])
        for blocked in ("perfume", "funda", "libro", "escritorio"):
            self.assertIn(blocked, rules["block_keywords"])
        self.assertNotIn("zapatillas", rules["block_keywords"])
        self.assertIn("zapatilla", rules["fashion_keywords"])

    def test_error_de_precio_de_marca_pasa(self):
        cand = deal(name="Apple iPhone 13 128 GB", title="Apple iPhone 13 128 GB", brand="Apple",
                    price=180, avg90=720, rating=3.0, reviews=2)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertEqual(category, "ERROR DE PRECIO")
        self.assertIn("reventa OK", reason)

    def test_error_barato_no_se_cuela(self):
        cand = deal(name="Apple iPhone SE", title="Apple iPhone SE", brand="Apple", price=19, avg90=200)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertIsNone(category)
        self.assertIn("mínimo de reventa", reason)

    def test_la_moda_no_esta_bloqueada_pero_la_talla_si(self):
        cand = deal(name="Skechers Og 85 Zapatillas", title="Skechers Mujer Zapatillas", brand="Skechers",
                    price=80, avg90=400)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertEqual(category, "ERROR DE PRECIO")
        self.assertIn("reventa OK", reason)

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
        self.assertIn("premium", reason)

    def test_sin_lista_de_categorias_un_proyector_o_un_frigorifico_pueden_seguir(self):
        projector = deal(name="Google TV Proyector Portatil", title="LYNCAST Google TV Proyector Portatil",
                         brand="LYNCAST", price=209.99, avg90=400.58, rating=4.4, reviews=80)
        category, reason = scanner.classify(self.cfg, projector)
        self.assertIsNone(category)
        self.assertIn("premium", reason)
        fridge = deal(name="Frigorífico Samsung RB38", title="Frigorífico Samsung RB38", brand="Samsung",
                      price=400, avg90=800)
        category, reason = scanner.classify(self.cfg, fridge)
        self.assertIsNone(category)
        self.assertIn("premium", reason)

    def test_dyson_fuera_de_tecnologia_si_pasa(self):
        cand = deal(name="Aspiradora sin cable V15", title="Aspiradora Dyson V15", brand="Dyson",
                    price=350, avg90=600)
        category, reason = scanner.classify(self.cfg, cand)
        self.assertEqual(category, "GANGA")
        self.assertIn("reventa OK", reason)

    def test_portatil_que_menciona_el_cable_si_pasa(self):
        cand = deal(name="MacBook Pro 14 con cable USB", title="MacBook Pro",
                    brand="Apple", price=450, avg90=800)
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
        self.assertIsNone(category)
        self.assertIn("premium", reason)
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

        passing = scanner.resale_check(self.cfg, deal(price=100, avg90=200))
        self.assertTrue(passing[0])

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
        category, reason = scanner.classify(self.cfg, cand)
        self.assertEqual(category, "ERROR DE PRECIO")
        with mock.patch.object(scanner, "resolve_asin", return_value=None):
            checked, why = scanner.quality_checks(cand, datetime.now(timezone.utc), category, reason)
        self.assertIsNone(checked)
        self.assertIn("ASIN", why)
        with mock.patch.object(scanner, "resolve_asin", return_value="B0TEST1234"):
            checked, why = scanner.quality_checks(dict(cand), datetime.now(timezone.utc), category, reason)
        self.assertEqual(checked, "ERROR DE PRECIO")

        absurd = deal(name="Apple iPhone 13", title="Apple iPhone 13", brand="Apple", price=40, avg90=800)
        absurd["modified"] = datetime.now(timezone.utc).isoformat()
        category, reason = scanner.classify(self.cfg, absurd)
        self.assertEqual(category, "ERROR DE PRECIO")
        checked, why = scanner.quality_checks(absurd, datetime.now(timezone.utc), category, reason)
        self.assertIsNone(checked)
        self.assertIn("92", why)


class HonestReferenceTest(unittest.TestCase):
    def test_con_grafico_usa_el_minimo_de_los_30_dias_previos_y_no_la_media(self):
        today = datetime.now(timezone.utc).date()
        days = lambda n: (today - timedelta(days=n)).isoformat()
        # Media inflada por picos de 1.999 €, pero hace 20 días estuvo a 799,99 €.
        series = [{"label": "Amazon ES", "flag": "/static/assets/flags/amazon.es.png",
                   "points": [[days(80), 1999.99], [days(50), 1299.99], [days(20), 799.99], [days(1), 379.98]]}]
        cand = deal(price=379.98, avg90=1019.76, series=series)
        self.assertEqual(scanner.market_reference(cand), 799.99)
        self.assertEqual(cand["ref_label"], "MÍNIMO 30 DÍAS ANTES")
        self.assertIn("30 días anteriores", cand["ref_text"])

    def test_sin_historial_no_hay_referencia_ni_publicacion(self):
        cand = deal(price=100, avg90=300, series=[])
        category, why = scanner.classify(load_cfg(), cand)
        self.assertIsNone(category)
        self.assertIn("30 días", why)


def chart(spain, europe=None, step_days=1) -> list[dict]:
    today = datetime.now(timezone.utc).date()

    def points(values):
        return [[(today - timedelta(days=index * step_days)).isoformat(), value] for index, value in enumerate(values)]

    series = [{"label": "Amazon ES", "flag": "/static/assets/flags/amazon.es.png", "points": points(spain)}]
    if europe:
        series.append({"label": "Amazon FR", "flag": "/static/assets/flags/amazon.fr.png", "points": points(europe)})
    return series


class MarketReferenceTest(unittest.TestCase):
    def setUp(self):
        self.cfg = load_cfg()

    def test_la_media_inflada_se_corrige_con_la_mediana_y_la_ue(self):
        cand = deal(price=40, avg90=200, series=chart([80] * 20, [70, 90]))
        category, reason = scanner.classify(self.cfg, cand)
        self.assertEqual(cand["reference_price"], 70)
        self.assertNotEqual(category, "ERROR DE PRECIO")
        self.assertEqual(category, "GANGA")
        self.assertIn("reventa OK", reason)

    def test_quince_puntos_y_pvp_hinchado(self):
        short = deal(price=40, avg90=160, series=chart([160] * 5))
        category, reason = scanner.classify(self.cfg, short)
        self.assertIsNone(category)
        self.assertIn("puntos de precio en España", reason)

        pvp = deal(price=80, avg90=140, was=220, series=chart([140] * 20))
        category, reason = scanner.classify(self.cfg, pvp)
        self.assertIsNone(category)
        self.assertIn("PVP", reason)

    def test_el_descuento_del_30_entra_y_el_margen_sigue_cortando(self):
        ganga = deal(price=65, avg90=100)
        category, reason = scanner.classify(self.cfg, ganga)
        self.assertEqual(category, "GANGA")
        self.assertIn("reventa OK", reason)
        tight = deal(price=70, avg90=100)
        category, reason = scanner.classify(self.cfg, tight)
        self.assertEqual(category, "GANGA")
        self.assertIn("reventa OK", reason)

    def test_veinte_opiniones_solo_si_la_marca_es_conocida(self):
        known = deal(reviews=20, rating=4.0, price=70, avg90=120)
        category, _reason = scanner.classify(self.cfg, known)
        self.assertEqual(category, "GANGA")
        few = deal(reviews=19, rating=4.2, price=70, avg90=120)
        category, reason = scanner.classify(self.cfg, few)
        self.assertIsNone(category)
        self.assertIn("valoraciones flojas", reason)
        unknown = deal(name="Auriculares Bluetooth", title="Auriculares Bluetooth", brand="MarcaInventada",
                       reviews=20, rating=4.5, price=70, avg90=120)
        category, reason = scanner.classify(self.cfg, unknown)
        self.assertIsNone(category)
        self.assertIn("premium", reason)

    def test_escritorio_mesa_y_adaptador_de_marca(self):
        desk = deal(name="Escritorio Corsair Platform 6 con soporte para monitor",
                    title="Escritorio gaming", brand="Corsair", price=180, avg90=320)
        category, reason = scanner.classify(self.cfg, desk)
        self.assertIsNone(category)
        self.assertIn("escritorio", reason)
        drive = deal(name="SanDisk SSD Disco Duro de Escritorio 4TB", title="Disco duro", brand="SanDisk",
                     price=120, avg90=200)
        category, reason = scanner.classify(self.cfg, drive)
        self.assertEqual(category, "GANGA")
        self.assertIn("reventa OK", reason)
        wifi = deal(name="Adaptador ASUS WiFi 7 PCIe", title="Adaptador WiFi 7", brand="ASUS", price=70, avg90=120)
        category, reason = scanner.classify(self.cfg, wifi)
        self.assertIsNone(category)
        self.assertIn("premium", reason)
        self.assertNotIn("adaptador", reason)
        coffee = deal(name="Cápsulas de café", title="Cápsulas de café", brand="Philips", price=40, avg90=80)
        category, reason = scanner.classify(self.cfg, coffee)
        self.assertIsNone(category)
        self.assertIn("cafe", reason)
        mic = deal(name="Cápsula de micrófono SteelSeries Alias", title="Micrófono", brand="SteelSeries",
                   price=90, avg90=160)
        category, reason = scanner.classify(self.cfg, mic)
        self.assertIsNone(category)
        self.assertIn("premium", reason)

    def test_echo_de_amazon_si_el_patinete_generico_no(self):
        echo = deal(name="Echo Dot (5.ª generación)", title="Echo Dot", brand="Amazon", price=49, avg90=90)
        category, reason = scanner.classify(self.cfg, echo)
        self.assertIsNone(category)
        self.assertIn("premium", reason)
        scooter = deal(name="Patinete eléctrico plegable", title="Patinete", brand="Acclafit", price=180, avg90=320)
        category, reason = scanner.classify(self.cfg, scooter)
        self.assertIsNone(category)
        self.assertIn("premium", reason)

    def test_otro_pais_barato_descarta_cualquier_descuento(self):
        cand = deal(price=50, avg90=100, series=chart([100] * 20, [52, 90]))
        now = datetime.now(timezone.utc)
        problem = scanner.history_problem(cand, now)
        self.assertIsNotNone(problem)
        self.assertIn("Amazon FR", problem)
        self.assertLess(cand["discount"] if cand.get("discount") else 0, 70)


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
        offers = []
        with mock.patch.object(scanner, "fetch", return_value=b"img"), \
             mock.patch.object(scanner, "create_price_card", side_effect=lambda offer: offers.append(offer) or Path("/tmp/card.jpg")), \
             mock.patch.object(scanner, "attach_wallapop", side_effect=fake_wallapop):
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
        self.assertEqual(offers[0]["resale"]["price"], 90)
        self.assertEqual(offers[0]["resale"]["count"], 18)
        self.assertEqual(offers[0]["resale"]["roi"], 40)
        self.assertEqual(offers[0]["ref_label"], "ANTES · PRECIO HABITUAL")
        self.assertIn("Wallapop", tg.photos[0]["caption"])

    def test_sin_ean_el_boton_sigue_siendo_de_afiliado(self):
        cfg = load_cfg()
        state = {"admin_chat_id": 7, "posts": [], "seen": {}}
        cand = deal(category="GANGA", discount=40, gtin=None, direct_url=None)
        tg = FakeTG()
        with mock.patch.object(scanner, "fetch", return_value=b"img"), \
             mock.patch.object(scanner, "create_price_card", return_value=Path("/tmp/card.jpg")), \
             mock.patch.object(scanner, "attach_wallapop", side_effect=fake_wallapop):
            ok = scanner.publish(tg, cfg, state, cand, "@caza_errores", False, test_private=True, preview=True)
        self.assertTrue(ok)
        url = tg.photos[0]["extra"]["reply_markup"]["inline_keyboard"][0][0]["url"]
        self.assertIn("https://www.amazon.es/s?k=", url)
        self.assertIn("tag=cazadores_errores-21", url)
        self.assertTrue(tg.photos[0]["caption"].startswith("🧪 PRUEBA · vista previa"))

    def test_publicacion_normal_sigue_yendo_al_canal_y_se_recuerda(self):
        cfg = load_cfg()
        state = {"admin_chat_id": 1880159117, "posts": [], "seen": {}}
        cand = deal(category="ERROR DE PRECIO", discount=75,
                    direct_url="https://www.amazon.es/dp/B0TEST1234?tag=cazadores_errores-21")
        tg = FakeTG()
        with mock.patch.object(scanner, "fetch", return_value=b"img"), \
             mock.patch.object(scanner, "create_price_card", return_value=Path("/tmp/card.jpg")), \
             mock.patch.object(scanner, "attach_wallapop", side_effect=fake_wallapop):
            ok = scanner.publish(tg, cfg, state, cand, "@caza_errores", False)
        self.assertTrue(ok)
        self.assertEqual(tg.photos[0]["chat_id"], "@caza_errores")
        self.assertIn("/dp/B0TEST1234", tg.photos[0]["extra"]["reply_markup"]["inline_keyboard"][0][0]["url"])
        self.assertFalse(tg.photos[0]["caption"].startswith("🧪"))
        self.assertEqual(tg.photos[1]["chat_id"], 1880159117)
        self.assertEqual(len(state["posts"]), 1)
        self.assertEqual(state["posts"][0]["id"], cand["id"])
        self.assertIn("tag=cazadores_errores-21", tg.photos[0]["extra"]["reply_markup"]["inline_keyboard"][0][0]["url"])
        self.assertEqual(state["seen"], {})

    def test_sin_producto_exacto_no_sale_al_canal_con_busqueda_por_ean(self):
        cfg = load_cfg()
        state = {"admin_chat_id": 1880159117, "posts": [], "seen": {}}
        cand = deal(category="ERROR DE PRECIO", discount=75)  # tiene EAN pero no ASIN
        tg = FakeTG()
        with mock.patch.object(scanner, "fetch", return_value=b"img"), \
             mock.patch.object(scanner, "create_price_card", return_value=Path("/tmp/card.jpg")), \
             mock.patch.object(scanner, "attach_wallapop", side_effect=fake_wallapop):
            scanner.publish(tg, cfg, state, cand, "@caza_errores", False)
        self.assertTrue(all(photo["chat_id"] != "@caza_errores" for photo in tg.photos))
        self.assertTrue(state["posts"][0].get("pending"))

    def test_segunda_lectura_con_otro_precio_no_publica(self):
        cfg = load_cfg()
        state = {"admin_chat_id": 7, "posts": [], "seen": {}}
        cand = deal(category="GANGA", discount=50, series=[],
                    direct_url="https://www.amazon.es/dp/B0TEST1234?tag=cazadores_errores-21")
        tg = FakeTG()
        with mock.patch.object(scanner, "fetch", return_value="html"), \
             mock.patch.object(scanner, "parse_detail", return_value={"price": 229.0, "in_stock": True}), \
             mock.patch.object(scanner, "attach_wallapop", side_effect=fake_wallapop):
            ok = scanner.publish(tg, cfg, state, cand, "@caza_errores", False)
        self.assertFalse(ok)
        self.assertEqual(tg.photos, [])

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

        def fake_lookup(cand, rules, state):
            if cand["id"] == "p1":
                return {"ok": True, "price": 80, "count": 6, "roi": 0.5, "profit": 30, "source_label": "WALLAPOP"}
            return {"ok": False, "prices": [], "transient": False, "reason": "pocos"}

        with mock.patch.object(scanner, "scan", side_effect=fake_scan), \
             mock.patch.object(scanner, "publish", side_effect=fake_publish), \
             mock.patch.object(scanner.resale_market, "lookup", side_effect=fake_lookup), \
             mock.patch.object(scanner, "preview_details_from_listings") as fallback:
            code = scanner.run_private_test(None, cfg, state, "@caza_errores", cli(dry_run=True, test_private=True),
                                            scanner.now_utc())
        self.assertEqual(code, 0)
        fallback.assert_not_called()
        self.assertEqual([item[0] for item in sent], ["p1"])
        self.assertTrue(sent[0][2] and sent[0][3])
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


class WallapopTest(unittest.TestCase):
    def setUp(self):
        self.rules = load_cfg()["resale"]["wallapop"]
        self.cand = {
            "name": "CORSAIR Vengeance LPX DDR4 RAM 16GB (2x8GB) 3200MHz CL16",
            "brand": "Corsair",
            "title": "Memoria RAM",
            "price": 64.2,
        }

    def listings(self):
        def item(title, amount, reserved=False):
            return {"title": title, "price": {"amount": amount, "currency": "EUR"}, "reserved": {"flag": reserved}}
        return [
            item("Memoria RAM Corsair Vengeance LPX 16GB DDR4", 90),
            item("Memoria RAM Corsair Vengeance LPX 16GB (2x8GB)", 85),
            item("Memoria RAM Corsair Vengeance LPX 16GB DDR4", 70),
            item("PC Gaming Ryzen 5 5600 | RX 6600 8GB | 16GB RAM", 749),
            item("Corsair Vengeance LPX 32GB DDR4 2400MHz RAM", 180),
            item("Memoria RAM Corsair Vengeance 16GB DDR4 3600MHz", 90),
            item("Memorias RAM Corsair Vengeance LPX 16GB DDR4", 120),
            item("Memoria RAM Corsair Vengeance LPX 16GB DDR4", 85),
            item("Corsair Vengeance LPX 16GB DDR4 3200", 95),
            item("Memoria RAM Corsair Vengeance LPX DDR4 16GB", 100),
            item("Memoria RAM Corsair Vengeance 16GB DDR4", 100),
            item("Funda Corsair Vengeance LPX 16GB DDR4", 15),
            item("Memoria RAM Corsair Vengeance LPX 16GB DDR4 reservada", 40, reserved=True),
        ]

    def test_filtra_pcs_otra_capacidad_fundas_y_calcula_la_mediana(self):
        prices = wallapop.matching_prices(self.cand, self.listings(), self.rules)
        self.assertNotIn(749, prices)
        self.assertNotIn(180, prices)
        self.assertNotIn(15, prices)
        self.assertNotIn(40, prices)
        result = wallapop.evaluate(self.cand, prices, self.rules)
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["count"], 5)
        self.assertGreaterEqual(result["price"], 80)
        self.assertLessEqual(result["price"], 100)
        self.assertGreaterEqual(result["roi"], 0.25)
        self.assertGreaterEqual(result["profit"], 15)

    def test_roi_insuficiente_no_publica(self):
        result = wallapop.evaluate({**self.cand, "price": 80}, [90] * 8, self.rules)
        self.assertFalse(result["ok"])
        self.assertIn("ROI", result["reason"])
        self.assertFalse(result["transient"])

    def test_pocos_anuncios(self):
        result = wallapop.evaluate(self.cand, [90, 90], self.rules)
        self.assertFalse(result["ok"])
        self.assertIn("mínimo", result["reason"])

    def test_la_cache_no_repite_la_peticion(self):
        state = {}
        calls = []

        def fake_fetch(keywords, rules):
            calls.append(keywords)
            return self.listings()

        rules = {**self.rules, "min_seconds_between_requests": 0}
        with mock.patch.object(wallapop, "fetch_items", side_effect=fake_fetch):
            first = wallapop.lookup(self.cand, rules, state)
            second = wallapop.lookup(self.cand, rules, state)
        self.assertTrue(first["ok"] and second["ok"])
        self.assertEqual(len(calls), 1)
        self.assertTrue(second.get("cached"))

    def test_la_consulta_es_marca_y_modelo_no_la_frase_entera(self):
        glorious = {"brand": "GLORIOUS", "name": "Alfombrilla de Tela para Gaming Bordes Cosidos LE"}
        self.assertEqual(wallapop.query_keywords(glorious, 3), "glorious alfombrilla")
        tommy = {"brand": "Tommy Hilfiger", "name": "Camisa Hombre Linen Solid Manga Corta"}
        self.assertEqual(wallapop.query_keywords(tommy, 3), "tommy hilfiger camisa")
        intex = {"brand": "Intex", "name": "Piscina, Flotador y Pelota Color con Accesorios"}
        self.assertEqual(wallapop.query_keywords(intex, 3), "intex piscina")
        nike = {"brand": "Nike", "name": "Zapatillas Air Force 1"}
        self.assertEqual(wallapop.query_keywords(nike, 3), "nike zapatillas")

    def test_el_boton_cambia_una_etiqueta_ajena(self):
        cfg = load_cfg()
        state = {"admin_chat_id": 1, "posts": [], "seen": {}}
        cand = deal(category="ERROR DE PRECIO", discount=63, price=64.2, avg90=173.51,
                    direct_url="https://www.amazon.es/dp/B07X1KT6LD?tag=otro-21", gtin=None)
        tg = FakeTG()
        with mock.patch.object(scanner, "fetch", return_value=b"img"), \
             mock.patch.object(scanner, "create_price_card", return_value=Path("/tmp/card.jpg")), \
             mock.patch.object(scanner, "attach_wallapop", side_effect=fake_wallapop):
            ok = scanner.publish(tg, cfg, state, cand, "@caza_errores", False)
        self.assertTrue(ok)
        url = tg.photos[0]["extra"]["reply_markup"]["inline_keyboard"][0][0]["url"]
        self.assertIn("tag=cazadores_errores-21", url)
        self.assertNotIn("otro-21", url)
        self.assertIn("/dp/B07X1KT6LD", url)
        self.assertIn("Wallapop", tg.photos[0]["caption"])

    def test_si_wallapop_falla_no_hay_tarjeta_y_se_avisa(self):
        cfg = load_cfg()
        state = {"admin_chat_id": 7, "posts": [], "seen": {"abc": {"price": 199, "t": 1, "result": "GANGA"}}}
        cand = deal(category="GANGA", discount=43)
        tg = FakeTG()
        tg.call = lambda method, params=None: {"message_id": 1} if method == "sendMessage" else (_ for _ in ()).throw(AssertionError(method))
        sent = []
        original = tg.call

        def record(method, params=None):
            sent.append((method, params))
            return original(method, params)

        tg.call = record
        down = {"ok": False, "transient": True, "prices": [], "reason": "no he podido consultar Wallapop (timeout)"}
        blocked = {"ok": False, "transient": False, "prices": [], "blocked": True,
                   "reason": "Milanuncios bloqueado (HTTP 403, 120 bytes)"}
        with mock.patch.object(wallapop, "lookup", return_value=down), \
             mock.patch.object(milanuncios, "lookup", return_value=blocked):
            ok = scanner.publish(tg, cfg, state, cand, "@caza_errores", False)
        self.assertFalse(ok)
        self.assertEqual(state["posts"], [])
        self.assertEqual(sent[0][0], "sendMessage")
        self.assertIn("Wallapop", sent[0][1]["text"])
        self.assertEqual(sent[0][1]["chat_id"], 7)
        scanner.note_wallapop_skip(state, cand)
        self.assertNotIn("abc", state["seen"])


class SecondHandSourcesTest(unittest.TestCase):
    def test_vinted_lee_precios_del_catalogo(self):
        page = '''<img alt="Nike Air Force 1 39 EU, Marca: Nike, Estado: Muy bueno, 32.00 €, 34.30 €" data-testid="product-item-id-1--image--img"/>
        <img alt="Funda Nike, Marca: Nike, Estado: Bueno, 5.00 €, 6.00 €"/>'''
        items = vinted.parse_catalog(page)
        self.assertEqual(items[0]["title"], "Nike Air Force 1 39 EU")
        self.assertEqual(items[0]["price"]["amount"], 32.0)
        self.assertEqual(len(items), 2)

    def test_milanuncios_detecta_el_bloqueo_y_lee_una_ficha(self):
        self.assertTrue(milanuncios.is_blocked("<html><title>Pardon Our Interruption</title></html>"))
        page = '''<a class="ma-AdCard-titleLink">iPhone 13 128GB</a><span class="ma-AdPrice">350 €</span>'''
        items = milanuncios.parse_listings(page)
        self.assertEqual(items[0]["title"], "iPhone 13 128GB")
        self.assertEqual(items[0]["price"]["amount"], 350.0)

    def test_la_moda_va_a_vinted_y_el_resto_a_wallapop(self):
        rules = load_cfg()["resale"]
        shoe = {"brand": "Nike", "name": "Zapatillas Air Force"}
        phone = {"brand": "Apple", "name": "iPhone 13 128GB"}
        watch = {"brand": "Apple", "name": "Apple Watch Series 9"}
        bag = {"brand": "Michael Kors", "name": "Bolso bandolera"}
        casio = {"brand": "Casio", "name": "Reloj de pulsera"}
        self.assertEqual(resale_market.source_order(shoe, rules), ["vinted", "wallapop", "milanuncios"])
        self.assertEqual(resale_market.source_order(bag, rules)[0], "vinted")
        self.assertEqual(resale_market.source_order(casio, rules)[0], "vinted")
        self.assertEqual(resale_market.source_order(phone, rules), ["wallapop", "milanuncios"])
        self.assertEqual(resale_market.source_order(watch, rules)[0], "wallapop")

    def test_junta_fuentes_y_etiqueta_el_panel(self):
        cand = {"brand": "Corsair", "name": "Vengeance LPX 16GB", "price": 64.2}

        def ok_prices(prices, label_ok=True):
            return {"ok": label_ok, "prices": prices, "transient": False, "blocked": False, "reason": ""}

        with mock.patch.object(resale_market.wallapop, "lookup", return_value=ok_prices([100, 100, 90, 110, 95])), \
             mock.patch.object(resale_market.milanuncios, "lookup", return_value=ok_prices([100, 105, 98])):
            result = resale_market.lookup(cand, load_cfg()["resale"], {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 8)
        self.assertGreaterEqual(result["profit"], 25)
        self.assertEqual(result["source_label"], "WALLAPOP+MILANUNCIOS")
        self.assertIn("Mediana de 8", result["note"])
        self.assertIn("Wallapop 5", result["note"])
        self.assertIn("Milanuncios 3", result["note"])

    def test_vista_previa_de_muestra_si_no_hay_anuncios(self):
        pool = [
            deal(id="pool", price=2.99, avg90=20, image="http://img", name="Intex Piscina flotador", brand="Intex"),
            deal(id="pad", price=12, avg90=30, image="http://img", name="Alfombrilla Glorious", brand="Glorious"),
            deal(id="ps5", price=450, avg90=549, image="http://img", name="PlayStation 5 Slim", brand="Sony",
                 reject="solo -10% bajo la media"),
        ]
        with mock.patch.object(scanner.resale_market, "lookup", return_value={"ok": False, "prices": [], "reason": "solo tiene 2 anuncios parecidos"}):
            chosen = scanner.choose_test_previews(pool, load_cfg(), {})
        self.assertEqual([item["id"] for item in chosen], ["ps5"])
        self.assertFalse(chosen[0].get("wallapop_sample"))
        self.assertIn("anuncios", chosen[0]["reject"])

    def test_una_fuente_bloqueada_no_tira_el_resto(self):
        cand = {"brand": "Corsair", "name": "Vengeance LPX 16GB", "price": 64.2}
        blocked = {"ok": False, "prices": [], "transient": False, "blocked": True,
                   "reason": "Milanuncios bloqueado (HTTP 200, 90000 bytes)"}
        prices = {"ok": False, "prices": [100, 100, 100, 110, 90, 95, 105, 100], "transient": False, "reason": ""}
        with mock.patch.object(resale_market.wallapop, "lookup", return_value=prices), \
             mock.patch.object(resale_market.milanuncios, "lookup", return_value=blocked):
            result = resale_market.lookup(cand, load_cfg()["resale"], {})
        self.assertTrue(result["ok"])
        self.assertEqual(result["source_label"], "WALLAPOP")
        self.assertEqual(result["count"], 8)
        self.assertGreaterEqual(result["profit"], 25)
        self.assertGreaterEqual(result["roi"], 0.25)

    def test_si_todo_falla_se_conserva_el_motivo_y_se_reintenta(self):
        cand = {"brand": "Sony", "name": "WH-1000XM5", "price": 180}
        down = {"ok": False, "prices": [], "transient": True, "reason": "no he podido consultar Wallapop (timeout)"}
        blocked = {"ok": False, "prices": [], "transient": False, "blocked": True,
                   "reason": "Milanuncios bloqueado (HTTP 403, 100 bytes)"}
        with mock.patch.object(resale_market.wallapop, "lookup", return_value=down), \
             mock.patch.object(resale_market.milanuncios, "lookup", return_value=blocked):
            result = resale_market.lookup(cand, load_cfg()["resale"], {})
        self.assertFalse(result["ok"])
        self.assertTrue(result["transient"])
        self.assertIn("no he podido consultar Wallapop", result["reason"])
        self.assertIn("Milanuncios bloqueado", result["reason"])

    def test_la_cache_recalcula_el_roi_si_cambia_el_precio(self):
        state = {}
        rules = load_cfg()["resale"]
        base = {"brand": "Corsair", "name": "Vengeance LPX 16GB", "price": 50}
        prices = {"ok": True, "prices": [100] * 8, "transient": False, "reason": ""}
        empty = {"ok": False, "prices": [], "transient": False, "reason": "sin anuncios"}
        with mock.patch.object(resale_market.wallapop, "lookup", return_value=prices) as wallapop_lookup, \
             mock.patch.object(resale_market.milanuncios, "lookup", return_value=empty):
            first = resale_market.lookup(base, rules, state)
            second = resale_market.lookup({**base, "price": 95}, rules, state)
        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])
        self.assertTrue(second.get("cached"))
        self.assertEqual(wallapop_lookup.call_count, 1)


class PremiumChannelTest(unittest.TestCase):
    def test_la_piscina_y_la_alfombrilla_no_pasan_y_la_ps5_si(self):
        cfg = load_cfg()
        pool = deal(name="Intex Piscina, Flotador y Pelota", brand="Intex", price=30, avg90=80)
        category, reason = scanner.classify(cfg, pool)
        self.assertIsNone(category)
        self.assertIn("poco valor", reason)
        pad = deal(name="Alfombrilla Glorious", brand="Glorious", price=40, avg90=90)
        category, reason = scanner.classify(cfg, pad)
        self.assertIsNone(category)
        shirt = deal(name="Camisa Tommy Hilfiger", brand="Tommy Hilfiger", price=40, avg90=90)
        category, reason = scanner.classify(cfg, shirt)
        self.assertIsNone(category)
        ps5 = deal(name="PlayStation 5 Slim", brand="Sony", price=400, avg90=800, title="PS5")
        category, reason = scanner.classify(cfg, ps5)
        self.assertEqual(category, "GANGA")
        laptop = deal(name="ASUS TUF Gaming A16 RTX 5070", title="Portátil RTX", brand="ASUS", price=1200, avg90=1800)
        category, _reason = scanner.classify(cfg, laptop)
        self.assertIsNone(category)

    def test_roi_del_30_por_ciento_bajo_60(self):
        rules = {**load_cfg()["resale"]["wallapop"], "min_profit_eur": 10, "min_listings": 8}
        cheap = wallapop.evaluate({"price": 50}, [64] * 8, rules)
        self.assertFalse(cheap["ok"])
        self.assertIn("30", cheap["reason"])
        richer = wallapop.evaluate({"price": 80}, [110] * 8, rules)
        self.assertTrue(richer["ok"])

    def test_sin_reservas_ni_volumen_no_hay_demanda(self):
        rules = {**load_cfg()["resale"]["wallapop"], "demand_many_listings": 12}  # la regla, con volumen exigido
        quiet = wallapop.evaluate({"price": 40}, [80] * 8, rules, reserved=0, demand_known=True)
        self.assertFalse(quiet["ok"])
        self.assertIn("demanda", quiet["reason"])
        busy = wallapop.evaluate({"price": 40}, [80] * 8, rules, reserved=2, demand_known=True)
        self.assertTrue(busy["ok"])
        self.assertEqual(busy["demand"], "Reservas recientes")

    def test_nota_escapada_y_boton_de_la_tienda(self):
        from publisher import build_caption
        text = build_caption(url="https://www.carrefour.es/p/switch", category="RESERVA COLECCIONISTA",
                             title="Switch 2 Zelda", current=499, reference=499, brand="Nintendo",
                             note="Edición <limitada>\nsegunda línea", hold=True)
        self.assertIn("Ver en Carrefour", text)
        self.assertIn("Edición &lt;limitada&gt;", text)
        self.assertIn("segunda línea", text)
        self.assertIn("Producto de colección / hold", text)
        self.assertLess(text.find("Edición"), text.find("Ver en Carrefour"))
        button = scanner.buttons_for("https://www.mediamarkt.es/es/product/1")["inline_keyboard"][0][0]["text"]
        self.assertEqual(button, "🛒 Ver en MediaMarkt")
        plain = premium.apply_store_template("https://www.fnac.es/a", {"store_affiliates": {"fnac": {"template": ""}}})
        self.assertEqual(plain, "https://www.fnac.es/a")
        wrapped = premium.apply_store_template("https://www.fnac.es/a", {"store_affiliates": {"fnac": {"template": "https://awin.example/?ued={url}"}}})
        self.assertTrue(wrapped.startswith("https://awin.example/?ued="))
        self.assertIn("fnac.es", wrapped)

    def test_rss_watchlist_y_dedupe(self):
        xml = '''<item><title><![CDATA[210° - Nintendo Switch 2 Edición Zelda]]></title>
        <link>https://www.chollometro.com/ofertas/switch-2-zelda-2047001</link>
        <category><![CDATA[Gaming]]></category>
        <pepper:merchant name="Carrefour" price="499,00€"/>
        <media:content url="https://img.example/z.jpg" medium="image"/></item>'''
        parsed = feeds.parse_rss(xml)
        self.assertEqual(parsed[0]["temperature"], 210)
        self.assertEqual(parsed[0]["price"], 499.0)
        self.assertEqual(parsed[0]["merchant"], "Carrefour")
        self.assertEqual(feeds.page_status("<button>Ya en reserva</button>"), "preorder")
        self.assertEqual(feeds.page_status("<button>Añadir a la cesta</button>"), "in_stock")
        self.assertEqual(feeds.page_status("Pardon Our Interruption"), "blocked")
        self.assertEqual(feeds.page_status("<p>Agotado</p>"), "out")
        page = 'linkCloakedItemMainButton":"https:\\/\\/www.chollometro.com\\/visit\\/threadmain\\/9"'
        with mock.patch.object(feeds, "_unwrap_visit", return_value="https://www.carrefour.es/p/switch"):
            self.assertEqual(feeds.resolve_deal_url(page), "https://www.carrefour.es/p/switch")
        a = {"brand": "Nintendo", "name": "Switch 2 Zelda", "watch_id": "switch2-zelda-40"}
        b = {"brand": "Nintendo", "name": "Switch 2 Zelda", "watch_id": "switch2-zelda-40"}
        self.assertEqual(premium.product_key(a), premium.product_key(b))
        self.assertTrue(premium.reserva_allowed({"collector": True, "justification": "Edición limitada de aniversario"}))
        self.assertFalse(premium.reserva_allowed({"collector": False, "justification": "Edición limitada de aniversario"}))


if __name__ == "__main__":
    unittest.main()
