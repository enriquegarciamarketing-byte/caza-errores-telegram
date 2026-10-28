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
