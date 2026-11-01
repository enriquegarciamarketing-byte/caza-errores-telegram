"""Comprueba cada listado del canal normal: si existe, cuántos productos tiene y cuántos con precio de la última hora."""
import json, time, urllib.error
import canal_nube as cn, scanner
rules = cn.rules_from(json.load(open("config.json")))
now = time.time()
for url in rules["sources"]:
    try:
        items = scanner.parse_listing(cn.http_get(url))
        fresh = [i for i in items if i.get("ts") and now - i["ts"] <= 3600]
        top = [i for i in fresh if cn.interest(f"{i.get('brand') or ''} {i.get('title') or ''}", rules)["score"] >= 90]
        print(f"OK {len(items):3d} {len(fresh):3d} {len(top):3d} {url}")
    except urllib.error.HTTPError as exc:
        print(f"HTTP{exc.code} {url}")
    except Exception as exc:
        print(f"ERR {type(exc).__name__}: {exc} {url}")
    time.sleep(0.6)
