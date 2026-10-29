"""Foto lo más nítida posible para la tarjeta del canal normal, sin servicios de pago."""

from __future__ import annotations

import io
import re
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent
MODEL_DIR = Path.home() / ".cache" / "caza-chollos" / "models"
FSRCNN_URL = "https://github.com/Saafke/FSRCNN_Tensorflow/raw/master/models/FSRCNN_x4.pb"
FSRCNN_NAME = "FSRCNN_x4.pb"
USER_AGENT = "CazaChollosBot/1.0 (https://t.me/cazachollos_com)"
_SR = None


def source_candidates(url: str) -> list[str]:
    """Variantes de mayor resolución, y al final la URL original."""
    raw = (url or "").strip()
    if not raw:
        return []
    ordered: list[str] = []

    def add(candidate: str) -> None:
        if candidate and candidate not in ordered:
            ordered.append(candidate)

    if re.search(r"/re/\d+x\d+/qt/\d+/", raw):
        # La miniatura de Chollometro vive en /re/150x150/. El archivo sin ese tramo es el original.
        add(re.sub(r"/re/\d+x\d+/qt/\d+/", "/", raw))
        add(re.sub(r"/re/\d+x\d+/qt/\d+/", "/re/1024x1024/qt/75/", raw))
    if "amazon." in raw or "media-amazon." in raw or "ssl-images-amazon." in raw:
        add(re.sub(r"\._[^.]+_\.", ".", raw))
    if "wikimedia.org" in raw or "wikipedia.org" in raw:
        bumped = re.sub(r"/\d+px-", "/1600px-", raw)
        if "Special:FilePath" in bumped and "width=" not in bumped:
            bumped += ("&" if "?" in bumped else "?") + "width=1600"
        add(bumped)
    add(raw)
    return ordered


def _download(url: str, timeout: int = 25) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*,*/*"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
            kind = (response.headers.get("content-type") or "").lower()
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    if "text/html" in kind or not data or data[:1] == b"<":
        return None
    return data


def _min_side(data: bytes) -> int:
    try:
        with Image.open(io.BytesIO(data)) as image:
            return min(image.size)
    except (OSError, ValueError):
        return 0


def fetch_best(url: str, timeout: int = 25) -> bytes | None:
    """Descarga la variante más grande que responda. Para en cuanto pasa de ~900 px."""
    best = None
    best_side = 0
    for candidate in source_candidates(url):
        data = _download(candidate, timeout=timeout)
        if not data:
            continue
        side = _min_side(data)
        if side > best_side:
            best, best_side = data, side
        if side >= 900:
            break
    return best


def looks_like_collage(image: Image.Image) -> bool:
    """Captura de la tienda: varias cajas, flechas de carrusel o un marco gris.

    Una foto de producto sobre fondo blanco es un solo bloque y no se descarta.
    """
    rgb = image.convert("RGB")
    width, height = rgb.size
    if width < 64 or height < 64:
        return False
    sample_w = 160
    sample_h = max(48, int(round(height * (sample_w / width))))
    small = rgb.resize((sample_w, sample_h), Image.Resampling.BOX)
    px = small.load()

    def channel(x: int, y: int) -> tuple[int, int, int]:
        pixel = px[x, y]
        return int(pixel[0]), int(pixel[1]), int(pixel[2])

    def background(x: int, y: int) -> bool:
        red, green, blue = channel(x, y)
        return abs(red - green) < 12 and abs(green - blue) < 12 and red >= 226

    def gray_border(x: int, y: int) -> bool:
        red, green, blue = channel(x, y)
        return abs(red - green) < 14 and abs(green - blue) < 14 and 145 <= red <= 220

    ring_hits = 0
    ring_total = 0
    for x in range(sample_w):
        for y in (0, 1, sample_h - 2, sample_h - 1):
            if 0 <= y < sample_h:
                ring_total += 1
                ring_hits += gray_border(x, y)
    for y in range(sample_h):
        for x in (0, 1, sample_w - 2, sample_w - 1):
            ring_total += 1
            ring_hits += gray_border(x, y)
    gray_frame = bool(ring_total) and ring_hits / ring_total >= 0.55

    def side_arrow(x0: int, x1: int) -> bool:
        y0, y1 = int(sample_h * 0.32), int(sample_h * 0.68)
        dark = white = total = 0
        for y in range(y0, y1):
            for x in range(max(0, x0), min(sample_w, x1)):
                total += 1
                red, green, blue = channel(x, y)
                if red < 70 and green < 70 and blue < 70:
                    dark += 1
                elif red > 230 and green > 230 and blue > 230:
                    white += 1
        return total > 0 and 8 <= dark <= total * 0.4 and white >= total * 0.4

    margin = max(4, int(sample_w * 0.07))
    arrows = side_arrow(0, margin) and side_arrow(sample_w - margin, sample_w)

    seen = bytearray(sample_w * sample_h)
    blobs = 0
    area_floor = sample_w * sample_h * 0.02
    for y in range(sample_h):
        for x in range(sample_w):
            start = y * sample_w + x
            if seen[start] or background(x, y):
                continue
            stack = [(x, y)]
            seen[start] = 1
            area = 0
            min_x = max_x = x
            min_y = max_y = y
            while stack:
                cx, cy = stack.pop()
                area += 1
                min_x = min(min_x, cx)
                max_x = max(max_x, cx)
                min_y = min(min_y, cy)
                max_y = max(max_y, cy)
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if nx < 0 or ny < 0 or nx >= sample_w or ny >= sample_h:
                        continue
                    slot = ny * sample_w + nx
                    if seen[slot] or background(nx, ny):
                        continue
                    seen[slot] = 1
                    stack.append((nx, ny))
            wide = (max_x - min_x) > sample_w * 0.12 and (max_y - min_y) > sample_h * 0.06
            if area >= area_floor and wide:
                blobs += 1

    gutters = 0
    in_gap = False
    y_start, y_end = int(sample_h * 0.12), int(sample_h * 0.88)
    x_start, x_end = int(sample_w * 0.1), int(sample_w * 0.9)
    span = max(1, x_end - x_start)
    for y in range(y_start, y_end):
        row = sum(background(x, y) for x in range(x_start, x_end))
        if row / span >= 0.94:
            if not in_gap:
                gutters += 1
                in_gap = True
        else:
            in_gap = False
    return bool(gray_frame or arrows or blobs >= 3 or (blobs >= 2 and gutters >= 2))


def image_ok(data: bytes) -> bool:
    """Foto usable: no es un icono ni una captura con varias cajas."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if min(image.size) < 120:
                return False
            return not looks_like_collage(image)
    except (OSError, ValueError):
        return False


def fetch_clean(urls: list[str], timeout: int = 25) -> bytes | None:
    """Primera foto válida, en el orden pedido. Descarta capturas y collages."""
    seen: set[str] = set()
    tried = 0
    for url in urls:
        if tried >= 8:
            break
        for candidate in source_candidates(url):
            if candidate in seen:
                continue
            seen.add(candidate)
            tried += 1
            data = _download(candidate, timeout=timeout)
            if data and image_ok(data):
                return data
            if tried >= 8:
                break
    return None


def _model_path() -> Path | None:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    path = MODEL_DIR / FSRCNN_NAME
    if path.exists() and path.stat().st_size > 1000:
        return path
    data = _download(FSRCNN_URL, timeout=40)
    if not data or len(data) < 1000:
        return None
    path.write_bytes(data)
    return path


def _neural(image: Image.Image) -> Image.Image | None:
    """FSRCNN x4 en CPU. None si OpenCV o el modelo no están."""
    global _SR
    try:
        import cv2
    except ImportError:
        return None
    if not hasattr(cv2, "dnn_superres"):
        return None
    model = _model_path()
    if model is None:
        return None
    try:
        if _SR is None:
            engine = cv2.dnn_superres.DnnSuperResImpl_create()
            engine.readModel(str(model))
            engine.setModel("fsrcnn", 4)
            _SR = engine
        import numpy as np
        array = np.array(image.convert("RGB"))
        out = _SR.upsample(array[:, :, ::-1])
        return Image.fromarray(out[:, :, ::-1])
    except Exception:
        return None


def _unsharp(image: Image.Image) -> Image.Image:
    return image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=70, threshold=2))


def upscale(image: Image.Image, factor: float) -> Image.Image:
    """Amplía hasta `factor`. Una pasada neuronal x4 como máximo; el resto, Lanczos."""
    target = (max(1, int(round(image.width * factor))), max(1, int(round(image.height * factor))))
    if factor < 1.08:
        return image
    neural = _neural(image) if factor >= 1.7 and image.width * image.height <= 600 * 600 else None
    base = neural if neural is not None else image
    if base.size != target:
        base = base.resize(target, Image.Resampling.LANCZOS)
    return _unsharp(base)


def fit_for_panel(image: Image.Image, panel_w: int, panel_h: int, *, cover: bool = False) -> Image.Image:
    """Si no llega al hueco del panel, amplía. Si ya sobra, no toca la foto."""
    if panel_w < 1 or panel_h < 1 or image.width < 1 or image.height < 1:
        return image
    factor = max(panel_w / image.width, panel_h / image.height) if cover else min(panel_w / image.width, panel_h / image.height)
    if factor <= 1.08:
        return image
    return upscale(image, factor)
