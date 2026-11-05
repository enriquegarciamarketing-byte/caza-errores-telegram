import unittest
from datetime import datetime, timezone

import marca_personal as mp

NOW = datetime(2026, 11, 5, 8, 40, tzinfo=timezone.utc)
YDAY = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc).timestamp()


def posts(n, ended_after=None):
    out = []
    for i in range(n):
        p = {"t": YDAY + i * 600, "title": f"PRODUCTO {i}, algo", "price": 50.0, "reference": 100.0 + i}
        if ended_after is not None:
            p["ended"] = p["t"] + ended_after
        out.append(p)
    return out


class Marca(unittest.TestCase):
    def test_bot_post_needs_data(self):
        self.assertEqual(mp.bot_post(posts(3), NOW, 0), "")
        self.assertIn("t.me/cazachollos_com", mp.bot_post(posts(10), NOW, 1))

    def test_fast_post_only_when_things_really_flew(self):
        slow = [mp.bot_post(posts(10, ended_after=7200), NOW, s) for s in range(6)]
        self.assertFalse(any("minutos y fuera" in t for t in slow))
        fast = [mp.bot_post(posts(10, ended_after=900), NOW, s) for s in range(6)]
        self.assertTrue(any("15 minutos y fuera" in t for t in fast))

    def test_no_repeats_until_bank_used(self):
        state = {}
        seen = [mp.next_post("finanzas", state) for _ in range(len(mp.FINANZAS))]
        self.assertEqual(len(set(seen)), len(mp.FINANZAS))
        self.assertIn(mp.next_post("finanzas", state), seen)

    def test_banks_are_clean(self):
        for bank in (mp.AHORRO, mp.FINANZAS, mp.DIA):
            for text in bank:
                self.assertNotIn("amazon", text.lower())
                self.assertNotIn("—", text)
                self.assertTrue(text[0].isupper())

    def test_message_marks_brackets(self):
        msg = mp.draft_message("Tu día a día", "Hoy toca [gym].")
        self.assertIn("corchetes", msg)
        self.assertNotIn("corchetes", mp.draft_message("Ahorro", "Sin huecos."))


if __name__ == "__main__":
    unittest.main()
