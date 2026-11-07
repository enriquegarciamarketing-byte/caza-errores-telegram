#!/usr/bin/env python3
"""Limpieza puntual de posts ya publicados en el canal free."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import canal_nube as cn  # noqa: E402
import limpiar_posts as lp  # noqa: E402

CAP = ("🔥 <b>CHOLLAZO EN AMAZON</b>\n\n<b>Belkin</b>\n\n💶 PRECIO: <b>14,99€</b>\n❌ (Antes: <s>44,99€</s>)\n"
       "🔥 ¡Te ahorras <b>30€</b>! (67 % dto.)\n🏆 <b>Precio más bajo de su historia</b>\n\n"
       "🕒 Precio a las 10:31 · puede cambiar\n\nVisto en @cazachollos_com #Publicidad #Chollazo #MinimoHistorico")
RULES = {"chat_id": "@cazachollos_com", "button_style": "success", "admin_username": ""}


class FakeTG:
    def __init__(self):
        self.calls = []

    def call(self, method, params=None):
        self.calls.append((method, params))
        if method == "forwardMessage":
            return {"message_id": 99, "photo": [{"file_id": "chica", "width": 90, "height": 90},
                                               {"file_id": "grande", "width": 2000, "height": 2000}]}
        return True


class Limpieza(unittest.TestCase):
    def test_sin_historial(self):
        text = cn.sin_historial(CAP)
        self.assertNotIn("historia", text)
        self.assertNotIn("#MinimoHistorico", text)
        self.assertTrue(text.endswith("#Publicidad #Chollazo"))

    def test_terminado_tampoco_lo_recupera(self):
        self.assertNotIn("historia", cn.ended_caption(CAP))

    def post(self, **extra):
        return dict({"chat": "@cazachollos_com", "message_id": 356, "photo_message_id": 355, "caption": CAP,
                     "url": "https://www.amazon.es/dp/B0CWH4ND6V?tag=cazachollos0c-21", "title": "Belkin",
                     "price": 14.99, "reference": 44.99}, **extra)

    def test_pone_la_foto_del_producto_y_borra_la_suelta(self):
        tg, state = FakeTG(), {"posts": [self.post()], "admin_chat_id": 1}
        self.assertEqual(lp.limpiar(tg, state, RULES, {356}, dry=False, log=lambda *_: None), 0)
        methods = [m for m, _ in tg.calls]
        self.assertEqual(methods, ["forwardMessage", "editMessageMedia", "deleteMessage", "deleteMessage"])
        edit = tg.calls[1][1]
        self.assertEqual(edit["media"]["media"], "grande")
        self.assertNotIn("historia", edit["media"]["caption"])
        self.assertIn("Comprar en Amazon", str(edit["reply_markup"]))
        self.assertEqual(tg.calls[2][1], {"chat_id": "@cazachollos_com", "message_id": 355})
        self.assertIsNone(state["posts"][0]["photo_message_id"])

    def test_solo_texto_si_no_hay_foto_suelta_y_sin_boton_si_termino(self):
        tg, state = FakeTG(), {"posts": [self.post(photo_message_id=None, ended=1)]}
        lp.limpiar(tg, state, RULES, {356}, dry=False, log=lambda *_: None)
        self.assertEqual([m for m, _ in tg.calls], ["editMessageCaption"])
        self.assertNotIn("reply_markup", tg.calls[0][1])

    def test_texto_largo_pasa_al_corto(self):
        largo = ("💥 <b>CHOLLO EN AMAZON</b>\n\n<b>PHILIPS Lumea</b>\n\n💰 <b>299,95 €</b>   <s>559,99 €</s>\n"
                 "📉 <b>-46 %</b> frente a su PVP recomendado\n\n🕒 Precio a las 09:31 · puede cambiar\n\n"
                 "🔗 <b><a href=\"u\">Ver en Amazon</a></b>\n\n#Publicidad #Chollo #MinimoHistorico")
        text = lp.formato_corto(cn.sin_historial(largo), {"price": 299.95, "reference": 559.99, "title": "PHILIPS Lumea"}, RULES)
        self.assertIn("❌ (Antes: <s>559,99€</s>)", text)
        self.assertIn("Precio a las 09:31", text)
        self.assertNotIn("frente a su", text)
        self.assertNotIn("Ver en Amazon", text)
        self.assertTrue(text.endswith("Visto en @cazachollos_com #Publicidad #Chollo"))


if __name__ == "__main__":
    unittest.main()
