#!/usr/bin/env python3
"""Cliente mínimo de la API oficial de afiliados de AliExpress (Open Platform, pasarela TOP).

Solo usa la biblioteca estándar. Las llaves salen de variables de entorno (GitHub Secrets):
ALIEXPRESS_APP_KEY, ALIEXPRESS_APP_SECRET y ALIEXPRESS_TRACKING_ID (Telegram) /
ALIEXPRESS_TRACKING_ID_X (X). Nunca se escriben en el repo ni en los logs.

Firma: método "md5" de la pasarela TOP, igual que el SDK oficial de AliExpress
(secret + claves ordenadas con su valor + secret, MD5 en mayúsculas).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

GATEWAY = "https://api-sg.aliexpress.com/sync"
USER_AGENT = "CazaChollosBot/3.0 (+https://t.me/cazachollos_com)"

# Campos que pedimos en las consultas de productos (los que usa el bot y nada más).
PRODUCT_FIELDS = ",".join([
    "product_id", "product_title", "product_main_image_url", "product_detail_url", "promotion_link",
    "target_sale_price", "target_sale_price_currency", "target_original_price", "target_app_sale_price",
    "discount", "evaluate_rate", "lastest_volume", "first_level_category_id", "first_level_category_name",
    "second_level_category_name", "shop_id", "shop_url", "commission_rate", "hot_product_commission_rate",
    "promo_code_info",
])


class AliExpressError(RuntimeError):
    pass


def sign(secret: str, params: dict) -> str:
    """Firma MD5 de la pasarela TOP (la misma que el SDK oficial)."""
    joined = "".join(f"{key}{params[key]}" for key in sorted(params))
    return hashlib.md5(f"{secret}{joined}{secret}".encode("utf-8")).hexdigest().upper()


def _num(value) -> float | None:
    try:
        number = float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _pct(value) -> float | None:
    """'97.5%' -> 97.5"""
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace("%", "").replace(",", ".").strip())
    except ValueError:
        return None


def normalize(raw: dict) -> dict:
    """Producto de la API -> dict plano con lo que usa el bot."""
    promo = raw.get("promo_code_info") or {}
    if isinstance(promo, list):
        promo = promo[0] if promo else {}
    return {
        "id": str(raw.get("product_id") or ""),
        "title": str(raw.get("product_title") or "").strip(),
        "image": str(raw.get("product_main_image_url") or ""),
        "url": str(raw.get("product_detail_url") or ""),
        "link": str(raw.get("promotion_link") or ""),
        "price": _num(raw.get("target_sale_price")),
        "currency": str(raw.get("target_sale_price_currency") or "EUR"),
        "list_price": _num(raw.get("target_original_price")),
        "app_price": _num(raw.get("target_app_sale_price")),
        "rating": _pct(raw.get("evaluate_rate")),
        "volume": int(_num(raw.get("lastest_volume")) or 0),
        "category_id": str(raw.get("first_level_category_id") or ""),
        "category": str(raw.get("first_level_category_name") or ""),
        "subcategory": str(raw.get("second_level_category_name") or ""),
        "shop_id": str(raw.get("shop_id") or ""),
        "commission": _pct(raw.get("hot_product_commission_rate") or raw.get("commission_rate")),
        "coupon": {
            "code": str(promo.get("promo_code") or ""),
            "value": str(promo.get("code_value") or ""),
            "min_spend": str(promo.get("code_mini_spend") or ""),
            "ends": str(promo.get("code_availabletime_end") or ""),
        } if promo.get("promo_code") else None,
    }


def _products(result: dict) -> list[dict]:
    products = (result.get("products") or {})
    items = products.get("product") if isinstance(products, dict) else products
    return [normalize(p) for p in (items or []) if isinstance(p, dict)]


class AliExpressAPI:
    def __init__(self, app_key: str, app_secret: str, tracking_id: str, *, language: str = "ES",
                 currency: str = "EUR", country: str = "ES", opener=None, timeout: int = 30):
        if not app_key or not app_secret:
            raise AliExpressError("faltan ALIEXPRESS_APP_KEY / ALIEXPRESS_APP_SECRET")
        self._key = app_key
        self._secret = app_secret
        self.tracking_id = tracking_id
        self.language = language
        self.currency = currency
        self.country = country
        self._open = opener or urllib.request.urlopen
        self.timeout = timeout
        self.calls = 0

    @classmethod
    def from_env(cls, **kwargs) -> "AliExpressAPI | None":
        key = os.environ.get("ALIEXPRESS_APP_KEY", "").strip()
        secret = os.environ.get("ALIEXPRESS_APP_SECRET", "").strip()
        tracking = os.environ.get("ALIEXPRESS_TRACKING_ID", "").strip()
        if not key or not secret or not tracking:
            return None
        return cls(key, secret, tracking, **kwargs)

    # -------------------------------------------------------------- llamada base
    def call(self, method: str, params: dict) -> dict:
        system = {
            "app_key": self._key,
            "method": method,
            "timestamp": str(int(time.time() * 1000)),
            "sign_method": "md5",
            "format": "json",
            "v": "2.0",
        }
        business = {k: str(v) for k, v in params.items() if v not in (None, "")}
        system["sign"] = sign(self._secret, {**system, **business})
        url = GATEWAY + "?" + urllib.parse.urlencode(system)
        req = urllib.request.Request(url, data=urllib.parse.urlencode(business).encode("utf-8"),
                                     headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
                                              "User-Agent": USER_AGENT})
        self.calls += 1
        try:
            with self._open(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise AliExpressError(f"{method}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AliExpressError(f"{method}: {exc}") from exc
        if "error_response" in data:
            err = data["error_response"]
            raise AliExpressError(f"{method}: {err.get('code')} {err.get('msg')} {err.get('sub_msg') or ''}".strip())
        name = method.replace(".", "_") + "_response"
        resp_result = ((data.get(name) or {}).get("resp_result") or {})
        code = resp_result.get("resp_code")
        if code not in (200, "200"):
            raise AliExpressError(f"{method}: resp_code {code} {resp_result.get('resp_msg') or ''}".strip())
        return resp_result.get("result") or {}

    def _common(self) -> dict:
        return {"target_currency": self.currency, "target_language": self.language,
                "ship_to_country": self.country, "tracking_id": self.tracking_id}

    # -------------------------------------------------------------- consultas
    def hot_products(self, *, category_ids: str = "", keywords: str = "", page: int = 1, page_size: int = 50,
                     sort: str = "LAST_VOLUME_DESC", min_price: float | None = None,
                     max_price: float | None = None) -> list[dict]:
        params = {**self._common(), "fields": PRODUCT_FIELDS, "category_ids": category_ids, "keywords": keywords,
                  "page_no": page, "page_size": page_size, "sort": sort, "platform_product_type": "ALL",
                  "min_sale_price": _cents(min_price), "max_sale_price": _cents(max_price)}
        return _products(self.call("aliexpress.affiliate.hotproduct.query", params))

    def search(self, *, keywords: str = "", category_ids: str = "", page: int = 1, page_size: int = 50,
               sort: str = "LAST_VOLUME_DESC", min_price: float | None = None,
               max_price: float | None = None) -> list[dict]:
        params = {**self._common(), "fields": PRODUCT_FIELDS, "category_ids": category_ids, "keywords": keywords,
                  "page_no": page, "page_size": page_size, "sort": sort, "platform_product_type": "ALL",
                  "min_sale_price": _cents(min_price), "max_sale_price": _cents(max_price)}
        return _products(self.call("aliexpress.affiliate.product.query", params))

    def details(self, product_ids: list[str]) -> list[dict]:
        """Ficha en vivo de hasta 20 productos (precio actual para releer antes de publicar y para el seguimiento)."""
        out: list[dict] = []
        for i in range(0, len(product_ids), 20):
            chunk = ",".join(product_ids[i:i + 20])
            params = {"product_ids": chunk, "fields": PRODUCT_FIELDS, "target_currency": self.currency,
                      "target_language": self.language, "country": self.country, "tracking_id": self.tracking_id}
            out.extend(_products(self.call("aliexpress.affiliate.productdetail.get", params)))
        return out

    def affiliate_links(self, urls: list[str], tracking_id: str | None = None) -> dict[str, str]:
        """Enlaces de afiliado para otra etiqueta (p. ej. la de X). Devuelve {url original: enlace}."""
        if not urls:
            return {}
        params = {"promotion_link_type": 0, "source_values": ",".join(urls),
                  "tracking_id": tracking_id or self.tracking_id}
        result = self.call("aliexpress.affiliate.link.generate", params)
        links = (result.get("promotion_links") or {}).get("promotion_link") or []
        return {str(l.get("source_value")): str(l.get("promotion_link")) for l in links
                if l.get("source_value") and l.get("promotion_link")}


def _cents(value: float | None) -> str | None:
    """La API filtra precios en céntimos de la moneda pedida."""
    return None if value is None else str(int(round(value * 100)))
