import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

import amazon_page as amz
import canal_amazon as ca

PAD = "<!-- relleno -->" * 700  # las fichas reales pesan cientos de KB


def ficha(price="23,99 €", lowest="59,99 €", stock="En stock", seller="Amazon", shipper="Amazon",
          rating="4,5", reviews="1.234", prime=False, coupon=False, title="Auriculares Inalámbricos Marca X Pro, "
          "Cancelación de Ruido, 40 h de Batería - Negro", recommended=None):
    # Como en Amazon.es: importes con &nbsp;, scripts largos dentro del bloque de precio y el tachado
    # en un span basisPrice muy por debajo del inicio del bloque.
    nb = lambda v: v.replace(" €", "&nbsp;€")
    def basis(label, value):
        return (f'<span class="a-size-small a-color-secondary aok-align-center basisPrice">{label} '
                f'<span class="a-price a-text-price" data-a-strike="true"><span class="a-offscreen">{nb(value)}</span>'
                f'<span aria-hidden="true">{nb(value)}</span></span></span>')
    refs = (basis("Precio más bajo reciente:", lowest) if lowest else "") + (
        basis("Precio recomendado:", recommended) if recommended else "")
    prime_html = '<span>Precio exclusivo para Prime</span>' if prime else ""
    coupon_html = '<div id="couponBadgeRegularVpc">Aplicar cupón de 5 €</div>' if coupon else ""
    script = "<script>P.when('A').execute(function(){ /* " + "x" * 15000 + " */ });</script>"
    whole, frac = price.replace(" €", "").split(",")
    return f"""<html><head><title>Amazon.es</title></head><body>{PAD}
<div id="title_feature_div"><span id="productTitle" class="a-size-large product-title-word-break">   {title}   </span></div>
<div id="averageCustomerReviews_feature_div"><a id="acrPopover" class="a-popover-trigger" title="{rating} de 5 estrellas"></a>
<span id="acrCustomerReviewText" class="a-size-base">{reviews} valoraciones</span></div>
<div id="corePriceDisplay_desktop_feature_div" class="celwidget">{script}
 <span class="a-price aok-align-center reinventPricePriceToPayMargin priceToPay" data-a-size="xl">
  <span class="a-offscreen">{nb(price)}</span><span aria-hidden="true"><span class="a-price-whole">{whole}<span class="a-price-decimal">,</span></span><span class="a-price-fraction">{frac}</span></span>
 </span>
 <span class="savingsPercentage">-60 %</span>{script}
 {refs}{prime_html}{coupon_html}
</div>
<div id="availability_feature_div"><div id="availability" class="a-section"><span class="a-size-medium a-color-success">{stock}</span></div></div>
<div id="offerDisplayFeatures_desktop"><div>Enviado por</div><div><span>{shipper}</span></div>
<div>Vendido por</div><div><span>{seller}</span></div><div>Devoluciones</div></div>
<div id="imageBlock_feature_div"><img id="landingImage" data-old-hires="https://m.media-amazon.com/images/I/71abcDEF._AC_SL1500_.jpg" src="x.jpg"></div>
<input id="add-to-cart-button" type="submit">
<div id="similarities_feature_div">{basis("Precio más bajo reciente:", "999,00 €")}</div>
{PAD}</body></html>"""


RULES = ca.rules_from({"affiliate_tag": "cazadores_errores-21", "amazon_channel": {
    "block_keywords": ["funda"], "discovery_urls": ["https://www.amazon.es/s?i=electronics&pct-off=40-"]}})


class LecturaFicha(unittest.TestCase):
    def test_lee_precio_referencia_vendedor_y_foto(self):
        p = amz.parse_product(ficha(), "B0TEST1234")
        self.assertEqual(p["price"], 23.99)
        self.assertEqual(p["lowest_30"], 59.99)
        self.assertTrue(p["in_stock"])
        self.assertEqual(p["seller"], "Amazon")
        self.assertEqual(p["shipper"], "Amazon")
        self.assertEqual(p["rating"], 4.5)
        self.assertEqual(p["reviews"], 1234)
        self.assertEqual(p["image"], "https://m.media-amazon.com/images/I/71abcDEF.jpg")
        self.assertTrue(p["title"].startswith("Auriculares"))

    def test_importes_con_miles(self):
        self.assertEqual(amz.parse_eur("1.299,00 €"), 1299.0)
        self.assertEqual(amz.parse_eur("7,5 €"), 7.5)
        self.assertEqual(amz.parse_eur("12 €"), 12.0)
        self.assertIsNone(amz.parse_eur("gratis"))
        p = amz.parse_product(ficha(price="1.049,90 €", lowest="1.899,00 €"), "B0TEST1234")
        self.assertEqual((p["price"], p["lowest_30"]), (1049.90, 1899.0))

    def test_sin_precio_mas_bajo_reciente_no_hay_referencia(self):
        p = amz.parse_product(ficha(lowest=None), "B0TEST1234")
        self.assertIsNone(p["lowest_30"])
        self.assertIn("no muestra precio más bajo", ca.evaluate(p, RULES))

    def test_pvpr_no_cuenta_como_referencia(self):
        p = amz.parse_product(ficha(lowest=None, recommended="79,99 €"), "B0TEST1234")
        self.assertIsNone(p["lowest_30"])
        self.assertEqual(p["list_price"], 79.99)
        p = amz.parse_product(ficha(recommended="79,99 €"), "B0TEST1234")
        self.assertEqual((p["lowest_30"], p["list_price"]), (59.99, 79.99))

    def test_no_lee_tachados_de_otros_productos(self):
        # El 999,00 € del carrusel de abajo no debe usarse nunca.
        p = amz.parse_product(ficha(lowest=None), "B0TEST1234")
        self.assertIsNone(p["lowest_30"])

    def test_referencia_igual_al_precio_se_descarta(self):
        p = amz.parse_product(ficha(price="23,99 €", lowest="23,99 €"), "B0TEST1234")
        self.assertIsNone(p["lowest_30"])

    def test_diagnostico(self):
        text = amz.diagnose(ficha(), "B0TEST1234")
        self.assertIn("lowest_30: 59.99", text)
        self.assertIn("price: 23.99", text)

    def test_detecta_captcha(self):
        page = "<html><!-- To discuss automated access to Amazon data please contact api-services-support@amazon.com --></html>"
        self.assertTrue(amz.is_blocked(page))
        self.assertFalse(amz.is_blocked(ficha()))

    def test_agotado(self):
        p = amz.parse_product(ficha(stock="Actualmente no disponible."), "B0TEST1234")
        self.assertFalse(p["in_stock"])
        self.assertIn("sin stock", ca.evaluate(p, RULES))

    def test_listado(self):
        page = PAD + "".join(
            f'<div data-asin="{asin}" data-component-type="s-search-result"><h2><span>{name}</span></h2>'
            f'<span class="a-price"><span class="a-offscreen">{now}</span></span>'
            f'<span class="a-price a-text-price"><span class="a-offscreen">{was}</span></span></div>'
            for asin, name, now, was in [("B0AAAAAAA1", "Uno", "10,00 €", "25,00 €"), ("B0AAAAAAA2", "Dos", "9,00 €", "10,00 €")])
        items = {i["asin"]: i for i in amz.parse_listing(page)}
        self.assertEqual(items["B0AAAAAAA1"]["price"], 10.0)
        self.assertEqual(round(amz.listing_drop(items["B0AAAAAAA1"])), 60)
        self.assertEqual(round(amz.listing_drop(items["B0AAAAAAA2"])), 10)


class Reglas(unittest.TestCase):
    def test_chollo_bueno_pasa(self):
        self.assertEqual(ca.evaluate(amz.parse_product(ficha(), "B0TEST1234"), RULES), "")

    def test_rebaja_pequena_no_pasa(self):
        p = amz.parse_product(ficha(price="49,99 €", lowest="59,99 €"), "B0TEST1234")
        self.assertIn("solo -17%", ca.evaluate(p, RULES))

    def test_vendedor_externo_no_pasa(self):
        p = amz.parse_product(ficha(seller="TiendaRara", shipper="TiendaRara"), "B0TEST1234")
        self.assertIn("ni vendido ni enviado por Amazon", ca.evaluate(p, RULES))

    def test_vendedor_externo_con_envio_amazon_pasa(self):
        p = amz.parse_product(ficha(seller="MarcaX Oficial", shipper="Amazon"), "B0TEST1234")
        self.assertEqual(ca.evaluate(p, RULES), "")

    def test_prime_exclusivo_no_pasa(self):
        self.assertIn("Prime", ca.evaluate(amz.parse_product(ficha(prime=True), "B0TEST1234"), RULES))

    def test_pocas_opiniones_y_mala_nota(self):
        self.assertIn("pocas opiniones", ca.evaluate(amz.parse_product(ficha(reviews="12"), "B0X"), RULES))
        self.assertIn("valoración baja", ca.evaluate(amz.parse_product(ficha(rating="3,6"), "B0X"), RULES))

    def test_palabra_bloqueada(self):
        p = amz.parse_product(ficha(title="Funda para móvil de silicona resistente premium"), "B0X")
        self.assertIn("excluida", ca.evaluate(p, RULES))

    def test_comprobacion_final_exige_mismo_precio(self):
        first = amz.parse_product(ficha(), "B0TEST1234")
        second = amz.parse_product(ficha(price="24,99 €"), "B0TEST1234")
        self.assertIn("ha cambiado", ca.same_offer(first, second, RULES))
        self.assertEqual(ca.same_offer(first, amz.parse_product(ficha(), "B0TEST1234"), RULES), "")


class Texto(unittest.TestCase):
    def test_caption_usa_precio_de_ficha_y_enlace_directo(self):
        p = amz.parse_product(ficha(), "B0TEST1234")
        url = amz.canonical_url("B0TEST1234", "cazadores_errores-21")
        text = ca.build_caption(p, url, RULES, datetime(2026, 10, 31, 13, 5, tzinfo=timezone.utc))
        self.assertIn("23,99 €", text)
        self.assertIn("<s>59,99 €</s>", text)
        self.assertIn("-60 %", text)
        self.assertIn("a las 14:05", text)
        self.assertIn("https://www.amazon.es/dp/B0TEST1234?tag=cazadores_errores-21", text)
        self.assertIn("CHOLLAZO", text)
        self.assertNotIn("PVP", text)

    def test_titulo_limpio(self):
        self.assertEqual(ca.clean_title("Auriculares Inalámbricos Marca X Pro, Cancelación de Ruido, 40 h - Negro"),
                         "Auriculares Inalámbricos Marca X Pro")


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        for key, page in self.pages.items():
            if key in url:
                return page() if callable(page) else page
        raise RuntimeError("sin página")


class Pasada(unittest.TestCase):
    def test_dry_run_completo_sin_enviar(self):
        listing = PAD + ('<div data-asin="B0TEST1234"><h2>Auris</h2><span class="a-offscreen">23,99 €</span>'
                         '<span class="a-offscreen">59,99 €</span></div>')
        session = FakeSession({"/s?": listing, "/dp/B0TEST1234": ficha()})
        out = []
        args = SimpleNamespace(dry_run=True, test_private=False, ignore_limits=True)
        state = {"posts": [], "seen": {}}
        now = datetime(2026, 10, 31, 13, 0, tzinfo=timezone.utc)
        ca.run(args, {"affiliate_tag": "cazadores_errores-21", "amazon_channel": RULES | {"tag": None}},
               state, now, tg=None, session=session, log=out.append)
        text = "\n".join(out)
        self.assertIn("[prueba, no se envía]", text)
        self.assertIn("23,99 €", text)
        self.assertEqual(sum("/dp/B0TEST1234" in c for c in session.calls), 2, "debe leer la ficha dos veces")
        self.assertEqual(state["posts"], [])

    def test_precio_que_cambia_entre_lecturas_no_sale(self):
        reads = iter([ficha(), ficha(price="31,99 €")])
        listing = PAD + '<div data-asin="B0TEST1234"><span>-60 %</span></div>'
        session = FakeSession({"/s?": listing, "/dp/B0TEST1234": lambda: next(reads)})
        out = []
        args = SimpleNamespace(dry_run=True, test_private=False, ignore_limits=True)
        ca.run(args, {"affiliate_tag": "cazadores_errores-21", "amazon_channel": RULES | {"tag": None}},
               {"posts": []}, datetime(2026, 10, 31, 13, 0, tzinfo=timezone.utc), session=session, log=out.append)
        text = "\n".join(out)
        self.assertIn("comprobación final", text)
        self.assertNotIn("[prueba, no se envía]", text)

    def test_captcha_para_sin_publicar(self):
        class Blocker:
            def get(self, url):
                raise amz.Blocked("captcha")
        out = []
        args = SimpleNamespace(dry_run=True, test_private=False, ignore_limits=True)
        state = {"posts": []}
        ca.run(args, {"affiliate_tag": "cazadores_errores-21", "amazon_channel": RULES | {"tag": None}},
               state, datetime(2026, 10, 31, 13, 0, tzinfo=timezone.utc), session=Blocker(), log=out.append)
        self.assertIn("captcha", "\n".join(out))
        self.assertIn("blocked_at", state)

    def test_horario_de_silencio(self):
        night = datetime(2026, 10, 31, 2, 0, tzinfo=timezone.utc)  # 03:00 en Madrid
        self.assertEqual(ca.quota_reason({"posts": []}, night, RULES), "horario de silencio")


if __name__ == "__main__":
    unittest.main()
