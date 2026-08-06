"""Helpers compartidos por las páginas de Streamlit."""
from __future__ import annotations

import sqlite3

import streamlit as st

from . import catalogo, stock
from .db import DB_PATH, conectar

EMOJI_ESTADO = {
    stock.VENCIDO: "🔴",
    stock.CRITICO: "🟠",
    stock.AVISO: "🟡",
    stock.OK: "🟢",
    stock.SIN_FECHA: "⚪",
}

TEXTO_ESTADO = {
    stock.VENCIDO: "Vencido",
    stock.CRITICO: "Vence pronto",
    stock.AVISO: "Por vencer",
    stock.OK: "Vigente",
    stock.SIN_FECHA: "Sin fecha",
}


@st.cache_resource
def conn() -> sqlite3.Connection:
    """Conexión única para toda la sesión (crea y siembra la base si hace falta)."""
    primera_vez = not DB_PATH.exists()
    c = conectar()
    if primera_vez or not catalogo.marcas(c):
        catalogo.sembrar(c)
    return c


def semaforo(estado: str, dias: int | None = None) -> str:
    base = f"{EMOJI_ESTADO.get(estado, '⚪')} {TEXTO_ESTADO.get(estado, estado)}"
    if dias is None:
        return base
    if dias < 0:
        return f"{base} (hace {abs(dias)} d)"
    return f"{base} ({dias} d)"


def selector_producto(
    etiqueta_campo: str,
    tipo: str | None = None,
    key: str | None = None,
    incluir_vacio: bool = False,
    ayuda: str | None = None,
) -> int | None:
    """Combo de productos que devuelve el producto_id elegido."""
    filas = catalogo.productos(conn(), tipo=tipo)
    ids = [f["id"] for f in filas]
    opciones = ([None] + ids) if incluir_vacio else ids
    mapa = {f["id"]: catalogo.etiqueta(f) for f in filas}
    if not filas:
        st.warning("No hay productos cargados en el catálogo.")
        return None
    return st.selectbox(
        etiqueta_campo,
        opciones,
        format_func=lambda pid: "— sin oxidante —" if pid is None else mapa[pid],
        key=key,
        help=ayuda,
    )


def encabezado(titulo: str, subtitulo: str = "") -> None:
    st.title(titulo)
    if subtitulo:
        st.caption(subtitulo)


def barra_alertas() -> None:
    """Franja de alertas que va arriba de todas las páginas."""
    a = stock.alertas(conn())
    if not any(a.values()):
        return
    partes = []
    if a["vencidos"]:
        partes.append(f"🔴 {len(a['vencidos'])} lote(s) vencido(s)")
    if a["criticos"]:
        partes.append(f"🟠 {len(a['criticos'])} vence(n) en 30 días")
    if a["bajo_minimo"]:
        partes.append(f"📉 {len(a['bajo_minimo'])} producto(s) bajo el mínimo")
    if partes:
        st.warning(" · ".join(partes))
