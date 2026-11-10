"""Aprende de lo que vende: importa el informe de pedidos de Amazon Afiliados (CSV o TSV).

Uso: python tools/importar_ventas.py informe.csv
Cuenta los productos pedidos por búsqueda (amazon_search.keywords del config) y por categoría de Amazon,
y lo guarda en state/ventas.json. El bot busca más a menudo lo que vende en la comunidad.
"""
import csv
import io
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import aprendizaje  # noqa: E402

TITLE = ("nombre", "name", "título", "titulo", "producto", "product", "item name")
CATEGORY = ("categoría", "categoria", "category", "product group", "grupo")
QTY = ("cantidad", "quantity", "items", "artículos", "articulos", "unidades", "pedidos")


def column(headers: list[str], names) -> int | None:
    low = [aprendizaje.fold(h) for h in headers]
    for i, h in enumerate(low):
        if any(aprendizaje.fold(n) in h for n in names):
            return i
    return None


def read_rows(raw: str) -> tuple[list[str], list[list[str]]]:
    lines = [l for l in raw.splitlines() if l.strip()]
    # Amazon pone a veces una línea de título antes de la cabecera: se busca la que tiene ASIN.
    start = next((i for i, l in enumerate(lines) if "asin" in l.lower()), 0)
    text = "\n".join(lines[start:])
    dialect = csv.Sniffer().sniff(text[:2000], delimiters=",;\t")
    rows = list(csv.reader(io.StringIO(text), dialect))
    return rows[0], rows[1:]


def main() -> int:
    raw = Path(sys.argv[1]).read_text(encoding="utf-8-sig", errors="replace")
    headers, rows = read_rows(raw)
    ti, ci, qi = column(headers, TITLE), column(headers, CATEGORY), column(headers, QTY)
    if ti is None:
        print(f"No encuentro la columna del nombre del producto en: {headers}")
        return 2
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    conf = cfg.get("amazon_search") or {}
    keywords = list(conf.get("keywords") or [])
    for season in conf.get("seasons") or []:
        keywords += season.get("keywords") or []
    by_kw, by_cat, total = {}, {}, 0
    for row in rows:
        if len(row) <= ti:
            continue
        try:
            qty = int(float(str(row[qi]).replace(",", "."))) if qi is not None and row[qi].strip() else 1
        except ValueError:
            qty = 1
        title = aprendizaje.fold(row[ti])
        total += qty
        for kw in keywords:
            words = [w for w in aprendizaje.fold(kw).split() if len(w) > 2]
            if words and all(w in title for w in words):
                by_kw[aprendizaje.fold(kw)] = by_kw.get(aprendizaje.fold(kw), 0) + qty
        if ci is not None and len(row) > ci and row[ci].strip():
            by_cat[row[ci].strip()] = by_cat.get(row[ci].strip(), 0) + qty
    out = {"updated": date.today().isoformat(), "items": total,
           "keywords": dict(sorted(by_kw.items(), key=lambda kv: -kv[1])),
           "categories": dict(sorted(by_cat.items(), key=lambda kv: -kv[1]))}
    (ROOT / "state" / "ventas.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{total} productos pedidos. Búsquedas que más venden: {list(out['keywords'].items())[:8]}")
    print(f"Categorías: {list(out['categories'].items())[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
