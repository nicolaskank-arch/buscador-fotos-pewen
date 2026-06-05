"""Lista archivos de imagen en una carpeta pública de Google Drive.

Usa gdown 6.x con skip_download=True (devuelve lista de objetos con id+path
sin descargar). No requiere API key ni OAuth: la carpeta tiene que ser
'cualquiera con el link, lector'.
"""
from __future__ import annotations

import re
import sys
from typing import Any

import gdown

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".gif", ".bmp", ".tiff"}


def _is_image(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(ext) for ext in IMAGE_EXTS)


def _extract_folder_id(url_or_id: str) -> str:
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", url_or_id)
    return m.group(1) if m else url_or_id


def listar_carpeta(folder_url: str) -> list[dict]:
    """Recorre la carpeta pública del Drive (recursivo).

    Retorna lista de dicts con keys:
        id, name, carpeta, url_view, url_download, url_thumb_drive
    """
    folder_id = _extract_folder_id(folder_url)
    url = f"https://drive.google.com/drive/folders/{folder_id}"

    try:
        archivos: list[Any] = gdown.download_folder(
            url=url, skip_download=True, quiet=True, use_cookies=False
        )  # type: ignore[assignment]
    except Exception as e:
        print(f"[drive] no pude listar la carpeta: {e}", file=sys.stderr)
        return []

    imagenes: list[dict] = []
    for f in archivos or []:
        fid = getattr(f, "id", None)
        path = getattr(f, "path", "") or ""
        local_path = getattr(f, "local_path", "") or path
        name = path.split("/")[-1] if path else local_path.split("/")[-1]
        carpeta = "/".join(path.split("/")[:-1]) if "/" in path else ""

        if not fid or not name:
            continue
        if not _is_image(name):
            continue

        imagenes.append({
            "id": fid,
            "name": name,
            "mime": "",
            "carpeta": carpeta,
            "url_view": f"https://drive.google.com/file/d/{fid}/view",
            "url_download": f"https://drive.google.com/uc?export=download&id={fid}",
            "url_thumb_drive": f"https://drive.google.com/thumbnail?id={fid}&sz=w1600",
        })
    return imagenes


if __name__ == "__main__":
    from src.config import DRIVE_FOLDER_URL  # noqa
    items = listar_carpeta(DRIVE_FOLDER_URL)
    print(f"Encontradas {len(items)} imágenes en la carpeta pública.")
    for it in items[:10]:
        print(f"  · {it['carpeta']}/{it['name']}")
