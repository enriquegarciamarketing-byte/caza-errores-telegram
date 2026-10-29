#!/usr/bin/env python3
"""Canal normal: formato, filtros, afiliado y workflow. No llama a Telegram ni a la red."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import affiliate
import feeds
import generic
from publisher import build_deal_caption, deal_badge as generic_badge, deal_closer, euro

ROOT = Path(__file__).resolve().parent
MADRID = ZoneInfo("Europe/Madrid")
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


def at_madrid(hour: int) -> datetime:
    return datetime(2026, 10, 28, hour, 30, tzinfo=MADRID).astimezone(timezone.utc)


class FormatTest(unittest.TestCase):
    def test_bloque_de_precio_con_pvp(self):
        text = build_deal_caption(
            url="https://www.amazon.es/dp/B0H8T5GC4W?tag=cazadores_errores-21",
            title="Portátil ASUS TUF Gaming A16",
            current=223.71,
            previous=1149.50,
            store="Amazon",
            temperature=357,
        )
        self.assertIn("❌ PVP Amazon: <s>1.149,50 €</s>", text)
        self.assertIn("💰 AHORA: 223,71 €", text)
        self.assertIn("📉 −81 % sobre PVP", text)
        self.assertIn("🤑 Te ahorras: 925,79 €", text)
        self.assertIn("Se ha colado un precio", text)
        self.assertEqual(generic_badge("Portátil ASUS TUF Gaming A16", 223.71, 1149.50), "ERROR DE PRECIO")
        self.assertIn("Ver en Amazon", text)
        self.assertNotIn("ROI", text)
        self.assertNotIn("Wallapop", text)
        self.assertNotIn("º", text)
        self.assertNotIn("357", text)
        self.assertNotIn("Chollometro", text)
        self.assertEqual(euro(925.79), "925,79 €")

    def test_sin_pvp_solo_ahora(self):
        text = build_deal_caption(url="https://www.mediamarkt.es/p/1", title="Auriculares",
                                  current=49.9, previous=None, store="MediaMarkt", temperature=90)
        self.assertIn("💰 AHORA: 49,90 €", text)
        self.assertNotIn("PVP", text)
        self.assertNotIn("Te ahorras", text)
        self.assertNotIn("Se ha colado un precio", text)
        self.assertNotIn("º", text)
        self.assertNotIn("90", text.split("49,90")[-1])

    def test_titular_y_cierre_segun_categoria(self):
        trip = build_deal_caption(url="https://www.carrefour.es/viaje", title="Viaje a Egipto 8 días con vuelos",
                                  current=468, previous=900, store="Carrefour")
        self.assertIn("✈️", trip)
        self.assertIn("Chollo de viaje", trip)
        self.assertNotIn("Se ha colado un precio", trip)
        self.assertEqual(generic_badge("Viaje a Egipto 8 días", 468, 900), "VIAJE")
        chollo = build_deal_caption(url="https://www.fnac.es/p/1", title="Auriculares Sony",
                                    current=49, previous=70, store="Fnac")
        self.assertIn("Chollo", chollo)
        self.assertNotIn("Chollazo", chollo)
        self.assertNotIn("Se ha colado un precio", chollo)
        self.assertEqual(generic_badge("Auriculares Sony", 49, 70), "CHOLLO")
        chollazo = build_deal_caption(url="https://www.fnac.es/p/2", title="Cafetera",
                                      current=80, previous=160, store="Fnac")
        self.assertIn("Chollazo", chollazo)
        self.assertNotIn("Se ha colado un precio", chollazo)
        self.assertEqual(generic_badge("Cafetera", 80, 160), "CHOLLAZO")
        minimo = build_deal_caption(url="https://www.amazon.es/dp/B0TEST0001?tag=cazadores_errores-21",
                                    title="Monitor", current=120, previous=180, store="Amazon", origin="minimos")
        self.assertIn("Precio mínimo", minimo)
        self.assertEqual(generic_badge("Monitor", 120, 180, origin="minimos"), "PRECIO MÍNIMO")
        self.assertNotIn("no lo dejes escapar", trip)
        self.assertNotIn("no lo dejes escapar", chollo)
        self.assertNotIn("no lo dejes escapar", chollazo)
        self.assertNotIn("no lo dejes escapar", minimo)
        closers = {
            deal_closer("Viaje a Roma 4 días", "viaje"),
            deal_closer("Portátil", "error"),
            deal_closer("Monitor", "minimo"),
            deal_closer("Cafetera", "chollazo"),
            deal_closer("Auriculares", "chollo"),
        }
        self.assertGreaterEqual(len(closers), 4)
        titled = build_deal_caption(url="https://www.fnac.es/p/3", title="Error de precio en la batidora",
                                    current=40, previous=55, store="Fnac")
        self.assertIn("Se ha colado un precio", titled)
        self.assertEqual(generic_badge("Error de precio en la batidora", 40, 55), "ERROR DE PRECIO")


class CardTest(unittest.TestCase):
    def test_viaje_sin_foto_y_chollo_con_pvp(self):
        from publisher import create_deal_card
        with mock.patch("destinations.destination_image", return_value=None):
            trip = create_deal_card({
                "id": "test-viaje",
                "title": "Viaje a Egipto 8 días con vuelos",
                "current": 468,
                "previous": 900,
                "store": "Carrefour",
            })
        solo = create_deal_card({
            "id": "test-solo-ahora",
            "title": "Auriculares sin PVP",
            "current": 49.9,
            "previous": None,
            "store": "Fnac",
            "image_path": ROOT / "images" / "taurus-radiador-hq.jpg",
        })
        self.assertTrue(trip.exists() and solo.exists())
        self.assertGreater(trip.stat().st_size, 8000)
        viaje = {"title": "Viaje a Egipto 8 días", "price": 468, "temperature": 200,
                 "link": "https://www.chollometro.com/ofertas/egipto-2047741", "published": ""}
        self.assertEqual(generic.reject_feed(viaje, CFG["generic"], at_madrid(12), set()), "")


class DestinationTest(unittest.TestCase):
    def test_detecta_egipto_paris_y_roma_y_no_un_trozo_de_palabra(self):
        import destinations
        self.assertEqual(destinations.match_destination("Viaje a Egipto 8 días")["wiki"], "Pirámides de Guiza")
        self.assertEqual(destinations.match_destination("Fin de semana en París")["file"], "Tour_Eiffel_Wikimedia_Commons.jpg")
        self.assertIn("Colosseum", destinations.match_destination("Roma en 4 días")["file"])
        self.assertIsNone(destinations.match_destination("Viaje del aroma"))
        self.assertIsNone(destinations.match_destination("Escapada sorpresa"))
        # La ciudad gana al país.
        self.assertIn("Colosseum", destinations.match_destination("Roma, Italia")["file"])

    def test_cache_y_wikipedia_si_commons_falla(self):
        import io
        import destinations
        from PIL import Image
        buffer = io.BytesIO()
        Image.new("RGB", (400, 300), (30, 90, 160)).save(buffer, format="JPEG", quality=85)
        blob = buffer.getvalue()
        self.assertGreater(len(blob), 2000)
        calls = []

        def fake_get(url, timeout=25):
            calls.append(url)
            if "Special:FilePath" in url:
                return None
            return blob

        summary = json.dumps({"thumbnail": {"source": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a/320px-X.jpg"}}).encode()

        class Resp:
            headers = {"content-type": "application/json"}
            def read(self):
                return summary
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with mock.patch.object(destinations, "_get", side_effect=fake_get), \
                 mock.patch.object(destinations.urllib.request, "urlopen", return_value=Resp()):
                first = destinations.destination_image("Viaje a Egipto", folder)
                second = destinations.destination_image("Egipto en 8 días", folder)
            self.assertIsNotNone(first)
            self.assertEqual(first, second)
            self.assertTrue(any("1600px-" in url for url in calls))
            self.assertEqual(sum("Special:FilePath" in url for url in calls), 1)


class PhotoSourceTest(unittest.TestCase):
    def test_pide_la_imagen_grande(self):
        import photos
        amazon = photos.source_candidates("https://m.media-amazon.com/images/I/71abc._AC_SX300_SY300_.jpg")
        self.assertEqual(amazon[0], "https://m.media-amazon.com/images/I/71abc.jpg")
        chollo = photos.source_candidates(
            "https://static.chollometro.com/threads/raw/zFfzq/2047812_1/re/150x150/qt/55/2047812_1.jpg")
        self.assertEqual(chollo[0], "https://static.chollometro.com/threads/raw/zFfzq/2047812_1/2047812_1.jpg")
        wiki = photos.source_candidates("https://upload.wikimedia.org/wikipedia/commons/thumb/a/a/320px-X.jpg")
        self.assertIn("1600px-", wiki[0])

    def test_amplia_con_lanczos_si_no_hay_modelo(self):
        import photos
        from PIL import Image
        small = Image.new("RGB", (80, 60), (20, 80, 140))
        with mock.patch.object(photos, "_neural", return_value=None):
            bigger = photos.upscale(small, 3)
        self.assertGreaterEqual(bigger.width, 230)
        self.assertGreaterEqual(bigger.height, 170)


class ProductPhotoTest(unittest.TestCase):
    def test_recorta_el_margen_blanco_y_agranda_el_producto(self):
        from PIL import Image, ImageDraw
        from publisher import _trim_margins
        canvas = Image.new("RGB", (400, 300), (255, 255, 255))
        ImageDraw.Draw(canvas).rectangle((140, 80, 260, 220), fill=(30, 30, 30))
        trimmed = _trim_margins(canvas)
        self.assertLess(trimmed.width, 160)
        self.assertLess(trimmed.height, 180)
        self.assertGreater(trimmed.width, 100)


class LinkTest(unittest.TestCase):
    def test_amazon_sustituye_el_tag_ajeno_y_comprueba_el_asin(self):
        url = affiliate.clean_store_url(
            "https://www.amazon.es/dp/B0H8T5GC4W?tag=otro-21&utm_source=afiliado",
            CFG, expected_asin="B0H8T5GC4W",
        )
        self.assertIn("tag=cazadores_errores-21", url)
        self.assertNotIn("otro-21", url)
        self.assertNotIn("utm_source", url)
        self.assertIsNone(affiliate.clean_store_url(
            "https://www.amazon.es/dp/B0OTROASIN?tag=cazadores_errores-21",
            CFG, expected_asin="B0H8T5GC4W",
        ))

    def test_otra_tienda_se_desenvolve_y_pierde_el_afiliado(self):
        wrapped = ("https://www.awin1.com/cread.php?awinmid=1&ued="
                   "https%3A%2F%2Fwww.mediamarkt.es%2Fes%2Fproduct%2F123%3Futm_source%3Dawin%26awc%3D999")
        url = affiliate.clean_store_url(wrapped, CFG)
        self.assertEqual(url, "https://www.mediamarkt.es/es/product/123")

    def test_si_no_se_puede_limpiar_no_hay_enlace(self):
        self.assertIsNone(affiliate.clean_store_url("https://www.awin1.com/cread.php?awinmid=1", CFG))
        self.assertIsNone(affiliate.clean_store_url("https://www.chollometro.com/visit/threadmain/1", CFG))

    def test_la_plantilla_de_afiliado_se_aplica_despues_de_limpiar(self):
        cfg = json.loads(json.dumps(CFG))
        cfg["store_affiliates"]["mediamarkt"] = {"template": "https://awin.example/?ued={url}"}
        url = affiliate.clean_store_url("https://www.mediamarkt.es/es/product/123?utm_source=x", cfg)
        self.assertTrue(url.startswith("https://awin.example/?ued="))
        self.assertIn("mediamarkt.es", url)
        self.assertNotIn("utm_source", url)


class FilterTest(unittest.TestCase):
    def setUp(self):
        self.rules = CFG["generic"]
        self.now = at_madrid(12)

    def test_temperatura_caducado_y_duplicado(self):
        seen = {"cm-10000"}
        cold = {"title": "Algo", "price": 20, "temperature": 10, "link": "https://www.chollometro.com/ofertas/x-99", "published": ""}
        self.assertEqual(generic.reject_feed(cold, self.rules, self.now, seen), "temperatura baja")
        dead = {**cold, "temperature": 200, "title": "Oferta expirada de verdad"}
        self.assertEqual(generic.reject_feed(dead, self.rules, self.now, seen), "caducado")
        dup = {**cold, "temperature": 200, "title": "Otro", "link": "https://www.chollometro.com/ofertas/y-10000"}
        self.assertEqual(generic.reject_feed(dup, self.rules, self.now, seen), "duplicado")
        empty = {**cold, "temperature": 200, "price": None, "link": "https://www.chollometro.com/ofertas/y-11"}
        self.assertEqual(generic.reject_feed(empty, self.rules, self.now, set()), "sin precio")

    def test_silencio_y_cupos(self):
        rules = self.rules
        self.assertIn("silencio", generic.quota_reason({"posts": []}, at_madrid(2), rules))
        self.assertEqual(generic.quota_reason({"posts": []}, at_madrid(8), rules), "")
        self.assertEqual(generic.quota_reason({"posts": []}, at_madrid(0), rules), "")
        hour = [{"t": self.now.timestamp() - 60} for _ in range(4)]
        self.assertIn("hora", generic.quota_reason({"posts": hour}, self.now, rules))
        day = [{"t": self.now.timestamp() - 7200} for _ in range(40)]
        self.assertIn("día", generic.quota_reason({"posts": day}, self.now, rules))

    def test_el_bot_solo_publica_si_es_admin(self):
        self.assertTrue(generic.posting_rights({"status": "administrator", "can_post_messages": True}))
        self.assertTrue(generic.posting_rights({"status": "creator"}))
        self.assertFalse(generic.posting_rights({"status": "administrator", "can_post_messages": False}))
        self.assertFalse(generic.posting_rights({"status": "member"}))
        self.assertFalse(generic.posting_rights({"status": "left"}))

    def test_la_prueba_privada_no_guarda_ni_usa_el_canal(self):
        state = {"posts": [], "admin_chat_id": 1880159117}
        rss = """<item><title><![CDATA[357° - Portátil ASUS TUF]]></title>
        <link>https://www.chollometro.com/ofertas/asus-tuf-2047001</link>
        <pepper:merchant name="MediaMarkt" price="223,71€"/>
        <media:content url="https://img.example/a.jpg" medium="image"/>
        <pubDate>Wed, 28 Oct 2026 12:00:00 +0200</pubDate></item>"""
        page = '"isExpired":false,"nextBestPrice":1149.5,"temperature":357'

        def fetch(url, timeout=20):
            if "rss" in url:
                return 200, rss.encode()
            return 200, page.encode()

        sent = []

        class TG:
            def call(self, method, params=None):
                sent.append((method, params))
                if method == "getMe":
                    return {"id": 1, "username": "cazaerroresAmazon_bot"}
                if method == "getChatMember":
                    return {"status": "administrator", "can_post_messages": True}
                if method == "sendMessage":
                    return {"message_id": 77}
                raise AssertionError(method)

            def send_photo(self, chat_id, image, caption, extra=None):
                sent.append(("sendPhoto", {"chat_id": chat_id, "caption": caption, "image": str(image)}))
                return {"message_id": 77}

        args = generic.argparse.Namespace(dry_run=False, test_private=True)
        with mock.patch.object(feeds, "resolve_deal_url", return_value="https://www.mediamarkt.es/es/product/123"), \
             mock.patch.object(generic, "_image", return_value=ROOT / "images" / "taurus-radiador-hq.jpg"):
            code = generic.run(args, CFG, state, self.now, tg=TG(), fetch=fetch)
        self.assertEqual(code, 0)
        self.assertEqual(state["posts"], [])
        self.assertEqual(sent[-1][0], "sendPhoto")
        self.assertEqual(sent[-1][1]["chat_id"], 1880159117)
        self.assertIn("PVP MediaMarkt", sent[-1][1]["caption"])
        self.assertIn("1.149,50 €", sent[-1][1]["caption"])
        self.assertNotIn("º", sent[-1][1]["caption"])
        self.assertTrue(Path(sent[-1][1]["image"]).exists())


class WorkflowTest(unittest.TestCase):
    def test_el_premium_no_cambia_de_grupo_y_el_normal_es_independiente(self):
        premium = (ROOT / ".github/workflows/scan-deals.yml").read_text(encoding="utf-8")
        normal = (ROOT / ".github/workflows/scan-generic.yml").read_text(encoding="utf-8")
        self.assertIn("group: telegram-scanner", premium)
        self.assertNotIn("cazachollos_com", premium)
        self.assertNotIn("generic.py", premium)
        self.assertIn("name: Canal normal @cazachollos_com", normal)
        self.assertIn("group: telegram-canal-normal", normal)
        self.assertNotIn("telegram-scanner", normal)
        self.assertIn("python generic.py", normal)
        self.assertIn("manual_url", normal)
        self.assertIn("manual_price", normal)
        self.assertIn("manual_pvp", normal)
        self.assertIn("--manual-url", normal)
        self.assertIn("MANUAL_URL", normal)
        self.assertIn("state/generic.json", normal)
        self.assertIn('inputs.test_private != true', normal)
        self.assertIn("git pull --rebase --autostash && git push", normal)
        self.assertEqual(CFG["generic"]["chat_id"], "@cazachollos_com")
        self.assertEqual(CFG["generic"]["max_per_hour"], 4)
        self.assertEqual(CFG["generic"]["max_per_day"], 40)
        self.assertEqual(CFG["generic"]["quiet_hours"], [1, 8])


def _rss_item(title: str, price: str, link: str, temp: int = 400, image: str = "https://img.example/mesa.jpg") -> str:
    return f"""<item><title><![CDATA[{temp}° - {title}]]></title>
        <link>{link}</link>
        <pepper:merchant name="Ibernest" price="{price}€"/>
        <media:content url="{image}" medium="image"/>
        <pubDate>Wed, 28 Oct 2026 12:00:00 +0200</pubDate></item>"""


def _feed_fetch(page: str, rss: str):
    blob = page.encode()
    feed = rss.encode()

    def fetch(url, timeout=20):
        if "/rss/" in url:
            return 200, feed
        return 200, blob

    return fetch


class StrictFilterTest(unittest.TestCase):
    def setUp(self):
        self.now = at_madrid(12)

    def test_el_widget_del_lateral_no_salva_un_chollo_sin_pvp(self):
        """La mesa de Ibernest: nextBestPrice del lateral por debajo del precio, temperatura alta."""
        rss = _rss_item("Mesa de billar Transformable", "348",
                        "https://www.chollometro.com/ofertas/mesa-billar-2049001", temp=420)
        page = '"linkHost":"www.ibernest.com","isExpired":false,"nextBestPrice":299,"temperature":420,"price":348'
        found = generic.gather(CFG, {"posts": []}, self.now, fetch=_feed_fetch(page, rss))
        self.assertEqual(found, [])

    def test_empareja_el_pvp_con_el_precio_del_chollo(self):
        rss = _rss_item("Mesa de billar Transformable", "348",
                        "https://www.chollometro.com/ofertas/mesa-billar-2049002")
        page = ('"linkHost":"www.ibernest.com","nextBestPrice":299,"price":199,"isExpired":false,'
                '"price":348,"nextBestPrice":599,"temperature":400')
        found = generic.gather(CFG, {"posts": []}, self.now, fetch=_feed_fetch(page, rss))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["previous"], 599.0)
        self.assertAlmostEqual(generic.discount_of(348, 599), 41.9, delta=0.2)

    def test_una_bajada_menor_del_20_no_se_publica(self):
        rss = _rss_item("Mesa de billar Transformable", "348",
                        "https://www.chollometro.com/ofertas/mesa-billar-2049003")
        page = '"linkHost":"www.ibernest.com","isExpired":false,"price":348,"nextBestPrice":400,"temperature":300'
        found = generic.gather(CFG, {"posts": []}, self.now, fetch=_feed_fetch(page, rss))
        self.assertEqual(found, [])

    def test_sin_foto_valida_salta_al_siguiente(self):
        rss = (
            _rss_item("Mesa de billar Transformable", "348",
                      "https://www.chollometro.com/ofertas/mesa-billar-2049004", temp=500)
            + _rss_item("Auriculares de diadema", "49",
                        "https://www.chollometro.com/ofertas/auriculares-2049005", temp=200,
                        image="https://img.example/audio.jpg")
        )
        page = '"isExpired":false,"nextBestPrice":500,"temperature":500'
        sent = []

        class TG:
            def call(self, method, params=None):
                if method == "getMe":
                    return {"id": 1, "username": "cazaerroresAmazon_bot"}
                if method == "getChatMember":
                    return {"status": "administrator", "can_post_messages": True}
                raise AssertionError(method)

            def send_photo(self, chat_id, image, caption, extra=None):
                sent.append(caption)
                return {"message_id": 9}

        def image(cand):
            if "Mesa" in cand["title"]:
                return None
            return ROOT / "images" / "taurus-radiador-hq.jpg"

        args = generic.argparse.Namespace(dry_run=False, test_private=True)
        state = {"posts": [], "admin_chat_id": 1880159117}
        with mock.patch.object(feeds, "resolve_deal_url", return_value="https://www.ibernest.com/mesa"), \
             mock.patch.object(generic, "_image", side_effect=image):
            code = generic.run(args, CFG, state, self.now, tg=TG(), fetch=_feed_fetch(page, rss))
        self.assertEqual(code, 0)
        self.assertEqual(len(sent), 1)
        self.assertIn("Auriculares", sent[0])
        self.assertNotIn("Mesa de billar", sent[0])
        self.assertEqual(state["posts"], [])


class CollageTest(unittest.TestCase):
    def test_descarta_captura_con_cajas_y_acepta_el_producto(self):
        import io
        from PIL import Image, ImageDraw
        import photos
        shot = Image.new("RGB", (480, 640), (255, 255, 255))
        draw = ImageDraw.Draw(shot)
        draw.rectangle((36, 30, 444, 180), fill=(40, 90, 160))
        draw.rectangle((36, 230, 444, 390), fill=(20, 120, 80))
        draw.rectangle((36, 450, 444, 610), fill=(30, 30, 90))
        draw.polygon([(6, 320), (26, 300), (26, 340)], fill=(0, 0, 0))
        draw.polygon([(474, 320), (454, 300), (454, 340)], fill=(0, 0, 0))
        self.assertTrue(photos.looks_like_collage(shot))
        framed = Image.new("RGB", (360, 280), (188, 188, 188))
        ImageDraw.Draw(framed).rectangle((18, 18, 342, 262), fill=(250, 250, 250))
        ImageDraw.Draw(framed).rectangle((70, 50, 290, 230), fill=(20, 40, 70))
        self.assertTrue(photos.looks_like_collage(framed))
        product = Image.new("RGB", (420, 420), (255, 255, 255))
        ImageDraw.Draw(product).rounded_rectangle((70, 80, 350, 340), radius=18, fill=(25, 45, 80))
        self.assertFalse(photos.looks_like_collage(product))
        buffer = io.BytesIO()
        shot.save(buffer, format="JPEG", quality=85)
        self.assertFalse(photos.image_ok(buffer.getvalue()))
        buffer = io.BytesIO()
        product.save(buffer, format="JPEG", quality=85)
        self.assertTrue(photos.image_ok(buffer.getvalue()))


BUYBOX_REAL = """
<html><head>
<meta property="og:image" content="https://m.media-amazon.com/images/I/71ogtv.jpg" />
</head><body>
<span class="a-offscreen">114,88€</span>
<span class="a-offscreen">189,26€</span>
<span id="productTitle">XIAOMI TV Pro 32" QLED</span>
<div id="corePriceDisplay_desktop_feature_div">
  <span class="a-price aok-align-center priceToPay" data-a-size="xl">
    <span class="a-offscreen">139,00€</span>
  </span>
  <span class="aok-offscreen">Precio recomendado: </span>
  <span class="a-price a-text-price" data-a-strike="true">
    <span class="a-offscreen">229,00€</span>
  </span>
</div>
"hiRes":"https://m.media-amazon.com/images/I/81tvhires.jpg"
</body></html>
"""

BUYBOX_OTRA_VARIANTE = """
<html><body>
<span class="a-offscreen">99,00€</span>
<span id="productTitle">XIAOMI TV Pro 32" QLED</span>
<div id="corePriceDisplay_desktop_feature_div">
  <span class="a-price priceToPay"><span class="a-offscreen">114,88€</span></span>
  <span>Precio recomendado</span>
  <span class="a-price a-text-price"><span class="a-offscreen">189,26€</span></span>
</div>
"hiRes":"https://m.media-amazon.com/images/I/81tvhires.jpg"
</body></html>
"""


class ManualDealTest(unittest.TestCase):
    def test_el_buybox_no_es_el_primer_precio_de_la_pagina(self):
        box = feeds.amazon_buybox(BUYBOX_REAL)
        self.assertEqual(box["price"], 139.0)
        self.assertEqual(box["previous"], 229.0)
        self.assertIn("QLED", box["title"])
        self.assertEqual(box["images"][0], "https://m.media-amazon.com/images/I/81tvhires.jpg")

    def test_el_precio_manual_manda_y_el_enlace_queda_limpio(self):
        cand = generic.manual_candidate(
            "https://www.amazon.es/Xiaomi-TV-Pro/dp/B0H7BF91XG?tag=otro-21&ref=sr_1_1",
            CFG, "139,00", "229,00", lambda url, timeout=20: (200, BUYBOX_OTRA_VARIANTE.encode()),
        )
        self.assertIsNotNone(cand)
        self.assertEqual(cand["price"], 139.0)
        self.assertEqual(cand["previous"], 229.0)
        self.assertEqual(cand["url"], "https://www.amazon.es/dp/B0H7BF91XG?tag=cazadores_errores-21")
        self.assertNotIn("otro-21", cand["url"])
        self.assertNotIn("ref=", cand["url"])
        self.assertIn("81tvhires", cand["images"][0])
        text = build_deal_caption(url=cand["url"], title=cand["title"], current=cand["price"],
                                  store=cand["store"], previous=cand["previous"], origin=cand["origin"])
        self.assertIn("AHORA: 139,00 €", text)
        self.assertIn("229,00 €", text)
        self.assertIn("−39 %", text)
        self.assertIn("90,00 €", text)
        self.assertNotIn("Se ha colado un precio", text)

    def test_sin_precios_manuales_usa_el_buybox(self):
        cand = generic.manual_candidate(
            "https://www.amazon.es/dp/B0H7BF91XG",
            CFG, "", "", lambda url, timeout=20: (200, BUYBOX_REAL.encode()),
        )
        self.assertEqual(cand["price"], 139.0)
        self.assertEqual(cand["previous"], 229.0)
        self.assertEqual(cand["url"], "https://www.amazon.es/dp/B0H7BF91XG?tag=cazadores_errores-21")

    def test_el_manual_ignora_el_silencio_y_no_cuenta_en_la_hora(self):
        now = at_madrid(3)
        rules = CFG["generic"]
        hour = [{"t": now.timestamp() - 30, "manual": True} for _ in range(6)]
        self.assertEqual(generic.quota_reason({"posts": hour}, at_madrid(12), rules), "")
        state = {"posts": [{"t": now.timestamp() - 30} for _ in range(4)], "admin_chat_id": 7}
        self.assertIn("silencio", generic.quota_reason(state, now, rules))
        args = generic.argparse.Namespace(
            dry_run=True, test_private=False,
            manual_url="https://www.amazon.es/dp/B0H7BF91XG",
            manual_price="139,00", manual_pvp="229,00",
        )
        image = mock.Mock(return_value=ROOT / "images" / "taurus-radiador-hq.jpg")
        with mock.patch.object(generic, "_image", image):
            code = generic.run(args, CFG, state, now, tg=None, fetch=lambda url, timeout=20: (200, BUYBOX_OTRA_VARIANTE.encode()))
        self.assertEqual(code, 0)
        image.assert_called_once()
        self.assertEqual(len(state["posts"]), 4)


if __name__ == "__main__":
    unittest.main()
