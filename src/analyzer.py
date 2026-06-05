"""Genera thumbnails y calcula color dominante de una imagen."""
from __future__ import annotations

import colorsys
import hashlib
import io
from pathlib import Path

import requests
from PIL import Image, ImageOps

from src.config import HTTP_HEADERS, REQUEST_TIMEOUT, THUMB_QUALITY, THUMB_SIZE, THUMBS_DIR

THUMBS_DIR.mkdir(parents=True, exist_ok=True)


def hash_id(source: str, key: str) -> str:
    """ID estable para una foto, sirve de nombre de archivo del thumb."""
    h = hashlib.md5(f"{source}:{key}".encode("utf-8")).hexdigest()[:16]
    return f"{source}_{h}"


def descargar_imagen(url: str) -> Image.Image | None:
    try:
        r = requests.get(url, headers=HTTP_HEADERS, timeout=REQUEST_TIMEOUT, stream=True)
        if r.status_code != 200:
            return None
        img = Image.open(io.BytesIO(r.content))
        img = ImageOps.exif_transpose(img)
        return img.convert("RGB")
    except Exception:
        return None


def generar_thumb(img: Image.Image, dest: Path) -> bool:
    try:
        thumb = img.copy()
        thumb.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
        thumb.save(dest, "JPEG", quality=THUMB_QUALITY, optimize=True)
        return True
    except Exception:
        return False


def color_dominante(img: Image.Image) -> tuple[int, int, int]:
    """Color medio recortando el 10% de los bordes (suele eliminar marcos blancos)."""
    w, h = img.size
    crop = img.crop((int(w * 0.1), int(h * 0.1), int(w * 0.9), int(h * 0.9)))
    small = crop.resize((50, 50))
    pixels = list(small.getdata())
    r = sum(p[0] for p in pixels) // len(pixels)
    g = sum(p[1] for p in pixels) // len(pixels)
    b = sum(p[2] for p in pixels) // len(pixels)
    return (r, g, b)


def rgb_a_hsv(rgb: tuple[int, int, int]) -> tuple[float, float, float]:
    r, g, b = [c / 255 for c in rgb]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return (h * 360, s, v)


def nombre_tono(hsv: tuple[float, float, float]) -> str:
    h, s, v = hsv
    if v < 0.15:
        return "Negro"
    if v > 0.92 and s < 0.08:
        return "Blanco"
    if s < 0.12:
        if v < 0.4:
            return "Gris oscuro"
        if v < 0.75:
            return "Gris"
        return "Gris claro"
    if h < 15 or h >= 345:
        return "Rojo" if v > 0.4 else "Bordó"
    if h < 40:
        if v > 0.7 and s < 0.5:
            return "Beige"
        return "Naranja" if s > 0.4 else "Marrón claro"
    if h < 65:
        return "Amarillo" if v > 0.5 else "Mostaza"
    if h < 80:
        return "Marrón" if v < 0.5 else "Beige"
    if h < 170:
        return "Verde"
    if h < 200:
        return "Cian"
    if h < 260:
        return "Azul"
    if h < 290:
        return "Violeta"
    return "Rosa"


def procesar(url_o_path: str, foto_id: str) -> dict | None:
    """Descarga (si es URL), genera thumb y calcula color. Retorna metadata."""
    if url_o_path.startswith("http"):
        img = descargar_imagen(url_o_path)
    else:
        try:
            img = ImageOps.exif_transpose(Image.open(url_o_path)).convert("RGB")
        except Exception:
            img = None
    if img is None:
        return None

    thumb_path = THUMBS_DIR / f"{foto_id}.jpg"
    if not generar_thumb(img, thumb_path):
        return None

    rgb = color_dominante(img)
    hsv = rgb_a_hsv(rgb)
    tono = nombre_tono(hsv)

    return {
        "thumb_path": str(thumb_path.relative_to(THUMBS_DIR.parent)).replace("\\", "/"),
        "r": rgb[0], "g": rgb[1], "b": rgb[2],
        "h": hsv[0], "s": hsv[1], "v": hsv[2],
        "tono": tono,
        "width": img.width,
        "height": img.height,
    }
