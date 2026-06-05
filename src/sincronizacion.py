"""Dispara workflows del repo (re-indexado) desde la app vía la API de GitHub.

Reusa el mismo PAT que ya está configurado en st.secrets["github_pat"] para
persistir las ocultaciones. El PAT necesita scope "Actions: read and write"
y "Contents: read and write" (ya lo tiene si seguiste el setup).
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import requests

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_FILE = "indexar.yml"


def _get_pat() -> str | None:
    if st is not None:
        try:
            pat = st.secrets.get("github_pat")
            if pat:
                return str(pat)
        except Exception:
            pass
    return os.environ.get("GITHUB_PAT")


def _owner_repo() -> tuple[str, str] | None:
    """Lee owner/repo del remote 'origin'."""
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return None
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$", out)
    if not m:
        return None
    return m.group(1), m.group(2)


def disparar_reindex() -> tuple[bool, str]:
    """POST al endpoint workflow_dispatch. Devuelve (ok, mensaje)."""
    pat = _get_pat()
    if not pat:
        return False, "Falta el PAT en st.secrets[\"github_pat\"]."

    owner_repo = _owner_repo()
    if not owner_repo:
        return False, "No pude leer owner/repo del remote 'origin'."
    owner, repo = owner_repo

    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{WORKFLOW_FILE}/dispatches"
    headers = {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        r = requests.post(url, headers=headers, json={"ref": "main"}, timeout=20)
    except Exception as e:
        return False, f"Error de red: {e}"

    if r.status_code == 204:
        return True, f"https://github.com/{owner}/{repo}/actions"
    return False, f"HTTP {r.status_code}: {r.text[:200]}"


def ultima_corrida() -> dict | None:
    """Trae info de la última corrida del workflow, si existe."""
    pat = _get_pat()
    owner_repo = _owner_repo()
    if not pat or not owner_repo:
        return None
    owner, repo = owner_repo
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{WORKFLOW_FILE}/runs?per_page=1"
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json"},
            timeout=15,
        )
    except Exception:
        return None
    if r.status_code != 200:
        return None
    runs = r.json().get("workflow_runs", [])
    if not runs:
        return None
    run = runs[0]
    return {
        "status": run.get("status"),         # queued / in_progress / completed
        "conclusion": run.get("conclusion"),  # success / failure / None
        "html_url": run.get("html_url"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
    }
