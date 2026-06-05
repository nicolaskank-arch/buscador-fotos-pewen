"""Sube fotos al Google Drive de Pewen usando una Service Account.

Setup necesario por el usuario (una vez):
  1. Google Cloud Console → crear proyecto → habilitar Drive API.
  2. Crear Service Account → bajar JSON.
  3. Compartir la carpeta del Drive con el email de la SA (que termina en
     @<proyecto>.iam.gserviceaccount.com) con permisos "Editor".
  4. Pegar el JSON entero en Streamlit secrets bajo la clave
     [gcp_service_account] (formato TOML inline table o sección).

La SA acepta tanto el JSON serializado en una sola línea como dict.
"""
from __future__ import annotations

import io
import json
import os
import re
from typing import Any

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore

from src.config import DRIVE_FOLDER_URL

SCOPES = ["https://www.googleapis.com/auth/drive"]


def _extraer_folder_id(url: str) -> str:
    m = re.search(r"/folders/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else url


def _get_sa_info() -> dict | None:
    """Lee la SA desde Streamlit secrets o env GCP_SERVICE_ACCOUNT_JSON."""
    if st is not None:
        try:
            raw = st.secrets.get("gcp_service_account")
            if raw:
                if isinstance(raw, dict):
                    return dict(raw)
                return json.loads(str(raw))
        except Exception:
            pass
    env_json = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
    if env_json:
        try:
            return json.loads(env_json)
        except Exception:
            return None
    return None


def esta_habilitada() -> bool:
    return _get_sa_info() is not None


def _service():
    info = _get_sa_info()
    if not info:
        raise RuntimeError("Falta gcp_service_account en Streamlit secrets.")
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def subir_archivo(file_bytes: bytes, filename: str, mime: str = "image/jpeg",
                   subcarpeta: str | None = None) -> dict[str, Any]:
    """Sube un archivo al Drive y devuelve dict con id, name, web_view_link.

    Si pasás `subcarpeta`, busca o crea esa carpeta DENTRO de la carpeta root.
    """
    from googleapiclient.http import MediaIoBaseUpload

    service = _service()
    parent_id = _extraer_folder_id(DRIVE_FOLDER_URL)

    if subcarpeta:
        parent_id = _asegurar_subcarpeta(service, parent_id, subcarpeta)

    metadata = {"name": filename, "parents": [parent_id]}
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime, resumable=False)
    f = service.files().create(
        body=metadata,
        media_body=media,
        fields="id,name,webViewLink,mimeType,parents",
        supportsAllDrives=True,
    ).execute()
    return {
        "id": f["id"],
        "name": f["name"],
        "mime": f.get("mimeType", mime),
        "url_view": f.get("webViewLink") or f"https://drive.google.com/file/d/{f['id']}/view",
        "url_download": f"https://drive.google.com/uc?export=download&id={f['id']}",
        "url_thumb_drive": f"https://drive.google.com/thumbnail?id={f['id']}&sz=w1600",
        "parent_id": f["parents"][0] if f.get("parents") else parent_id,
        "subcarpeta": subcarpeta or "",
    }


def _asegurar_subcarpeta(service, parent_id: str, nombre: str) -> str:
    q = (
        f"'{parent_id}' in parents and name = '{nombre}' "
        "and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    res = service.files().list(
        q=q, fields="files(id,name)", supportsAllDrives=True,
        includeItemsFromAllDrives=True,
    ).execute()
    folders = res.get("files", [])
    if folders:
        return folders[0]["id"]
    nueva = service.files().create(
        body={"name": nombre, "mimeType": "application/vnd.google-apps.folder",
              "parents": [parent_id]},
        fields="id",
        supportsAllDrives=True,
    ).execute()
    return nueva["id"]


def listar_subcarpetas() -> list[str]:
    """Devuelve los nombres de las subcarpetas existentes para el selector."""
    try:
        service = _service()
    except Exception:
        return []
    parent_id = _extraer_folder_id(DRIVE_FOLDER_URL)
    q = (f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' "
         "and trashed = false")
    res = service.files().list(
        q=q, fields="files(id,name)", pageSize=200,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    return sorted(f["name"] for f in res.get("files", []))
