"""Diagnóstico del premium desde GitHub (rama de pruebas, no publica nada)."""
import re
import time
import urllib.request
import urllib.error

import canal_nube
import scanner

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"


def get(url, ua=scanner.USER_AGENT):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": "es-ES,es;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.geturl()
    except urllib.error.HTTPError as e:
        return e.code, "", url
    except Exception as e:
        return str(e)[:60], "", url


now = time.time()
print("== Categorías de Jimmyleaks")
st, home, _ = get("https://jimmyleaks.com/es/")
cats = sorted(set(re.findall(r'href="/es/c/([a-z0-9-]+)/"', home)))
print(st, cats)
brands = sorted(set(re.findall(r'href="/es/b/([a-z0-9-]+)/"', home)))[:40]
print("marcas en portada:", brands)
links = sorted(set(re.findall(r'href="(/es/[a-z0-9-]+/)"', home)))
print("otras rutas:", links[:60])

print("\n== Listados: edad y bajadas")
for url in ["https://jimmyleaks.com/es/minimos-de-hoy/", "https://jimmyleaks.com/es/?order=-modified",
            "https://jimmyleaks.com/es/?order=-discount", "https://jimmyleaks.com/es/c/hogar-y-cocina/?order=-modified",
            "https://jimmyleaks.com/es/?order=-discount&page=2", "https://jimmyleaks.com/es/minimos-de-hoy/?page=2",
            "https://jimmyleaks.com/es/errores/", "https://jimmyleaks.com/es/?order=-drop"]:
    st, page, final = get(url)
    items = scanner.parse_listing(page) if page else []
    ages = sorted(int((now - i["ts"]) / 60) for i in items if i["ts"])
    big = [i for i in items if scanner.listing_drop(i) >= 0.5]
    verdicts = [i["verdict"] for i in items][:6]
    print(f"{url} -> {st} {final if final != url else ''} items={len(items)} edades(min)={ages[:5]}..{ages[-3:] if ages else ''} "
          f"<60min={sum(a < 60 for a in ages)} drop>=50%={len(big)} veredictos={verdicts}")
    for i in big[:4]:
        print(f"    {i['price']} (antes {i['was']}) · {i['verdict']} · {i['title'][:60]} · hace {int((now - i['ts'])/60)} min")
    time.sleep(1)

print("\n== Búsqueda por ASIN en Jimmyleaks")
st, page, _ = get("https://jimmyleaks.com/es/minimos-de-hoy/")
first = scanner.parse_listing(page)[:2]
for item in first:
    asin = canal_nube.asin_from_jl(item["id"])
    print("jl", item["id"], "→ asin", asin, item["title"][:50])
    if not asin:
        continue
    for url in [f"https://jimmyleaks.com/es/?q={asin}", f"https://jimmyleaks.com/es/buscar/?q={asin}",
                f"https://jimmyleaks.com/es/search/?q={asin}", f"https://jimmyleaks.com/es/dp/{asin}/",
                f"https://jimmyleaks.com/es/a/{asin}/", f"https://jimmyleaks.com/es/asin/{asin}/"]:
        st, body, final = get(url)
        hit = item["id"] in body
        print(f"   {url} -> {st} final={final} contiene_ficha={hit} len={len(body)}")
        time.sleep(0.6)

print("\n== Chollometro: feeds de errores")
st, page, _ = get("https://www.chollometro.com/grupo/errores-de-precio", UA)
print("grupo errores:", st, len(page), sorted(set(re.findall(r'href="(https://www\.chollometro\.com/rss/[^"]+)"', page)))[:10])
for url in ["https://www.chollometro.com/rss/grupo/errores-de-precio", "https://www.chollometro.com/rss/grupo/errores",
            "https://www.chollometro.com/rss/grupo/error-de-precio", "https://www.chollometro.com/rss/nuevos",
            "https://www.chollometro.com/rss/todo"]:
    st, body, final = get(url, UA)
    titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>", body)[:3]
    print(f"{url} -> {st} items={body.count('<item>')} {titles}")
