"""Imagen del resumen de la noche (26/11/2026): el top 5 de chollos del día con la misma línea gráfica que las
tarjetas (marco naranja con la pestaña del canal, fuente Figtree, píldora de precio con el degradado de la marca).

Sin fotos de Amazon: las normas de afiliados no dejan componerlas en un collage, y ya salen en cada post.
Se dibuja todo a 2x y se reduce para que el texto y las curvas salgan finos."""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import marco_canal as mc

DARK, GREY, LIGHT, BORDER = (26, 26, 26), (130, 130, 130), (247, 246, 242), (232, 230, 226)
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def _eur(v: float) -> str:
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + "€"


def _titulo(t: str) -> str:
    t = re.sub(r"\s*[\(\[].*?[\)\]]", "", t or "")
    t = re.split(r"\s[-–|,]\s|,\s", t)[0]
    return re.sub(r"\s+", " ", t).strip()


def _lineas(d: ImageDraw.ImageDraw, texto: str, font, ancho: float, maximo: int) -> list[str]:
    palabras, lineas, linea = texto.split(), [], ""
    for p in palabras:
        prueba = f"{linea} {p}".strip()
        if d.textlength(prueba, font=font) <= ancho:
            linea = prueba
        else:
            if linea:
                lineas.append(linea)
            linea = p
    if linea:
        lineas.append(linea)
    if len(lineas) > maximo:
        lineas = lineas[:maximo]
        while d.textlength(lineas[-1] + "…", font=font) > ancho and " " in lineas[-1]:
            lineas[-1] = lineas[-1].rsplit(" ", 1)[0]
        lineas[-1] = lineas[-1].rstrip(".,;:-") + "…"
    return lineas


def crear_resumen(items: list[dict], now: datetime, out: Path, canal: str = "cazachollos",
                  maximo: int = 5) -> Path | None:
    picked = [i for i in items if i.get("price") is not None][:maximo]
    if len(picked) < 2:
        return None
    S = 2                      # supermuestreo
    W, H = 2160, 1160          # tamaño final del contenido (sin marco)
    u = W / 1000 * S
    im = Image.new("RGB", (W * S, H * S), "white")
    d = ImageDraw.Draw(im)
    f = mc._font

    # Cabecera
    mx = 46 * u
    d.text((mx, 40 * u), "TOP 5 DE HOY" if len(picked) == 5 else f"TOP {len(picked)} DE HOY",
           font=f(round(40 * u), b"Black"), fill=DARK, anchor="lm")
    d.text((mx, 74 * u), "Los chollos más bestias del día, aún activos", font=f(round(19 * u), b"Medium"),
           fill=GREY, anchor="lm")
    fecha = now.strftime("%d ") + MESES[now.month - 1]
    fb = f(round(20 * u), b"ExtraBold")
    tw = d.textlength(fecha, font=fb)
    d.rounded_rectangle((1000 * u / 1 - mx - tw - 36 * u, 38 * u, 1000 * u - mx, 76 * u), 19 * u,
                        outline=mc.NARANJA, width=round(2.5 * u))
    d.text((1000 * u - mx - 18 * u - tw / 2, 57.5 * u), fecha, font=fb, fill=mc.NARANJA, anchor="mm")

    # Columnas
    n = len(picked)
    gap = 14 * u
    top, bottom = 104 * u, 486 * u
    cw = (1000 * u - 2 * mx - (n - 1) * gap) / n
    sombra = Image.new("L", im.size, 0)
    sd = ImageDraw.Draw(sombra)
    for i in range(n):
        x0 = mx + i * (cw + gap)
        sd.rounded_rectangle((x0, top + 6 * u, x0 + cw, bottom + 6 * u), 22 * u, fill=36)
    im.paste((90, 90, 90), (0, 0), sombra.filter(ImageFilter.GaussianBlur(10 * u)))
    d = ImageDraw.Draw(im)
    for i, item in enumerate(picked):
        x0 = mx + i * (cw + gap)
        x1, cx = x0 + cw, x0 + cw / 2
        d.rounded_rectangle((x0, top, x1, bottom), 22 * u, fill="white", outline=BORDER, width=round(1.5 * u))
        # Posición y descuento
        r = 19 * u
        d.ellipse((x0 + 18 * u, top + 18 * u, x0 + 18 * u + 2 * r, top + 18 * u + 2 * r), fill=DARK)
        d.text((x0 + 18 * u + r, top + 18 * u + r + 1 * u), str(i + 1), font=f(round(21 * u), b"Black"),
               fill="white", anchor="mm")
        if item.get("discount"):
            pct = f"-{round(float(item['discount']))}%"
            fp = f(round(22 * u), b"ExtraBold")
            pw = d.textlength(pct, font=fp) + 26 * u
            d.rounded_rectangle((x1 - 18 * u - pw, top + 18 * u, x1 - 18 * u, top + 18 * u + 2 * r), r,
                                fill=mc.NARANJA)
            d.text((x1 - 18 * u - pw / 2, top + 18 * u + r + 1 * u), pct, font=fp, fill="white", anchor="mm")
        # Nombre del producto
        ft = f(round(19 * u), b"Bold")
        y = top + 90 * u
        for linea in _lineas(d, _titulo(item.get("title") or ""), ft, cw - 36 * u, 4):
            d.text((cx, y), linea, font=ft, fill=DARK, anchor="mm")
            y += 25 * u
        # Precio de antes tachado y píldora con el de hoy, alineados abajo
        if item.get("reference"):
            fa = f(round(24 * u), b"ExtraBold")
            antes = _eur(float(item["reference"]))
            aw = d.textlength(antes, font=fa)
            ya = bottom - 104 * u
            d.text((cx, ya), antes, font=fa, fill=(110, 110, 110), anchor="mm")
            d.line((cx - aw / 2 - 3 * u, ya + 1 * u, cx + aw / 2 + 3 * u, ya + 1 * u), fill=(80, 80, 80),
                   width=round(3 * u))
        ph = 62 * u
        px0, px1, py0 = x0 + 16 * u, x1 - 16 * u, bottom - 16 * u - ph
        pill = mc._degradado(round(px1 - px0), round(ph))
        mk = Image.new("L", pill.size, 0)
        ImageDraw.Draw(mk).rounded_rectangle((0, 0, pill.width - 1, pill.height - 1), ph / 2, fill=255)
        im.paste(pill, (round(px0), round(py0)), mk)
        precio = _eur(float(item["price"]))
        size = round(38 * u)
        while f(size, b"Black").getlength(precio) > (px1 - px0) - 30 * u:
            size -= 2
        d.text(((px0 + px1) / 2, py0 + ph / 2 + 2 * u), precio, font=f(size, b"Black"), fill="white", anchor="mm")

    # Pie
    fy = 515 * u
    d.text((mx, fy), f"Precios a las {now.strftime('%H:%M')} · pueden cambiar", font=f(round(17 * u), b"Medium"),
           fill=GREY, anchor="lm")
    fm = f(round(19 * u), b"ExtraBold")
    texto = "Mañana a las 7:00 más chollos"
    d.text((1000 * u - mx, fy), texto, font=fm, fill=mc.NARANJA, anchor="rm")

    im = im.resize((W, H), Image.LANCZOS)
    final = mc.enmarcar_canal(im, canal)
    return mc.guardar(final, out, quality=95)


if __name__ == "__main__":
    ejemplo = [
        {"title": "Ring Videotimbre 2K con batería y Cámara interior", "price": 49.99, "reference": 149.98,
         "discount": 67},
        {"title": "Cecotec Cepillo moldeador de pelo con aire AirGlisse 8in1", "price": 59.00, "reference": 124.90,
         "discount": 53},
        {"title": "JBL Auriculares Tune 520 BT, inalámbricos por Bluetooth", "price": 29.99, "reference": 59.99,
         "discount": 50},
        {"title": "Logitech M705 Marathon Ratón inalámbrico", "price": 24.69, "reference": 44.99, "discount": 45},
        {"title": "Blink Outdoor 4 Cámara con Blink Mini 2K+ gratis", "price": 24.99, "reference": 124.98,
         "discount": 80},
    ]
    import sys
    from zoneinfo import ZoneInfo
    ahora = datetime(2026, 11, 25, 23, 59, tzinfo=ZoneInfo("Europe/Madrid"))
    canal = sys.argv[2] if len(sys.argv) > 2 else "cazachollos"
    print(crear_resumen(ejemplo, ahora, Path(sys.argv[1]), canal))
