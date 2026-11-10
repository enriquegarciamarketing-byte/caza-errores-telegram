"""Fichas nuevas de jimmyleaks (10/11/2026): sin historial ni stock. Se publica con el listado, en modo estricto."""
import time
from datetime import datetime, timezone
from pathlib import Path
import canal_nube, scanner

NUEVA = Path("tests_fixtures/jl_detail_nueva_2026_11.html").read_text()
RULES = canal_nube.rules_from({"amazon_channel": {
    "max_price_age_minutes": 60, "min_price_eur": 7, "max_price_eur": 3000,
    "modo_listado": {"enabled": True, "min_discount": 50, "max_discount": 85},
    "interest": {"tiers": [{"label": "Aspiradoras", "keywords": ["aspiradora"], "score": 100, "min_discount": 25},
                           {"label": "Moda", "keywords": ["camiseta"], "score": 60}]}}})
NOW = datetime.now(timezone.utc)


def item(title="Aspiradora sin cable Cecotec", price=99.0, was=249.0):
    return {"id": "X1", "title": title, "price": price, "was": was, "ts": int(time.time()) - 60,
            "image": "https://m.media-amazon.com/images/I/abc._AC_SL400_.jpg"}


def test_ficha_nueva_sin_datos_completos():
    d = scanner.parse_detail(NUEVA)
    assert d["full"] is False and d["price"] is None and d["page_price"] == 12.34


def test_top_con_gran_descuento_sale():
    why, deal = canal_nube.evaluate_listing(item(), {}, RULES, NOW)
    assert why == "" and deal["ref_kind"] == "pvp" and round(deal["discount"]) == 60
    assert deal["image"].endswith("_AC_SL1500_.jpg") and deal["modo_listado"]


def test_poco_descuento_no_sale():
    assert "solo -" in canal_nube.evaluate_listing(item(price=180.0), {}, RULES, NOW)[0]


def test_pvp_inflado_no_sale():
    assert "inflado" in canal_nube.evaluate_listing(item(price=20.0, was=249.0), {}, RULES, NOW)[0]


def test_fuera_de_top_no_sale():
    assert "solo categorías top" in canal_nube.evaluate_listing(item(title="Camiseta básica"), {}, RULES, NOW)[0]


def test_precio_de_ficha_distinto_no_sale():
    assert "no coinciden" in canal_nube.evaluate_listing(item(), {"page_price": 109.0}, RULES, NOW)[0]


def test_seguimiento_no_marca_agotado_con_ficha_nueva():
    post = {"asin": "B0TEST1234", "jl_id": "X1", "price": 12.34, "t": time.time(), "message_id": 1, "chat": "@c",
            "caption": "x"}
    state = {"posts": [post]}
    rules = dict(RULES, track_hours=48, max_tracking_checks_per_run=4)
    canal_nube.track_posts(None, state, NOW, rules, lambda *_: None, True, lambda url: NUEVA)
    assert not post.get("ended")


RELAX = canal_nube.rules_from({"amazon_channel": {
    "max_price_age_minutes": 60, "min_price_eur": 7, "max_price_eur": 3000,
    "modo_listado": {"enabled": True, "min_discount": 50, "max_discount": 85,
                     "relaxed_min_discount": 30, "relaxed_any_category_min_discount": 60},
    "interest": {"tiers": [{"label": "Aspiradoras", "keywords": ["aspiradora"], "score": 100, "min_discount": 25}]}}})


def test_sin_silencios_top_desde_30():
    assert canal_nube.evaluate_listing(item(price=170.0), {}, RELAX, NOW, relaxed=True)[0] == ""
    assert "solo -" in canal_nube.evaluate_listing(item(price=200.0), {}, RELAX, NOW, relaxed=True)[0]
    assert "solo -" in canal_nube.evaluate_listing(item(price=170.0), {}, RELAX, NOW)[0]


def test_sin_silencios_fuera_de_top_solo_muy_grande():
    assert canal_nube.evaluate_listing(item("Gorra marrón", 90.0, 249.0), {}, RELAX, NOW, relaxed=True)[0] == ""
    assert "categorías top" in canal_nube.evaluate_listing(item("Gorra marrón", 120.0, 249.0), {}, RELAX, NOW, relaxed=True)[0]
    assert "categorías top" in canal_nube.evaluate_listing(item("Gorra marrón", 90.0, 249.0), {}, RELAX, NOW)[0]
