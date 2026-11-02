"""Cascada: lo que el premium descarta por no dar para revender puede salir en el canal normal."""

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import canal_nube as cn
import cascada
import scanner
from test_canal_nube import CFG, LEFANT, LISTING, NOW, item_for
from test_premium_errores import ticket
from test_scanner import load_cfg


class MotivosTest(unittest.TestCase):
    def test_bajan_los_descartes_de_reventa(self):
        for reason in ("fuera de las categorías premium de reventa",
                       "ahorro de 12,00 € inferior al mínimo de reventa (30,00 €)",
                       "precio 19,99 € por debajo del mínimo de reventa (25,00 €)",
                       "solo -22% bajo la referencia",
                       "sin margen de reventa (ROI 4 % con 6 anuncios)",
                       "listado: fuera de las categorías premium"):
            self.assertTrue(cascada.reason_ok(reason), reason)

    def test_nunca_baja_lo_dudoso(self):
        for reason in ("precio del listado (20 €) y de la ficha (25 €) no coinciden",
                       "datos de la ficha con más de 3 horas",
                       "tiene tallas y sin Creators API no se puede comprobar cada talla",
                       "descuento superior al 98 %: probable error de datos",
                       "la referencia corregida no supera el precio (media inflada)",
                       "media de 90 días por encima del PVP: datos incoherentes",
                       "en Alemania cuesta 20 €: la media de España está inflada",
                       "sin stock", "sin imagen", "Amazon marca 30 € y no 20 €",
                       "no he podido sacar el producto exacto de Amazon (ASIN)", ""):
            self.assertFalse(cascada.reason_ok(reason), reason)

    def test_solo_amazon_de_jimmyleaks(self):
        col = cascada.Collector()
        base = {"id": "ABC123", "title": "Freidora", "price": 40.0, "ts": int(time.time())}
        self.assertFalse(col.add({**base, "origin": "chollometro"}, "fuera de las categorías premium", time.time()))
        self.assertFalse(col.add({**base, "direct_url": "https://www.aliexpress.com/item/1"},
                                 "fuera de las categorías premium", time.time()))
        self.assertTrue(col.add(base, "fuera de las categorías premium", time.time()))


class PremiumTest(unittest.TestCase):
    def setUp(self):
        scanner.CASCADA = cascada.Collector()
        scanner.CASCADA_LOADED = True
        self.cfg = {**load_cfg(), "cascada": {**load_cfg().get("cascada", {}), "enabled": True}}

    def test_el_filtro_rapido_apunta_los_descartes_con_rebaja(self):
        page = (ticket("FRY1", "Freidora de aire XXL 6L", "Cosori", 59.0, 129.0)
                + ticket("TOAST1", "Tostadora 2 ranuras", "Taurus", 21.0, 23.0, verdict="5% por debajo de la media"))
        cfg = {**self.cfg, "sources": ["x"], "rotating_sources": [], "max_detail_fetches_per_run": 0}
        with mock.patch.object(scanner, "fetch", return_value=page), \
             mock.patch.object(scanner.feeds, "amazon_hot_titles", return_value=[]), \
             mock.patch("builtins.print"):
            scanner.scan(cfg, {"seen": {}}, scanner.now_utc(), with_external=False)
        self.assertIn("FRY1", scanner.CASCADA.entries)        # -54 % en el listado
        self.assertNotIn("TOAST1", scanner.CASCADA.entries)   # -5 %: ni para el canal normal

    def test_lo_publicado_o_esperando_ok_no_baja(self):
        now = scanner.now_utc()
        for jl_id in ("PUB1", "OK1", "FREE1"):
            scanner.CASCADA.add({"id": jl_id, "title": "x", "price": 50.0, "ts": int(now.timestamp())},
                                "fuera de las categorías premium", now.timestamp())
        state = {"posts": [{"id": "PUB1", "price": 50.0, "t": 1},
                           {"id": "OK1", "price": 50.0, "t": 1, "needs_ok": True, "pending": True}]}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"CASCADA_FILE": f"{tmp}/c.json"}), \
             mock.patch("builtins.print"):
            scanner.flush_cascade(self.cfg, state, now, dry=False)
            data = json.loads(Path(f"{tmp}/c.json").read_text())
        self.assertEqual([e["item"]["id"] for e in data["entries"]], ["FREE1"])

    def test_sin_margen_en_wallapop_se_apunta(self):
        cand = {"id": "LEGO1", "title": "LEGO Technic", "price": 40.0, "series": []}
        with mock.patch.object(scanner.resale_market, "lookup", return_value={"ok": False, "reason": "ROI 3 %"}), \
             mock.patch.object(scanner.resale_market, "with_estimate", side_effect=lambda c, r, res: res), \
             mock.patch.object(scanner.premium, "reserva_allowed", return_value=False), \
             mock.patch("builtins.print"):
            self.assertFalse(scanner.attach_wallapop(None, self.cfg, {}, cand, dry=True))
        self.assertTrue(cand["cascade_reason"].startswith("sin margen de reventa"))

    def test_fallo_de_red_en_wallapop_no_se_apunta(self):
        cand = {"id": "LEGO2", "title": "LEGO Technic", "price": 40.0, "series": []}
        with mock.patch.object(scanner.resale_market, "lookup",
                               return_value={"ok": False, "transient": True, "reason": "timeout"}), \
             mock.patch.object(scanner.resale_market, "with_estimate", side_effect=lambda c, r, res: res), \
             mock.patch("builtins.print"):
            scanner.attach_wallapop(None, self.cfg, {}, cand, dry=True)
        self.assertNotIn("cascade_reason", cand)


class CanalNormalTest(unittest.TestCase):
    """El Lefant solo llega por la cascada (el listado del canal normal viene vacío)."""

    def pages(self):
        def fetch(url):
            return LEFANT if "/es/dp/" in url else "<html></html>"
        return fetch

    def entry(self, **over):
        item = {k: v for k, v in item_for("R0ZG4Bv").items() if k in cascada.ITEM_FIELDS}
        base = {"t": int(NOW.timestamp()) - 300, "reason": "sin margen de reventa (ROI 2 %)", "item": item}
        base.update(over)
        return base

    def run_with(self, entries, premium_state=None):
        out = []
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scanner.json"
            path.write_text(json.dumps(premium_state or {"posts": []}))
            with mock.patch.object(cn, "PREMIUM_STATE", path):
                cn.run(SimpleNamespace(dry_run=True, test_private=False, ignore_limits=True), CFG, {"posts": []},
                       NOW, fetch=self.pages(), resolve_asin=lambda jl: "B0G7YP6MXV", log=out.append,
                       cascade_loader=lambda log: entries)
        return "\n".join(out)

    def test_descarte_del_premium_pasa_por_las_reglas_y_sale(self):
        text = self.run_with([self.entry()])
        self.assertIn("descarte del premium", text)
        self.assertIn("[prueba, no se envía]", text)
        self.assertIn("https://www.amazon.es/dp/B0G7YP6MXV?tag=cazadores_errores-21", text)

    def test_si_el_premium_lo_publico_no_sale(self):
        text = self.run_with([self.entry()], {"posts": [{"id": "R0ZG4Bv", "price": 379.98, "t": 1}]})
        self.assertNotIn("[prueba, no se envía]", text)

    def test_descarte_viejo_no_se_mira(self):
        text = self.run_with([self.entry(t=int(NOW.timestamp()) - 3 * 3600)])
        self.assertNotIn("[prueba, no se envía]", text)

    def test_motivo_dudoso_no_se_acepta_aunque_venga_en_la_lista(self):
        text = self.run_with([self.entry(reason="datos de la ficha con más de 3 horas")])
        self.assertNotIn("[prueba, no se envía]", text)

    def test_con_tallas_no_sale(self):
        entry = self.entry()
        entry["item"]["title"] = "Zapatillas running hombre talla 42"
        text = self.run_with([entry])
        self.assertIn("tallas", text)
        self.assertNotIn("[prueba, no se envía]", text)

    def test_apagada_no_entra_en_el_canal_pero_si_en_pruebas(self):
        cfg = {**CFG, "cascada": {"enabled": False}}
        rules = cn.rules_from(cfg)
        loader = lambda log: [self.entry()]
        self.assertEqual(cn.cascade_items(cfg, rules, NOW, loader=loader), [])
        self.assertEqual(len(cn.cascade_items(cfg, rules, NOW, loader=loader, test=True)), 1)

    def test_sin_cascada_todo_sigue_igual(self):
        self.assertEqual(cn.cascade_items(CFG, cn.rules_from(CFG), NOW, loader=lambda log: []), [])


if __name__ == "__main__":
    unittest.main()
