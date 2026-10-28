#!/usr/bin/env python3
"""Cliente mínimo de la Creators API de Amazon Afiliados (API oficial).

Se activa solo cuando existen los secretos AMAZON_CREATORS_CLIENT_ID y
AMAZON_CREATORS_CLIENT_SECRET (requisito de Amazon: 10 ventas válidas en 30 días).
Sirve para comprobar en vivo el precio y el stock de cada talla antes de publicar.

Cualquier respuesta inesperada lanza ApiError: el escáner descarta el producto
en vez de publicarlo con datos dudosos.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

TOKEN_URL = "https://api.amazon.co.uk/auth/o2/token"  # región Europa
API_BASE = "https://creatorsapi.amazon/catalog/v1/"
MARKETPLACE = "www.amazon.es"

PRICE_RESOURCES = [
    "itemInfo.title",
    "parentASIN",
    "images.primary.large",
    "offersV2.listings.price",
    "offersV2.listings.availability",
]


class ApiError(RuntimeError):
    pass


def _get(data, *path, default=None):
    """Navega claves sin distinguir mayúsculas (la documentación mezcla Price/price)."""
    for key in path:
        if isinstance(data, list):
            if isinstance(key, int) and len(data) > key:
                data = data[key]
                continue
            return default
        if not isinstance(data, dict):
            return default
        match = next((k for k in data if k.lower() == str(key).lower()), None)
        if match is None:
            return default
        data = data[match]
    return data


class CreatorsAPI:
    def __init__(self, client_id: str, client_secret: str, partner_tag: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.partner_tag = partner_tag
        self._token = None
        self._token_exp = 0.0

    @classmethod
    def from_env(cls, partner_tag: str) -> "CreatorsAPI | None":
        cid = os.environ.get("AMAZON_CREATORS_CLIENT_ID", "").strip()
        secret = os.environ.get("AMAZON_CREATORS_CLIENT_SECRET", "").strip()
        return cls(cid, secret, partner_tag) if cid and secret else None

    def _post(self, url: str, body: dict, headers: dict) -> dict:
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise ApiError(f"HTTP {exc.code} en {url.rsplit('/', 1)[-1]}: {detail}") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ApiError(f"Fallo de conexión con la Creators API: {exc}") from None

    def _auth(self) -> str:
        if self._token and time.time() < self._token_exp - 60:
            return self._token
        data = self._post(TOKEN_URL, {"grant_type": "client_credentials", "client_id": self.client_id,
                                      "client_secret": self.client_secret, "scope": "creatorsapi::default"}, {})
        if not data.get("access_token"):
            raise ApiError("La Creators API no devolvió token")
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 3600))
        return self._token

    def call(self, operation: str, body: dict) -> dict:
        headers = {"Authorization": f"Bearer {self._auth()}", "x-marketplace": MARKETPLACE}
        payload = {"partnerTag": self.partner_tag, "marketplace": MARKETPLACE, **body}
        return self._post(API_BASE + operation, payload, headers)

    # ------------------------------------------------------------ ayudas

    @staticmethod
    def _offer(item: dict) -> dict:
        listing = _get(item, "offersV2", "listings", 0, default={}) or {}
        money = _get(listing, "price", "money", default=None) or _get(listing, "price", default={}) or {}
        basis = (_get(listing, "price", "savingBasis", "money", default=None)
                 or _get(listing, "price", "savingBasis", default={}) or {})
        avail = str(_get(listing, "availability", "type", default="") or "")
        amount = _get(money, "amount")
        basis_amount = _get(basis, "amount")
        return {
            "price": float(amount) if isinstance(amount, (int, float, str)) and str(amount) else None,
            "saving_basis": float(basis_amount) if isinstance(basis_amount, (int, float, str)) and str(basis_amount) else None,
            "in_stock": avail.upper() in {"IN_STOCK", "INSTOCK", "AVAILABLE"},
        }

    def find_by_ean(self, ean: str) -> dict:
        """Devuelve el artículo de Amazon.es cuyo EAN coincide (ASIN, padre, precio, stock)."""
        data = self.call("searchItems", {"keywords": ean, "itemCount": 3, "resources": PRICE_RESOURCES})
        items = _get(data, "searchResult", "items", default=[]) or []
        if not items:
            raise ApiError(f"Ningún resultado para el EAN {ean}")
        item = items[0]
        return {
            "asin": _get(item, "asin"),
            "parent": _get(item, "parentASIN") or _get(item, "parentAsin"),
            "title": _get(item, "itemInfo", "title", "displayValue", default=""),
            "image": _get(item, "images", "primary", "large", "url"),
            **self._offer(item),
        }

    def variations(self, parent_asin: str, max_pages: int = 4) -> list[dict]:
        """Todas las variantes (tallas/colores) con su precio y stock en vivo."""
        out = []
        for page in range(1, max_pages + 1):
            data = self.call("getVariations", {
                "asin": parent_asin, "variationCount": 9, "variationPage": page,
                "resources": PRICE_RESOURCES + ["variationSummary.variationDimension"],
            })
            items = _get(data, "variationsResult", "items", default=[]) or []
            for item in items:
                attrs = {}
                for attr in _get(item, "variationAttributes", default=[]) or []:
                    name = str(_get(attr, "name", default="")).lower()
                    value = _get(attr, "value") or _get(attr, "displayValue")
                    if name and value:
                        attrs[name] = str(value)
                out.append({"asin": _get(item, "asin"), "attrs": attrs, **self._offer(item)})
            if len(items) < 9:
                break
        if not out:
            raise ApiError(f"Sin variantes para {parent_asin}")
        return out


def size_of(attrs: dict) -> str | None:
    for key, value in attrs.items():
        if "size" in key or "talla" in key or "tamaño" in key:
            return value
    return None


def color_of(attrs: dict) -> str | None:
    for key, value in attrs.items():
        if "color" in key or "colour" in key:
            return value
    return None
