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
from publisher import build_deal_caption, euro

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
        self.assertIn("Ver en Amazon", text)
        self.assertNotIn("ROI", text)
        self.assertNotIn("Wallapop", text)
        self.assertEqual(euro(925.79), "925,79 €")

    def test_sin_pvp_solo_ahora(self):
        text = build_deal_caption(url="https://www.mediamarkt.es/p/1", title="Auriculares",
                                  current=49.9, previous=None, store="MediaMarkt", temperature=90)
        self.assertIn("💰 AHORA: 49,90 €", text)
        self.assertNotIn("PVP", text)
        self.assertNotIn("Te ahorras", text)


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

            def send_photo(self, *args, **kwargs):
                raise AssertionError("sin foto en esta prueba")

        args = generic.argparse.Namespace(dry_run=False, test_private=True)
        with mock.patch.object(feeds, "resolve_deal_url", return_value="https://www.mediamarkt.es/es/product/123"), \
             mock.patch.object(generic, "_image", return_value=None):
            code = generic.run(args, CFG, state, self.now, tg=TG(), fetch=fetch)
        self.assertEqual(code, 0)
        self.assertEqual(state["posts"], [])
        self.assertEqual(sent[-1][0], "sendMessage")
        self.assertEqual(sent[-1][1]["chat_id"], 1880159117)
        self.assertIn("PVP MediaMarkt", sent[-1][1]["text"])
        self.assertIn("1.149,50 €", sent[-1][1]["text"])


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
        self.assertIn("state/generic.json", normal)
        self.assertIn('inputs.test_private != true', normal)
        self.assertIn("git pull --rebase --autostash && git push", normal)
        self.assertEqual(CFG["generic"]["chat_id"], "@cazachollos_com")
        self.assertEqual(CFG["generic"]["max_per_hour"], 4)
        self.assertEqual(CFG["generic"]["max_per_day"], 40)
        self.assertEqual(CFG["generic"]["quiet_hours"], [1, 8])


if __name__ == "__main__":
    unittest.main()
