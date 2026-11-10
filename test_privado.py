import json
import os
import unittest
from unittest import mock

import canal_nube as cn
import generic
import privado


class Privado(unittest.TestCase):
    STATE = {"posts": [], "admin_chat_id": 111, "private_chats": {"yo": 111}}

    def test_sin_secreto_no_cambia_nada(self):
        with mock.patch.dict(os.environ, {"ADMIN_CHAT_ID": ""}):
            self.assertIsNone(privado.admin_id())
            self.assertEqual(privado.strip(self.STATE), self.STATE)
            self.assertEqual(privado.fill({"a": 1}), {"a": 1})

    def test_con_secreto_no_se_guarda_y_se_usa(self):
        with mock.patch.dict(os.environ, {"ADMIN_CHAT_ID": "222"}):
            self.assertEqual(privado.strip(self.STATE), {"posts": []})
            self.assertEqual(privado.fill({})["admin_chat_id"], 222)
            self.assertEqual(cn.admin_chat_id({}, {"admin_username": "otro"}), 222)
            self.assertEqual(generic.admin_chat_id({}), 222)

    def test_memoria_guardada_sin_chat(self):
        with mock.patch.dict(os.environ, {"ADMIN_CHAT_ID": "222"}), \
                mock.patch.object(cn, "STATE_PATH", cn.OUTPUT / "privado_test.json"):
            cn.save_state(dict(self.STATE))
            saved = json.loads(cn.STATE_PATH.read_text())
        self.assertNotIn("admin_chat_id", saved)
        self.assertNotIn("private_chats", saved)


if __name__ == "__main__":
    unittest.main()
