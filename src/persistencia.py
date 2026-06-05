"""Persiste la DB en GitHub haciendo commit + push automático.

Pensado para correr dentro de Streamlit Cloud: cada vez que un usuario
oculta/restaura fotos, esta función hace push de fotos.db al repo así
los cambios sobreviven a reinicios del container y son visibles en
todas las réplicas.

Necesita un PAT (Personal Access Token) en st.secrets["github_pat"].
Si el PAT no está, la función no hace nada (modo solo-local).
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from threading import Lock

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
_PUSH_LOCK = Lock()


def _get_pat() -> str | None:
    if st is not None:
        try:
            pat = st.secrets.get("github_pat")
            if pat:
                return str(pat)
        except Exception:
            pass
    return os.environ.get("GITHUB_PAT")


def _repo_url_con_pat(pat: str) -> str | None:
    """Lee el remote 'origin', le inyecta el PAT y devuelve la URL.

    Format esperado: https://github.com/owner/repo.git
    Resultado:       https://x-access-token:PAT@github.com/owner/repo.git
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(ROOT), "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return None
    m = re.match(r"https?://(?:[^@]+@)?([^/]+/.+)$", out)
    if not m:
        return None
    return f"https://x-access-token:{pat}@{m.group(1)}"


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=ROOT, capture_output=True, text=True, timeout=60, **kw
    )


def persistir(mensaje: str) -> tuple[bool, str]:
    """Hace add + commit + pull --rebase + push.

    Retorna (ok, mensaje_humano). No tira excepciones.
    Thread-safe vía un lock global para evitar pisar commits concurrentes
    en el mismo container.
    """
    pat = _get_pat()
    if not pat:
        return False, "no_pat"

    url_con_pat = _repo_url_con_pat(pat)
    if not url_con_pat:
        return False, "no_remote"

    with _PUSH_LOCK:
        # En Streamlit Cloud el repo está clonado pero quizás falta user/email
        _run(["git", "config", "user.email", "buscador-fotos-pewen-bot@users.noreply.github.com"])
        _run(["git", "config", "user.name", "buscador-fotos-pewen-bot"])

        _run(["git", "add", "fotos.db"])

        diff = _run(["git", "diff", "--cached", "--quiet"])
        if diff.returncode == 0:
            return True, "sin_cambios"

        commit = _run(["git", "commit", "-m", mensaje])
        if commit.returncode != 0:
            return False, f"commit_fail: {commit.stderr[:200]}"

        # Bring in any commits that landed mientras tanto (workflow de actions)
        pull = _run(["git", "pull", "--rebase", url_con_pat, "main"])
        if pull.returncode != 0:
            # Rebase falló — abortamos y dejamos commit local, próximo intento reintenta
            _run(["git", "rebase", "--abort"])
            return False, f"pull_fail: {pull.stderr[:200]}"

        push = _run(["git", "push", url_con_pat, "HEAD:main"])
        if push.returncode != 0:
            return False, f"push_fail: {push.stderr[:200]}"

        return True, "ok"


def esta_habilitada() -> bool:
    """True si hay PAT configurado (la app va a intentar persistir)."""
    return _get_pat() is not None
