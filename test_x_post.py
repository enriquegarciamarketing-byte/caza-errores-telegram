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
    def test_tv_format(self):
        text = x_post.build_x_post("Xiaomi TV Pro 32 Pulgadas QLED Smart TV", "Xiaomi", "https://amzn.example/x", seed="a")
        lines = text.split("\n\n")
        self.assertIn(lines[0], x_post.HOOKS)
        self.assertTrue(lines[1].startswith("TV de la marca @XiaomiEspana "))
        self.assertEqual(lines[-2], "🔗 https://amzn.example/x")
        self.assertEqual(lines[-1], "#ad")

    def test_amazon_compliant(self):
        deal = {"title": "Gillette Fusion5 Cuchillas de Afeitar Hombre", "brand": "Gillette", "asin": "B04",
                "price": 34.99, "reference": 54.33}
        text = cn.x_text(deal, "https://www.amazon.es/dp/B04?tag=t-21", {})
        for banned in ("€", "%", "Amazon", "AMAZON", "⭐", "valoraciones"):
            self.assertNotIn(banned, text)
        self.assertIn("Afeitadora de la marca Gillette", text)

    def test_unknown_brand_not_tagged_and_amazon_brand_dropped(self):
        self.assertEqual(x_post.brand_mention("Cecotec"), "Cecotec")
        self.assertEqual(x_post.brand_mention("Amazon Basics"), "")
        self.assertEqual(x_post.brand_mention("Dreame", {"dreame": "DreameES"}), "@DreameES")

    def test_draft_goes_to_admin_only(self):
        tg = FakeTG()
        state = {"private_chats": {"x": 42}}
        rules = {"admin_username": "x", "chat_id": "@cazachollos_com"}
        cn.send_x_draft(tg, state, rules, {"title": "Xiaomi TV", "brand": "Xiaomi", "asin": "B1"},
                        "https://www.amazon.es/dp/B1?tag=t-21", log=lambda *_: None)
        self.assertEqual(len(tg.sent), 1)
        method, params = tg.sent[0]
        self.assertEqual(params["chat_id"], 42)
        self.assertIn("#ad", params["text"])

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
            rules = dict(cn.rules_from({}), **self.RULES)
            msg = cn.publish(object(), "@c", dict(self.DEAL), rules, "texto", "https://www.amazon.es/dp/B0TEST")
        finally:
            cn._media_group = original
        self.assertEqual(msg["message_id"], 11)
        self.assertEqual(sent["media"][0]["media"], self.DEAL["image"])
        self.assertEqual(sent["media"][0]["caption"], "texto")
        self.assertEqual(list(sent["files"]), ["card"], "la foto de Amazon no se descarga ni se sube retocada")
