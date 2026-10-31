"""Pruebas del canal en la nube con páginas reales de Jimmyleaks (31/10/2026)."""

import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import canal_nube as cn
import scanner

FIX = Path(__file__).resolve().parent / "tests_fixtures"
LISTING = (FIX / "jl_listing.html").read_text(encoding="utf-8")
LEFANT = (FIX / "jl_detail_lefant.html").read_text(encoding="utf-8")
SOCKS = (FIX / "jl_detail_calcetines.html").read_text(encoding="utf-8")
CFG = {"affiliate_tag": "cazadores_errores-21",
       "amazon_channel": {"sources": ["https://jimmyleaks.com/es/minimos-de-hoy/"], "block_keywords": ["funda"]}}
RULES = cn.rules_from(CFG)
# Lefant visto en Jimmyleaks a las 15:52:40 UTC (data-timestamp 1793461960).
NOW = datetime.fromtimestamp(1793461960 + 9 * 60, timezone.utc)


def item_for(jl_id: str) -> dict:
    return next(i for i in scanner.parse_listing(LISTING) if i["id"] == jl_id)


class Historial(unittest.TestCase):
    def test_precio_habitual_es_la_mediana_antes_de_la_bajada(self):
        points = [["2026-07-01", 100.0], ["2026-09-01", 120.0], ["2026-10-20", 50.0]]
        hist = cn.history_reference(points, 50.0, date(2026, 10, 21))
        self.assertTrue(hist["ok"])
        self.assertEqual(hist["drop_start"], "2026-10-20")
        self.assertEqual(hist["reference"], 120.0)  # 49 días a 120 frente a 41 a 100
        self.assertEqual(hist["min_30"], 120.0)
        self.assertEqual(hist["days"], 90)

    def test_lefant_real(self):
        detail = scanner.parse_detail(LEFANT)
        hist = cn.history_reference(cn.amazon_series(detail["series"]), detail["price"], date(2026, 10, 31))
        self.assertEqual(hist["drop_start"], "2026-10-30")
        # Pasó 49 de los 90 días a 1.299,99 €, pero en los 30 días previos llegó a estar a 799,99 €.
        # La referencia publicada es esta última: es la que no exagera el descuento.
        self.assertEqual(hist["reference"], 1299.99)
        self.assertEqual(hist["min_30"], 799.99)


class Reglas(unittest.TestCase):
    def test_lefant_pasa_con_precio_y_referencia_honestos(self):
        why, deal = cn.evaluate(item_for("R0ZG4Bv"), scanner.parse_detail(LEFANT), RULES, NOW)
        self.assertEqual(why, "")
        self.assertEqual(deal["price"], 379.98)
        self.assertEqual(deal["reference"], 799.99)
        self.assertEqual(round(deal["discount"]), 53)
        self.assertTrue(deal["historical_low"])

    def test_precio_visto_hace_mucho_no_pasa(self):
        later = datetime.fromtimestamp(1793461960 + 3 * 3600, timezone.utc)
        why, _ = cn.evaluate(item_for("R0ZG4Bv"), scanner.parse_detail(LEFANT), RULES, later)
        self.assertIn("precio visto hace", why)

    def test_listado_y_ficha_deben_coincidir(self):
        item = dict(item_for("R0ZG4Bv"), price=399.0)
        why, _ = cn.evaluate(item, scanner.parse_detail(LEFANT), RULES, NOW)
        self.assertIn("no coinciden", why)

    def test_calcetines_rebaja_pequena_no_pasa(self):
        item = item_for("RavB6pe")
        now = datetime.fromtimestamp(item["ts"] + 60, timezone.utc)
        why, _ = cn.evaluate(item, scanner.parse_detail(SOCKS), RULES, now)
        self.assertTrue(why.startswith("solo -") or "opiniones" in why or "rango" in why, why)

    def test_asin_del_boton_de_compra(self):
        self.assertEqual(cn.parse_asin("https://amazon.es/dp/B0G7YP6MXV?tag=jimmylks-21"), "B0G7YP6MXV")
        self.assertEqual(cn.parse_asin("https://www.amazon.es/Lefant-M5/dp/B0G7YP6MXV/ref=x"), "B0G7YP6MXV")
        self.assertIsNone(cn.parse_asin("https://amazon.com/dp/B0G7YP6MXV"))
        self.assertIsNone(cn.parse_asin("https://jimmyleaks.com/es/"))


class Texto(unittest.TestCase):
    def test_caption(self):
        _, deal = cn.evaluate(item_for("R0ZG4Bv"), scanner.parse_detail(LEFANT), RULES, NOW)
        deal["asin"] = "B0G7YP6MXV"
        text = cn.build_caption(deal, "https://www.amazon.es/dp/B0G7YP6MXV?tag=cazadores_errores-21", RULES)
        self.assertIn("379,98 €", text)
        self.assertIn("precio más bajo de los 30 días anteriores", text)
        self.assertIn("<s>799,99 €</s>", text)
        self.assertIn("a las 16:52", text)
        self.assertIn("dp/B0G7YP6MXV?tag=cazadores_errores-21", text)
        self.assertNotIn("PVP", text)
        self.assertNotIn("jimmylks", text)


class Administrador(unittest.TestCase):
    def setUp(self):
        self._premium = cn.PREMIUM_STATE
        cn.PREMIUM_STATE = FIX / "no_existe.json"  # sin depender del estado real del escáner

    def tearDown(self):
        cn.PREMIUM_STATE = self._premium

    def test_busca_tu_chat_por_usuario_sin_marcar_mensajes(self):
        calls = []

        class TG:
            def call(self, method, params):
                calls.append((method, params))
                return [{"update_id": 5, "message": {"chat": {"id": 42, "type": "private", "username": "Darkness_gg"}}},
                        {"update_id": 6, "message": {"chat": {"id": 7, "type": "private", "username": "otro"}}}]
        state = {}
        rules = dict(RULES, admin_username="@Darkness_gg")
        self.assertEqual(cn.admin_chat_id(state, rules, TG()), 42)
        self.assertNotIn("offset", calls[0][1], "no debe confirmar los mensajes del escáner")
        self.assertEqual(state["private_chats"]["darkness_gg"], 42)

    def test_sin_mensaje_tuyo_no_usa_otro_chat(self):
        class TG:
            def call(self, method, params):
                return []
        self.assertIsNone(cn.admin_chat_id({}, dict(RULES, admin_username="nadie_xyz"), TG()))


class Fuentes(unittest.TestCase):
    def test_rota_las_categorias_y_mantiene_las_principales(self):
        rules = dict(RULES, sources=["a", "b", "c"] + [f"cat{i}" for i in range(20)], core_sources=3,
                     max_sources_per_run=10)
        seen = set()
        for step in range(4):
            now = datetime.fromtimestamp(1793462400 + step * 300, timezone.utc)
            picked = cn.sources_for_run(rules, now)
            self.assertEqual(picked[:3], ["a", "b", "c"])
            self.assertEqual(len(picked), 10)
            seen.update(picked[3:])
        self.assertEqual(len(seen), 20, "en cuatro pasadas se recorren todas las categorías")


class Resumen(unittest.TestCase):
    def state(self, now):
        base = int(now.timestamp()) - 3600
        return {"posts": [
            {"asin": "B0G7YP6MXV", "jl_id": "R0ZG4Bv", "price": 379.98, "reference": 799.99, "t": base,
             "url": "https://www.amazon.es/dp/B0G7YP6MXV?tag=cazadores_errores-21", "title": "Lefant M5 Pro Robot"},
            {"asin": "B0FDQD4L48", "jl_id": "OTRO", "price": 39.98, "reference": 132.99, "t": base,
             "url": "https://www.amazon.es/dp/B0FDQD4L48?tag=cazadores_errores-21", "title": "Plancha Faszin", "ended": 1},
        ]}

    def test_lista_solo_los_que_siguen_activos_y_ordenados(self):
        now = datetime(2026, 10, 31, 22, 30, tzinfo=timezone.utc)  # 23:30 en Madrid
        items = cn.summary_items(self.state(now), now, RULES, lambda url: LEFANT, lambda *_: None)
        self.assertEqual([i["asin"] for i in items], ["B0G7YP6MXV"])  # el terminado no sale
        text = cn.build_summary(items, now)
        self.assertIn("LO MEJOR DEL DÍA", text)
        self.assertIn("1️⃣", text)
        self.assertIn("379,98 €", text)
        self.assertIn("a las 23:30", text)
        self.assertIn("tag=cazadores_errores-21", text)

    def test_si_ha_subido_no_sale(self):
        now = datetime(2026, 10, 31, 22, 30, tzinfo=timezone.utc)
        dearer = LEFANT.replace('"price": "379.98"', '"price": "449.00"')
        self.assertEqual(cn.summary_items(self.state(now), now, RULES, lambda url: dearer, lambda *_: None), [])

    def test_solo_a_su_hora_y_una_vez(self):
        out = []
        args = SimpleNamespace(dry_run=True, test_private=False, ignore_limits=False)
        cn.run_summary(args, CFG, {"posts": []}, datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc), log=out.append)
        self.assertIn("no es la hora", out[-1])
        state = {"posts": [], "summary_sent": "2026-10-31"}
        cn.run_summary(args, CFG, state, datetime(2026, 10, 31, 22, 31, tzinfo=timezone.utc), log=out.append)
        self.assertIn("ya enviado", out[-1])


class Pasada(unittest.TestCase):
    def pages(self, detail_pages=None):
        detail_pages = detail_pages or {}

        def fetch(url):
            if "/es/dp/" in url:
                jl_id = url.rstrip("/").split("/")[-1]
                value = detail_pages.get(jl_id, LEFANT)
                return value() if callable(value) else value
            return LISTING
        return fetch

    def test_dry_run_publica_lefant_con_enlace_exacto(self):
        out = []
        state = {"posts": []}
        cn.run(SimpleNamespace(dry_run=True, test_private=False, ignore_limits=True), CFG, state, NOW,
               fetch=self.pages({"R0ZG4Bv": LEFANT}), resolve_asin=lambda jl: "B0G7YP6MXV", log=out.append)
        text = "\n".join(out)
        self.assertIn("[prueba, no se envía]", text)
        self.assertIn("https://www.amazon.es/dp/B0G7YP6MXV?tag=cazadores_errores-21", text)
        self.assertEqual(state["posts"], [])

    def test_sin_asin_no_se_publica(self):
        out = []
        cn.run(SimpleNamespace(dry_run=True, test_private=False, ignore_limits=True), CFG, {"posts": []}, NOW,
               fetch=self.pages(), resolve_asin=lambda jl: None, log=out.append)
        self.assertNotIn("[prueba, no se envía]", "\n".join(out))
        self.assertIn("ASIN", "\n".join(out))

    def test_cambio_de_precio_en_la_segunda_lectura(self):
        reads = iter([LEFANT, LEFANT.replace('"price": "379.98"', '"price": "449.00"')])
        changed = LEFANT.replace('"price": "379.98"', '"price": "449.00"')
        self.assertNotEqual(changed, LEFANT, "el JSON-LD debe tener el precio en este formato")
        out = []
        cn.run(SimpleNamespace(dry_run=True, test_private=False, ignore_limits=True), CFG, {"posts": []}, NOW,
               fetch=self.pages({"R0ZG4Bv": lambda: next(reads)}), resolve_asin=lambda jl: "B0G7YP6MXV",
               log=out.append)
        text = "\n".join(out)
        self.assertIn("el precio ha cambiado", text)
        self.assertNotIn("[prueba, no se envía]", text)

    def test_horario_de_silencio(self):
        night = datetime(2026, 10, 31, 2, 0, tzinfo=timezone.utc)
        self.assertEqual(cn.quota_reason({"posts": []}, night, RULES), "horario de silencio")


if __name__ == "__main__":
    unittest.main()
