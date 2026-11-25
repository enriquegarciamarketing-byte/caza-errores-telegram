"""Tarjeta del premium @caza_errores (1000x1000) solo con datos de Amazon.

Diseño fijado el 17/11/2026 para cumplir Amazon Afiliados: foto del producto sobre blanco, panel
«PRECIO EN AMAZON · recomendado vs. hoy» con badge -%, fecha y hora del precio, precio recomendado tachado,
precio actual en píldora naranja y el aviso de afiliado al pie. Sin logo de Amazon, sin Keepa ni historial.
Con agotado=True sale en blanco y negro con el sello AGOTADO en medio.

Uso suelto: python tarjeta_premium.py <foto> <recomendado> <actual> "<dd/mm · hh:mm>" <salida.jpg> [--agotado]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

FONT = Path(__file__).resolve().parent / "fonts" / "Figtree[wght].ttf"
BEIGE = (247, 246, 242)
ORANGE = (239, 96, 38)
GRID = (238, 236, 232)
BORDER = (232, 230, 226)
SELLO_Y = 583  # 26/11/2026: el sello AGOTADO va encima del gráfico de precio, no de la foto del producto
AVISO = "En calidad de Afiliado de Amazon, obtengo ingresos por las compras adscritas que cumplen los requisitos aplicables."


def _font(size: int, weight: bytes) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT), size)
    f.set_variation_by_name(weight)
    return f


def eur(value: float, space: bool = False) -> str:
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return text + (" €" if space else "€")  # Enrique: el € siempre pegado al número


def _product_on_white(src: Image.Image) -> Image.Image:
    """Recorta los márgenes blancos. Las fotos principales de Amazon ya vienen sobre blanco."""
    src = src.convert("RGB")
    diff = ImageChops.difference(src, Image.new("RGB", src.size, "white")).convert("L")
    box = diff.point(lambda v: 255 if v > 12 else 0).getbbox()
    return src.crop(box) if box else src


def sellar(im: Image.Image, motivo: str = "agotado") -> Image.Image:
    """Tarjeta terminada: en blanco y negro con el sello rojo en medio de la foto del producto.

    motivo «agotado» → AGOTADO (no se puede comprar a ningún precio); «terminada» → OFERTA TERMINADA
    (sigue a la venta pero más cara). Mismo sello que las tarjetas marcadas a mano el 17/11/2026."""
    import marco_canal
    caja = marco_canal.caja_tarjeta(im.size)  # 26/11/2026: tarjeta dentro del marco naranja del canal
    ox, oy, k = caja if caja else (0, 0, im.width / 1000)
    gray = ImageOps.grayscale(im.convert("RGB")).point(lambda v: int(v * 0.9 + 25))
    out = gray.convert("RGB")
    lines = ["AGOTADO"] if motivo == "agotado" else ["OFERTA", "TERMINADA"]
    font = _font(int((120 if len(lines) == 1 else 92) * k), b"Black")
    mw = max(font.getlength(t) for t in lines)
    bw, bh = int(mw + 90 * k), int((180 if len(lines) == 1 else 250) * k)
    red = (220, 38, 38, 255)
    stamp = Image.new("RGBA", (bw + 4, bh + 4), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.rounded_rectangle((2, 2, bw + 1, bh + 1), int(28 * k), fill=(255, 255, 255, 235))
    inset, width = int(12 * k), max(2, int(14 * k))
    sd.rounded_rectangle((2 + inset, 2 + inset, bw + 1 - inset, bh + 1 - inset), int(20 * k), outline=red, width=width)
    for i, text in enumerate(lines):
        y = bh / 2 + 2 + ((i - (len(lines) - 1) / 2) * 96 + 6) * k
        sd.text((bw / 2 + 2, y), text, font=font, fill=red, anchor="mm")
    stamp = stamp.rotate(12, resample=Image.BICUBIC, expand=True)
    cx, cy = (ox + int(500 * k), oy + int(SELLO_Y * k)) if caja else (int(500 * k), int(SELLO_Y * im.height / 1000))
    out.paste(stamp, (cx - stamp.width // 2, cy - stamp.height // 2), stamp)
    return out


def es_blanco_y_negro(im: Image.Image) -> bool:
    """True si la tarjeta ya está en blanco y negro (ya marcada como terminada): no se vuelve a sellar.
    Mira la píldora del precio (abajo a la derecha), que en color es naranja y lejos del sello."""
    import marco_canal
    caja = marco_canal.caja_tarjeta(im.size)
    if caja:  # enmarcada: se mira la píldora de la tarjeta de dentro
        ox, oy, k = caja
        im = im.crop((ox, oy, ox + round(1000 * k), oy + round(1000 * k)))
    w, h = im.size
    pill = im.convert("RGB").crop((int(w * 0.6), int(h * 0.85), int(w * 0.9), int(h * 0.93))).resize((60, 16))
    return sum(1 for px in pill.getdata() if max(px) - min(px) > 40) < 50


def crear_tarjeta(photo: Path, reference: float | None, current: float, when: str, out: Path,
                  agotado: bool = False, ref_label: str = "recomendado", marco: str | None = "caza_errores") -> Path:
    # ref_label: «recomendado» (PVP de la ficha) o «mediano» cuando la ficha solo da «Precio mediano».
    # reference None: la ficha no da precio de referencia → tarjeta sin panel ni tachado, solo el precio de hoy.
    pct = round((reference - current) / reference * 100) if reference else None
    product = _product_on_white(Image.open(photo))

    im = Image.new("RGB", (1000, 1000), "white")
    d = ImageDraw.Draw(im)
    d.polygon([(x, 712 + 118 * (1 - x / 1000) ** 2) for x in range(0, 1001, 5)] + [(1000, 1000), (0, 1000)],
              fill=BEIGE)
    bw, bh = (640, 415) if reference else (700, 640)
    s = min(bw / product.width, bh / product.height)
    product = product.resize((max(1, int(product.width * s)), max(1, int(product.height * s))), Image.LANCZOS)
    im.paste(product, (500 - product.width // 2, 30 + (bh - product.height) // 2))

    # Panel: precio recomendado de Amazon frente al de hoy (sin afirmar historial).
    if reference:
        _panel(im, reference, current, pct, ref_label)
    d = ImageDraw.Draw(im)

    # Fecha y hora del precio (lo pide Amazon).
    d.text((60, 878), f"Precio a {when}", font=_font(30, b"Bold"), fill=(110, 110, 110), anchor="ls")
    d.text((60, 916), "puede cambiar", font=_font(26, b"Medium"), fill=(150, 150, 150), anchor="ls")

    # Precio recomendado tachado.
    if reference:
        fs = _font(68, b"ExtraBold")
        text = eur(reference, False)
        w = fs.getlength(text)
        d.text((949, 812), text, font=fs, fill=(85, 85, 85), anchor="rs")
        d.line((949 - w - 4, 788, 953, 787), fill=(85, 85, 85), width=7)
    _resto(im, current, agotado, out, marco)
    return out


def _panel(im, reference, current, pct, ref_label):
    shadow = Image.new("L", (1000, 1000), 0)
    ImageDraw.Draw(shadow).rounded_rectangle((62, 476, 938, 702), 26, fill=40)
    im.paste(Image.new("RGB", (1000, 1000), (90, 90, 90)), (0, 0), shadow.filter(ImageFilter.GaussianBlur(9)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((60, 470, 940, 698), 26, fill="white", outline=BORDER, width=2)
    ft = _font(25, b"ExtraBold")
    d.text((92, 508), "PRECIO EN AMAZON", font=ft, fill=(40, 40, 40), anchor="lm")
    d.text((92 + ft.getlength("PRECIO EN AMAZON") + 14, 509), f"· {ref_label} vs. hoy",
           font=_font(22, b"Medium"), fill=(140, 140, 140), anchor="lm")
    fb = _font(28, b"ExtraBold")
    badge = f"-{pct}%"
    tw = fb.getlength(badge)
    d.rounded_rectangle((910 - tw - 40, 486, 910, 528), 21, fill=ORANGE)
    d.text((910 - tw / 2 - 20, 507), badge, font=fb, fill="white", anchor="mm")
    d.text((106, 546), f"Precio {ref_label}: {eur(reference)}", font=_font(24, b"Bold"), fill=(90, 90, 90),
           anchor="lm")
    for y in (585, 608, 632, 656):
        d.rectangle((100, y, 790, y + 1), fill=GRID)
    x = 100
    while x < 736:
        d.rectangle((x, 560, min(x + 21, 735), 565), fill=(90, 90, 90))
        x += 36
    d.rectangle((738, 563, 744, 641), fill=ORANGE)
    d.rectangle((738, 636, 789, 641), fill=ORANGE)
    d.ellipse((783, 632, 796, 645), fill=ORANGE)
    size = 30
    while _font(size, b"Bold").getlength(eur(current)) > 112:
        size -= 1
    d.text((811, 642), eur(current), font=_font(size, b"Bold"), fill=ORANGE, anchor="lm")
    d.text((773, 683), "hoy", font=_font(19, b"Bold"), fill=(150, 150, 150), anchor="lm")



def _resto(im, current, agotado, out, marco=None):
    d = ImageDraw.Draw(im)
    # Píldora naranja con el precio actual.
    pill = Image.new("RGB", (500, 125))
    pd = ImageDraw.Draw(pill)
    c0, c1 = (247, 131, 67), (205, 43, 5)
    for i in range(500):
        q = i / 499
        pd.line((i, 0, i, 124), fill=tuple(int(c0[j] + (c1[j] - c0[j]) * q) for j in range(3)))
    mask = Image.new("L", (500, 125), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 560, 124), 62, fill=255)
    im.paste(pill, (500, 828), mask)
    text = eur(current, False)
    size = 116
    while _font(size, b"Black").getlength(text) > 400:
        size -= 2
    d.text((956, 933 - (116 - size) // 2), text, font=_font(size, b"Black"), fill="white", anchor="rs")

    # Aviso de afiliado, centrado abajo entre dos líneas finas.
    fa = _font(15, b"Medium")
    aw = fa.getlength(AVISO)
    d.text((500, 980), AVISO, font=fa, fill=(110, 110, 110), anchor="mm")
    d.line((40, 980, 500 - aw / 2 - 16, 980), fill=(170, 170, 170), width=1)
    d.line((500 + aw / 2 + 16, 980, 960, 980), fill=(170, 170, 170), width=1)

    if marco:  # 26/11/2026: marco naranja con la pestaña del canal (marco_canal.py)
        import marco_canal
        im = marco_canal.enmarcar_canal(im, marco)
    if agotado:
        im = sellar(im, "agotado")

    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, quality=96, subsampling=0, optimize=True)  # 4:4:4, sin emborronar naranjas ni textos


if __name__ == "__main__":
    a = sys.argv[1:]
    crear_tarjeta(Path(a[0]), float(a[1]), float(a[2]), a[3], Path(a[4]), agotado="--agotado" in a)
    print(a[4])
