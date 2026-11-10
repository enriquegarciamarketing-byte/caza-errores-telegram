"""Qué datos de vendedor y oferta da la API (temporal)."""
import json, time
from amazon_api import CreatorsAPI
api = CreatorsAPI.from_env("cazachollos0c-21")
RES = ["offersV2.listings.price", "offersV2.listings.availability", "offersV2.listings.merchantInfo",
       "offersV2.listings.isBuyBoxWinner", "offersV2.listings.dealDetails", "offersV2.listings.condition",
       "itemInfo.title", "itemInfo.byLineInfo", "itemInfo.externalIds", "customerReviews.count", "customerReviews.starRating"]
for kw in ["sony auriculares", "tablet android", "roborock"]:
    try:
        d = api.call("searchItems", {"keywords": kw, "minSavingPercent": 40, "itemCount": 4, "resources": RES})
        for it in (d.get("searchResult") or {}).get("items") or []:
            print(kw, "→", json.dumps({k: it.get(k) for k in ("asin", "offersV2", "customerReviews")}, ensure_ascii=False)[:900])
            print("   ids:", json.dumps(((it.get("itemInfo") or {}).get("externalIds")), ensure_ascii=False)[:200])
    except Exception as e:
        print(kw, "ERROR", str(e)[:500])
    time.sleep(1.2)
