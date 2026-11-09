"""La API oficial de Amazon manda sobre el precio de jimmyleaks justo antes de publicar."""
import canal_nube
from amazon_api import ApiError, CreatorsAPI


class FakeAPI:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0

    def get_item(self, asin):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def deal():
    return {"asin": "B0TEST1234", "price": 50.0, "reference": 100.0, "discount": 50.0}


def check(api, d):
    canal_nube.API = api
    try:
        return canal_nube.api_price_check(d, log=lambda *_: None)
    finally:
        left = canal_nube.API
        canal_nube.API = None
        check.left = left


def test_sin_api_no_cambia_nada():
    d = deal()
    assert check(None, d) == "" and d["price"] == 50.0 and "api_price" not in d


def test_mismo_precio_confirma():
    d = deal()
    assert check(FakeAPI({"price": 50.0, "availability": "IN_STOCK"}), d) == ""
    assert d["api_price"] is True


def test_amazon_mas_caro_descarta():
    assert "Amazon lo tiene a" in check(FakeAPI({"price": 59.99, "availability": "IN_STOCK"}), deal())


def test_amazon_mas_barato_actualiza_precio_y_descuento():
    d = deal()
    assert check(FakeAPI({"price": 40.0, "availability": "IN_STOCK"}), d) == ""
    assert d["price"] == 40.0 and round(d["discount"]) == 60


def test_sin_stock_descarta():
    assert check(FakeAPI({"price": 50.0, "availability": "OUT_OF_STOCK"}), deal()) == "Amazon lo da sin stock"


def test_api_sin_acceso_sigue_con_jimmyleaks_y_no_insiste():
    d = deal()
    assert check(FakeAPI(error=ApiError("HTTP 403 AssociateNotEligible")), d) == ""
    assert d["price"] == 50.0 and check.left is None


def test_sin_precio_en_la_respuesta_no_bloquea():
    assert check(FakeAPI({"price": None, "availability": ""}), deal()) == ""
    assert check(FakeAPI(None), deal()) == ""


def test_secretos_con_nombre_nuevo_y_antiguo(monkeypatch):
    for name in ("AMAZON_CREATORS_ID", "AMAZON_CREATORS_SECRET", "AMAZON_CREATORS_CLIENT_ID", "AMAZON_CREATORS_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    assert CreatorsAPI.from_env("tag-21") is None
    monkeypatch.setenv("AMAZON_CREATORS_ID", "a")
    monkeypatch.setenv("AMAZON_CREATORS_SECRET", "b")
    assert CreatorsAPI.from_env("tag-21").client_id == "a"


def test_get_item_lee_precio_y_stock():
    api = CreatorsAPI("a", "b", "tag-21")
    api.call = lambda op, body: {"itemsResult": {"items": [{"asin": "B0TEST1234", "offersV2": {"listings": [
        {"price": {"money": {"amount": 49.99}, "savingBasis": {"money": {"amount": 99.0}}},
         "availability": {"type": "IN_STOCK"}}]}}]}}
    item = api.get_item("B0TEST1234")
    assert item["price"] == 49.99 and item["saving_basis"] == 99.0 and item["in_stock"]
    api.call = lambda op, body: {"itemsResult": {"items": []}}
    assert api.get_item("B0TEST1234") is None
