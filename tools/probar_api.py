"""Prueba de búsqueda por descuento en la API de creadores de Amazon (sin imprimir secretos)."""
import json
import time

from amazon_api import ApiError, CreatorsAPI

api = CreatorsAPI.from_env("cazachollos0c-21")
RES = ["offersV2.listings.price", "offersV2.listings.availability", "itemInfo.title", "browseNodeInfo.browseNodes"]


def show(label, body):
    try:
        data = api.call("searchItems", body)
    except ApiError as exc:
        print(label, "ERROR:", str(exc)[:400])
        return
    items = (data.get("searchResult") or {}).get("items") or []
    print(f"{label}: {len(items)} productos · total {(data.get('searchResult') or {}).get('totalResultCount')}")
    for it in items[:12]:
        lst = ((it.get("offersV2") or {}).get("listings") or [{}])[0]
        p = lst.get("price") or {}
        print("   ", it["asin"], (p.get("money") or {}).get("amount"), "←", ((p.get("savingBasis") or {}).get("money") or {}).get("amount"),
              (p.get("savingBasis") or {}).get("savingBasisType"), f"-{(p.get('savings') or {}).get('percentage')}%",
              ((it.get("itemInfo") or {}).get("title") or {}).get("displayValue", "")[:50])


show("A minSaving70 Electronics", {"searchIndex": "Electronics", "keywords": "-", "minSavingPercent": 70, "itemCount": 10, "resources": RES})
time.sleep(1.2)
show("B minSaving70 HomeAndKitchen sin keywords", {"searchIndex": "HomeAndKitchen", "browseNodeId": "599391031", "minSavingPercent": 70, "itemCount": 10, "resources": RES})
time.sleep(1.2)
show("C minSaving70 All 'oferta'", {"searchIndex": "All", "keywords": "oferta", "minSavingPercent": 70, "itemCount": 10, "resources": RES})
time.sleep(1.2)
show("D itemCount 50", {"searchIndex": "All", "keywords": "robot aspirador", "minSavingPercent": 60, "itemCount": 50, "resources": RES})
time.sleep(1.2)
show("E sortBy NewestArrivals", {"searchIndex": "Electronics", "keywords": "auriculares", "minSavingPercent": 60, "sortBy": "NewestArrivals", "itemCount": 10, "resources": RES})
