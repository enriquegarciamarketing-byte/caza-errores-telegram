"""Prueba de acceso a la API de creadores de Amazon (sin imprimir secretos)."""
import json
import os

from amazon_api import ApiError, CreatorsAPI

api = CreatorsAPI.from_env("cazachollos0c-21")
print("credenciales:", "sí" if api else "NO")
if api:
    for name, body in [
        ("getItems", {"itemIds": ["B0BTYCRJSS"], "itemIdType": "ASIN",
                      "resources": ["offersV2.listings.price", "itemInfo.title"]}),
        ("searchItems", {"keywords": "aspirador", "searchIndex": "All", "itemCount": 10, "minSavingPercent": 50,
                         "resources": ["offersV2.listings.price", "itemInfo.title"]}),
    ]:
        try:
            data = api.call(name, body)
            print(name, "OK:", json.dumps(data, ensure_ascii=False)[:1500])
        except ApiError as exc:
            print(name, "ERROR:", str(exc)[:600])
