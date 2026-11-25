"""25/11/2026: los Funko Pop no salen en ningún canal."""
import unittest

import vetados


class VetadosTest(unittest.TestCase):
    def test_funko_de_cualquier_tipo(self):
        for t in ("Funko POP! Animation: Solo Leveling", "POP Funko Games: Baldur's Gate 3",
                  "Funko Pop! TV: Futurama", "FUNKO Bitty Pop", "Figura funkopop Naruto", "Pack 3 Funkos Marvel",
                  "Pop! Animation: One Piece - Luffy"):
            self.assertIsNotNone(vetados.vetado(t), t)

    def test_no_veta_lo_demas(self):
        for t in ("Altavoz Bose SoundLink", "Máquina de palomitas Pop Corn", "Vinilo de música pop",
                  "Cecotec Conga 8290", "Popeye Blu-ray"):
            self.assertIsNone(vetados.vetado(t), t)


if __name__ == "__main__":
    unittest.main()
