"""Marco de canal para las tarjetas (26/11/2026, Enrique eligió la «muesca integrada»).

La tarjeta de siempre va dentro de un marco con el degradado naranja de la píldora del precio, y el marco entra en
la tarjeta por arriba con una pestaña de curvas suaves: logo (solo el avión de Telegram o el teléfono de WhatsApp)
en blanco, nombre del canal en negrita y el @ más suave. Formas y texto se dibujan a 4x y se reducen, para que los
bordes salgan finos y sin dientes de sierra.

    enmarcar(tarjeta, "Caza Errores", "@caza_errores", "telegram")

caja_tarjeta(tamaño) dice dónde queda la tarjeta de 1000 dentro de una imagen ya enmarcada (para el sello AGOTADO).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent
FONT = ROOT / "fonts" / "Figtree[wght].ttf"
LOGOS = ROOT / "assets" / "logos"

NARANJA_IZQ = (245, 127, 65)   # mismo degradado que la píldora del precio
NARANJA_DER = (205, 43, 4)
NARANJA = (239, 96, 38)

SS = 4          # supermuestreo de formas y textos
BORDE = 30      # marco a los lados, arriba y abajo
AIRE = 64       # blanco extra arriba de la tarjeta para que la pestaña no tape el producto
RADIO = 30      # esquinas de la tarjeta
PESTANA = 70    # lo que baja la pestaña dentro de la tarjeta
CURVA = 22      # radio de los empalmes cóncavos y de las esquinas de la pestaña

CANALES = {
    "caza_errores": ("Caza Errores", "@caza_errores", "telegram"),
    "cazachollos": ("Caza Chollos", "@cazachollos_com", "telegram"),
    "whatsapp": ("Caza Chollos", "en WhatsApp", "whatsapp_completo"),
}


def _font(size: int, weight: bytes) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT), size)
    f.set_variation_by_name(weight)
    return f


def _degradado(w: int, h: int) -> Image.Image:
    fila = Image.new("RGB", (w, 1))
    px = fila.load()
    for x in range(w):
        t = x / max(w - 1, 1)
        px[x, 0] = tuple(round(a + (b - a) * t) for a, b in zip(NARANJA_IZQ, NARANJA_DER))
    return fila.resize((w, h))


def _glifo(nombre: str, alto: int) -> Image.Image:
    """Máscara (L) del logo. «telegram»: solo el avión. «whatsapp_completo»: el logo entero que pasó Enrique
    (bocadillo con el teléfono hueco, 26/11/2026)."""
    completo = nombre.endswith("_completo")
    nombre = nombre.removesuffix("_completo")
    raw = Image.open(LOGOS / f"{nombre}.png").convert("RGBA")
    src = Image.alpha_composite(Image.new("RGBA", raw.size, "white"), raw).convert("L")
    tinta = src.point(lambda v: 255 if v < 128 else 0)
    tinta = ImageOps.expand(tinta.crop(tinta.getbbox()), 4, fill=0)
    if completo:
        g = tinta.crop(tinta.getbbox())
        return g.resize((round(g.width * alto / g.height), alto), Image.LANCZOS)
    silueta = tinta.copy()
    ImageDraw.floodfill(silueta, (0, 0), 128)
    silueta = silueta.point(lambda v: 0 if v == 128 else 255)
    g = ImageChops.subtract(silueta, tinta)
    g = g.crop(g.getbbox())
    return g.resize((round(g.width * alto / g.height), alto), Image.LANCZOS)


def caja_tarjeta(size: tuple[int, int]) -> tuple[int, int, float] | None:
    """(x, y, escala) de la tarjeta de 1000 dentro de una imagen enmarcada de este tamaño; None si no lo es."""
    w, h = size
    f = w / (1000 + 2 * BORDE)  # Telegram puede devolverla reescalada
    if abs(h - f * (1000 + AIRE + 2 * BORDE)) > 3 * max(f, 1):
        return None
    return round(BORDE * f), round((BORDE + AIRE) * f), f


def enmarcar(tarjeta: Image.Image, nombre: str, handle: str, logo: str = "telegram") -> Image.Image:
    """Sirve para cualquier tamaño: las medidas están pensadas para 1000 px de ancho y se escalan (la tarjeta del
    premium mide 1000 y la foto del free, 2560)."""
    tarjeta = tarjeta.convert("RGB")
    u = tarjeta.width / 1000
    B, AI, R, P, CU = (round(v * u) for v in (BORDE, AIRE, RADIO, PESTANA, CURVA))
    S = SS if u < 1.5 else 2  # en las fotos grandes basta con 2x
    cw, ch = tarjeta.width, tarjeta.height + AI
    W, H = cw + 2 * B, ch + 2 * B

    # Medidas de la pestaña según lo que lleva dentro
    f1, f2 = _font(round(36 * u * S), b"ExtraBold"), _font(round(28 * u * S), b"Medium")
    medir = ImageDraw.Draw(Image.new("L", (1, 1)))
    glifo = _glifo(logo, round((38 if logo.endswith("_completo") else 30) * u * S))
    g1, g2, pad = 16 * u * S, 18 * u * S, round(34 * u)
    w1, w2 = medir.textlength(nombre, font=f1), medir.textlength(handle, font=f2)
    ancho = round((glifo.width + g1 + w1 + g2 + w2) / S) + 2 * pad
    x0, y0, y1 = (W - ancho) // 2, B, B + P

    # Máscaras supermuestreadas: tarjeta redondeada y pestaña con empalmes cóncavos
    m_tarjeta = Image.new("L", (W * S, H * S), 0)
    ImageDraw.Draw(m_tarjeta).rounded_rectangle((B * S, B * S, (B + cw) * S - 1, (B + ch) * S - 1), R * S, fill=255)
    m_pestana = Image.new("L", (W * S, H * S), 0)
    d = ImageDraw.Draw(m_pestana)
    c = CU * S
    d.rounded_rectangle((x0 * S, (y0 - CU) * S, (x0 + ancho) * S, y1 * S), c, fill=255)
    d.rectangle(((x0 - CU) * S, y0 * S, x0 * S, y0 * S + c), fill=255)
    d.rectangle(((x0 + ancho) * S, y0 * S, (x0 + ancho + CU) * S, y0 * S + c), fill=255)
    d.ellipse(((x0 - 2 * CU) * S, y0 * S, x0 * S, y0 * S + 2 * c), fill=0)
    d.ellipse(((x0 + ancho) * S, y0 * S, (x0 + ancho + 2 * CU) * S, y0 * S + 2 * c), fill=0)
    m_pestana = ImageChops.multiply(m_pestana, m_tarjeta)  # solo dentro de la tarjeta

    # Contenido de la pestaña: glifo blanco + nombre + @ (solo se dibuja la franja de arriba, a S×)
    franja = (y0 + P + 4 * u) * S
    capa = Image.new("RGBA", (W * S, round(franja)), (255, 255, 255, 0))
    cd = ImageDraw.Draw(capa)
    cy = (y0 + P / 2 - 2 * u) * S
    x = (x0 + pad) * S
    capa.paste(Image.new("RGBA", glifo.size, (255, 255, 255, 255)), (round(x), round(cy - glifo.height / 2)), glifo)
    x += glifo.width + g1
    cd.text((x, cy), nombre, font=f1, fill=(255, 255, 255, 255), anchor="lm")
    x += w1 + g2
    cd.text((x, cy + u * S), handle, font=f2, fill=(255, 224, 208, 255), anchor="lm")

    m_tarjeta = m_tarjeta.resize((W, H), Image.LANCZOS)
    m_pestana = m_pestana.resize((W, H), Image.LANCZOS)
    capa = capa.resize((W, round(franja / S)), Image.LANCZOS)

    fondo = _degradado(W, H)
    interior = Image.new("RGB", (W, H), "white")
    interior.paste(tarjeta, (B, B + AI))
    # Sombra suave de la pestaña sobre la tarjeta: da profundidad sin parecer una pegatina
    sombra = ImageChops.offset(m_pestana.filter(ImageFilter.GaussianBlur(7 * u)), 0, round(4 * u))
    sombra = sombra.point(lambda v: int(v * 0.22))
    interior.paste((150, 40, 0), (0, 0), ImageChops.multiply(sombra, m_tarjeta))

    lienzo = fondo.copy()
    lienzo.paste(interior, (0, 0), m_tarjeta)
    lienzo.paste(fondo, (0, 0), m_pestana)
    lienzo = lienzo.convert("RGBA")
    lienzo.alpha_composite(capa, (0, 0))
    return lienzo.convert("RGB")


def lienzo_con_precio(producto: Image.Image, reference: float | None, current: float, when: str,
                      lado: int = 2560) -> Image.Image:
    """Foto del producto en lienzo blanco cuadrado con el precio abajo, como en la tarjeta del premium: a la
    derecha el precio de antes tachado y la píldora naranja con el de hoy; a la izquierda «Precio a … puede
    cambiar» (Amazon pide fecha y hora si se enseña el precio)."""
    u = lado / 1000
    im = Image.new("RGB", (lado, lado), "white")
    prod = producto.convert("RGBA")
    caja_w, caja_h = 760 * u, 640 * u
    k = min(caja_w / prod.width, caja_h / prod.height)
    prod = prod.resize((max(1, round(prod.width * k)), max(1, round(prod.height * k))), Image.LANCZOS)
    im.paste(prod, ((lado - prod.width) // 2, round(70 * u + (caja_h - prod.height) / 2)), prod)
    d = ImageDraw.Draw(im)

    def eur(v: float) -> str:
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + "€"

    # Píldora con el degradado de la marca, pegada al borde derecho
    pw, ph, py = round(520 * u), round(140 * u), round(820 * u)
    pill = _degradado(pw, ph)
    mk = Image.new("L", (pw * 2, ph * 2), 0)
    ImageDraw.Draw(mk).rounded_rectangle((0, 0, pw * 2 + ph * 2, ph * 2 - 1), ph, fill=255)
    im.paste(pill, (lado - pw, py), mk.resize((pw, ph), Image.LANCZOS))
    texto = eur(current)
    size = round(118 * u)
    while _font(size, b"Black").getlength(texto) > pw - 110 * u:
        size -= 2
    d.text((lado - 44 * u, py + ph / 2 + 4 * u), texto, font=_font(size, b"Black"), fill="white", anchor="rm")
    if reference and reference > current:
        ft = _font(round(74 * u), b"ExtraBold")
        ref = eur(reference)
        x1 = lado - 44 * u
        y = py - 52 * u
        d.text((x1, y), ref, font=ft, fill=(95, 95, 95), anchor="rm")
        tw = ft.getlength(ref)
        d.line((x1 - tw - 6 * u, y + 2 * u, x1 + 6 * u, y + 2 * u), fill=(60, 60, 60), width=max(2, round(7 * u)))
        pct = round((reference - current) / reference * 100)
        fb = _font(round(40 * u), b"ExtraBold")
        bt = f"-{pct}%"
        bw, bh = fb.getlength(bt) + 44 * u, 64 * u
        bx, by = 60 * u, py - 52 * u - bh / 2
        d.rounded_rectangle((bx, by, bx + bw, by + bh), bh / 2, fill=NARANJA)
        d.text((bx + bw / 2, by + bh / 2 + 2 * u), bt, font=fb, fill="white", anchor="mm")
    d.text((60 * u, py + ph / 2 - 20 * u), f"Precio a {when}", font=_font(round(40 * u), b"Bold"),
           fill=(110, 110, 110), anchor="lm")
    d.text((60 * u, py + ph / 2 + 30 * u), "puede cambiar", font=_font(round(34 * u), b"Medium"),
           fill=(150, 150, 150), anchor="lm")
    return im


def enmarcar_canal(tarjeta: Image.Image, canal: str) -> Image.Image:
    return enmarcar(tarjeta, *CANALES[canal])


def guardar(im: Image.Image, out: Path, quality: int = 96) -> Path:
    """JPEG sin submuestreo de color (4:4:4): los bordes naranjas y el texto no se emborronan."""
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out, quality=quality, subsampling=0, optimize=True)
    return out


if __name__ == "__main__":
    import sys
    src, out, canal = sys.argv[1:4]
    guardar(enmarcar_canal(Image.open(src), canal), Path(out))
