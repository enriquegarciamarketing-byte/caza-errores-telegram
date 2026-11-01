"""Resuelve un enlace corto de Amazon y busca el producto en Jimmyleaks. No publica nada."""
import json, re, sys, urllib.request, urllib.error
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import affiliate, canal_nube as cn, scanner
link = sys.argv[1]
out = {"link": link}
try:
    final = affiliate.resolve_redirects(link)
except Exception as exc:
    final = None
    out["resolve_error"] = repr(exc)
out["final"] = final
out["asin"] = affiliate.extract_asin(final or "")
out["tags"] = affiliate.tag_values(final or "")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
      "Accept-Language": "es-ES,es;q=0.9"}
if out["asin"]:
    try:
        with urllib.request.urlopen(urllib.request.Request(f"https://www.amazon.es/dp/{out['asin']}", headers=UA), timeout=20) as r:
            page = r.read().decode("utf-8", "replace")
        out["amazon_status"] = r.status
        out["amazon_captcha"] = "api-services-support@amazon.com" in page or "validateCaptcha" in page
        t = re.search(r'id="productTitle"[^>]*>\s*(.*?)\s*</span>', page, re.S)
        out["amazon_title"] = scanner.strip_tags(t.group(1)) if t else None
    except Exception as exc:
        out["amazon_error"] = repr(exc)
    found = []
    for url in [f"https://jimmyleaks.com/es/?q={out['asin']}"] + ([f"https://jimmyleaks.com/es/?q={urllib.request.quote(out['amazon_title'][:60])}"] if out.get("amazon_title") else []):
        try:
            items = scanner.parse_listing(cn.http_get(url))
        except Exception as exc:
            out.setdefault("jl_errors", []).append(repr(exc)); continue
        for it in items[:12]:
            asin = cn.asin_from_jl(it["id"])
            found.append({"jl": it["id"], "asin": asin, "title": it["title"][:80], "price": it["price"], "ts": it["ts"]})
            if asin == out["asin"]:
                d = scanner.parse_detail(cn.http_get(f"https://jimmyleaks.com/es/dp/{it['id']}/"))
                hist = cn.history_reference(cn.amazon_series(d["series"]), d["price"], __import__("datetime").date.today()) if d.get("price") else {}
                out["match"] = {"jl": it["id"], "name": d["name"], "price": d["price"], "avg90": d["avg90"], "low": d["low"],
                                "in_stock": d["in_stock"], "rating": d["rating"], "reviews": d["reviews"], "image": d["image"],
                                "modified": d["modified"], "hist": hist, "listing_ts": it["ts"]}
                break
        if out.get("match"):
            break
    out["jl_candidates"] = found[:12]
print(json.dumps(out, ensure_ascii=False, indent=1))
