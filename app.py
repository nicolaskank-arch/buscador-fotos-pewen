"""Buscador de fotos Pewen - dashboard Streamlit.

Compartible: el link se puede pasar a clientes. La 'selección' se serializa
en la query string así un asesor puede armar un set y mandarle la URL al cliente.
"""
from __future__ import annotations

import colorsys
import math
import sqlite3
from pathlib import Path

import streamlit as st

DB_PATH = Path(__file__).parent / "fotos.db"
ROOT = Path(__file__).parent

st.set_page_config(page_title="Buscador de Fotos Pewen", layout="wide", page_icon="🏠")


@st.cache_resource
def get_conn():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False)
    return conn


@st.cache_data(ttl=300)
def stats():
    conn = get_conn()
    if conn is None:
        return {"total": 0, "drive": 0, "web": 0, "tonos": []}
    cur = conn.execute("SELECT source, COUNT(*) FROM fotos GROUP BY source")
    por_source = dict(cur.fetchall())
    cur = conn.execute("SELECT DISTINCT tono FROM fotos WHERE tono IS NOT NULL ORDER BY tono")
    tonos = [r[0] for r in cur.fetchall()]
    cur = conn.execute("SELECT DISTINCT categoria FROM fotos WHERE categoria != '' ORDER BY categoria")
    categorias = [r[0] for r in cur.fetchall()]
    total = sum(por_source.values())
    return {"total": total, "drive": por_source.get("drive", 0), "web": por_source.get("web", 0),
            "tonos": tonos, "categorias": categorias}


def buscar(query: str, sources: list[str], categorias: list[str], tonos: list[str],
           color_target_hsv: tuple[float, float, float] | None,
           tol_h: float, limit: int = 600) -> list[dict]:
    conn = get_conn()
    if conn is None:
        return []

    where = []
    params: list = []

    if sources:
        where.append(f"source IN ({','.join('?' * len(sources))})")
        params.extend(sources)
    if categorias:
        where.append(f"categoria IN ({','.join('?' * len(categorias))})")
        params.extend(categorias)
    if tonos:
        where.append(f"tono IN ({','.join('?' * len(tonos))})")
        params.extend(tonos)

    if query.strip():
        ids_fts = [r[0] for r in conn.execute(
            "SELECT id FROM fotos_fts WHERE fotos_fts MATCH ? LIMIT 2000",
            (query.strip() + "*",)
        ).fetchall()]
        if not ids_fts:
            return []
        where.append(f"id IN ({','.join('?' * len(ids_fts))})")
        params.extend(ids_fts)

    sql = "SELECT * FROM fotos"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " LIMIT ?"
    params.append(limit * 4 if color_target_hsv else limit)

    cur = conn.execute(sql, params)
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    if color_target_hsv:
        th, ts, tv = color_target_hsv
        def dist(r):
            dh = min(abs(r["h"] - th), 360 - abs(r["h"] - th)) / 180
            ds = abs(r["s"] - ts)
            dv = abs(r["v"] - tv)
            return math.sqrt(dh * dh * 4 + ds * ds + dv * dv)
        rows.sort(key=dist)
        rows = [r for r in rows if dist(r) < tol_h][:limit]

    return rows


def hex_a_hsv(hex_color: str) -> tuple[float, float, float]:
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16) / 255
    g = int(hex_color[2:4], 16) / 255
    b = int(hex_color[4:6], 16) / 255
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return (h * 360, s, v)


def rgb_a_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def get_seleccion() -> set[str]:
    ids = st.query_params.get_all("sel")
    if not ids:
        return set()
    return set(",".join(ids).split(","))


def set_seleccion(ids: set[str]) -> None:
    if ids:
        st.query_params["sel"] = ",".join(sorted(ids))
    else:
        st.query_params.clear()


# ============ UI ============

st.title("🏠 Buscador de Fotos Pewen")

s = stats()
if s["total"] == 0:
    st.warning("La base de datos está vacía. Corré `python indexador.py` para indexar las fotos.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Fotos totales", s["total"])
c2.metric("Del Drive", s["drive"])
c3.metric("Del sitio web", s["web"])

seleccion = get_seleccion()

st.divider()
with st.sidebar:
    st.header("Filtros")

    query = st.text_input("🔎 Buscar (nombre / alt / categoría)", placeholder="ej: porcelanato roble")

    sources = st.multiselect("Origen", ["drive", "web"], default=["drive", "web"])

    categorias_sel = st.multiselect("Categoría", s["categorias"])

    st.subheader("Por tono")
    modo_color = st.radio("Modo", ["Cualquiera", "Por nombre", "Por color exacto"], horizontal=False)

    tonos_sel: list[str] = []
    color_target = None
    tol_h = 0.4
    if modo_color == "Por nombre":
        tonos_sel = st.multiselect("Tonos", s["tonos"])
    elif modo_color == "Por color exacto":
        color = st.color_picker("Color de referencia", "#c8a878")
        tol_h = st.slider("Tolerancia", 0.05, 0.8, 0.25, 0.05)
        color_target = hex_a_hsv(color)

    st.divider()
    if seleccion:
        st.subheader(f"🗂 Selección ({len(seleccion)})")
        if st.button("Vaciar selección"):
            set_seleccion(set())
            st.rerun()
        link = st.text_input("Link compartible", value=f"?sel={','.join(sorted(seleccion))}", disabled=True)
        st.caption("Copialo y pasáselo a tu cliente.")

resultados = buscar(query, sources, categorias_sel, tonos_sel, color_target, tol_h)
st.caption(f"{len(resultados)} resultados")

if not resultados:
    st.info("No encontré fotos con esos filtros.")
    st.stop()

cols_per_row = 4
for i in range(0, len(resultados), cols_per_row):
    row = resultados[i:i + cols_per_row]
    cols = st.columns(cols_per_row)
    for col, foto in zip(cols, row):
        with col:
            thumb_path = ROOT / foto["thumb_path"]
            if thumb_path.exists():
                st.image(str(thumb_path), use_container_width=True)
            else:
                st.write("(thumb no encontrado)")

            color_chip = rgb_a_hex(foto["r"], foto["g"], foto["b"])
            etiqueta = foto.get("name") or foto.get("alt") or foto.get("categoria") or "—"
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:6px;font-size:12px'>"
                f"<span style='display:inline-block;width:14px;height:14px;border-radius:3px;"
                f"background:{color_chip};border:1px solid #ccc'></span>"
                f"<span><b>{foto['tono']}</b> · {foto['source']}</span></div>",
                unsafe_allow_html=True,
            )
            st.caption(etiqueta[:60])

            b1, b2 = st.columns(2)
            with b1:
                marcado = foto["id"] in seleccion
                if st.checkbox("✓", value=marcado, key=f"sel_{foto['id']}", label_visibility="collapsed"):
                    seleccion.add(foto["id"])
                else:
                    seleccion.discard(foto["id"])
            with b2:
                url_dl = foto.get("url_download") or foto.get("url_original")
                if url_dl:
                    st.link_button("⬇", url_dl, use_container_width=True)

# Persistir la selección actualizada en la query string
if seleccion != get_seleccion():
    set_seleccion(seleccion)
