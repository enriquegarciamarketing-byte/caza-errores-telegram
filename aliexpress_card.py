#!/usr/bin/env python3
"""Tarjeta de Caza Chollos para los chollos de AliExpress (1080×1080, JPEG).

- Tonos rojos propios del canal, sin el logo, el degradado ni ningún gráfico de AliExpress
  (el acuerdo de afiliados no deja modificar ni combinar sus logos y gráficos sin permiso por escrito).
- Sin foto del producto: la foto va aparte en el mismo post, tal cual la da AliExpress.
- Antes de guardar se comprueba con textbbox que ningún texto se sale de su caja ni del lienzo.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
LOGO = ROOT / "images" / "logo-caza-chollos.png"
OUTPUT = ROOT / "output" / "aliexpress"

SIZE = 1080
MARGIN = 48
RED = "#D9261C"
RED_DARK = "#B51D14"
TINT = "#FDEDEB"
TINT_LINE = "#F6C8C3"
INK = "#1C1C21"
MUTED = "#6B7078"
PAPER = "#F6F2F1"
WHITE = "#FFFFFF"


class CardOverflow(ValueError):
    pass


def _font(size: int, bold: bool = False):
    paths = (["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"] if bold
             else ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"])
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def euro(amount: float) -> str:
    whole = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{whole} €"


def _trim_white(image: Image.Image, pad: int = 6) -> Image.Image:
    diff = ImageChops.difference(image, Image.new("RGB", image.size, (255, 255, 255))).convert("L")
    box = diff.point(lambda v: 255 if v > 40 else 0).getbbox()
    if not box:
        return image
    return image.crop((max(box[0] - pad, 0), max(box[1] - pad, 0),
                       min(box[2] + pad, image.width), min(box[3] + pad, image.height)))


class _Canvas:
    """Dibuja y apunta cada texto con su caja para validarlo al final."""

    def __init__(self):
        self.img = Image.new("RGB", (SIZE, SIZE), PAPER)
        self.draw = ImageDraw.Draw(self.img)
        self.placed: list[tuple[str, tuple[int, int, int, int], tuple[int, int, int, int]]] = []

    def text(self, xy, text, font, fill, box):
        self.draw.text(xy, text, font=font, fill=fill)
        self.placed.append((text, tuple(int(v) for v in self.draw.textbbox(xy, text, font=font)), tuple(box)))

    def width(self, text, font) -> int:
        b = self.draw.textbbox((0, 0), text, font=font)
        return b[2] - b[0]

    def fit(self, text, size, max_width, bold=True, min_size=20):
        font = _font(size, bold)
        while self.width(text, font) > max_width and size > min_size:
            size -= 2
            font = _font(size, bold)
        return font

    def validate(self):
        for text, bbox, box in self.placed:
            if bbox[0] < 0 or bbox[1] < 0 or bbox[2] > SIZE or bbox[3] > SIZE:
                raise CardOverflow(f"'{text}' se sale del lienzo {bbox}")
            if bbox[0] < box[0] - 1 or bbox[1] < box[1] - 1 or bbox[2] > box[2] + 1 or bbox[3] > box[3] + 1:
                raise CardOverflow(f"'{text}' se sale de su caja {bbox} > {box}")


def _wrap(c: _Canvas, text: str, font, max_width: int, max_lines: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for word in words:
        cand = f"{line} {word}".strip()
        if line and c.width(cand, font) > max_width:
            lines.append(line)
            line = word
        else:
            line = cand
    if line:
        lines.append(line)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and c.width(last + "…", font) > max_width:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        lines[-1] = last.rstrip(" .,-") + "…"
    return lines


def _centered(c: _Canvas, box, text, font, fill, y=None):
    b = c.draw.textbbox((0, 0), text, font=font)
    x = box[0] + (box[2] - box[0] - (b[2] - b[0])) // 2 - b[0]
    if y is None:
        y = box[1] + (box[3] - box[1] - (b[3] - b[1])) // 2 - b[1]
    c.text((x, y), text, font, fill, box)


def _has_chips(deal: dict, price: float) -> bool:
    app = deal.get("app_price")
    return bool((app and float(app) < price - 0.25) or (deal.get("coupon") or {}).get("code"))


def create_card(deal: dict) -> Path:
    """deal: title, price, reference (o None), badge, ref_label, seen_hhmm, app_price, coupon, id."""
    c = _Canvas()
    d = c.draw
    # Tarjeta blanca con una franja roja arriba que sigue las esquinas redondeadas.
    d.rounded_rectangle((24, 24, SIZE - 24, SIZE - 24), radius=34, fill=RED)
    d.rounded_rectangle((24, 40, SIZE - 24, SIZE - 24), radius=34, fill=WHITE)
    d.rectangle((24, 40, SIZE - 24, 80), fill=WHITE)

    # Logo del canal, la única marca de la tarjeta.
    logo_box = (MARGIN, 64, MARGIN + 150, 214)
    with Image.open(LOGO) as src:
        logo = _trim_white(src.convert("RGB"))
        logo.thumbnail((logo_box[2] - logo_box[0], logo_box[3] - logo_box[1]), Image.Resampling.LANCZOS)
        logo = logo.filter(ImageFilter.UnsharpMask(radius=1.2, percent=70, threshold=2))
    c.img.paste(logo, (logo_box[0] + (logo_box[2] - logo_box[0] - logo.width) // 2,
                       logo_box[1] + (logo_box[3] - logo_box[1] - logo.height) // 2))

    badge = str(deal.get("badge") or "CHOLLO")
    bfont = _font(26, True)
    bw = c.width(badge, bfont) + 48
    bbox = (SIZE - MARGIN - bw, 104, SIZE - MARGIN, 168)
    d.rounded_rectangle(bbox, radius=30, fill=RED)
    _centered(c, bbox, badge, bfont, WHITE)

    store_box = (MARGIN, 236, SIZE - MARGIN, 270)
    c.text((MARGIN, 236), "EN ALIEXPRESS", _font(24, True), RED, store_box)

    tfont = _font(40, True)
    title_lines = _wrap(c, str(deal["title"]), tfont, SIZE - 2 * MARGIN, 3)
    for i, line in enumerate(title_lines):
        y = 284 + i * 52
        c.text((MARGIN, y), line, tfont, INK, (MARGIN, y, SIZE - MARGIN, y + 52))
    top = 284 + len(title_lines) * 52 + 28

    price = float(deal["price"])
    reference = deal.get("reference")
    if reference and float(reference) > price + 0.009:
        reference = float(reference)
        half = (SIZE - 2 * MARGIN - 24) // 2
        old = (MARGIN, top, MARGIN + half, top + 200)
        new = (MARGIN + half + 24, top, SIZE - MARGIN, top + 200)
        d.rounded_rectangle(old, radius=24, fill="#F4F4F5", outline="#E6E6E8", width=2)
        d.rounded_rectangle(new, radius=24, fill=TINT, outline=TINT_LINE, width=2)
        label = str(deal.get("ref_label") or "MÍNIMO 30 DÍAS ANTES")
        lfont = c.fit(label, 22, half - 48)
        c.text((old[0] + 24, top + 24), label, lfont, MUTED, old)
        ofont = c.fit(euro(reference), 50, half - 48)
        pos = (old[0] + 24, top + 86)
        c.text(pos, euro(reference), ofont, MUTED, old)
        ob = d.textbbox(pos, euro(reference), font=ofont)
        sy = (ob[1] + ob[3]) // 2
        d.line((ob[0] - 2, sy, ob[2] + 2, sy), fill=MUTED, width=4)
        c.text((new[0] + 24, top + 24), "PRECIO ACTUAL", _font(22, True), MUTED, new)
        pfont = c.fit(euro(price), 68, half - 48)
        c.text((new[0] + 24, top + 78), euro(price), pfont, RED, new)

        pct = round((reference - price) / reference * 100)
        disc = (MARGIN, top + 224, SIZE - MARGIN, top + 224 + 190)
        d.rounded_rectangle(disc, radius=26, fill=INK)
        _centered(c, disc, f"-{pct} %", _font(92, True), "#FF5A4E", y=disc[1] + 18)
        sub = str(deal.get("discount_label") or "frente a su precio más bajo de los 30 días anteriores")
        sfont = c.fit(sub, 26, disc[2] - disc[0] - 48, bold=False)
        _centered(c, disc, sub, sfont, WHITE, y=disc[1] + 136)
        bottom = disc[3]
    else:
        # Sin precio de referencia fiable: un solo panel grande que llena el hueco hasta el pie.
        note = str(deal.get("note") or "")
        reserve = (80 if note else 0) + (78 if _has_chips(deal, price) else 0)
        height = max(250, SIZE - 120 - top - reserve)
        panel = (MARGIN, top, SIZE - MARGIN, top + height)
        d.rounded_rectangle(panel, radius=26, fill=TINT, outline=TINT_LINE, width=2)
        c.text((panel[0] + 32, top + 28), "PRECIO", _font(24, True), MUTED, panel)
        pfont = c.fit(euro(price), 130, panel[2] - panel[0] - 64)
        pb = d.textbbox((0, 0), euro(price), font=pfont)
        py = top + 60 + (height - 60 - (pb[3] - pb[1])) // 2 - pb[1]
        c.text((panel[0] + 32, py), euro(price), pfont, RED, panel)
        bottom = panel[3]
        if note:
            nbox = (MARGIN, bottom + 22, SIZE - MARGIN, bottom + 80)
            c.text((MARGIN + 6, bottom + 30), note, c.fit(note, 28, SIZE - 2 * MARGIN - 12), INK, nbox)
            bottom = nbox[3]

    chips = []
    if deal.get("app_price") and float(deal["app_price"]) < price - 0.25:
        chips.append(f"EN LA APP {euro(float(deal['app_price']))}")
    coupon = deal.get("coupon") or {}
    if coupon.get("code"):
        chips.append(f"CUPÓN {coupon['code']}")
    x = MARGIN
    cy = bottom + 24
    cfont = _font(24, True)
    for chip in chips:
        w = c.width(chip, cfont) + 40
        if x + w > SIZE - MARGIN:
            break
        box = (x, cy, x + w, cy + 54)
        d.rounded_rectangle(box, radius=27, fill=WHITE, outline=RED, width=3)
        _centered(c, box, chip, cfont, RED_DARK)
        x += w + 16

    foot = f"Precio a las {deal.get('seen_hhmm') or '--:--'} · puede cambiar · Enlace de afiliado"
    fbox = (MARGIN, SIZE - 96, SIZE - MARGIN, SIZE - 52)
    c.text((MARGIN, SIZE - 92), foot, c.fit(foot, 24, SIZE - 2 * MARGIN, bold=False), MUTED, fbox)

    c.validate()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    out = OUTPUT / f"ae-{deal.get('id') or 'tarjeta'}.jpg"
    c.img.save(out, format="JPEG", quality=95, subsampling=0, optimize=True)
    return out
