#!/usr/bin/env python3
"""Tarjeta de Caza Chollos para los chollos de AliExpress (1280×1280, JPEG).

Calca el diseño de referencia de Enrique (rojo con brillo) quitando las fotos de producto:
cabecera con el logo del canal, separador y «EN ALIEXPRESS» en texto, etiqueta roja con icono,
título con los datos clave en rojo, tarjeta gris con el mínimo de 30 días tachado, panel rojo con
pestaña para el precio, barra negra con el descuento, píldoras de app y cupón, y las esquinas rojas.

- Sin el logo ni gráficos de AliExpress (cláusulas 8.2 a 8.4 del acuerdo): el nombre va solo como texto.
- Sin foto del producto: la foto va aparte en el mismo post, tal cual la da AliExpress.
- Las medidas están en píxeles de la referencia (lienzo de 896). Se dibuja a 2560 y se reduce a 1280.
- Antes de guardar se comprueba con textbbox que ningún texto se sale de su caja ni del lienzo.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
LOGO = ROOT / "images" / "logo-caza-chollos.png"
FONTS = ROOT / "fonts"
OUTPUT = ROOT / "output" / "aliexpress"

W = 896                 # lienzo de diseño (píxeles de la referencia)
DRAW = 2560             # tamaño al que se dibuja
OUT = 1280              # tamaño final
S = DRAW / W

RED = (232, 20, 14)
RED_TOP = (255, 58, 44)
RED_BOTTOM = (190, 8, 4)
RED_TEXT = (226, 18, 12)
INK = (28, 28, 30)
GREY_TEXT = (84, 87, 94)
GREY_PRICE = (92, 95, 102)
WHITE = (255, 255, 255)
PINK = (250, 214, 212)

SPEC = re.compile(
    r"(?i)\bbluetooth\s?\d(?:\.\d)?\b|\b(?:wi-?fi\s?\d+|[48]k|5g)\b|"
    r"\b\d+(?:[.,]\d+)?\s?(?:pa|mah|wh|w|gb|tb|hz|mp|mm|cm|km|kg|ml|l|v|°c|pulgadas|\")(?![a-z0-9])")


class CardOverflow(ValueError):
    pass


_fonts: dict = {}


def font(weight: int, size: float, italic: bool = False):
    """Figtree variable (300-900). Si falta, DejaVu."""
    key = (weight, round(size * S), italic)
    if key not in _fonts:
        path = FONTS / ("Figtree-Italic[wght].ttf" if italic else "Figtree[wght].ttf")
        try:
            f = ImageFont.truetype(str(path), round(size * S))
            f.set_variation_by_axes([weight])
        except (OSError, ValueError):
            f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", round(size * S * 0.92))
        _fonts[key] = f
    return _fonts[key]


def euro(amount: float) -> str:
    whole = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{whole} €"


def p(v: float) -> int:
    return int(round(v * S))


def pts(points) -> list:
    return [(v[0] * S, v[1] * S) for v in points]


def vgrad(size, stops) -> Image.Image:
    """Degradado vertical con varias paradas [(0..1, rgb), ...]."""
    w, h = size
    col = Image.new("RGB", (1, max(h, 1)))
    px = col.load()
    for y in range(max(h, 1)):
        t = y / max(h - 1, 1)
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                k = (t - t0) / max(t1 - t0, 1e-6)
                px[0, y] = tuple(int(c0[i] + (c1[i] - c0[i]) * k) for i in range(3))
                break
    return col.resize((max(w, 1), max(h, 1)))


def rounded_poly_mask(size, points, radius) -> Image.Image:
    """Máscara de un polígono con las esquinas redondeadas (desenfoque y umbral)."""
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).polygon(points, fill=255)
    if radius > 0:
        r = max(1, int(radius))
        m = m.filter(ImageFilter.GaussianBlur(r)).point(lambda v: 255 if v > 127 else 0)
        m = m.filter(ImageFilter.GaussianBlur(1.2))
    return m


class Card:
    def __init__(self):
        self.img = Image.new("RGB", (DRAW, DRAW), (236, 236, 239))
        self.draw = ImageDraw.Draw(self.img)
        self.placed: list[tuple[str, tuple, tuple]] = []

    # ---------------------------------------------------------------- relleno con máscara
    def fill(self, mask: Image.Image, color_or_img, alpha: float = 1.0):
        if alpha < 1:
            mask = mask.point(lambda v: int(v * alpha))
        src = color_or_img if isinstance(color_or_img, Image.Image) else Image.new("RGB", self.img.size, color_or_img)
        self.img.paste(src, (0, 0), mask)

    def mask_rr(self, box, radius) -> Image.Image:
        m = Image.new("L", self.img.size, 0)
        ImageDraw.Draw(m).rounded_rectangle([p(v) for v in box], radius=p(radius), fill=255)
        return m

    def mask_poly(self, points, radius=0) -> Image.Image:
        return rounded_poly_mask(self.img.size, pts(points), radius * S)

    def shadow(self, mask: Image.Image, blur=10, dy=6, alpha=0.28, color=(0, 0, 0)):
        sh = ImageChops.offset(mask, 0, p(dy)).filter(ImageFilter.GaussianBlur(p(blur)))
        self.fill(sh, color, alpha)

    def gradient_fill(self, mask: Image.Image, box, stops):
        x0, y0, x1, y1 = [p(v) for v in box]
        layer = Image.new("RGB", self.img.size, WHITE)
        layer.paste(vgrad((x1 - x0, y1 - y0), stops), (x0, y0))
        self.fill(mask, layer)

    def gloss(self, mask: Image.Image, box, strength=0.22, height=0.46):
        x0, y0, x1, y1 = [p(v) for v in box]
        g = Image.new("L", self.img.size, 0)
        ImageDraw.Draw(g).rectangle((x0, y0, x1, y0 + int((y1 - y0) * height)), fill=255)
        g = g.filter(ImageFilter.GaussianBlur(p(5)))
        self.fill(ImageChops.multiply(g, mask), WHITE, strength)

    def outline_rr(self, box, radius, color, width):
        self.draw.rounded_rectangle([p(v) for v in box], radius=p(radius), outline=color, width=max(1, p(width)))

    # ---------------------------------------------------------------- texto
    def text(self, xy, text, f, fill, box, anchor="ls", tracking=0.0):
        x, y = p(xy[0]), p(xy[1])
        if tracking:
            first = last = None
            for ch in text:
                self.draw.text((x, y), ch, font=f, fill=fill, anchor=anchor)
                b = self.draw.textbbox((x, y), ch, font=f, anchor=anchor)
                if ch.strip():
                    first = first or b
                    last = b
                x += self.draw.textlength(ch, font=f) + tracking * S
            bbox = (first[0], min(first[1], last[1]), last[2], max(first[3], last[3]))
        else:
            self.draw.text((x, y), text, font=f, fill=fill, anchor=anchor)
            bbox = self.draw.textbbox((x, y), text, font=f, anchor=anchor)
        self.placed.append((text, tuple(v / S for v in bbox), tuple(box)))
        return tuple(v / S for v in bbox)

    def tw(self, text, f, tracking=0.0) -> float:
        return (self.draw.textlength(text, font=f) + tracking * S * len(text)) / S

    def fit(self, weight, text, size, max_w, italic=False, tracking=0.0, min_size=14):
        while size > min_size and self.tw(text, font(weight, size, italic), tracking) > max_w:
            size -= 0.5
        return font(weight, size, italic)

    def validate(self):
        for text, bb, box in self.placed:
            if bb[0] < 0 or bb[1] < 0 or bb[2] > W or bb[3] > W:
                raise CardOverflow(f"'{text}' se sale del lienzo {bb}")
            if bb[0] < box[0] - 1 or bb[1] < box[1] - 1 or bb[2] > box[2] + 1 or bb[3] > box[3] + 1:
                raise CardOverflow(f"'{text}' se sale de su caja {tuple(round(v) for v in bb)} > {box}")


# ---------------------------------------------------------------- iconos (vectoriales, sin emojis)
def flame(c: Card, cx, cy, h, color):
    w = h * 0.78
    outer = [(0.52, 0.00), (0.62, 0.15), (0.78, 0.30), (0.92, 0.48), (0.98, 0.66), (0.93, 0.83), (0.78, 0.96),
             (0.58, 1.00), (0.40, 1.00), (0.20, 0.95), (0.06, 0.82), (0.02, 0.64), (0.10, 0.46), (0.22, 0.34),
             (0.30, 0.50), (0.38, 0.30), (0.46, 0.14)]
    inner = [(0.53, 0.44), (0.66, 0.60), (0.73, 0.76), (0.66, 0.90), (0.50, 0.95), (0.34, 0.90), (0.29, 0.76),
             (0.36, 0.62), (0.45, 0.56)]
    tr = lambda q: [(cx - w / 2 + x * w, cy - h / 2 + y * h) for x, y in q]
    c.fill(c.mask_poly(tr(outer), 1.2), color)
    c.fill(c.mask_poly(tr(inner), 1.0), RED)


def star(c: Card, cx, cy, r, color, inner=0.46):
    q = [(cx + (r if i % 2 == 0 else r * inner) * math.cos(math.radians(-90 + 36 * i)),
          cy + (r if i % 2 == 0 else r * inner) * math.sin(math.radians(-90 + 36 * i))) for i in range(10)]
    c.fill(c.mask_poly(q, 1.0), color)


def warning(c: Card, cx, cy, s, color):
    c.fill(c.mask_poly([(cx, cy - s * 0.55), (cx + s * 0.6, cy + s * 0.48), (cx - s * 0.6, cy + s * 0.48)], 2),
           color)
    c.draw.rounded_rectangle([p(cx - s * 0.07), p(cy - s * 0.22), p(cx + s * 0.07), p(cy + s * 0.16)],
                             radius=p(1.5), fill=RED)
    c.draw.ellipse([p(cx - s * 0.08), p(cy + s * 0.23), p(cx + s * 0.08), p(cy + s * 0.38)], fill=RED)


def phone(c: Card, cx, cy, h):
    w = h * 0.58
    c.draw.rounded_rectangle([p(cx - w / 2), p(cy - h / 2), p(cx + w / 2), p(cy + h / 2)], radius=p(h * 0.14),
                             outline=(52, 54, 58), width=p(2.2))
    c.draw.rounded_rectangle([p(cx - w / 2 + 3.2), p(cy - h / 2 + 5), p(cx + w / 2 - 3.2), p(cy + h / 2 - 7)],
                             radius=p(1.5), fill=(150, 170, 150))
    c.draw.rounded_rectangle([p(cx - w / 2 + 4.2), p(cy - h / 2 + 6), p(cx + w / 2 - 4.2), p(cy - h / 2 + 13)],
                             radius=p(1), fill=(105, 185, 120))
    c.draw.ellipse([p(cx - 1.6), p(cy + h / 2 - 5.2), p(cx + 1.6), p(cy + h / 2 - 2)], fill=(52, 54, 58))


def ticket(c: Card, cx, cy, s):
    big = Image.new("L", (p(s * 1.8), p(s * 1.8)), 0)
    d = ImageDraw.Draw(big)
    w, h = p(s * 1.25), p(s * 0.72)
    x0, y0 = (big.width - w) // 2, (big.height - h) // 2
    d.rounded_rectangle((x0, y0, x0 + w, y0 + h), radius=p(s * 0.12), fill=255)
    r = p(s * 0.15)
    for x in (x0, x0 + w):
        d.ellipse((x - r, y0 + h // 2 - r, x + r, y0 + h // 2 + r), fill=0)
    for i in range(3):
        yy = y0 + int(h * (0.3 + i * 0.2))
        d.rectangle((x0 + int(w * 0.62) - p(1.1), yy - p(1.7), x0 + int(w * 0.62) + p(1.1), yy + p(1.7)), fill=0)
    big = big.rotate(38, resample=Image.Resampling.BICUBIC)
    m = Image.new("L", c.img.size, 0)
    m.paste(big, (p(cx) - big.width // 2, p(cy) - big.height // 2))
    c.fill(m, RED)


def clock(c: Card, cx, cy, r, color):
    c.draw.ellipse([p(cx - r), p(cy - r), p(cx + r), p(cy + r)], outline=color, width=p(2.2))
    c.draw.line([p(cx), p(cy), p(cx), p(cy - r * 0.58)], fill=color, width=p(2.2))
    c.draw.line([p(cx), p(cy), p(cx + r * 0.45), p(cy + r * 0.2)], fill=color, width=p(2.2))


def medal(c: Card, cx, cy, s):
    for sign in (-1, 1):
        c.fill(c.mask_poly([(cx + sign * s * 0.16, cy + s * 0.18), (cx + sign * s * 0.42, cy + s * 0.12),
                            (cx + sign * s * 0.5, cy + s * 0.82), (cx + sign * s * 0.36, cy + s * 0.68),
                            (cx + sign * s * 0.2, cy + s * 0.76)], 1), RED_BOTTOM)
    c.draw.ellipse([p(cx - s * 0.46), p(cy - s * 0.46), p(cx + s * 0.46), p(cy + s * 0.46)], fill=RED)
    c.draw.ellipse([p(cx - s * 0.33), p(cy - s * 0.33), p(cx + s * 0.33), p(cy + s * 0.33)],
                   outline=WHITE, width=p(2.4))
    star(c, cx, cy, s * 0.2, WHITE)


def chevron(c: Card, x, cy, h, color):
    """Flecha «>» gruesa con puntas redondeadas."""
    w = h * 0.26
    pts_ = [(x + w / 2, cy - h / 2 + w / 2), (x + h * 0.52, cy), (x + w / 2, cy + h / 2 - w / 2)]
    c.draw.line([(p(a), p(b)) for a, b in pts_], fill=color, width=p(w), joint="curve")
    for a, b in (pts_[0], pts_[2]):
        c.draw.ellipse([p(a - w / 2), p(b - w / 2), p(a + w / 2), p(b + w / 2)], fill=color)


# ---------------------------------------------------------------- fondo, cabecera y título
def _trim_white(image: Image.Image, pad: int = 4) -> Image.Image:
    diff = ImageChops.difference(image, Image.new("RGB", image.size, (255, 255, 255))).convert("L")
    box = diff.point(lambda v: 255 if v > 40 else 0).getbbox()
    if not box:
        return image
    return image.crop((max(box[0] - pad, 0), max(box[1] - pad, 0),
                       min(box[2] + pad, image.width), min(box[3] + pad, image.height)))


CARD = (8, 8, 888, 888)


def _background(c: Card):
    card = c.mask_rr(CARD, 40)
    c.shadow(card, blur=9, dy=3, alpha=0.22)
    # Blanco con un viñeteado gris muy suave hacia los bordes.
    base = Image.new("RGB", c.img.size, (244, 244, 246))
    glow = Image.new("L", c.img.size, 0)
    ImageDraw.Draw(glow).ellipse([p(-120), p(-140), p(820), p(860)], fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(p(120)))
    base.paste(WHITE, (0, 0), glow)
    c.fill(card, base)
    # Raya diagonal gris muy suave.
    streak = c.mask_poly([(430, 8), (520, 8), (888, 520), (888, 650)], 0)
    c.fill(ImageChops.multiply(streak.filter(ImageFilter.GaussianBlur(p(30))), card), (236, 236, 239), 0.55)

    def red(points, alpha=1.0, color=None):
        m = ImageChops.multiply(c.mask_poly(points, 0), card)
        if color:
            c.fill(m, color, alpha)
            return
        layer = vgrad((DRAW, DRAW), [(0, RED_TOP), (0.5, RED), (1, RED_BOTTOM)])
        c.fill(m, layer, alpha)

    # Arriba solo por encima del título (que va a todo el ancho); abajo, la esquina roja de la referencia.
    red([(600, 196), (650, 196), (888, 40), (888, 8), (880, 8)], 0.25, (255, 160, 150))
    red([(662, 196), (742, 196), (888, 100), (888, 48)])
    red([(760, 8), (888, 8), (888, 84)], color=RED_TOP)
    red([(700, 888), (744, 888), (888, 746), (888, 706)], 0.5, PINK)
    red([(758, 888), (888, 888), (888, 758)])


def _header(c: Card, badge: str, badge_top: float):
    with Image.open(LOGO) as src:
        logo = _trim_white(src.convert("RGB"))
        side = p(166)
        logo.thumbnail((side, side), Image.Resampling.LANCZOS)
    c.img.paste(logo, (p(50) + (side - logo.width) // 2, p(32) + (side - logo.height) // 2))
    c.draw.line([p(243), p(50), p(243), p(180)], fill=(42, 42, 46), width=p(2.4))
    box = (262, 70, 640, 140)
    long_badge = len(badge) > 12
    hs = 34 if long_badge else 40
    b = c.text((270, 117 - (40 - hs) * 0.35), "EN", font(600, hs), INK, box)
    hb = c.text((b[2] + c.tw(" ", font(600, hs)), 117 - (40 - hs) * 0.35), "ALIEXPRESS", font(860, hs), RED_TEXT, box)

    icon = 30
    pad = 50 if long_badge else 62
    bf = c.fit(850, badge, 30, (866 - (hb[2] + 26)) - icon - pad)
    bw = c.tw(badge, bf) + icon + pad
    pill = (866 - bw, badge_top, 866, badge_top + 68)
    if pill[0] < hb[2] + 18:
        raise CardOverflow("la etiqueta pisa la cabecera")
    outer = c.mask_rr((pill[0] - 3, pill[1] - 3, pill[2] + 3, pill[3] + 3), 37)
    c.shadow(outer, blur=7, dy=5, alpha=0.32, color=(120, 0, 0))
    c.fill(outer, WHITE)
    m = c.mask_rr(pill, 34)
    c.gradient_fill(m, pill, [(0, RED_TOP), (0.55, RED), (1, RED_BOTTOM)])
    c.gloss(m, pill, 0.2)
    cy = (pill[1] + pill[3]) / 2
    tb = c.text((pill[0] + pad * 0.45, cy), badge, bf, WHITE, pill, anchor="lm")
    ix = tb[2] + 10 + icon / 2
    if badge == "TOP VENTAS":
        star(c, ix, cy, 15, WHITE)
    elif badge == "ERROR DE PRECIO":
        warning(c, ix, cy, 30, WHITE)
    else:
        flame(c, ix, cy, 30, WHITE)


def _title(c: Card, title: str, x: float, first_baseline: float, max_w: float, size: float, lh_ratio: float,
           max_lines: int = 3) -> float:
    spans = [(m.start(), m.end()) for m in SPEC.finditer(title)]
    # Los datos clave («20000 mAh») no se parten entre líneas.
    chars = list(title)
    for a, b in spans:
        for i in range(a, b):
            if chars[i] == " ":
                chars[i] = "\u00a0"
    title = "".join(chars)
    words, pos = [], 0
    for word in title.split(" "):
        if not word:
            pos += 1
            continue
        start = title.index(word, pos)
        pos = start + len(word)
        words.append((word, any(a <= start and pos <= b for a, b in spans)))
    while True:
        f = font(760, size)
        space = c.tw(" ", f)
        lines, line, width = [], [], 0.0
        for word, hot in words:
            w = c.tw(word.replace("\u00a0", " "), f)
            if line and width + space + w > max_w:
                lines.append(line)
                line, width = [], 0.0
            width += (space if line else 0) + w
            line.append((word, hot))
        if line:
            lines.append(line)
        if len(lines) <= max_lines or size <= 28:
            break
        size -= 1
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while len(last) > 1 and c.tw(" ".join(w for w, _ in last) + "…", f) > max_w:
            last = last[:-1]
        lines[-1] = last[:-1] + [(last[-1][0].rstrip(".,-") + "…", last[-1][1])]
    lh = size * lh_ratio
    for i, line in enumerate(lines):
        y = first_baseline + i * lh
        box = (x - 2, y - size * 1.05, x + max_w + 4, y + size * 0.32)
        cx = x
        for j, (word, hot) in enumerate(line):
            b = c.text((cx, y), word.replace("\u00a0", " "), f, RED_TEXT if hot else INK, box)
            cx = b[2] + c.tw(" ", f)
    return first_baseline + (len(lines) - 1) * lh


def _price_text(c: Card, x, cy, price: float, size: float, color, box, shadow=None, max_w=None, center=False):
    """Precio en cursiva gruesa con el símbolo del euro algo más pequeño, como en la referencia."""
    num = euro(price)[:-2]
    tr = -1.2

    def fonts(sz):
        return font(900, sz, True), font(900, sz * 0.86, True)

    def width(sz):
        f, fe = fonts(sz)
        return c.tw(num, f, tr) + sz * 0.12 + c.tw("€", fe)

    if max_w:
        while width(size) > max_w and size > 30:
            size -= 1
    f, fe = fonts(size)
    if center:
        x = x - width(size) / 2
    if shadow:
        c.text((x + 1.5, cy + 2.5), num, f, shadow, box, anchor="lm", tracking=tr)
    b = c.text((x, cy), num, f, color, box, anchor="lm", tracking=tr)
    ex = b[2] + size * 0.12
    if shadow:
        c.text((ex + 1.5, cy + 2.5 + size * 0.04), "€", fe, shadow, box, anchor="lm")
    c.text((ex, cy + size * 0.04), "€", fe, color, box, anchor="lm")
    return size


# ---------------------------------------------------------------- bloques (todo a medida de su caja)
L, R = 42, 854          # márgenes de contenido


def _old_card(c: Card, box, reference: float, label: str):
    x0, y0, x1, y1 = box
    m = c.mask_rr(box, 24)
    c.shadow(m, blur=6, dy=3, alpha=0.16)
    c.gradient_fill(m, box, [(0, (247, 247, 248)), (1, (233, 233, 236))])
    c.outline_rr(box, 24, (255, 255, 255), 1.5)
    h = y1 - y0
    lf = c.fit(820, label, 22.5, x1 - x0 - 50)
    pf = c.fit(900, euro(reference), min(64, h * 0.36), x1 - x0 - 52, italic=True, tracking=-1)
    block = 22 + 16 + pf.size / S * 0.72
    top = y0 + (h - block) / 2
    c.text((x0 + 26, top + 18), label, lf, GREY_TEXT, box)
    b = c.text((x0 + 24, top + 38 + pf.size / S * 0.72), euro(reference), pf, GREY_PRICE, box, tracking=-1)
    c.draw.line([p(b[0] - 3), p(b[3] - (b[3] - b[1]) * 0.25), p(b[2] + 8), p(b[1] + (b[3] - b[1]) * 0.42)],
                fill=RED, width=p(3.4))


def _red_panel(c: Card, box, price: float):
    x0, y0, x1, y1 = box
    tab_w = 232
    shape = [(x0, y0), (x0 + tab_w, y0), (x0 + tab_w + 22, y0 + 16), (x1, y0 + 16), (x1 + 4, y1), (x0, y1)]
    m = c.mask_poly(shape, 15)
    c.shadow(m, blur=9, dy=7, alpha=0.35, color=(130, 0, 0))
    c.gradient_fill(m, box, [(0, (255, 52, 40)), (0.45, (234, 22, 14)), (1, (186, 6, 2))])
    c.gloss(m, (x0, y0, x1, y0 + (y1 - y0) * 0.5), 0.16, 0.7)
    c.text((x0 + 28, y0 + 34), "PRECIO ACTUAL", font(880, 24), WHITE, box)
    h = y1 - y0
    _price_text(c, x0 + 28, y0 + 34 + (h - 34) / 2 + 4, price, min(150, (h - 40) * 0.82), WHITE, box,
                shadow=(150, 4, 0), max_w=x1 - x0 - 56)


def _discount_bar(c: Card, box, pct: int):
    x0, y0, x1, y1 = box
    m = c.mask_rr(box, 26)
    c.shadow(m, blur=9, dy=6, alpha=0.35)
    c.fill(c.mask_rr((x0 - 2, y0 - 2, x1 + 2, y1 + 2), 27), (200, 20, 14), 0.85)
    c.gradient_fill(c.mask_rr((x0, y0, x1 - 1, y1 - 1), 26), box,
                    [(0, (46, 46, 52)), (0.5, (22, 22, 26)), (1, (8, 8, 10))])
    c.gloss(c.mask_rr((x0 + 2, y0 + 2, x1 - 3, y1 - 3), 25), box, 0.08, 0.42)
    cy = (y0 + y1) / 2
    chevron(c, x0 + 46, cy, 40, (255, 34, 24))
    size = min(92, (y1 - y0) * 0.74)
    b = c.text((x0 + 100, cy + 2), f"-{pct} %", font(900, size, True), WHITE, box, anchor="lm", tracking=-1.5)
    sep = max(x0 + 380, b[2] + 40)
    c.draw.line([p(sep), p(cy - 34), p(sep), p(cy + 34)], fill=WHITE, width=p(2.2))
    tx = sep + 40
    f = c.fit(500, "frente a su precio más bajo", 30, x1 - tx - 28)
    fb = font(800, f.size / S)
    c.text((tx, cy - 17), "frente a su precio más bajo", f, WHITE, box, anchor="lm")
    b1 = c.text((tx, cy + 19), "de los", f, WHITE, box, anchor="lm")
    b2 = c.text((b1[2] + c.tw(" ", f), cy + 19), "30 días", fb, (255, 36, 26), box, anchor="lm")
    c.text((b2[2] + c.tw(" ", f), cy + 19), "anteriores", f, WHITE, box, anchor="lm")


def _chip_list(deal: dict, price: float) -> list:
    chips = []
    app = deal.get("app_price")
    if app and float(app) < price - 0.25:
        chips.append(("app", "EN LA APP", euro(float(app))))
    coupon = deal.get("coupon") or {}
    if coupon.get("code"):
        chips.append(("cupon", "CUPÓN", str(coupon["code"])))
    return chips


def _chips(c: Card, chips: list, top: float, height: float = 58):
    f1, f2 = font(820, 26), font(900, 26)
    widths = [80 + c.tw(a + " ", f1) + c.tw(b, f2) + 38 for _, a, b in chips]
    gap = 26
    if len(chips) == 1:
        widths = [max(widths[0], 380)]
    x = (W - (sum(widths) + gap * (len(widths) - 1))) / 2
    for (kind, a, b), w in zip(chips, widths):
        box = (x, top, x + w, top + height)
        m = c.mask_rr(box, height / 2)
        c.shadow(m, blur=5, dy=3, alpha=0.14)
        c.fill(m, WHITE)
        c.outline_rr(box, height / 2, RED, 2.4)
        cy = top + height / 2
        inner = 80 + c.tw(a + " ", f1) + c.tw(b, f2) + 38
        ox = x + (w - inner) / 2
        if kind == "app":
            phone(c, ox + 44, cy, 32)
        else:
            ticket(c, ox + 44, cy, 27)
        tb = c.text((ox + 80, cy + 1), a, f1, INK, box, anchor="lm")
        c.text((tb[2] + c.tw(" ", f1), cy + 1), b, f2, RED_TEXT, box, anchor="lm")
        x += w + gap


def _footer(c: Card, deal: dict, y: float):
    text = f"Precio a las {deal.get('seen_hhmm') or '--:--'} · puede cambiar · Enlace de afiliado"
    f = c.fit(500, text, 22, 640)
    total = 32 + c.tw(text, f)
    x = (W - total) / 2 - 20
    clock(c, x + 12, y, 12, (92, 95, 102))
    c.text((x + 32, y + 1), text, f, (88, 91, 98), (x, y - 20, x + total + 10, y + 20), anchor="lm")


def _price_box(c: Card, box, price: float):
    """TOP VENTAS: pestaña PRECIO y panel blanco con borde rojo a todo el ancho, precio centrado."""
    x0, y0, x1, y1 = box
    panel = (x0, y0 + 30, x1, y1)
    m = c.mask_rr(panel, 22)
    c.shadow(m, blur=8, dy=5, alpha=0.16)
    c.gradient_fill(m, panel, [(0, WHITE), (1, (250, 246, 246))])
    c.outline_rr(panel, 22, RED, 2.8)
    tab = [(x0, y0), (x0 + 190, y0), (x0 + 226, y0 + 46), (x0, y0 + 46)]
    tm = c.mask_poly(tab, 12)
    c.shadow(tm, blur=5, dy=3, alpha=0.25, color=(120, 0, 0))
    c.gradient_fill(tm, (x0, y0, x0 + 226, y0 + 46), [(0, (255, 52, 40)), (1, (200, 10, 4))])
    c.gloss(tm, (x0, y0, x0 + 226, y0 + 46), 0.16, 0.5)
    c.text((x0 + 32, y0 + 36), "PRECIO", font(850, 30), WHITE, (x0, y0, x0 + 226, y0 + 46))
    # Destellos rojos de la referencia, ahora junto a la esquina del precio.
    sx, sy = x0 + 240, y0 + 18
    for a, b in [((sx, sy - 6), (sx + 4, sy - 36)), ((sx + 14, sy), (sx + 34, sy - 24)),
                 ((sx + 22, sy + 12), (sx + 50, sy + 2))]:
        c.draw.line([p(a[0]), p(a[1]), p(b[0]), p(b[1])], fill=RED, width=p(7))
        for q in (a, b):
            c.draw.ellipse([p(q[0] - 3.5), p(q[1] - 3.5), p(q[0] + 3.5), p(q[1] + 3.5)], fill=RED)
    h = y1 - y0 - 30
    _price_text(c, (x0 + x1) / 2, y0 + 30 + h / 2 + 8, price, min(190, h * 0.7), RED_TEXT, panel,
                shadow=(150, 6, 2), max_w=x1 - x0 - 90, center=True)


def _note(c: Card, box):
    x0, y0, x1, y1 = box
    nm = c.mask_rr(box, 24)
    c.shadow(nm, blur=6, dy=3, alpha=0.14)
    c.gradient_fill(nm, box, [(0, (251, 251, 252)), (1, (240, 240, 243))])
    c.outline_rr(box, 24, (232, 232, 236), 1.2)
    t1, t2 = "De lo más vendido en", "AliExpress"
    f = c.fit(850, t1 + " " + t2, 33, x1 - x0 - 140)
    total = 74 + c.tw(t1 + " " + t2, f)
    x = (x0 + x1 - total) / 2
    cy = (y0 + y1) / 2
    medal(c, x + 24, cy - 4, 54)
    b = c.text((x + 74, cy + 3), t1, f, INK, box, anchor="lm")
    c.text((b[2] + c.tw(" ", f), cy + 3), t2, f, RED_TEXT, box, anchor="lm")


def _has_reference(deal: dict) -> bool:
    ref = deal.get("reference")
    return bool(ref) and float(ref) > float(deal["price"]) + 0.009


def _stack(start: float, end: float, items: list, flex: int, max_extra: float, gap_min=26, gap_max=48):
    """Reparte la altura libre: primero crece el bloque principal (flex), luego los huecos por igual.
    items: [(clave, altura base)] → {clave: (y0, y1)}"""
    base = sum(h for _, h in items)
    free = end - start - base - gap_min * (len(items) - 1)
    extra = max(0.0, min(max_extra, free))
    heights = [h + (extra if i == flex else 0) for i, (_, h) in enumerate(items)]
    rest = end - start - sum(heights)
    gap = min(gap_max, rest / max(len(items) - 1, 1))
    top = start + (rest - gap * (len(items) - 1)) / 2
    out = {}
    for (key, _), h in zip(items, heights):
        out[key] = (top, top + h)
        top += h + gap
    return out


def create_card(deal: dict) -> Path:
    """deal: title, price, reference (o None), badge, ref_label, seen_hhmm, app_price, coupon, id."""
    c = Card()
    price = float(deal["price"])
    discount = _has_reference(deal)
    _background(c)
    badge = str(deal.get("badge") or ("CHOLLO" if discount else "TOP VENTAS"))
    _header(c, badge, 42)
    title_bottom = _title(c, str(deal["title"]), L + 4, 262, R - L - 8, 46, 1.12) + 16
    chips = _chip_list(deal, price)
    footer_y = 852
    end = footer_y - 40
    if discount:
        items = [("row", 170), ("bar", 124)] + ([("chips", 58)] if chips else [])
        lay = _stack(title_bottom + 10, end, items, 0, 70)
        y0, y1 = lay["row"]
        _old_card(c, (L, y0 + 16, 340, y1), float(deal["reference"]),
                  str(deal.get("ref_label") or "MÍNIMO 30 DÍAS ANTES"))
        _red_panel(c, (362, y0, R, y1), price)
        _discount_bar(c, (L - 7, lay["bar"][0], R + 4, lay["bar"][1]), round((float(deal["reference"]) - price)
                                                                            / float(deal["reference"]) * 100))
        if chips:
            _chips(c, chips, lay["chips"][0])
    else:
        items = [("price", 220), ("note", 80)] + ([("chips", 58)] if chips else [])
        lay = _stack(title_bottom + 34, end, items, 0, 110)
        _price_box(c, (L, lay["price"][0], R, lay["price"][1]), price)
        _note(c, (L + 40, lay["note"][0], R - 40, lay["note"][1]))
        if chips:
            _chips(c, chips, lay["chips"][0])
    _footer(c, deal, footer_y)
    c.validate()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    out = OUTPUT / f"ae-{deal.get('id') or 'tarjeta'}.jpg"
    c.img.resize((OUT, OUT), Image.Resampling.LANCZOS).save(out, format="JPEG", quality=95, subsampling=0,
                                                            optimize=True)
    return out
