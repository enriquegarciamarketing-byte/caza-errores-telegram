"""Diagnóstico puntual: guarda fichas actuales de jimmyleaks y prueba la Creators API con su ASIN."""
import json, re, sys
from pathlib import Path
import canal_nube, scanner
from amazon_api import ApiError, CreatorsAPI

out = Path("state/diagnostico"); out.mkdir(parents=True, exist_ok=True)
items = scanner.parse_listing(canal_nube.http_get("https://jimmyleaks.com/es/minimos-de-hoy/"))
print(f"Listado: {len(items)} productos")
api = CreatorsAPI.from_env("cazachollos0c-21")
print("API:", "secretos presentes" if api else "SIN secretos")
for item in items[:3]:
    page = canal_nube.http_get(f"https://jimmyleaks.com/es/dp/{item['id']}/")
    (out / f"jl_{item['id']}.html").write_text(page)
    print(f"\n{item['id']} {item['title'][:60]} | listado {item['price']} € | {len(page)} bytes")
    print("  parse_detail:", {k: v for k, v in scanner.parse_detail(page).items() if k != 'series'})
    print("  ld+json:", len(re.findall(r'application/ld\+json', page)), "| priceSeries:", "priceSeries" in page)
    asin = canal_nube.asin_from_jl(item["id"])
    print("  ASIN:", asin)
    if api and asin:
        try:
            print("  API getItem:", json.dumps(api.get_item(asin), ensure_ascii=False))
        except ApiError as exc:
            print("  API error:", exc)
