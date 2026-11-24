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


# ------------------------------------------------------------------ canales con los precios en el texto

# 25/11/2026 (Enrique): ErroresRutaYChollos no lleva tarjeta, sus precios van en el texto del post:
#   «💶 31,54 € ~~78,99 €~~», «💶 19,95 € PVP ~~79,95 €~~» o solo «💶 9,44 €», y a veces «📉 Precio habitual: 78,99 €».
PRECIO_TXT = re.compile(r"(\d{1,4}(?:\.\d{3})*,\d{2})\s*€")
PCT_TXT = re.compile(r"-\s?(\d{1,2})\s?%")


def leer_tarjeta_ruta(imagen) -> dict | None:
    """25/11/2026: tarjeta de ErroresRutaYChollos (@RutaYCapital): «19,95 €», «Precio real estos meses: 53,73 €» y
    «te ahorras 33,78 €». Solo vale si cuadra: real - ahorro = actual (±0,02). Devuelve como leer_tarjeta o None."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return None
    if isinstance(imagen, (bytes, bytearray)):
        imagen = Image.open(io.BytesIO(imagen))
    elif not hasattr(imagen, "size"):
        imagen = Image.open(imagen)
    im = imagen.convert("RGB")
    if im.width < 1000:  # la vista web da la foto más pequeña
        im = im.resize((1000, round(im.height * 1000 / im.width)), Image.LANCZOS)
    zona = im.crop((int(im.width * 0.42), 0, im.width, int(im.height * 0.42)))  # bloque de precios, sin la gráfica
    try:
        txt = pytesseract.image_to_string(zona, lang="spa", config="--psm 6")
    except Exception:
        return None
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    real = next((l for l in lines if re.search(r"precio (real|habitual)", l, re.I) and PRICE.search(l)), None)
    ahorro = next((l for l in lines if re.search(r"ahorr", l, re.I) and PRICE.search(l)), None)
    actual = next((l for l in lines if PRICE.search(l) and l not in (real, ahorro)), None)
    if not (real and ahorro and actual):
        return None
    reference, saving, current = (_num(PRICE.search(x).group(1)) for x in (real, ahorro, actual))
    if saving <= 0 or abs(reference - saving - current) > 0.02:
        return None
    pct = round(saving / reference * 100)
    leido = next((int(m.group(1)) for l in lines for m in [re.search(r"(\d{1,2})\s?%", l)] if m), None)
    if leido is not None and abs(leido - pct) > 1:
        return None
    return {"current": current, "reference": reference, "ahorro": saving, "pct": pct, "ref_label": "habitual"}


def desde_post_ruta(post: dict) -> dict | None:
    """Precios de la tarjeta de un post de ErroresRutaYChollos (foto de la vista web o de la cuenta)."""
    try:
        if post.get("foto_bytes"):
            data = post["foto_bytes"]()
        elif post.get("foto"):
            data = descargar(post["foto"])
        else:
            return None
        return leer_tarjeta_ruta(data) if data else None
    except Exception:
        return None


def desde_texto(texto: str) -> dict | None:
    """Precios del texto del post: {"current", "reference" (o None), "pct", "ref_label"} o None si no hay 💶."""
    lines = [l.strip() for l in (texto or "").splitlines() if l.strip()]
    linea = next((l for l in lines if "💶" in l), None)
    if not linea:
        return None
    precios = [_num(x) for x in PRECIO_TXT.findall(linea)]
    if not precios or precios[0] <= 0:
        return None
    current, reference = precios[0], None
    label = "recomendado" if re.search(r"\bPVP\b", linea, re.I) else "normal"
    if len(precios) > 1 and precios[1] > current:
        reference = precios[1]
    else:
        habitual = next((l for l in lines if re.search(r"precio habitual", l, re.I)), "")
        h = PRECIO_TXT.search(habitual)
        if h and _num(h.group(1)) > current:
            reference, label = _num(h.group(1)), "habitual"
    pct = round((reference - current) / reference * 100) if reference else None
    leido = next((int(m.group(1)) for l in lines[:2] for m in [PCT_TXT.search(l)] if m), None)
    if pct is not None and leido is not None and abs(leido - pct) > 1:  # su -% tiene que cuadrar
        return None
    return {"current": current, "reference": reference, "pct": pct, "ref_label": label}


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(leer_tarjeta(sys.argv[1]), ensure_ascii=False))
