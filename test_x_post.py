import json
import unittest

import canal_nube as cn
import x_post


class FakeTG:
    def __init__(self):
        self.sent = []

    def call(self, method, params=None):
        self.sent.append((method, params))
        return {"message_id": 1}


class XPost(unittest.TestCase):
    def test_voice(self):
        text = x_post.build_x_post("XIAOMI TV Pro 32 Pulgadas 2026, QLED Smart TV", "Xiaomi",
                                   "https://amzn.example/x", seed="a", badge="CHOLLAZO")
        lines = text.split("\n\n")
        self.assertIn("tv de @XiaomiEspana (Xiaomi TV Pro 32 Pulgadas 2026)", text)
        self.assertTrue(all(l[0].isupper() or l[0] in "@h¿👇" for l in lines))
        self.assertEqual(lines[-1], "https://amzn.example/x")
        self.assertTrue(lines[-2].endswith("👇🏼"), "el enlace va debajo de la flechita")
        self.assertNotIn("afiliado", text)
        self.assertLessEqual(x_post.x_length(text), 280)

    def test_templates_rotate(self):
        recent, firsts = [], []
        for i in range(10):
            text = x_post.build_x_post("Cecotec Conga 2290 Robot aspirador", "Cecotec", "https://a.example/x",
                                       seed=f"s{i % 2}", recent=recent, hour=16, month=11, day=7)
            firsts.append(text.split("\n\n")[0])
            self.assertLessEqual(x_post.x_length(text), 280)
        self.assertEqual(len(set(firsts[:8])), 8, "no se repite el gancho en 8 posts seguidos")

    def test_season_and_error_templates(self):
        ids = {t["id"] for t in x_post.TEMPLATES if x_post._fits(t, "CHOLLO", "esta tv", 15, 12, 5)}
        self.assertNotIn("black-friday", ids)
        self.assertNotIn("error", ids)
        self.assertIn("error", {t["id"] for t in x_post.TEMPLATES
                                if x_post._fits(t, "ERROR DE PRECIO", "", 15, 11, 7)})
        self.assertEqual(x_post.indefinite("esta tv"), "una tv")

    def test_aliexpress_numbers(self):
        text = x_post.build_x_post("Auriculares Soundcore P40i", "Soundcore", "https://s.click.aliexpress.com/e/_x",
                                   badge="CHOLLAZO", price=24.5, reference=49.0, numbers=True)
        self.assertIn("24,50€", text)
        self.assertIn("49€", text)
        self.assertIn("50%", text)

    def test_amazon_compliant(self):
        deal = {"title": "Gillette Fusion5 Cuchillas de Afeitar Hombre", "brand": "Gillette", "asin": "B04",
                "price": 34.99, "reference": 54.33}
        text = cn.x_text(deal, "https://www.amazon.es/dp/B04?tag=t-21", {})
        for banned in ("€", "%", "Amazon", "AMAZON", "⭐", "valoraciones"):
            self.assertNotIn(banned, text)
        self.assertIn("esta afeitadora gillette fusion5", text.lower())

    def test_unknown_brand_not_tagged_and_amazon_brand_dropped(self):
        self.assertEqual(x_post.brand_mention("CECOTEC"), "Cecotec")
        self.assertEqual(x_post.brand_mention("Amazon Basics"), "")
        self.assertEqual(x_post.brand_mention("Dreame", {"dreame": "DreameES"}), "@DreameES")

    def test_draft_goes_to_admin_only(self):
        tg = FakeTG()
        state = {"private_chats": {"x": 42}}
        rules = {"admin_username": "x", "chat_id": "@cazachollos_com"}
        cn.send_x_draft(tg, state, rules, {"title": "Xiaomi TV", "brand": "Xiaomi", "asin": "B1"},
                        "https://www.amazon.es/dp/B1?tag=t-21", log=lambda *_: None, manual=True)
        self.assertEqual(len(tg.sent), 1)
        method, params = tg.sent[0]
        self.assertEqual(params["chat_id"], 42)
        self.assertIn("Paid partnership", params["text"])

    def test_prices_only_with_api_flag(self):
        deal = {"title": "Corsair Vengeance 16GB DDR4", "brand": "Corsair", "asin": "B1", "discount": 65,
                "price": 19.9, "reference": 69.9}
        without = cn.x_text(deal, "https://www.amazon.es/dp/B1?tag=t-21", cn.rules_from({}))
        self.assertNotIn("€", without)
        with_api = cn.x_text(deal, "https://www.amazon.es/dp/B1?tag=t-21", dict(cn.rules_from({}), x_prices=True))
        self.assertIn("19,90€", with_api)

    def test_draft_can_be_turned_off(self):
        tg = FakeTG()
        cn.send_x_draft(tg, {"admin_chat_id": 42}, {"x_drafts": False}, {"title": "t", "asin": "1"}, "u")
        self.assertEqual(tg.sent, [])


if __name__ == "__main__":
    unittest.main()


class AlbumAmazon(unittest.TestCase):
    DEAL = {"asin": "B0TEST", "title": "XIAOMI TV Pro 32 Pulgadas 2026, QLED Smart TV", "price": 149.0,
            "reference": 229.0, "discount": 34.9, "ref_kind": "pvp", "seen_ts": 1793872000,
            "image": "https://m.media-amazon.com/images/I/test.jpg"}
    RULES = {"bargain_min_discount": 20, "error_min_discount": 60, "chollazo_min_discount": 40}

    def test_card_amazon_colors_without_brand(self):
        import aliexpress_card as ac
        rules = dict(cn.rules_from({}), **self.RULES)
        card = cn.make_card(dict(self.DEAL), rules)
        self.assertTrue(card.exists())
        self.assertTrue(card.name.startswith("amz-"))
        self.assertEqual(ac.HEADER, ("EN", "ALIEXPRESS"), "el tema de Amazon no debe quedarse puesto")
        self.assertNotIn("AMAZON", " ".join(ac.THEMES["amazon"]["HEADER"]).upper())

    def test_album_photo_by_url_untouched(self):
        sent = {}

        def fake_group(tg, chat, media, files):
            sent.update(media=media, files=files)
            return [{"message_id": 11}, {"message_id": 12}]

        original = cn._media_group
        cn._media_group = fake_group
        try:
            rules = dict(cn.rules_from({}), **self.RULES, post_style="album")
            msg = cn.publish(object(), "@c", dict(self.DEAL), rules, "texto", "https://www.amazon.es/dp/B0TEST")
        finally:
            cn._media_group = original
        self.assertEqual(msg["message_id"], 11)
        self.assertEqual(sent["media"][0]["media"], self.DEAL["image"])
        self.assertEqual(sent["media"][0]["caption"], "texto")
        self.assertEqual(list(sent["files"]), ["card"], "la foto de Amazon no se descarga ni se sube retocada")


    def test_two_separate_photos_by_default(self):
        calls = []

        class FakeTG:
            def call(self, method, params):
                calls.append((method, params))
                return {"message_id": 21}

            def send_photo(self, chat, image, caption, extra=None):
                calls.append(("sendPhoto-card", {"caption": caption, **(extra or {})}))
                return {"message_id": 22}

        rules = dict(cn.rules_from({}), **self.RULES)
        rules.pop("post_style", None)
        msg = cn.publish(FakeTG(), "@c", dict(self.DEAL), rules, "texto", "https://www.amazon.es/dp/B0TEST")
        self.assertEqual([c[0] for c in calls], ["sendPhoto", "sendPhoto-card"])
        self.assertEqual(calls[0][1]["photo"], self.DEAL["image"], "la foto de Amazon va por URL, sin retocar")
        self.assertTrue(calls[0][1]["disable_notification"])
        self.assertEqual(calls[1][1]["caption"], "texto")
        button = calls[1][1]["reply_markup"]["inline_keyboard"][0][0]
        self.assertEqual((button["text"], button["style"]), ("🛒 Comprar en Amazon", "success"))
        self.assertEqual((msg["message_id"], msg["photo_message_id"]), (22, 21))

    def test_channel_own_affiliate_tag(self):
        cfg = {"affiliate_tag": "viejo-21", "amazon_channel": {"affiliate_tag": "cazachollos0c-21"}}
        self.assertEqual(cn.rules_from(cfg)["tag"], "cazachollos0c-21")
        self.assertEqual(cn.rules_from({"affiliate_tag": "viejo-21"})["tag"], "viejo-21")
        real = json.load(open(cn.ROOT / "config.json", encoding="utf-8"))
        self.assertEqual(cn.rules_from(real)["tag"], "cazachollos0c-21")
        self.assertNotIn("album_solo_pruebas", real["amazon_channel"])

    def test_summary_image_without_amazon_photos(self):
        items = [{"title": f"Producto {i}", "price": 10.0 + i, "reference": 30.0, "discount": 50, "image": "https://x/y.jpg"}
                 for i in range(4)]

        def no_download(url):
            raise AssertionError("la imagen de cierre no debe bajar fotos de Amazon")

        self.assertTrue(cn.make_summary_collage(items, download=no_download).is_file())
        self.assertIsNone(cn.make_summary_collage(items[:1]))

class FiltroX(unittest.TestCase):
    from datetime import datetime, timezone
    NOW = datetime(2026, 11, 5, 11, 0, tzinfo=timezone.utc)
    BASE = {"title": "Roborock Qrevo S", "asin": "B1", "price": 199.0, "reference": 399.0, "discount": 50,
            "interest": 100, "interest_label": "Aspiradoras"}

    def rules(self):
        return cn.rules_from(__import__("json").load(open("config.json")))

    def test_top_and_strong_passes(self):
        self.assertEqual(cn.x_worthy(dict(self.BASE), self.rules(), {}, self.NOW), "")

    def test_low_interest_category_out(self):
        why = cn.x_worthy(dict(self.BASE, interest=60, interest_label="Moda de marca"), self.rules(), {}, self.NOW)
        self.assertIn("categoría", why)

    def test_weak_discount_out(self):
        self.assertIn("descuento", cn.x_worthy(dict(self.BASE, discount=26, price=295), self.rules(), {}, self.NOW))

    def test_small_saving_out(self):
        self.assertIn("ahorro", cn.x_worthy(dict(self.BASE, price=6.0, reference=12.0), self.rules(), {}, self.NOW))

    def test_daily_cap_and_spacing(self):
        t = self.NOW.timestamp()
        self.assertIn("seguido", cn.x_worthy(dict(self.BASE), self.rules(), {"x_drafts": [t - 600]}, self.NOW))
        full = {"x_drafts": [t - 3600 * h for h in range(1, 7)]}
        self.assertIn("hoy", cn.x_worthy(dict(self.BASE), self.rules(), full, self.NOW))

    def test_auto_skips_but_manual_sends(self):
        tg = FakeTG()
        state = {"private_chats": {"x": 42}}
        rules = {**self.rules(), "admin_username": "x"}
        weak = dict(self.BASE, interest=55, interest_label="Textil hogar")
        cn.send_x_draft(tg, state, rules, weak, "u", log=lambda *_: None)
        self.assertEqual(tg.sent, [])
        cn.send_x_draft(tg, state, rules, weak, "u", log=lambda *_: None, manual=True)
        self.assertEqual(len(tg.sent), 1)


class TagX(unittest.TestCase):
    def test_x_uses_its_own_tag(self):
        deal = {"title": "Xiaomi TV", "brand": "Xiaomi", "asin": "B0TV", "discount": 50}
        rules = dict(cn.rules_from({}), x_affiliate_tag="nuevo-21")
        text = cn.x_text(deal, "https://www.amazon.es/dp/B0TV?tag=cazadores_errores-21", rules)
        self.assertIn("tag=nuevo-21", text)
        self.assertNotIn("cazadores_errores-21", text)
