"""Pruebas del canal en la nube con páginas reales de Jimmyleaks (31/10/2026)."""

import json
import unittest
from datetime import date, datetime, timedelta, timezone
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
        self.assertIn("-71 %</b> frente a su precio habitual de los últimos 90 días (1.299,99 €)", text)
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


REAL = cn.rules_from(json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8")))


class Interes(unittest.TestCase):
    def test_lo_que_mas_se_compra_puntua_alto(self):
        for title in ["Roborock Qrevo S Pro Robot Aspirador", "De'Longhi Cafetera superautomática",
                      "Samsung Galaxy A56 smartphone 256GB", "Frigorífico combi No Frost", "Sofá cama 3 plazas",
                      "Cosori Freidora de aire 5,5 L"]:
            self.assertGreaterEqual(cn.interest(title, REAL)["score"], 90, title)

    def test_lo_de_poco_interes_queda_fuera(self):
        for title in ["Amazon Basics Cinta de Embalaje de 7,2 CM", "fischer DUOPOWER 8 x 65 caja de tacos",
                      "MANN-FILTER P 917/2 x Filtro de combustible", "Oxford Classic Pack de 10 libretas",
                      "Funda para iPhone 15 de silicona", "Der Rose Plantas Artificiales Grandes",
                      "FILA Calzoncillos Hombre Boxer Pack de 4"]:
            self.assertTrue(cn.interest(title, REAL)["blocked"], title)

    def test_las_categorias_estrella_salen_desde_el_18(self):
        self.assertEqual(cn.interest("Cecotec Robot Aspirador Conga", REAL)["min_discount"], 18)
        self.assertEqual(cn.interest("Samsung televisor smart tv 55", REAL)["min_discount"], 20)
        self.assertIsNone(cn.interest("Rowenta Intense Comfort calefactor", REAL).get("min_discount"))

    def test_la_categoria_la_marca_el_arranque_del_titulo(self):
        wmf = cn.interest("WMF Atria - Cubertería 60 piezas 12 comensales acero Cromargan, apto para lavavajillas", REAL)
        self.assertLess(wmf["score"], 90, "una cubertería no es un electrodoméstico")
        self.assertIsNone(wmf.get("min_discount"))
        coche = cn.interest("ISAMUTO Arrancador de Coche 3000A con Compresor, Power Bank para cargar el móvil", REAL)
        self.assertLess(coche["score"], 90)
        self.assertEqual(cn.interest("Cecotec, Robot Aspirador Conga 2290 Ultra, láser", REAL)["score"], 100)
        self.assertEqual(cn.interest("GTPLAYER Silla de Gaming, Silla de Oficina con Cojín", REAL)["score"], 95)

    def test_cafe_soluble_no_es_una_cafetera(self):
        self.assertTrue(cn.interest("Nescafé Classic café soluble 20 bolsitas", REAL)["blocked"])

    def test_orden_prioriza_interes_y_descuento(self):
        robot = {"interest": 100, "discount": 45, "price": 330, "reference": 600}
        tape = {"interest": 0, "discount": 52, "price": 9.4, "reference": 19.59}
        self.assertGreater(cn.deal_rank(robot), cn.deal_rank(tape))


class SinSilencios(unittest.TestCase):
    def test_tras_un_rato_sin_publicar_admite_rebajas_algo_menores(self):
        today = NOW.astimezone(cn.MADRID).date()
        points = [[(today - timedelta(days=100)).isoformat(), 800.0], [today.isoformat(), 660.0]]
        detail = dict(scanner.parse_detail(LEFANT), price=660.0,
                      series=[{"label": "Amazon ES", "flag": "/static/assets/flags/amazon.es.png", "points": points}])
        item = dict(item_for("R0ZG4Bv"), price=660.0)  # robot aspirador a -17,5 % de su mínimo de 30 días (800 €)
        why, _ = cn.evaluate(item, detail, REAL, NOW)
        self.assertIn("solo -18%", why)
        why, deal = cn.evaluate(item, detail, REAL, NOW, relaxed=True)
        self.assertEqual(why, "")
        self.assertEqual(round(deal["discount"]), 18)
        detail["price"] = item["price"] = 720.0  # -10 %: ni en modo sin silencios
        detail["series"][0]["points"][-1][1] = 720.0
        why, _ = cn.evaluate(item, detail, REAL, NOW, relaxed=True)
        self.assertIn("solo -10%", why)

    def test_en_minimo_historico_basta_un_10(self):
        today = NOW.astimezone(cn.MADRID).date()
        points = [[(today - timedelta(days=100)).isoformat(), 800.0], [today.isoformat(), 710.0]]
        detail = dict(scanner.parse_detail(LEFANT), price=710.0, low=710.0,
                      series=[{"label": "Amazon ES", "flag": "/static/assets/flags/amazon.es.png", "points": points}])
        item = dict(item_for("R0ZG4Bv"), price=710.0)  # robot aspirador a -11 % y en su mínimo de siempre
        why, deal = cn.evaluate(item, detail, REAL, NOW)
        self.assertEqual(why, "")
        self.assertTrue(deal["historical_low"])
        detail["low"] = 500.0  # mismo precio, pero ya estuvo más barato: no sale
        why, _ = cn.evaluate(item, detail, REAL, NOW)
        self.assertIn("solo -11%", why)

    def test_el_modo_se_activa_tras_40_minutos(self):
        out = []
        state = {"posts": [{"t": int(NOW.timestamp()) - 45 * 60}], "seen": {}}
        cfg = {"affiliate_tag": "cazadores_errores-21", "amazon_channel": {**{k: v for k, v in REAL.items() if k != "tag"},
               "sources": []}}
        cn.run(SimpleNamespace(dry_run=True, test_private=False, ignore_limits=True), cfg, state, NOW,
               fetch=lambda url: LISTING, resolve_asin=lambda jl: None, log=out.append)
        self.assertTrue(any("Modo sin silencios" in line for line in out))


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


class Turnos(unittest.TestCase):
    def test_con_pasadas_seguidas_no_repite_listados(self):
        rules = dict(RULES, sources=["a", "b"] + [f"cat{i}" for i in range(30)], core_sources=2,
                     max_sources_per_run=12)
        state, seen = {}, set()
        for _ in range(3):  # tres pasadas en el mismo minuto
            picked = cn.sources_for_run(rules, NOW, state)
            self.assertEqual(picked[:2], ["a", "b"])
            seen.update(picked[2:])
        self.assertEqual(len(seen), 30)
        self.assertEqual(state["rotation"], 3)


class JuntarMemoria(unittest.TestCase):
    def test_dos_ejecuciones_solapadas_no_pierden_posts(self):
        silla = {"asin": "B0DY1HFV3W", "chat": "@cazachollos_com", "message_id": 93, "t": 100, "price": 118.71}
        remote = {"posts": [silla, {"asin": "A", "chat": "@cazachollos_com", "message_id": 94, "t": 200,
                                    "ended": 300}],
                  "seen": {"x": {"t": 50, "why": "viejo"}, "y": {"t": 400, "why": "nuevo en GitHub"}},
                  "rotation": 9, "summary_sent": "2026-10-31"}
        local = {"posts": [{"asin": "A", "chat": "@cazachollos_com", "message_id": 94, "t": 200},
                           {"asin": "B", "chat": "@cazachollos_com", "message_id": 95, "t": 250}],
                 "seen": {"x": {"t": 60, "why": "reciente"}, "y": {"t": 10, "why": "antiguo"}},
                 "rotation": 4, "admin_chat": 1}
        merged = cn.merge_states(local, remote)
        self.assertEqual([p["message_id"] for p in merged["posts"]], [93, 94, 95])
        self.assertEqual(merged["posts"][1]["ended"], 300, "si GitHub ya sabía que acabó, no se olvida")
        self.assertEqual(merged["seen"]["x"]["why"], "reciente")
        self.assertEqual(merged["seen"]["y"]["why"], "nuevo en GitHub")
        self.assertEqual(merged["rotation"], 9)
        self.assertEqual(merged["summary_sent"], "2026-10-31")
        self.assertEqual(merged["admin_chat"], 1)
        self.assertTrue(cn.recently_posted(merged, "B0DY1HFV3W", 118.71, datetime.fromtimestamp(1000, timezone.utc), REAL))


class MismoProducto(unittest.TestCase):
    def test_otro_color_del_mismo_robot_no_se_repite(self):
        posted = {"asin": "B0GHMV8ML5", "price": 369.99, "t": int(NOW.timestamp()) - 86400,
                  "title": "roborock Qrevo S Pro Set Robot Aspirador (Versión Mejorada del QV 35A) Succión de 18500 Pa"}
        state = {"posts": [posted]}
        title = "roborock Qrevo S Pro Set Robot Aspirador (Versión Mejorada del QV)"
        self.assertTrue(cn.recently_posted(state, "B0GHN3V6BP", 369.99, NOW, REAL, title))
        self.assertFalse(cn.recently_posted(state, "B0GHN3V6BP", 320.0, NOW, REAL, title), "si baja un 10 % más, sí")

    def test_modelos_distintos_de_la_misma_marca_si_salen(self):
        state = {"posts": [{"asin": "B0G81F3HSR", "price": 329.98, "t": int(NOW.timestamp()) - 3600,
                            "title": "Lefant Robot Aspirador y Friegasuelos con Base 4 en 1 de Autovaciado M3 MAX"}]}
        self.assertFalse(cn.recently_posted(state, "B0G7YP6MXV", 379.98, NOW, REAL,
                                            "Lefant M5 Pro Robot Aspirador y Fregasuelos con Base de Autovaciado"))
        self.assertFalse(cn.same_product("Philips OneBlade Intimate", "Philips OneBlade Pro 360"))


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
        self.assertIn("CERRAMOS EL DÍA", text)
        self.assertIn("1️⃣", text)
        self.assertIn("379,98 €", text)
        self.assertIn("a las 23:30", text)  # hora de la comprobación
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
        cn.run_summary(args, CFG, {"posts": []}, datetime(2026, 10, 31, 22, 31, tzinfo=timezone.utc), log=out.append)
        self.assertIn("no es la hora", out[-1])  # 23:31: aún no
        state = {"posts": [], "summary_sent": "2026-10-31"}
        cn.run_summary(args, CFG, state, datetime(2026, 10, 31, 22, 59, tzinfo=timezone.utc), log=out.append)
        self.assertIn("ya enviado", out[-1])

    def test_si_github_se_retrasa_cierra_el_dia_anterior(self):
        late = datetime(2026, 10, 31, 23, 20, tzinfo=timezone.utc)  # 00:20 del 1 de noviembre en Madrid
        self.assertEqual(cn.closing_day(late, RULES).isoformat(), "2026-10-31")
        out = []
        state = {"posts": [], "summary_sent": "2026-10-31"}
        cn.run_summary(SimpleNamespace(dry_run=True, test_private=False, ignore_limits=False), CFG, state, late,
                       log=out.append)
        self.assertIn("ya enviado", out[-1])

    def test_tras_el_resumen_no_salen_mas_productos(self):
        rules = dict(RULES, close_time="23:50", quiet_hours=[0, 8])
        evening = datetime(2026, 10, 31, 21, 0, tzinfo=timezone.utc)  # 22:00 en Madrid
        self.assertEqual(cn.quota_reason({"posts": []}, evening, rules), "")
        self.assertEqual(cn.quota_reason({"posts": [], "summary_sent": "2026-10-31"}, evening, rules),
                         "día cerrado con el resumen")
        self.assertEqual(cn.quota_reason({"posts": []}, datetime(2026, 10, 31, 22, 52, tzinfo=timezone.utc), rules),
                         "día cerrado con el resumen")
        self.assertEqual(cn.quota_reason({"posts": []}, datetime(2026, 10, 31, 23, 30, tzinfo=timezone.utc), rules),
                         "horario de silencio")
        morning = datetime(2026, 11, 1, 7, 5, tzinfo=timezone.utc)  # 08:05 en Madrid
        self.assertEqual(cn.quota_reason({"posts": [], "summary_sent": "2026-10-31"}, morning, rules), "")


class Manual(unittest.TestCase):
    SPEC = {"asin": "B0HC84XR1P", "title": "Lenovo LOQ Tower 26ADR10 Torre Gaming con Ryzen 7 y RTX 5050",
            "price": 999.0, "reference": 1299.0, "image": "images/manual/B0HC84XR1P.png", "seen_at": "10:05",
            "lines": ["⏰ Oferta flash: termina hoy a las 23:59"]}

    def test_post_manual_con_datos_de_la_ficha(self):
        deal = cn.manual_deal(self.SPEC, RULES)
        url = "https://www.amazon.es/dp/B0HC84XR1P?tag=cazadores_errores-21"
        text = cn.build_caption(deal, url, RULES)
        self.assertIn("999,00 €", text)
        self.assertIn("<s>1.299,00 €</s>", text)
        self.assertIn("-23 %", text)
        self.assertIn("Oferta flash", text)
        self.assertIn("a las 10:05", text)
        self.assertIn("dp/B0HC84XR1P?tag=cazadores_errores-21", text)

    def test_datos_incoherentes_no_se_publican(self):
        with self.assertRaises(ValueError):
            cn.manual_deal(dict(self.SPEC, reference=900), RULES)
        with self.assertRaises(ValueError):
            cn.manual_deal(dict(self.SPEC, asin="XYZ"), RULES)

    def test_enlace_corto(self):
        spec = dict(self.SPEC, asin="", url="https://link.amazon/B0b6EnJWF")
        final = "https://www.amazon.es/dp/B0HC84XR1P/ref=x?tag=cazadores_errores-21"
        self.assertEqual(cn.manual_deal(spec, RULES, resolve=lambda u: final)["asin"], "B0HC84XR1P")
        wrong = dict(self.SPEC, url="https://link.amazon/otro")
        with self.assertRaises(ValueError):
            cn.manual_deal(wrong, RULES, resolve=lambda u: "https://www.amazon.es/dp/B0OTROPROD")

    def test_imagen_del_repositorio(self):
        deal = cn.manual_deal(self.SPEC, RULES)
        card = cn.make_card(deal, RULES)
        self.assertTrue(card.exists())


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
