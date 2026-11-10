"""Pasada real de prueba del buscador de errores en Amazon (no publica nada)."""
import json

import scanner
from amazon_api import CreatorsAPI

cfg = json.load(open("config.json", encoding="utf-8"))
cfg["amazon_search"]["per_pass"] = 12
scanner.API = CreatorsAPI.from_env(cfg["affiliate_tag"])
state = {"seen": {}}
found = scanner.scan_amazon(cfg, state, scanner.now_utc(), state["seen"])
print("\nERRORES ENCONTRADOS:", len(found))
for c in found:
    print(" ", c["asin"], c["price"], "←", c["was"], f"-{c['discount']:.0f}%", c["brand"], "|", c["title"][:70], "|", c["direct_url"])
