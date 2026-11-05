import hashlib
import io
import json
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import aliexpress_api as api_mod
import aliexpress_card
import canal_aliexpress as ca

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "tests_fixtures" / "aliexpress_products.json"
NOW = datetime(2026, 11, 20, 11, 0, tzinfo=timezone.utc)  # 12:00 en Madrid
TODAY = NOW.astimezone(ca.MADRID).date()


def rules(**over):
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    r = ca.rules_from(cfg)
    r.update({"live": True, "admin_username": "tester", **over})
    return r


def products():
    return [api_mod.normalize(p) for p in json.loads(FIXTURE.read_text(encoding="utf-8"))]


def with_history(pid: str, price: float, days: int) -> dict:
    state = {"history": {pid: {"t": "x", "s": ca.day_num(TODAY), "p": []}}}
    for i in range(days, 0, -1):
        state["history"][pid]["p"].append([ca.day_num(TODAY - timedelta(days=i)), int(price * 100)])
    return state


class FakeTG:
    def __init__(self):
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        return []

    def multipart(self, method, fields, files):
        self.calls.append((method, fields, list(files)))
        return [{"message_id": 10}, {"message_id": 11}]


class SignAndParse(unittest.TestCase):
    def test_sign_matches_top_md5(self):
        params = {"b": "2", "a": "1", "method": "x.y"}
        expected = hashlib.md5("SECRETa1b2methodx.ySECRET".encode()).hexdigest().upper()
        self.assertEqual(api_mod.sign("SECRET", params), expected)

    def test_call_parses_result_and_errors(self):
        body = {"aliexpress_affiliate_productdetail_get_response": {"resp_result": {
            "resp_code": 200, "result": {"products": {"product": json.loads(FIXTURE.read_text())[:1]}}}}}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        api = api_mod.AliExpressAPI("k", "s", "cazachollos_tg", opener=lambda req, timeout: Resp(json.dumps(body).encode()))
        got = api.details(["1005001"])
        self.assertEqual(got[0]["price"], 129.99)
        self.assertEqual(got[0]["coupon"]["code"], "ESAE08")
        err = {"error_response": {"code": "IncompleteSignature", "msg": "bad sign"}}
        api2 = api_mod.AliExpressAPI("k", "s", "t", opener=lambda req, timeout: Resp(json.dumps(err).encode()))
        with self.assertRaises(api_mod.AliExpressError):
            api2.details(["1"])

    def test_from_env_without_keys(self):
        import os
        for k in ("ALIEXPRESS_APP_KEY", "ALIEXPRESS_APP_SECRET", "ALIEXPRESS_TRACKING_ID"):
            os.environ.pop(k, None)
        self.assertIsNone(api_mod.AliExpressAPI.from_env())


class Evaluate(unittest.TestCase):
    def test_real_discount_needs_history(self):
        p = products()[0]
        verdict, _ = ca.evaluate(p, {}, TODAY, rules())
        self.assertTrue(verdict.startswith("aprendiendo"))
        verdict, deal = ca.evaluate(p, with_history(p["id"], 199.0, 8), TODAY, rules())
        self.assertEqual(verdict, "ok")
        self.assertEqual(round(deal["discount"]), 35)
        self.assertEqual(deal["badge"], "CHOLLO")
        self.assertEqual(deal["reference"], 199.0)  # nunca el "precio original" inflado (399,99)

    def test_error_needs_14_days(self):
        p = {**products()[0], "price": 40.0}
        _, deal = ca.evaluate(p, with_history(p["id"], 199.0, 8), TODAY, rules(max_discount_pct=95))
        self.assertEqual(deal["badge"], "CHOLLAZO")
        _, deal = ca.evaluate(p, with_history(p["id"], 199.0, 20), TODAY, rules(max_discount_pct=95))
        self.assertEqual(deal["badge"], "ERROR DE PRECIO")

    def test_top_sales_blocked_and_rating(self):
        top, blocked, low = products()[1:]
        self.assertEqual(ca.evaluate(top, {}, TODAY, rules())[0], "top")
        self.assertTrue(ca.evaluate(blocked, {}, TODAY, rules())[0].startswith("bloqueado"))
        self.assertEqual(ca.evaluate(low, {}, TODAY, rules())[0], "valoración baja")

    def test_history_excludes_today_and_prunes(self):
        state = {}
        p = products()[0]
        ca.record(state, p, TODAY)
        ca.record(state, {**p, "price": 120.0}, TODAY)
        self.assertEqual(state["history"][p["id"]]["p"], [[ca.day_num(TODAY), 12000]])
        self.assertEqual(ca.reference_30(state, p["id"], TODAY), (None, 0))
        old = with_history("viejo", 10, 3)
        old["history"]["viejo"]["s"] = ca.day_num(TODAY) - 100
        ca.prune(old, TODAY, rules())
        self.assertNotIn("viejo", old["history"])


class Texts(unittest.TestCase):
    def test_caption_and_x(self):
        p = products()[0]
        _, deal = ca.evaluate(p, with_history(p["id"], 199.0, 8), TODAY, rules())
        cap = ca.build_caption(deal, "12:00")
        for bit in ("#Publicidad", "enlace de afiliado", "Ver en AliExpress", "precio más bajo de los 30 días",
                    "ESAE08", "124,50 €"):
            self.assertIn(bit, cap)
        self.assertNotIn("399", cap)
        x = ca.build_x_text({**deal, "title": "Producto " * 60}, "https://s.click.aliexpress.com/e/_x")
        self.assertLessEqual(ca.x_length(x), 280)
        self.assertNotIn("#ad", x)
        self.assertNotIn("€", x)
        ended = ca.ended_caption(cap, "15:00")
        self.assertTrue(ended.startswith("⛔"))
        self.assertNotIn("Ver en AliExpress", ended)

    def test_top_caption_has_no_strikethrough(self):
        _, deal = ca.evaluate(products()[1], {}, TODAY, rules())
        cap = ca.build_caption(deal, "12:00")
        self.assertNotIn("<s>", cap)
        self.assertNotIn("%</b> frente", cap)

    def test_cards_fit(self):
        long = "Título larguísimo de prueba " * 12
        aliexpress_card.create_card({"id": "t1", "title": long, "price": 1234.56, "reference": 9999.99,
                                     "badge": "ERROR DE PRECIO", "seen_hhmm": "12:00", "app_price": 1200,
                                     "coupon": {"code": "ESAE20AAAAA"}})
        aliexpress_card.create_card({"id": "t3", "title": long, "price": 89, "reference": 329,
                                     "badge": "ERROR DE PRECIO", "seen_hhmm": "12:00"})
        aliexpress_card.create_card({"id": "t2", "title": long, "price": 9.99, "badge": "TOP VENTAS",
                                     "note": ca.TOP_NOTE, "seen_hhmm": "12:00", "app_price": 8,
                                     "coupon": {"code": "X"}})


class Codes(unittest.TestCase):
    def test_best_valid_campaign_code(self):
        r = rules()
        when = datetime(2026, 11, 12, 10, tzinfo=timezone.utc)
        self.assertIsNone(ca.campaign_code(10, r, when))
        self.assertEqual(ca.campaign_code(50, r, when)["code"], "AEES08")
        self.assertEqual(ca.campaign_code(500, r, when)["code"], "AEES75")
        self.assertIsNone(ca.campaign_code(50, r, datetime(2026, 11, 19, tzinfo=timezone.utc)))

    def test_product_coupon_wins_and_shows_in_texts(self):
        r = rules()
        when = datetime(2026, 11, 12, 10, tzinfo=timezone.utc)
        own = ca.with_coupon(products()[0], r, when)
        self.assertEqual(own["coupon"]["code"], "ESAE08")
        _, deal = ca.evaluate(products()[1], {}, TODAY, r)
        deal = ca.with_coupon({**deal, "price": 50.0}, r, when)
        cap = ca.build_caption(deal, "12:00")
        self.assertIn("AEES08", cap)
        self.assertIn("hasta el 18/11", cap)
        self.assertIn("AEES08", ca.build_x_text(deal, "https://s.click.aliexpress.com/e/_x"))


class Quotas(unittest.TestCase):
    def test_quota_and_repost(self):
        r = rules()
        deal = {"id": "1", "price": 10.0, "badge": "CHOLLO"}
        state = {"posts": [{"id": "1", "price": 10.5, "badge": "CHOLLO", "ts": (NOW - timedelta(minutes=3)).timestamp()}]}
        self.assertEqual(ca.quota_reason(state, NOW, r, deal, 0), "muy seguido del anterior")
        self.assertTrue(ca.recently_posted(state, deal, NOW, r))
        self.assertFalse(ca.recently_posted(state, {**deal, "price": 8.0}, NOW, r))
        self.assertTrue(ca.in_quiet_hours(datetime(2026, 11, 20, 2, 0, tzinfo=timezone.utc), r))


class RunPass(unittest.TestCase):
    def args(self, **kw):
        import argparse
        return argparse.Namespace(dry_run=False, test_private=False, **kw)

    def test_test_private_goes_only_to_admin_with_x_draft(self):
        import os
        os.environ["ALIEXPRESS_TRACKING_ID_X"] = "cazachollos_x"
        api = ca.FixtureAPI(str(FIXTURE))
        state = {"private_chats": {"tester": 999}, **with_history("1005001", 199.0, 8)}
        tg = FakeTG()
        import argparse
        sent = ca.run_pass(argparse.Namespace(dry_run=False, test_private=True),
                           rules(), state, NOW, api, tg, log=lambda *_: None)
        self.assertEqual(sent, 2)
        groups = [c for c in tg.calls if c[0] == "sendMediaGroup"]
        self.assertTrue(all(c[1]["chat_id"] == "999" for c in groups))
        self.assertIn("PRUEBA", groups[0][1]["media"][0]["caption"])
        drafts = [c for c in tg.calls if c[0] == "sendPhoto"]
        self.assertEqual(len(drafts), 2)
        self.assertIn("aff_fcid=prueba-cazachollos_x", drafts[0][1]["caption"])
        self.assertFalse(state.get("posts"))

    def test_live_off_learns_but_does_not_post(self):
        api = ca.FixtureAPI(str(FIXTURE))
        state = {"private_chats": {"tester": 999}}
        tg = FakeTG()
        import argparse
        sent = ca.run_pass(argparse.Namespace(dry_run=False, test_private=False), rules(live=False), state,
                           NOW, api, tg, log=lambda *_: None)
        self.assertFalse([c for c in tg.calls if c[0] == "sendMediaGroup"])
        self.assertIn("1005001", state["history"])
        self.assertGreaterEqual(sent, 0)

    def test_live_posts_to_channel_and_records(self):
        api = ca.FixtureAPI(str(FIXTURE))
        state = {"private_chats": {"tester": 999}, **with_history("1005001", 199.0, 8)}
        tg = FakeTG()
        import argparse
        ca.run_pass(argparse.Namespace(dry_run=False, test_private=False), rules(), state, NOW, api, tg,
                    log=lambda *_: None)
        groups = [c for c in tg.calls if c[0] == "sendMediaGroup"]
        self.assertEqual(groups[0][1]["chat_id"], "@cazachollos_com")
        self.assertEqual(state["posts"][0]["message_ids"], [10, 11])


if __name__ == "__main__":
    unittest.main()
