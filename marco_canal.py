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
    "whatsapp": ("Caza Chollos", "en WhatsApp", "whatsapp"),
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
    """Máscara (L) solo del dibujo de dentro del logo: el avión de Telegram o el teléfono de WhatsApp."""
    raw = Image.open(LOGOS / f"{nombre}.png").convert("RGBA")
    src = Image.alpha_composite(Image.new("RGBA", raw.size, "white"), raw).convert("L")
    tinta = src.point(lambda v: 255 if v < 128 else 0)
    tinta = ImageOps.expand(tinta.crop(tinta.getbbox()), 4, fill=0)
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
    tarjeta = tarjeta.convert("RGB")
    S = SS
    cw, ch = tarjeta.width, tarjeta.height + AIRE
    W, H = cw + 2 * BORDE, ch + 2 * BORDE

    # Medidas de la pestaña según lo que lleva dentro
    f1, f2 = _font(36 * S, b"ExtraBold"), _font(28 * S, b"Medium")
    medir = ImageDraw.Draw(Image.new("L", (1, 1)))
    glifo = _glifo(logo, 30 * S)
    w1, w2 = medir.textlength(nombre, font=f1), medir.textlength(handle, font=f2)
    ancho = round((glifo.width + 16 * S + w1 + 18 * S + w2) / S) + 2 * 34
    x0, y0, y1 = (W - ancho) // 2, BORDE, BORDE + PESTANA

    # Máscaras a 4x: tarjeta redondeada y pestaña con empalmes cóncavos
    m_tarjeta = Image.new("L", (W * S, H * S), 0)
    ImageDraw.Draw(m_tarjeta).rounded_rectangle(
        (BORDE * S, BORDE * S, (BORDE + cw) * S - 1, (BORDE + ch) * S - 1), RADIO * S, fill=255)
    m_pestana = Image.new("L", (W * S, H * S), 0)
    d = ImageDraw.Draw(m_pestana)
    c = CURVA * S
    d.rounded_rectangle((x0 * S, (y0 - CURVA) * S, (x0 + ancho) * S, y1 * S), c, fill=255)
    d.rectangle(((x0 - CURVA) * S, y0 * S, x0 * S, y0 * S + c), fill=255)
    d.rectangle(((x0 + ancho) * S, y0 * S, (x0 + ancho + CURVA) * S, y0 * S + c), fill=255)
    d.ellipse(((x0 - 2 * CURVA) * S, y0 * S, x0 * S, y0 * S + 2 * c), fill=0)
    d.ellipse(((x0 + ancho) * S, y0 * S, (x0 + ancho + 2 * CURVA) * S, y0 * S + 2 * c), fill=0)
    m_pestana = ImageChops.multiply(m_pestana, m_tarjeta)  # solo dentro de la tarjeta

    # Contenido de la pestaña a 4x: glifo blanco + nombre + @
    capa = Image.new("RGBA", (W * S, H * S), (255, 255, 255, 0))
    cd = ImageDraw.Draw(capa)
    cy = (y0 + PESTANA / 2 - 2) * S
    x = (x0 + 34) * S
    capa.paste(Image.new("RGBA", glifo.size, (255, 255, 255, 255)), (round(x), round(cy - glifo.height / 2)), glifo)
    x += glifo.width + 16 * S
    cd.text((x, cy), nombre, font=f1, fill=(255, 255, 255, 255), anchor="lm")
    x += w1 + 18 * S
    cd.text((x, cy + S), handle, font=f2, fill=(255, 224, 208, 255), anchor="lm")

    m_tarjeta = m_tarjeta.resize((W, H), Image.LANCZOS)
    m_pestana = m_pestana.resize((W, H), Image.LANCZOS)
    capa = capa.resize((W, H), Image.LANCZOS)

    fondo = _degradado(W, H)
    interior = Image.new("RGB", (W, H), "white")
    interior.paste(tarjeta, (BORDE, BORDE + AIRE))
    # Sombra suave de la pestaña sobre la tarjeta: da profundidad sin parecer una pegatina
    sombra = ImageChops.offset(m_pestana.filter(ImageFilter.GaussianBlur(7)), 0, 4).point(lambda v: int(v * 0.22))
    interior.paste((150, 40, 0), (0, 0), ImageChops.multiply(sombra, m_tarjeta))

    lienzo = fondo.copy()
    lienzo.paste(interior, (0, 0), m_tarjeta)
    lienzo.paste(fondo, (0, 0), m_pestana)
    return Image.alpha_composite(lienzo.convert("RGBA"), capa).convert("RGB")


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
