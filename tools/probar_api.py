"""Qué tiendas y comparadores dejan buscar por EAN al bot (temporal)."""
import re, urllib.request
EAN = "4548736142374"  # Sony WH-CH520
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
      "Accept-Language": "es-ES,es;q=0.9", "Accept": "text/html,application/xhtml+xml"}
URLS = {
    "idealo": f"https://www.idealo.es/resultados.html?q={EAN}",
    "pccomponentes": f"https://www.pccomponentes.com/buscar/?query={EAN}",
    "mediamarkt": f"https://www.mediamarkt.es/es/search.html?query={EAN}",
    "elcorteingles": f"https://www.elcorteingles.es/search-nwx/1/?s={EAN}",
    "carrefour": f"https://www.carrefour.es/?q={EAN}",
    "fnac": f"https://www.fnac.es/SearchResult/ResultList.aspx?Search={EAN}",
    "worten": f"https://www.worten.es/search?query={EAN}",
    "kelkoo": f"https://www.kelkoo.es/buscar?query={EAN}",
    "pricerunner": f"https://www.pricerunner.com/results?q={EAN}",
    "google_shopping": f"https://www.google.com/search?tbm=shop&q={EAN}",
}
for name, url in URLS.items():
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
            html = r.read().decode("utf-8", "replace")
        prices = re.findall(r"(\d{1,4}[.,]\d{2})\s*(?:€|&euro;|EUR)", html)
        print(f"{name}: HTTP {r.status} · {len(html)//1024} KB · 'WH-CH520' {'sí' if 'CH520' in html.upper() else 'no'} · precios {prices[:8]}")
    except Exception as e:
        print(f"{name}: ERROR {str(e)[:120]}")
