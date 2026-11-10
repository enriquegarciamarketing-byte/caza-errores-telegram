import time
import unittest
from unittest import mock

import revision_semanal as rs


class RevisionTest(unittest.TestCase):
    def test_resumen_propuestas_y_borradores(self):
        now = time.time()
        prem = {"posts": [{"t": now - 100, "alert_id": 1, "approved": True},
                          {"t": now - 200, "alert_id": 2, "rejected": True},
                          {"t": now - 300, "alert_id": 3, "expired": True},
                          {"t": now - 400, "alert_id": 4, "expired": True}],
                "seen": {"B0AAAAAAA1": {"t": now - 50, "result": "no es ninguna bajada: hace menos de una semana..."},
                         "B0AAAAAAA2": {"t": now - 50, "result": "lo vende ZIIZI Store, no Amazon ni la tienda oficial"}},
                "learning": {"brand": {"faszin": {"ok": 0, "no": 2, "name": "Faszin"}}}}
        free = {"posts": [{"t": now - 60, "price": 50, "reference": 100, "label": "Aspiradoras"}] * 3,
                "seen": {"amz-B0AAAAAAA3": {"t": now - 50, "why": "marca poco conocida (UJJ): ..."}}}
        files = {"scanner.json": prem, "canal_nube.json": free, "ventas.json": {}}
        with mock.patch.object(rs, "load", side_effect=lambda name: files[name]):
            s = rs.gather(now)
        self.assertEqual((s["ok"], s["no"], s["expired"]), (1, 1, 2))
        self.assertEqual(s["kinds"], {"trampa": 1, "vendedor": 1, "marca": 1})
        self.assertIn("Faszin", s["blocked"])
        text = rs.summary_text(s)
        self.assertIn("la trampa de subir el precio", text)
        props = rs.proposals(s, now)
        self.assertTrue(any("informe de pedidos" in p for p in props))
        drafts = rs.x_drafts(s)
        self.assertTrue(2 <= len(drafts) <= 3)
        self.assertTrue(all("amazon.es" not in t and "tag=" not in t for _, t in drafts))  # sin afiliado


if __name__ == "__main__":
    unittest.main()
