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


def _background(c: Card, kind: str):
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

    if kind == "discount":
        red([(586, 236), (640, 236), (888, 86), (888, 52)], 0.25, (255, 160, 150))
        red([(650, 236), (742, 236), (888, 148), (888, 96)])
        red([(760, 8), (888, 8), (888, 84)], color=RED_TOP)
        red([(700, 888), (744, 888), (888, 746), (888, 706)], 0.5, PINK)
        red([(758, 888), (888, 888), (888, 758)])
    else:
        red([(770, 8), (888, 8), (888, 120)], 0.45, PINK)
        red([(806, 8), (888, 8), (888, 82)])
        red([(640, 888), (690, 888), (888, 742), (888, 702)], 0.5, PINK)
        red([(700, 888), (888, 888), (888, 762)])


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


def _price_text(c: Card, x, cy, price: float, size: float, color, box, shadow=None, max_w=None):
    """Precio con el símbolo del euro algo más pequeño, como en la referencia."""
    num = euro(price)[:-2]
    tr = -1.2

    def fonts(sz):
        return font(900, sz, True), font(900, sz * 0.86, True)

    f, fe = fonts(size)
    if max_w:
        while c.tw(num, f, tr) + 6 + c.tw("€", fe) > max_w and size > 30:
            size -= 1
            f, fe = fonts(size)
    if shadow:
        c.text((x + 1.5, cy + 2.5), num, f, shadow, box, anchor="lm", tracking=tr)
    b = c.text((x, cy), num, f, color, box, anchor="lm", tracking=tr)
    ex = b[2] + size * 0.12
    if shadow:
        c.text((ex + 1.5, cy + 2.5 + size * 0.04), "€", fe, shadow, box, anchor="lm")
    c.text((ex, cy + size * 0.04), "€", fe, color, box, anchor="lm")
    return size


# ---------------------------------------------------------------- bloques
def _old_card(c: Card, reference: float, label: str):
    box = (42, 372, 400, 478)
    m = c.mask_rr(box, 22)
    c.shadow(m, blur=6, dy=3, alpha=0.16)
    c.gradient_fill(m, box, [(0, (247, 247, 248)), (1, (233, 233, 236))])
    c.outline_rr(box, 22, (255, 255, 255), 1.5)
    c.text((70, 408), label, c.fit(820, label, 22.5, 310), GREY_TEXT, box)
    f = c.fit(900, euro(reference), 56, 310, italic=True, tracking=-1)
    b = c.text((66, 460), euro(reference), f, GREY_PRICE, box, tracking=-1)
    c.draw.line([p(b[0] - 3), p(b[3] - 10), p(b[2] + 8), p(b[1] + 20)], fill=RED, width=p(3.2))


def _red_panel(c: Card, price: float):
    shape = [(42, 497), (266, 497), (288, 512), (452, 512), (458, 632), (42, 632)]
    box = (42, 497, 458, 632)
    m = c.mask_poly(shape, 15)
    c.shadow(m, blur=8, dy=6, alpha=0.35, color=(130, 0, 0))
    c.gradient_fill(m, box, [(0, (255, 52, 40)), (0.45, (234, 22, 14)), (1, (188, 6, 2))])
    c.gloss(m, (42, 497, 458, 560), 0.16, 0.6)
    c.text((70, 530), "PRECIO ACTUAL", font(880, 23.5), WHITE, box)
    _price_text(c, 72, 584, price, 98, WHITE, box, shadow=(150, 4, 0), max_w=372)


def _discount_bar(c: Card, pct: int):
    box = (35, 655, 858, 766)
    m = c.mask_rr(box, 26)
    c.shadow(m, blur=9, dy=6, alpha=0.35)
    # Borde rojo fino, como en la referencia.
    c.fill(c.mask_rr((33, 653, 860, 768), 27), (200, 20, 14), 0.85)
    c.gradient_fill(c.mask_rr((35, 655, 857, 765), 26), box,
                    [(0, (46, 46, 52)), (0.5, (22, 22, 26)), (1, (8, 8, 10))])
    c.gloss(c.mask_rr((37, 657, 855, 763), 25), box, 0.08, 0.42)
    cy = 712
    chevron(c, 84, cy, 40, (255, 34, 24))
    b = c.text((136, cy + 2), f"-{pct} %", font(900, 86, True), WHITE, box, anchor="lm", tracking=-1.5)
    sep = max(415, b[2] + 40)
    c.draw.line([p(sep), p(cy - 32), p(sep), p(cy + 32)], fill=WHITE, width=p(2.2))
    tx = sep + 38
    f = c.fit(500, "frente a su precio más bajo", 28.5, 858 - tx - 24)
    fb = font(800, f.size / S)
    c.text((tx, cy - 16), "frente a su precio más bajo", f, WHITE, box, anchor="lm")
    b1 = c.text((tx, cy + 18), "de los", f, WHITE, box, anchor="lm")
    b2 = c.text((b1[2] + c.tw(" ", f), cy + 18), "30 días", fb, (255, 36, 26), box, anchor="lm")
    c.text((b2[2] + c.tw(" ", f), cy + 18), "anteriores", f, WHITE, box, anchor="lm")


def _chips(c: Card, deal: dict, price: float, top: float) -> bool:
    chips = []
    app = deal.get("app_price")
    if app and float(app) < price - 0.25:
        chips.append(("app", "EN LA APP", euro(float(app))))
    coupon = deal.get("coupon") or {}
    if coupon.get("code"):
        chips.append(("cupon", "CUPÓN", str(coupon["code"])))
    if not chips:
        return False
    f1, f2 = font(820, 25.5), font(900, 25.5)
    widths = [76 + c.tw(a + " ", f1) + c.tw(b, f2) + 34 for _, a, b in chips]
    gap = 24
    x = (W - (sum(widths) + gap * (len(widths) - 1))) / 2
    for (kind, a, b), w in zip(chips, widths):
        box = (x, top, x + w, top + 54)
        m = c.mask_rr(box, 27)
        c.shadow(m, blur=5, dy=3, alpha=0.14)
        c.fill(m, WHITE)
        c.outline_rr(box, 27, RED, 2.4)
        cy = top + 27
        if kind == "app":
            phone(c, x + 42, cy, 30)
        else:
            ticket(c, x + 42, cy, 26)
        tb = c.text((x + 76, cy + 1), a, f1, INK, box, anchor="lm")
        c.text((tb[2] + c.tw(" ", f1), cy + 1), b, f2, RED_TEXT, box, anchor="lm")
        x += w + gap
    return True


def _footer(c: Card, deal: dict, y: float):
    text = f"Precio a las {deal.get('seen_hhmm') or '--:--'} · puede cambiar · Enlace de afiliado"
    f = c.fit(500, text, 21.5, 620)
    total = 32 + c.tw(text, f)
    x = (W - total) / 2 - 20
    clock(c, x + 12, y, 12, (92, 95, 102))
    c.text((x + 32, y + 1), text, f, (88, 91, 98), (x, y - 20, x + total + 10, y + 20), anchor="lm")


def _top_layout(c: Card, deal: dict, price: float):
    # Círculo rosa y destellos de la referencia (sin el producto).
    disc = Image.new("L", c.img.size, 0)
    ImageDraw.Draw(disc).ellipse([p(492), p(228), p(892), p(628)], fill=255)
    disc = ImageChops.multiply(disc.filter(ImageFilter.GaussianBlur(p(3))), c.mask_rr(CARD, 40))
    tint = Image.new("RGB", c.img.size, (251, 226, 226))
    tint.paste(vgrad((DRAW, p(400)), [(0, (252, 232, 232)), (1, (248, 214, 214))]), (0, p(228)))
    c.fill(disc, tint, 0.42)
    for a, b in [((779, 213), (786, 175)), ((796, 222), (822, 191)), ((806, 236), (836, 220))]:
        c.draw.line([p(a[0]), p(a[1]), p(b[0]), p(b[1])], fill=RED, width=p(8))
        for q in (a, b):
            c.draw.ellipse([p(q[0] - 4), p(q[1] - 4), p(q[0] + 4), p(q[1] + 4)], fill=RED)

    panel = (55, 458, 492, 636)
    m = c.mask_rr(panel, 20)
    c.shadow(m, blur=8, dy=5, alpha=0.16)
    c.gradient_fill(m, panel, [(0, WHITE), (1, (250, 247, 247))])
    c.outline_rr(panel, 20, RED, 2.6)
    tab_shape = [(55, 430), (238, 430), (272, 474), (55, 474)]
    tm = c.mask_poly(tab_shape, 12)
    c.shadow(tm, blur=5, dy=3, alpha=0.25, color=(120, 0, 0))
    c.gradient_fill(tm, (55, 430, 272, 474), [(0, (255, 52, 40)), (1, (200, 10, 4))])
    c.gloss(tm, (55, 430, 272, 474), 0.16, 0.5)
    c.text((90, 465), "PRECIO", font(850, 30), WHITE, (55, 430, 272, 474))
    _price_text(c, 84, 556, price, 116, RED_TEXT, panel, shadow=(150, 6, 2), max_w=388)

    note = (105, 683, 820, 757)
    nm = c.mask_rr(note, 22)
    c.shadow(nm, blur=6, dy=3, alpha=0.14)
    c.gradient_fill(nm, note, [(0, (251, 251, 252)), (1, (240, 240, 243))])
    c.outline_rr(note, 22, (232, 232, 236), 1.2)
    t1, t2 = "De lo más vendido en", "AliExpress"
    f = c.fit(850, t1 + " " + t2, 31, 560)
    total = 70 + c.tw(t1 + " " + t2, f)
    x = (note[0] + note[2] - total) / 2
    medal(c, x + 22, 716, 50)
    b = c.text((x + 70, 721), t1, f, INK, note, anchor="lm")
    c.text((b[2] + c.tw(" ", f), 721), t2, f, RED_TEXT, note, anchor="lm")
    if _chips(c, deal, price, 772):
        _footer(c, deal, 852)
    else:
        _footer(c, deal, 807)


def _discount_layout(c: Card, deal: dict, price: float, reference: float):
    _old_card(c, reference, str(deal.get("ref_label") or "MÍNIMO 30 DÍAS ANTES"))
    _red_panel(c, price)
    _discount_bar(c, round((reference - price) / reference * 100))
    if not _chips(c, deal, price, 788):
        _footer(c, deal, 815)


def _has_reference(deal: dict) -> bool:
    ref = deal.get("reference")
    return bool(ref) and float(ref) > float(deal["price"]) + 0.009


def create_card(deal: dict) -> Path:
    """deal: title, price, reference (o None), badge, ref_label, seen_hhmm, app_price, coupon, id."""
    c = Card()
    price = float(deal["price"])
    discount = _has_reference(deal)
    _background(c, "discount" if discount else "top")
    badge = str(deal.get("badge") or ("CHOLLO" if discount else "TOP VENTAS"))
    _header(c, badge, 42 if discount else 40)
    if discount:
        _title(c, str(deal["title"]), 45, 250, 545, 40, 1.08)
        _discount_layout(c, deal, price, float(deal["reference"]))
    else:
        _title(c, str(deal["title"]), 56, 274, 505, 45, 1.21)
        _top_layout(c, deal, price)
    c.validate()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    out = OUTPUT / f"ae-{deal.get('id') or 'tarjeta'}.jpg"
    c.img.resize((OUT, OUT), Image.Resampling.LANCZOS).save(out, format="JPEG", quality=95, subsampling=0,
                                                            optimize=True)
    return out
