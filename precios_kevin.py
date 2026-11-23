"""Precios de la tarjeta de @kevincrestt (23/11/2026, Enrique: «pon los datos de Kevin, tenlo en cuenta para las
próximas veces»).

Su texto no trae precios: van solo en la imagen (Precio normal tachado, Precio actual, Ahorro y -%).
Se leen con OCR (tesseract):
- precio actual = la caja naranja bajo «Precio actual» (texto blanco, se lee aparte);
- ahorro = el número que va debajo de «Ahorro»;
- precio normal = actual + ahorro (el normal va tachado y el OCR lo lee mal);
- el -% de la tarjeta tiene que leerse y cuadrar (±1) con esas cuentas; si no, no se usa nada y el vigía sigue
  con los precios de la API de Amazon.
"""
from __future__ import annotations

import io
import re
import urllib.request

PRICE = re.compile(r"(\d{1,4}(?:\.\d{3})*,\d{2})")
PCT = re.compile(r"^-?(\d{1,2})%$")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _num(text: str) -> float:
    return float(text.replace(".", "").replace(",", "."))


def _palabras(im) -> list[dict]:
    import pytesseract
    d = pytesseract.image_to_data(im, lang="spa", output_type=pytesseract.Output.DICT)
    return [{"t": d["text"][i].strip(), "x": d["left"][i], "y": d["top"][i], "w": d["width"][i],
             "h": d["height"][i]} for i in range(len(d["text"])) if d["text"][i].strip()]


def _precio_actual(im, label: dict) -> float | None:
    """El precio actual va en blanco sobre la caja naranja: se recorta la caja bajo «actual» y se lee solo lo blanco."""
    import numpy as np
    import pytesseract
    from PIL import Image
    h = label["h"]
    box = np.array(im.crop((max(0, label["x"] - 4 * h), label["y"] + h, im.width, label["y"] + 7 * h))).astype(int)
    out = Image.fromarray(np.where(box.min(2) > 200, 0, 255).astype("uint8"))
    if out.width < 800:
        out = out.resize((out.width * 3, out.height * 3))
    txt = pytesseract.image_to_string(out, config="--psm 7 -c tessedit_char_whitelist=0123456789,.€")
    m = PRICE.search(txt)
    return _num(m.group(1)) if m else None


def leer_tarjeta(imagen) -> dict | None:
    """imagen: ruta, bytes o PIL.Image. Devuelve {"current", "reference", "ahorro", "pct"} o None si no cuadra."""
    try:
        import pytesseract  # noqa: F401
        from PIL import Image
    except ImportError:
        return None
    if isinstance(imagen, (bytes, bytearray)):
        imagen = Image.open(io.BytesIO(imagen))
    elif not hasattr(imagen, "size"):
        imagen = Image.open(imagen)
    im = imagen.convert("RGB")
    if im.width < 1100:  # la vista web da la foto más pequeña: se amplía para el OCR
        im = im.resize((1200, round(im.height * 1200 / im.width)), Image.LANCZOS)
    try:
        words = _palabras(im)
    except Exception:  # sin tesseract instalado: se sigue con la API
        return None
    actual = next((w for w in words if w["t"].lower() == "actual"), None)
    ahorro_l = next((w for w in words if w["t"].lower().startswith("ahorr")), None)
    if not (actual and ahorro_l):
        return None
    current = _precio_actual(im, actual)
    debajo = [dict(w, v=_num(PRICE.search(w["t"]).group(1))) for w in words if PRICE.search(w["t"])
              and 0 < w["y"] - ahorro_l["y"] < 6 * max(ahorro_l["h"], 12)]
    leido = next((int(PCT.match(w["t"]).group(1)) for w in words if PCT.match(w["t"])), None)
    if not (current and debajo and leido):
        return None
    saving = min(debajo, key=lambda w: w["y"])["v"]
    reference = round(current + saving, 2)
    pct = round(saving / reference * 100)
    if saving <= 0 or abs(leido - pct) > 1:  # el -% de su tarjeta tiene que cuadrar con actual + ahorro
        return None
    return {"current": current, "reference": reference, "ahorro": saving, "pct": pct}


def descargar(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def desde_post(post: dict) -> dict | None:
    """Precios de la tarjeta de un post del vigía (foto de la vista web o descargada con la cuenta)."""
    try:
        if post.get("foto_bytes"):
            data = post["foto_bytes"]()
        elif post.get("foto"):
            data = descargar(post["foto"])
        else:
            return None
        return leer_tarjeta(data) if data else None
    except Exception:
        return None


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(leer_tarjeta(sys.argv[1]), ensure_ascii=False))
