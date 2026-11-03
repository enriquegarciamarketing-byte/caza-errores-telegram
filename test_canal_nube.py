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

    def test_las_categorias_estrella_salen_desde_el_25(self):
        self.assertEqual(cn.interest("Cecotec Robot Aspirador Conga", REAL)["min_discount"], 25)
        self.assertEqual(cn.interest("Samsung televisor smart tv 55", REAL)["min_discount"], 25)
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
        cafe = cn.interest("Nescafé Classic café soluble 20 bolsitas", REAL)
        self.assertEqual(cafe["label"], "Súper y bebidas")
        self.assertNotEqual(cafe["label"], "Cafeteras")

    def test_compra_del_dia_a_dia_entra_en_las_top(self):
        casos = {
            "Aceite de Oliva Virgen Extra Hojiblanca 3 Litros": "Súper y bebidas",
            "Mahou Cinco Estrellas Cerveza Dorada Lager, Pack de 24 latas x 33 cl": "Súper y bebidas",
            "Monster Energy Ultra Zero Bebida Energética, pack 24 latas": "Súper y bebidas",
            "Dodot Sensitive Pañales Talla 5, 11-16 kg, 42 unidades": "Bebé",
            "Royal Canin Mini Adult Pienso para perros 8 kg": "Mascotas",
            "VASAGLE Mesa de Centro Elevable con almacenaje": "Muebles y descanso",
        }
        for title, label in casos.items():
            taste = cn.interest(title, REAL)
            self.assertEqual(taste["label"], label, title)
            self.assertEqual(taste["min_discount"], 25, title)

    def test_el_detergente_no_es_un_electrodomestico(self):
        for title in ["Ariel Todo en Uno Pods Detergente Lavadora en Cápsulas, 90 lavados",
                      "Finish Ultimate Plus Pastillas Lavavajillas, 100 unidades"]:
            self.assertEqual(cn.interest(title, REAL)["label"], "Droguería y limpieza", title)
        self.assertEqual(cn.interest("Bosch Serie 4 Lavavajillas 60 cm", REAL)["label"], "Electrodomésticos")

    def test_monster_hunter_no_es_una_bebida(self):
        self.assertNotEqual(cn.interest("Monster Hunter Wilds PS5", REAL)["label"], "Súper y bebidas")
        self.assertTrue(cn.interest("Filtro de aceite para coche Bosch", REAL)["blocked"])

    def test_orden_prioriza_interes_y_descuento(self):
        robot = {"interest": 100, "discount": 45, "price": 330, "reference": 600}
        tape = {"interest": 0, "discount": 52, "price": 9.4, "reference": 19.59}
        self.assertGreater(cn.deal_rank(robot), cn.deal_rank(tape))


class SinSilencios(unittest.TestCase):
    def test_tras_un_rato_sin_publicar_admite_rebajas_algo_menores(self):
        today = NOW.astimezone(cn.MADRID).date()
        points = [[(today - timedelta(days=100)).isoformat(), 800.0], [today.isoformat(), 640.0]]
        detail = dict(scanner.parse_detail(LEFANT), price=640.0,
                      series=[{"label": "Amazon ES", "flag": "/static/assets/flags/amazon.es.png", "points": points}])
        item = dict(item_for("R0ZG4Bv"), price=640.0, was=None)  # robot aspirador a -20 % de su mínimo de 30 días (800 €)
        why, _ = cn.evaluate(item, detail, REAL, NOW)
        self.assertIn("solo -20%", why)
        why, deal = cn.evaluate(item, detail, REAL, NOW, relaxed=True)
        self.assertEqual(why, "")
        self.assertEqual(round(deal["discount"]), 20)
        detail["price"] = item["price"] = 720.0  # -10 %: ni en modo sin silencios
        detail["series"][0]["points"][-1][1] = 720.0
        why, _ = cn.evaluate(item, detail, REAL, NOW, relaxed=True)
        self.assertIn("solo -10%", why)

    def test_en_minimo_historico_basta_un_15(self):
        today = NOW.astimezone(cn.MADRID).date()
        points = [[(today - timedelta(days=100)).isoformat(), 800.0], [today.isoformat(), 670.0]]
        detail = dict(scanner.parse_detail(LEFANT), price=670.0, low=670.0,
                      series=[{"label": "Amazon ES", "flag": "/static/assets/flags/amazon.es.png", "points": points}])
        item = dict(item_for("R0ZG4Bv"), price=670.0, was=None)  # robot aspirador a -16 % y en su mínimo de siempre
        why, deal = cn.evaluate(item, detail, REAL, NOW)
        self.assertEqual(why, "")
        self.assertTrue(deal["historical_low"])
        detail["low"] = 500.0  # mismo precio, pero ya estuvo más barato: no sale
        why, _ = cn.evaluate(item, detail, REAL, NOW)
        self.assertIn("solo -16%", why)

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


class ManualDesdeJimmyleaks(unittest.TestCase):
    def detail(self, points, price=249.0, low=249.0, modified="2026-10-31T15:30:00"):
        return {"name": "MSI MAG 346CQDF E20 Monitor Gaming Curvo 34", "price": price, "in_stock": True,
                "image": "https://img/x.jpg", "low": low, "avg90": 372.4, "modified": modified,
                "rating": None, "reviews": None,
                "series": [{"label": "Amazon ES", "flag": "/static/assets/flags/amazon.es.png", "points": points}]}

    def run_spec(self, detail, spec=None):
        import scanner as sc
        old = sc.parse_detail
        sc.parse_detail = lambda page: detail
        try:
            return cn.spec_from_jl(dict({"jl_id": "ROo6W62"}, **(spec or {})), REAL, NOW,
                                   fetch=lambda url: "", resolve_asin=lambda jl: "B0TESTASIN", log=lambda *_: None)
        finally:
            sc.parse_detail = old

    def test_sin_rebaja_frente_al_minimo_usa_la_media_90_bien_rotulada(self):
        today = NOW.astimezone(cn.MADRID).date()
        points = [[(today - timedelta(days=d)).isoformat(), 260.0 if d == 20 else 393.55] for d in range(90, 3, -1)]
        points += [[today.isoformat(), 249.0]]  # hace 20 días estuvo a 260 €: frente al mínimo solo -4 %
        spec = self.run_spec(self.detail(sorted(points)))
        self.assertEqual(spec["ref_kind"], "media90")
        deal = cn.manual_deal(spec, REAL)
        caption = cn.build_caption(deal, "https://www.amazon.es/dp/B0TESTASIN?tag=x", REAL)
        self.assertIn("frente a su precio medio de los últimos 90 días", caption)
        self.assertIn("Su precio más bajo de los 30 días anteriores fue 260,00", caption)
        self.assertEqual(spec["seen_at"], "16:30")

    def test_con_rebaja_real_frente_al_minimo_usa_el_minimo(self):
        today = NOW.astimezone(cn.MADRID).date()
        points = [[(today - timedelta(days=d)).isoformat(), 393.55] for d in range(90, 0, -1)] + [[today.isoformat(), 249.0]]
        spec = self.run_spec(self.detail(points))
        self.assertNotIn("ref_kind", spec)
        self.assertEqual(spec["reference"], 393.55)

    def test_precio_cambiado_o_viejo_no_se_publica(self):
        today = NOW.astimezone(cn.MADRID).date()
        points = [[(today - timedelta(days=40)).isoformat(), 393.55], [today.isoformat(), 249.0]]
        with self.assertRaises(ValueError):
            self.run_spec(self.detail(points), {"price": 239.0})
        with self.assertRaises(ValueError):
            self.run_spec(self.detail(points, modified="2026-10-31T11:00:00"))


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

    def test_segundos_hasta_las_8(self):
        rules = dict(RULES, quiet_hours=[0, 8])
        # 07:32 en Madrid (UTC+1 en noviembre): faltan 28 minutos.
        self.assertEqual(cn.seconds_until_quiet_end(datetime(2026, 11, 2, 6, 32, tzinfo=timezone.utc), rules), 28 * 60)
        # 08:05: ya no hay silencio.
        self.assertEqual(cn.seconds_until_quiet_end(datetime(2026, 11, 2, 7, 5, tzinfo=timezone.utc), rules), 0)
        # 03:00: faltan 5 horas, fuera de la ventana de espera.
        self.assertGreater(cn.seconds_until_quiet_end(datetime(2026, 11, 2, 2, 0, tzinfo=timezone.utc), rules),
                           cn.DEFAULTS["wake_before_minutes"] * 60)


if __name__ == "__main__":
    unittest.main()


def robot_with(points: list, price: float, low: float | None = None):
    detail = dict(scanner.parse_detail(LEFANT), price=price,
                  series=[{"label": "Amazon ES", "flag": "/static/assets/flags/amazon.es.png", "points": points}])
    if low is not None:
        detail["low"] = low
    return dict(item_for("R0ZG4Bv"), price=price, was=None), detail


class MejorDescuentoReal(unittest.TestCase):
    """Noviembre 2026: más cadencia y descuentos gordos, siempre frente a precios que se han pagado de verdad."""

    def setUp(self):
        self.today = NOW.astimezone(cn.MADRID).date()

    def test_usa_la_media_de_90_dias_si_es_mayor_y_estable(self):
        # 90 días a 100 €, la última semana a 90 € y hoy a 45 €: -50 % frente al mínimo de 30, -55 % frente a la media.
        points = [[(self.today - timedelta(days=100)).isoformat(), 100.0],
                  [(self.today - timedelta(days=7)).isoformat(), 90.0], [self.today.isoformat(), 45.0]]
        item, detail = robot_with(points, 45.0)
        why, deal = cn.evaluate(item, detail, REAL, NOW)
        self.assertEqual(why, "")
        self.assertEqual(deal["ref_kind"], "media90")
        self.assertEqual(deal["reference"], 100.0)
        self.assertEqual(round(deal["discount"]), 55)
        self.assertEqual(round(deal["drop_30"]), 50)
        self.assertIn("precio medio de los últimos 90 días", cn.build_caption(dict(deal, asin="B0G7YP6MXV"), "u", REAL))

    def test_lefant_sigue_con_el_minimo_de_30_porque_estuvo_mucho_mas_barato(self):
        why, deal = cn.evaluate(dict(item_for("R0ZG4Bv"), was=None), scanner.parse_detail(LEFANT), REAL, NOW)
        self.assertEqual(why, "")
        self.assertEqual(deal["ref_kind"], "")
        self.assertEqual(deal["reference"], 799.99)

    def test_sin_bajada_real_ahora_no_vale_la_media(self):
        # Volvió a su precio normal tras una subida: -5 % frente al mínimo de 30, aunque la media sea más alta.
        points = [[(self.today - timedelta(days=100)).isoformat(), 100.0],
                  [(self.today - timedelta(days=20)).isoformat(), 90.0], [self.today.isoformat(), 85.5]]
        item, detail = robot_with(points, 85.5)
        why, _ = cn.evaluate(item, detail, REAL, NOW)
        self.assertIn("frente a su mínimo de los 30 días anteriores", why)

    def test_error_de_precio_solo_con_bajada_real_de_70(self):
        deal = {"discount": 72, "ref_kind": "media90", "drop_30": 55}
        self.assertEqual(cn.badge_for(deal["discount"], REAL, cn.real_drop(deal)), "CHOLLAZO")
        deal["drop_30"] = 71
        self.assertEqual(cn.badge_for(deal["discount"], REAL, cn.real_drop(deal)), "ERROR DE PRECIO")
        self.assertEqual(cn.badge_for(75, REAL, cn.real_drop({"discount": 75})), "ERROR DE PRECIO")

    def test_cualquier_categoria_desde_el_40(self):
        self.assertEqual(REAL["interest"]["any_category_min_discount"], 40)
        self.assertEqual(REAL["interest"]["any_category_min_price_eur"], 8)

    def test_deporte_tiene_categoria_propia(self):
        for title in ["Wilson Balón Baloncesto MVP Talla 7", "Bullpadel Pala de pádel Vertex",
                      "Garmin Forerunner 165 reloj GPS running"]:
            self.assertGreater(cn.interest(title, REAL)["score"], 0, title)

    def test_se_abren_antes_las_grandes_bajadas(self):
        big = {"title": "Cronómetro deportivo digital", "price": 5.0, "was": 13.0, "ts": 1}
        small = {"title": "Roborock Robot Aspirador", "price": 280.0, "was": 300.0, "ts": 2}
        self.assertGreater(cn.listing_priority(big, REAL), cn.listing_priority(small, REAL))
        self.assertLess(cn.listing_priority({"title": "Funda para iPhone", "price": 1, "was": 9}, REAL)[0], 0)

    def test_se_publica_antes_el_descuento_mas_gordo(self):
        aspiradora = {"interest": 100, "discount": 32, "price": 340, "reference": 500}
        zapatillas = {"interest": 0, "discount": 65, "price": 35, "reference": 100}
        self.assertGreater(cn.deal_rank(zapatillas), cn.deal_rank(aspiradora))

    def test_todas_las_categorias_y_sin_listas_por_marca(self):
        sources = REAL["sources"]
        self.assertFalse([u for u in sources if "/marca/" in u])
        self.assertIn("https://jimmyleaks.com/es/c/deportes-y-aire-libre/?order=-modified", sources)
        core = sources[: REAL["core_sources"]]
        self.assertIn("https://jimmyleaks.com/es/?order=-modified&page=6", core)


class PrecioRecomendado(unittest.TestCase):
    """3/11/2026: Enrique elige el PVP recomendado como titular para probar si se factura más."""

    def setUp(self):
        self.today = NOW.astimezone(cn.MADRID).date()

    def test_lefant_titular_frente_al_pvp_y_linea_real(self):
        why, deal = cn.evaluate(item_for("R0ZG4Bv"), scanner.parse_detail(LEFANT), REAL, NOW)
        self.assertEqual(why, "")
        self.assertEqual(deal["ref_kind"], "pvp")
        self.assertEqual(deal["reference"], 1799.99)
        self.assertEqual(round(deal["discount"]), 79)
        text = cn.build_caption(dict(deal, asin="B0G7YP6MXV"), "u", REAL)
        self.assertIn("-79 %</b> frente a su PVP recomendado", text)
        self.assertIn("-53 %</b> frente a su precio más bajo de los 30 días anteriores (799,99 €)", text)
        self.assertIn("<s>1.799,99 €</s>", text)
        self.assertIn("frente al PVP", text)
        self.assertNotIn("ERROR DE PRECIO", text, "el error de precio sale de la bajada real, no del PVP")

    def test_sin_bajada_real_no_sale_aunque_el_pvp_sea_enorme(self):
        points = [[(self.today - timedelta(days=100)).isoformat(), 40.0], [self.today.isoformat(), 39.0]]
        _, detail = robot_with(points, 39.0)
        item = dict(item_for("R0ZG4Bv"), price=39.0, was=99.0)
        why, _ = cn.evaluate(item, detail, REAL, NOW)
        self.assertIn("de bajada real", why)
        self.assertTrue(why.startswith("solo -"))

    def test_pvp_inflado_no_cuenta(self):
        # PVP de 400 € para algo que se paga a 100: más de 2,5 veces la media, se usa el descuento real.
        points = [[(self.today - timedelta(days=100)).isoformat(), 100.0], [self.today.isoformat(), 80.0]]
        _, detail = robot_with(points, 80.0)
        item = dict(item_for("R0ZG4Bv"), price=80.0, was=400.0)
        why, deal = cn.evaluate(item, detail, REAL, NOW)
        self.assertEqual(why, "")  # sale por su mínimo histórico, con el descuento real
        self.assertEqual(deal["ref_kind"], "")
        self.assertEqual(deal["reference"], 100.0)

    def test_umbral_de_pvp_por_categoria(self):
        points = [[(self.today - timedelta(days=100)).isoformat(), 100.0], [self.today.isoformat(), 85.0]]
        _, detail = robot_with(points, 85.0)
        item = dict(item_for("R0ZG4Bv"), price=85.0, was=135.0)  # aspirador: -37 % de PVP, -15 % real
        why, _ = cn.evaluate(item, detail, REAL, NOW)
        self.assertIn("frente a su PVP recomendado", why)
        why, deal = cn.evaluate(item, detail, REAL, NOW, relaxed=True)  # sin silencios: top desde -30 %
        self.assertEqual(why, "")
        self.assertEqual(deal["ref_kind"], "pvp")

    def test_tarjeta_dice_pvp_recomendado(self):
        import inspect
        self.assertIn("PVP RECOMENDADO", inspect.getsource(cn.make_card))


class Pendientes(unittest.TestCase):
    """Lo aprobado que no cabe en una pasada no se pierde: el 3/11 se aprobaron 9 y solo salieron 3."""

    def test_lo_que_no_cabe_entra_en_la_siguiente_pasada(self):
        item = dict(item_for("R0ZG4Bv"))
        state = {"seen": {}, "backlog": [item]}
        fetched = []

        def fetch(url):
            fetched.append(url)
            return LEFANT if "/dp/" in url else "<html></html>"
        approved = cn.find_deals(dict(REAL, sources=[]), state, NOW, fetch, lambda jl: "B0G7YP6MXV", lambda *a: None)
        self.assertEqual([i["id"] for i, _ in approved], ["R0ZG4Bv"])

    def test_pendiente_caducado_no_vuelve(self):
        item = dict(item_for("R0ZG4Bv"))
        later = datetime.fromtimestamp(item["ts"] + 2 * 3600, timezone.utc)
        state = {"seen": {}, "backlog": [item]}
        approved = cn.find_deals(dict(REAL, sources=[]), state, later, lambda url: "<html></html>",
                                 lambda jl: "B0G7YP6MXV", lambda *a: None)
        self.assertEqual(approved, [])

    def test_run_guarda_lo_que_no_cupo(self):
        item = dict(item_for("R0ZG4Bv"))
        state = {"seen": {}, "posts": [], "backlog": [item]}
        cfg = {"affiliate_tag": "cazadores_errores-21",
               "amazon_channel": {**{k: v for k, v in REAL.items() if k != "tag"}, "sources": [], "max_per_run": 0}}
        cn.run(SimpleNamespace(dry_run=True, test_private=False, ignore_limits=True), cfg, state, NOW,
               fetch=lambda url: LEFANT if "/dp/" in url else "<html></html>",
               resolve_asin=lambda jl: "B0G7YP6MXV", log=lambda *a: None, cascade_loader=lambda log: [])
        self.assertEqual([i["id"] for i in state["backlog"]], ["R0ZG4Bv"])
