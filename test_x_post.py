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
