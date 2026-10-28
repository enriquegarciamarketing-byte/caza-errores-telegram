#!/usr/bin/env python3
"""Canal normal: formato, enlaces, ritmo y workflow propio. El premium no se toca."""

from __future__ import annotations

import json
import os
import subprocess
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import affiliate
import feeds
import generic
from publisher import euro

ROOT = Path(__file__).resolve().parent
PREMIUM_WORKFLOW = ROOT / ".github" / "workflows" / "scan-deals.yml"
GENERIC_WORKFLOW = ROOT / ".github" / "workflows" / "scan-generic.yml"
TAG = "cazadores_errores-21"
MADRID = ZoneInfo("Europe/Madrid")
DAY = datetime(2026, 10, 28, 10, 0, tzinfo=MADRID)
NIGHT = datetime(2026, 10, 28, 2, 30, tzinfo=MADRID)
FEED = "https://example.test/hot"


def cfg(**generic_over):
    data = {
        "affiliate_tag": TAG,
        "sources": [],
        "generic": {
            "chat_id": "@cazachollos_com",
            "feeds": [FEED],
            "use_amazon_sources": False,
            "min_temperature": 80,
            "min_price_eur": 3,
            "min_discount_pct": 20,
            "max_discount_pct": 95,
            "min_reliable_discount_pct": 5,
            "max_posts_per_hour": 4,
            "max_posts_per_day": 40,
            "max_posts_per_run": 1,
            "test_private_posts": 3,
            "min_minutes_between_posts": 15,
            "quiet_hours": [1, 8],
            "repost_after_days": 14,
            "max_deal_age_hours": 36,
            "max_amazon_age_minutes": 120,
            "max_opens_per_run": 8,
        },
    }
    data["generic"].update(generic_over)
    return data


def rss_item(thread, title, price, merchant="MediaMarkt", temp=None, category="Electrónica", published=""):
    shown = f"{temp}° - {title}" if temp else title
    pub = f"<pubDate>{published}</pubDate>" if published else ""
    return f"""<item>
      <title><![CDATA[{shown}]]></title>
      <link>https://www.chollometro.com/ofertas/producto-{thread}</link>
      <category><![CDATA[{category}]]></category>
      <pepper:merchant name="{merchant}" price="{price}"/>
      <media:content url="https://static.chollometro.com/threads/raw/x/re/150x150/qt/55/a.jpg" medium="image"/>
      {pub}
    </item>"""


def rss(*items):
    return "<rss><channel>" + "".join(items) + "</channel></rss>"


def page(thread, price, previous, temp, expired=False, maybe=False, status="Activated"):
    prev = "null" if previous is None else str(previous)
    return (
        '"price":1,"nextBestPrice":9,"temperature":1,'
        f'"nextBestPrice":{prev},"price":{price},"temperature":{temp},'
        f'"threadId":"{thread}","status":"{status}","stale":false,'
        f'"isMaybeExpired":{"true" if maybe else "false"},'
        f'"isExpired":{"true" if expired else "false"}'
    )


class FakeTG:
    def __init__(self, member=None, fail=None):
        self.member = member or {"status": "administrator", "can_post_messages": True}
        self.fail = fail or {}
        self.sent = []

    def call(self, method, params=None):
        if method in self.fail:
            raise RuntimeError(self.fail[method])
        if method == "getMe":
            return {"id": 42, "username": "cazaerroresAmazon_bot"}
        if method == "getChatMember":
            return self.member
        if method == "sendMessage":
            self.sent.append(("message", params))
            return {"message_id": len(self.sent)}
        raise AssertionError(method)

    def send_photo(self, chat_id, image, caption, extra=None):
        self.sent.append(("photo", {"chat_id": chat_id, "caption": caption, "extra": extra, "image": image}))
        return {"message_id": len(self.sent)}


class CaptionTest(unittest.TestCase):
    def test_bloque_de_pvp_tachado_en_formato_espanol(self):
        deal = {
            "title": "LG OLED 55 pulgadas",
            "store": "MediaMarkt",
            "price": 223.71,
            "previous": 1149.50,
            "temperature": 300,
            "category": "Electrónica",
            "url": "https://www.mediamarkt.es/es/product/lg-oled-55",
        }
        text = generic.build_caption(deal)
        self.assertEqual(
            text,
            "\n".join([
                "🔥 <b>BAJÓN DE PRECIO</b>",
                "",
                "<b>LG OLED 55 pulgadas</b>",
                "📂 Electrónica",
                "",
                "❌ PVP MediaMarkt: <s>1.149,50 €</s>",
                "💰 AHORA: 223,71 €",
                "📉 −81 % sobre PVP",
                "🤑 Te ahorras: 925,79 €",
                "",
                '🔗 <b><a href="https://www.mediamarkt.es/es/product/lg-oled-55">Ver en MediaMarkt</a></b>',
            ]),
        )
        self.assertIn("<s>1.149,50 €</s>", text)
        self.assertNotIn("ROI", text)
        self.assertNotIn("Reventa", text)
        self.assertEqual(euro(1149.50), "1.149,50 €")
        self.assertEqual(euro(223.71), "223,71 €")
        self.assertEqual(euro(925.79), "925,79 €")

    def test_sin_pvp_fiable_solo_queda_ahora(self):
        deal = {
            "title": "ASUS TUF Gaming M4 Air",
            "store": "Amazon",
            "price": 34.03,
            "previous": None,
            "temperature": 208,
            "category": "Electrónica",
            "url": "https://www.amazon.es/dp/B0TEST1234?tag=cazadores_errores-21",
        }
        text = generic.build_caption(deal)
        self.assertEqual(
            text,
            "\n".join([
                "🔥 <b>CHOLLO CALIENTE</b>",
                "",
                "<b>ASUS TUF Gaming M4 Air</b>",
                "📂 Electrónica",
                "",
                "💰 AHORA: 34,03 €",
                "",
                '🔗 <b><a href="https://www.amazon.es/dp/B0TEST1234?tag=cazadores_errores-21">Ver en Amazon</a></b>',
            ]),
        )
        self.assertNotIn("PVP", text)
        self.assertNotIn("<s>", text)
        self.assertNotIn("Te ahorras", text)
        self.assertNotIn("sobre PVP", text)

    def test_un_pvp_ridiculo_o_minimo_no_se_pinta(self):
        tiny = {"title": "Ratón", "store": "Amazon", "price": 34.03, "previous": 34.50,
                "temperature": 40, "category": "", "url": "https://www.amazon.es/dp/B0TEST1234?tag=x"}
        absurd = {**tiny, "previous": 10000, "price": 10}
        for deal in (tiny, absurd):
            text = generic.build_caption(deal)
            self.assertIn("💰 AHORA:", text)
            self.assertNotIn("PVP", text)
            self.assertNotIn("<s>", text)
        self.assertIn("✨ <b>CAZADO</b>", generic.build_caption(tiny))

    def test_el_boton_lleva_el_nombre_de_la_tienda(self):
        deal = {"store": "PcComponentes", "url": "https://www.pccomponentes.com/portatil"}
        button = generic.button_for(deal)["inline_keyboard"][0][0]
        self.assertEqual(button["text"], "🛒 Ver en PcComponentes")
        self.assertEqual(button["url"], deal["url"])


class LinkTest(unittest.TestCase):
    def test_amazon_es_cambia_el_tag_ajeno_y_conserva_el_asin(self):
        raw = "https://www.amazon.es/dp/B0TEST1234?tag=chollometro-21&tag=otro-21&ref=sr"
        url = generic.clean_merchant_url(raw, cfg())
        self.assertEqual(affiliate.tag_values(url), [TAG])
        self.assertIn("/dp/B0TEST1234", url)
        self.assertNotIn("chollometro-21", url)
        self.assertNotIn("otro-21", url)
        self.assertIn("ref=sr", url)

    def test_amazon_de_pasa_a_amazon_es_con_la_etiqueta(self):
        url = generic.clean_merchant_url("https://www.amazon.de/dp/B0TEST1234?tag=otro-21", cfg())
        self.assertTrue(url.startswith("https://www.amazon.es/dp/B0TEST1234"))
        self.assertEqual(affiliate.tag_values(url), [TAG])
        self.assertIsNone(generic.clean_merchant_url("https://www.amazon.de/s?k=cosa", cfg()))

    def test_enlace_corto_con_otro_asin_no_se_publica_tal_cual(self):
        def resolve(_url):
            return f"https://www.amazon.es/dp/B0OTROPROD?tag={TAG}"

        url = generic.clean_merchant_url("https://amzn.to/mal", cfg(), asin="B0MIPROD99", resolve=resolve)
        self.assertIn("/dp/B0MIPROD99", url)
        self.assertNotIn("B0OTROPROD", url)
        self.assertEqual(affiliate.tag_values(url), [TAG])

    def test_enlace_corto_inservible_se_descarta(self):
        def resolve(_url):
            return "https://www.amazon.es/s?k=nada"

        self.assertIsNone(generic.clean_merchant_url("https://amzn.to/x", cfg(), resolve=resolve))

    def test_otra_tienda_pierde_el_afiliado_ajeno(self):
        raw = "https://www.mediamarkt.es/es/product/lg-oled?awc=999&utm_source=pepper&sku=55"
        url = generic.clean_merchant_url(raw, cfg())
        self.assertEqual(url, "https://www.mediamarkt.es/es/product/lg-oled?sku=55")
        self.assertNotIn("awc", url)
        self.assertNotIn("utm_", url)

    def test_plantilla_de_tienda_sobre_el_enlace_ya_limpio(self):
        local = cfg()
        local["store_affiliates"] = {"mediamarkt": {"template": "https://www.awin1.com/cread.php?ued={url}"}}
        url = generic.clean_merchant_url(
            "https://www.mediamarkt.es/es/product/lg-oled?awc=999", local,
        )
        self.assertTrue(url.startswith("https://www.awin1.com/cread.php?ued="))
        inner = urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["ued"][0])
        self.assertEqual(inner, "https://www.mediamarkt.es/es/product/lg-oled")
        self.assertNotIn("awc", inner)

    def test_una_red_de_afiliado_se_desenvuelve_o_se_tira(self):
        wrapped = "https://www.awin1.com/cread.php?ued=" + urllib.parse.quote(
            "https://www.pccomponentes.com/portatil-asus?awc=5", safe="",
        )
        url = generic.clean_merchant_url(wrapped, cfg())
        self.assertEqual(url, "https://www.pccomponentes.com/portatil-asus")
        self.assertIsNone(generic.clean_merchant_url("https://www.chollometro.com/visit/threadmain/2047000", cfg()))
        self.assertIsNone(generic.clean_merchant_url("http://www.mediamarkt.es/es/product/lg", cfg()))
        self.assertEqual(generic.store_label("https://es.aliexpress.com/item/100500.html"), "AliExpress")


class FilterTest(unittest.TestCase):
    def test_umbrales_de_config(self):
        rules = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["generic"]
        self.assertEqual(rules["chat_id"], "@cazachollos_com")
        self.assertEqual(rules["min_temperature"], 80)
        self.assertEqual(rules["max_posts_per_hour"], 4)
        self.assertEqual(rules["max_posts_per_day"], 40)
        self.assertEqual(rules["min_minutes_between_posts"], 15)
        self.assertEqual(rules["quiet_hours"], [1, 8])
        self.assertIn("https://www.chollometro.com/rss/hot", rules["feeds"])
        premium_rules = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))["resale"]
        self.assertEqual(premium_rules["min_price_eur"], 25)
        self.assertTrue(premium_rules["require_priority"])

    def test_ritmo_noche_hora_dia_y_separacion(self):
        base = {"posts": [], "skipped": {}}
        self.assertIn("horario de silencio", generic.pace_reason(cfg(), base, NIGHT))
        self.assertIn("horario de silencio", generic.pace_reason(cfg(), base, datetime(2026, 10, 28, 1, 0, tzinfo=MADRID)))
        self.assertIsNone(generic.pace_reason(cfg(), base, datetime(2026, 10, 28, 0, 30, tzinfo=MADRID)))
        self.assertIsNone(generic.pace_reason(cfg(), base, datetime(2026, 10, 28, 8, 0, tzinfo=MADRID)))

        hourly = {"posts": [{"id": str(i), "t": int((DAY - timedelta(minutes=5 + i)).timestamp())} for i in range(4)],
                  "skipped": {}}
        self.assertIn("cupo por hora", generic.pace_reason(cfg(), hourly, DAY))

        spaced = cfg(min_minutes_between_posts=0, max_posts_per_hour=100)
        daily_posts = [{"id": str(i), "t": int((DAY - timedelta(hours=3)).timestamp())} for i in range(40)]
        self.assertIn("cupo diario", generic.pace_reason(spaced, {"posts": daily_posts, "skipped": {}}, DAY))

        recent = {"posts": [{"id": "a", "t": int((DAY - timedelta(minutes=5)).timestamp())}], "skipped": {}}
        self.assertIn("demasiado pronto", generic.pace_reason(cfg(), recent, DAY))
        self.assertIsNone(generic.pace_reason(cfg(), base, DAY))

    def test_no_repite_y_la_temperatura_baja_no_abre_la_ficha(self):
        thread = "2047001"
        state = {"posts": [{"id": f"cm-{thread}", "fp": "lg oled", "store": "MediaMarkt", "asin": "",
                            "t": int(DAY.timestamp())}], "skipped": {}}
        calls = []

        def fetch(url):
            calls.append(url)
            if url == FEED:
                return rss(
                    rss_item(thread, "LG OLED repetido", "100€", temp=300),
                    rss_item("2047002", "Frío", "20€", temp=10),
                    rss_item("2047003", "Caducado en el tiempo", "30€", temp=200,
                             published="Mon, 26 Oct 2026 08:00:00 +0100"),
                )
            raise AssertionError(url)

        deals, skips = generic.select_deals(cfg(), state, DAY, limit=3, fetch=fetch, resolve=lambda _page: None)
        self.assertEqual(deals, [])
        self.assertEqual(calls, [FEED])
        self.assertEqual(skips["cm-2047002"], "temperatura baja")
        self.assertEqual(skips["cm-2047003"], "caducado")

    def test_prioriza_el_caliente_y_descarta_caducados_sin_precio_y_sin_enlace(self):
        hot = "2047111"
        cold_page = "2047222"
        dead = "2047333"
        dirty = "2047444"
        amazon_source = "https://example.test/amazon"
        local = cfg(use_amazon_sources=True, max_posts_per_run=1)
        local["sources"] = [amazon_source]
        calls = []

        def fetch(url):
            calls.append(url)
            if url == FEED:
                return rss(
                    rss_item(cold_page, "LEGO nuevo", "19,99€"),
                    rss_item(dead, "Ya pasó", "50€", temp=220),
                    rss_item(dirty, "Enlace sucio", "40€", temp=210),
                    rss_item("2047555", "Sin dinero", "", temp=300),
                    rss_item(hot, "LG OLED 55 pulgadas", "223,71€", temp=300),
                )
            if url.endswith(f"-{hot}"):
                return page(hot, 223.71, 1149.50, 300)
            if url.endswith(f"-{cold_page}"):
                return page(cold_page, 19.99, None, 20)
            if url.endswith(f"-{dead}"):
                return page(dead, 50, 80, 220, expired=True)
            if url.endswith(f"-{dirty}"):
                return page(dirty, 40, 90, 210)
            if url == amazon_source:
                return listing(int(DAY.timestamp()))
            raise AssertionError(url)

        def resolve(html):
            if f'"threadId":"{dirty}"' in html:
                return "https://www.chollometro.com/visit/threadmain/2047444"
            if f'"threadId":"{hot}"' in html:
                return "https://www.mediamarkt.es/es/product/lg-oled-55?awc=321&utm_source=pepper"
            return "https://www.carrefour.es/p/lego-frio"

        deals, skips = generic.select_deals(local, {"posts": [], "skipped": {}}, DAY, limit=1, fetch=fetch, resolve=resolve)
        self.assertEqual(len(deals), 1)
        deal = deals[0]
        self.assertEqual(deal["id"], f"cm-{hot}")
        self.assertEqual(deal["store"], "MediaMarkt")
        self.assertEqual(deal["url"], "https://www.mediamarkt.es/es/product/lg-oled-55")
        self.assertNotIn("awc", deal["url"])
        self.assertIn("/a.jpg", deal["image"])
        self.assertNotIn("/re/150x150/", deal["image"])
        self.assertEqual(deal["price"], 223.71)
        self.assertNotIn(f"https://jimmyleaks.com/es/dp/AbC123/", calls)
        self.assertTrue(any(url.endswith(f"-{hot}") for url in calls))

        def fetch_bad(url):
            if url == FEED:
                return rss(
                    rss_item(dead, "Ya pasó", "50€", temp=220),
                    rss_item(dirty, "Enlace sucio", "40€", temp=210),
                    rss_item("2047555", "Sin dinero", "0€", temp=300),
                )
            if url.endswith(f"-{dead}"):
                return page(dead, 50, 80, 220, expired=True)
            if url.endswith(f"-{dirty}"):
                return page(dirty, 40, 90, 210)
            raise AssertionError(url)

        _none, bad_skips = generic.select_deals(
            cfg(), {"posts": [], "skipped": {}}, DAY, limit=2, fetch=fetch_bad, resolve=resolve,
        )
        self.assertEqual(bad_skips[f"cm-{dead}"], "caducado")
        self.assertEqual(bad_skips[f"cm-{dirty}"], "enlace no limpiable")
        self.assertEqual(bad_skips["cm-2047555"], "sin precio")

    def test_rss_sin_grados_usa_la_temperatura_de_la_ficha(self):
        thread = "2047666"

        def fetch(url):
            if url == FEED:
                return rss(rss_item(thread, "Auriculares Sony", "29,99€", merchant="Amazon"))
            return page(thread, 29.99, None, 40)

        _deals, skips = generic.select_deals(
            cfg(), {"posts": [], "skipped": {}}, DAY, limit=1, fetch=fetch,
            resolve=lambda _html: "https://www.amazon.es/dp/B0SONY12345",
        )
        self.assertEqual(skips[f"cm-{thread}"], "temperatura baja")

        def fetch_hot(url):
            if url == FEED:
                return rss(rss_item(thread, "Auriculares Sony", "29,99€", merchant="Amazon"))
            return page(thread, 29.99, None, 140)

        deals, skips = generic.select_deals(
            cfg(), {"posts": [], "skipped": {}}, DAY, limit=1, fetch=fetch_hot,
            resolve=lambda _html: "https://www.amazon.es/dp/B0SONY1234?tag=otro-21",
        )
        self.assertEqual(skips, {})
        self.assertEqual(deals[0]["store"], "Amazon")
        self.assertEqual(affiliate.tag_values(deals[0]["url"]), [TAG])
        self.assertIn("/dp/B0SONY1234", deals[0]["url"])
        self.assertEqual(deals[0]["temperature"], 140)

    def test_amazon_cuando_chollometro_no_da_nada_publicable(self):
        source = "https://example.test/minimos"
        local = cfg(use_amazon_sources=True)
        local["sources"] = [source]
        detail_url = "https://jimmyleaks.com/es/dp/AbC123/"

        def fetch(url):
            if url == FEED:
                return rss(rss_item("2047009", "Caducado", "10€", temp=400))
            if url.endswith("-2047009"):
                return page("2047009", 10, 40, 400, maybe=True)
            if url == source:
                return listing(int(DAY.timestamp()))
            if url == detail_url:
                return detail_page()
            raise AssertionError(url)

        deals, skips = generic.select_deals(
            local, {"posts": [], "skipped": {}}, DAY, limit=1, fetch=fetch, resolve=lambda _html: None,
        )
        self.assertEqual(skips["cm-2047009"], "caducado")
        self.assertEqual(len(deals), 1)
        self.assertEqual(deals[0]["origin"], "amazon")
        self.assertEqual(deals[0]["asin"], "B0CAFE1234")
        self.assertEqual(affiliate.tag_values(deals[0]["url"]), [TAG])
        self.assertIn("/dp/B0CAFE1234", deals[0]["url"])
        self.assertEqual(deals[0]["store"], "Amazon")

    def test_una_ficha_amazon_ilegible_no_se_marca_agotada(self):
        deal, reason = generic.consider_amazon(
            {"id": "Zz9", "title": "Cosa", "price": 40, "was": 80},
            "<html>captcha</html>",
            cfg(),
        )
        self.assertIsNone(deal)
        self.assertEqual(reason, "")


class RunTest(unittest.TestCase):
    def test_de_noche_no_publica_ni_abre(self):
        def fetch(_url):
            raise AssertionError("no debe haber red de noche")

        state = {"posts": [], "skipped": {}}
        code = generic.execute(cfg(), state, NIGHT, dry=False, test_private=False, tg=FakeTG(),
                               fetch=fetch, resolve=lambda _p: None, download=None)
        self.assertEqual(code, 0)
        self.assertEqual(state["posts"], [])

    def test_prueba_privada_va_al_admin_y_no_guarda(self):
        thread = "2047800"
        state = {"posts": [], "skipped": {}}
        before = json.dumps(state)
        tg = FakeTG()

        def fetch(url):
            if url == FEED:
                return rss(
                    rss_item("2047800", "LG OLED 55 pulgadas", "223,71€", temp=320),
                    rss_item("2047801", "Cafetera", "49€", temp=180),
                    rss_item("2047802", "Monitor", "99€", temp=150),
                    rss_item("2047803", "Sobra", "15€", temp=140),
                )
            ident = url.rsplit("-", 1)[-1]
            return page(ident, 20 + int(ident[-1]), 80, 200)

        code = generic.execute(
            cfg(test_private_posts=3, max_posts_per_run=1), state, DAY,
            dry=False, test_private=True, tg=tg, fetch=fetch,
            resolve=lambda _html: "https://www.mediamarkt.es/es/product/algo",
            download=lambda _url: b"img", pause=0,
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.dumps(state), before)
        self.assertEqual(len(tg.sent), 3)
        admin = generic.resolve_admin({})
        for kind, payload in tg.sent:
            self.assertEqual(kind, "photo")
            self.assertEqual(payload["chat_id"], admin)
            self.assertNotEqual(payload["chat_id"], "@cazachollos_com")
            self.assertIn("PRUEBA · canal normal", payload["caption"])
            self.assertIn("Ver en MediaMarkt", payload["caption"])
            self.assertEqual(payload["extra"]["reply_markup"]["inline_keyboard"][0][0]["text"], "🛒 Ver en MediaMarkt")

    def test_publicar_guarda_solo_la_memoria_del_canal_normal(self):
        thread = "2047900"
        state = {"posts": [], "skipped": {}}
        scanner_before = generic.SCANNER_STATE.read_text(encoding="utf-8")
        tg = FakeTG()

        def fetch(url):
            if url == FEED:
                return rss(rss_item(thread, "LG OLED 55 pulgadas", "223,71€", temp=300))
            return page(thread, 223.71, 1149.50, 300)

        with mock.patch.object(generic, "STATE_PATH", Path("/tmp/generic-test-state.json")):
            code = generic.execute(
                cfg(), state, DAY, dry=False, test_private=False, tg=tg, fetch=fetch,
                resolve=lambda _html: "https://www.mediamarkt.es/es/product/lg-oled-55?awc=1",
                download=lambda _url: None, pause=0,
            )
            saved = json.loads(Path("/tmp/generic-test-state.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertEqual(len(saved["posts"]), 1)
        self.assertEqual(saved["posts"][0]["id"], f"cm-{thread}")
        self.assertEqual(tg.sent[0][1]["chat_id"], "@cazachollos_com")
        self.assertIn("<s>1.149,50 €</s>", tg.sent[0][1]["text"])
        self.assertNotIn("awc", tg.sent[0][1]["text"])
        self.assertEqual(generic.SCANNER_STATE.read_text(encoding="utf-8"), scanner_before)

        again = generic.execute(
            cfg(), saved, DAY + timedelta(minutes=5), dry=False, test_private=False, tg=FakeTG(),
            fetch=lambda _url: (_ for _ in ()).throw(AssertionError("no debe buscar")),
            resolve=lambda _html: None, download=None,
        )
        self.assertEqual(again, 0)
        self.assertEqual(len(saved["posts"]), 1)

    def test_sin_permiso_el_main_no_rompe_y_la_prueba_privada_sigue(self):
        blocked = FakeTG(member={"status": "left"})
        with mock.patch.object(generic.scanner, "Telegram", return_value=blocked), \
             mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token-de-prueba"}), \
             mock.patch.object(generic, "execute", side_effect=AssertionError("no debe publicar")):
            self.assertEqual(generic.main([]), 0)

        seen = {}

        def fake_execute(*_args, **kwargs):
            seen["test_private"] = kwargs["test_private"]
            return 0

        with mock.patch.object(generic.scanner, "Telegram", return_value=blocked), \
             mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token-de-prueba"}), \
             mock.patch.object(generic, "execute", side_effect=fake_execute):
            self.assertEqual(generic.main(["--test-private"]), 0)
        self.assertTrue(seen["test_private"])

        ok, message = generic.check_can_post(
            FakeTG(fail={"getChatMember": "Forbidden: bot is not a member"}), "@cazachollos_com",
        )
        self.assertFalse(ok)
        self.assertIn("getChatMember", message)
        self.assertIn("@cazachollos_com", message)
        self.assertNotIn("Traceback", message)
        allowed, _text = generic.membership_can_post({"status": "creator"}, "@cazachollos_com")
        self.assertTrue(allowed)
        denied, text = generic.membership_can_post(
            {"status": "administrator", "can_post_messages": False}, "@cazachollos_com",
        )
        self.assertFalse(denied)
        self.assertIn("no tiene permiso", text)

    def test_dry_run_no_escribe_memoria_premium_ni_normal(self):
        generic_before = generic.STATE_PATH.read_text(encoding="utf-8")
        scanner_before = generic.SCANNER_STATE.read_text(encoding="utf-8")

        def offline(_url, timeout=20):
            raise urllib.error.URLError("sin red")

        with mock.patch.object(generic, "http_get", side_effect=offline), \
             mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": ""}):
            code = generic.main(["--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(generic.STATE_PATH.read_text(encoding="utf-8"), generic_before)
        self.assertEqual(generic.SCANNER_STATE.read_text(encoding="utf-8"), scanner_before)


class WorkflowTest(unittest.TestCase):
    def test_workflow_nuevo_separado_del_premium(self):
        text = GENERIC_WORKFLOW.read_text(encoding="utf-8")
        premium = PREMIUM_WORKFLOW.read_text(encoding="utf-8")
        committed = subprocess.check_output(
            ["git", "show", "HEAD:.github/workflows/scan-deals.yml"], text=True,
        )
        self.assertEqual(premium, committed)
        self.assertIn("name: Canal normal @cazachollos_com", text)
        self.assertIn("group: telegram-generic", text)
        self.assertNotIn("telegram-scanner", text)
        self.assertNotIn("TELEGRAM_CHAT_ID", text)
        self.assertIn("python generic.py", text)
        self.assertIn("state/generic.json", text)
        self.assertNotIn("state/scanner.json", text)
        self.assertIn("fetch-depth: 0", text)
        self.assertIn("git pull --rebase --autostash", text)
        self.assertIn("git rebase --abort", text)
        self.assertIn("exit 1", text)
        self.assertGreaterEqual(text.count("reintento"), 1)
        self.assertIn("for i in 1 2 3 4 5", text)
        self.assertIn("inputs.test_private != true", text)
        self.assertRegex(
            text,
            r"dry_run:\n\s+description:.*\n\s+required: false\n\s+type: boolean\n\s+default: true",
        )
        self.assertRegex(
            text,
            r"test_private:\n\s+description:.*\n\s+required: false\n\s+type: boolean\n\s+default: false",
        )
        self.assertIn('if [ "${{ inputs.dry_run }}" = "true" ]; then ARGS+=(--dry-run); fi', text)
        self.assertIn('if [ "${{ inputs.test_private }}" = "true" ]; then ARGS+=(--test-private); fi', text)
        self.assertIn("group: telegram-scanner", premium)
        self.assertIn("name: Escanear chollos automáticamente", premium)

    def test_el_rss_compartido_guarda_la_fecha(self):
        parsed = feeds.parse_rss(rss_item("1", "Cosa", "10€", temp=90, published="Wed, 28 Oct 2026 10:00:00 +0100"))
        self.assertEqual(parsed[0]["published"], "Wed, 28 Oct 2026 10:00:00 +0100")
        self.assertEqual(parsed[0]["temperature"], 90)
        self.assertIsNotNone(generic.parse_pubdate(parsed[0]["published"]))


def listing(ts: int) -> str:
    return f"""
    <article class="ticket fresh">
      <a href="/es/dp/AbC123/">ficha</a>
      <h2 class="tk-title">Cafetera Dedica</h2>
      <a class="tk-brand" href="/marca">DeLonghi</a>
      <span class="now">49,90 €</span>
      <span class="was">89,90 €</span>
      <span class="verdict">44% por debajo</span>
      <div data-timestamp="{ts}"></div>
    </article>
    """


def detail_page() -> str:
    return """
    <script type="application/ld+json">
    {"@type":"Product","name":"Cafetera Dedica","brand":{"name":"DeLonghi"},
     "gtin":"8004399334567","image":["https://img.example/c.jpg"],
     "offers":{"price":"49.90","availability":"https://schema.org/InStock"}}
    </script>
    <a href="https://www.amazon.es/dp/B0CAFE1234">amazon</a>
    """


if __name__ == "__main__":
    unittest.main()
