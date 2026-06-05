"""Buscador de fotos Pewen - dashboard Streamlit.

Compartible: el link se puede pasar a clientes. La 'selección' se serializa
en la query string así un asesor puede armar un set y mandarle la URL al cliente.
"""
from __future__ import annotations

import colorsys
import io
import math
import re
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import requests
import streamlit as st

from src.persistencia import esta_habilitada as persist_habilitada, persistir as persist_a_github
from src.sincronizacion import disparar_reindex, ultima_corrida

DB_PATH = Path(__file__).parent / "fotos.db"
ROOT = Path(__file__).parent

st.set_page_config(page_title="Buscador de Fotos Pewen", layout="wide", page_icon="🏠")


@st.cache_resource
def get_conn():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        # Streamlit Cloud no siempre permite crear los archivos -shm/-wal del modo WAL.
        # Caemos al journal default (DELETE), que para nuestro nivel de concurrencia alcanza.
        pass
    return conn


def stats():
    conn = get_conn()
    if conn is None:
        return {"total": 0, "drive": 0, "web": 0, "ocultas": 0, "tonos": [], "categorias": []}
    cur = conn.execute("SELECT source, COUNT(*) FROM fotos WHERE hidden = 0 GROUP BY source")
    por_source = dict(cur.fetchall())
    ocultas = conn.execute("SELECT COUNT(*) FROM fotos WHERE hidden = 1").fetchone()[0]
    tonos = [r[0] for r in conn.execute(
        "SELECT DISTINCT tono FROM fotos WHERE tono IS NOT NULL ORDER BY tono").fetchall()]
    categorias = [r[0] for r in conn.execute(
        "SELECT DISTINCT categoria FROM fotos WHERE categoria != '' ORDER BY categoria").fetchall()]
    total = sum(por_source.values())
    return {"total": total, "drive": por_source.get("drive", 0), "web": por_source.get("web", 0),
            "ocultas": ocultas, "tonos": tonos, "categorias": categorias}


# Equivalencias alemán ↔ español. Las fotos del Drive vienen con nombres
# originales (Kronotex usa alemán): traducimos para que matchee con los
# nombres en castellano del sitio. Bidireccional.
SINONIMOS = {
    "zement": ["cemento", "cementicio", "cement"],
    "cement": ["cemento", "cementicio", "zement"],
    "cemento": ["zement", "cementicio", "cement"],
    "cementicio": ["zement", "cemento", "cement"],
    "holz": ["madera"],
    "madera": ["holz"],
    "marmor": ["marmol", "mármol"],
    "marmol": ["marmor"],
    "mármol": ["marmor"],
    "stein": ["piedra"],
    "piedra": ["stein"],
    "eiche": ["roble"],
    "roble": ["eiche"],
    "nussbaum": ["nogal"],
    "nogal": ["nussbaum"],
    "weiss": ["blanco"],
    "weiß": ["blanco"],
    "blanco": ["weiss", "weiß"],
    "grau": ["gris"],
    "gris": ["grau"],
    "schwarz": ["negro"],
    "negro": ["schwarz"],
    "beige": ["sand"],
    "sand": ["arena", "beige"],
    "arena": ["sand"],
    "dark": ["oscuro"],
    "light": ["claro"],
    "oscuro": ["dark"],
    "claro": ["light"],
}


def _tokens_y_sinonimos(palabra: str) -> list[str]:
    p = palabra.lower().strip()
    if not p:
        return []
    return [p, *SINONIMOS.get(p, [])]


def buscar(query: str, sources: list[str], categorias: list[str], tonos: list[str],
           color_target_hsv: tuple[float, float, float] | None,
           tol_h: float, modo_papelera: bool, limit: int = 600) -> list[dict]:
    conn = get_conn()
    if conn is None:
        return []

    where = [f"hidden = {1 if modo_papelera else 0}"]
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
        # Búsqueda substring (LIKE %tok%) con sinónimos alemán/español.
        # Cada palabra del usuario debe matchear (AND), y cada palabra acepta
        # cualquiera de sus sinónimos (OR).
        palabras_usuario = [p for p in query.strip().lower().split() if p]
        for palabra in palabras_usuario:
            opciones = _tokens_y_sinonimos(palabra)
            cond = []
            for op in opciones:
                like = f"%{op}%"
                cond.append("(name LIKE ? OR alt LIKE ? OR categoria LIKE ?)")
                params.extend([like, like, like])
            where.append("(" + " OR ".join(cond) + ")")

    sql = "SELECT * FROM fotos"
    if where:
        sql += " WHERE " + " AND ".join(where)
    # SIN LIMIT en SQL: sino el orden por rowid hace que solo aparezcan
    # las primeras 600 inserciones (todas Drive). Aplicamos el limit
    # después de ordenar y mezclar.

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
        rows = [r for r in rows if dist(r) < tol_h]
    else:
        # Intercalar drive y web para que ninguna fuente domine los primeros N
        rows = _intercalar(rows)

    return rows[:limit]


def _intercalar(rows: list[dict]) -> list[dict]:
    drive = [r for r in rows if r.get("source") == "drive"]
    web = [r for r in rows if r.get("source") == "web"]
    otros = [r for r in rows if r.get("source") not in ("drive", "web")]
    out = []
    for i in range(max(len(drive), len(web))):
        if i < len(drive): out.append(drive[i])
        if i < len(web): out.append(web[i])
    return out + otros


def set_hidden(foto_id: str, value: int) -> None:
    conn = get_conn()
    if conn is None:
        return
    conn.execute("UPDATE fotos SET hidden = ? WHERE id = ?", (value, foto_id))
    conn.commit()
    accion = "ocultada" if value else "restaurada"
    _persist_async(f"app: 1 foto {accion}")


def set_hidden_bulk(foto_ids: set[str], value: int) -> int:
    conn = get_conn()
    if conn is None or not foto_ids:
        return 0
    placeholders = ",".join("?" * len(foto_ids))
    cur = conn.execute(
        f"UPDATE fotos SET hidden = ? WHERE id IN ({placeholders})",
        [value, *foto_ids],
    )
    conn.commit()
    accion = "ocultadas" if value else "restauradas"
    _persist_async(f"app: {cur.rowcount} fotos {accion}")
    return cur.rowcount


def _persist_async(mensaje: str) -> None:
    """Empuja la persistencia a un thread daemon para no bloquear el rerun."""
    if not persist_habilitada():
        return
    import threading
    t = threading.Thread(target=_persist_worker, args=(mensaje,), daemon=True)
    t.start()


def _persist_worker(mensaje: str) -> None:
    ok, info = persist_a_github(mensaje)
    if not ok:
        print(f"[persistir] {info}")


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str, fallback: str, ext: str) -> str:
    base = _SAFE_NAME_RE.sub("_", (name or fallback).strip()).strip("_")[:80] or fallback
    if not ext.startswith("."):
        ext = "." + ext
    if base.lower().endswith(ext.lower()):
        return base
    return base + ext


def _ext_de_url(url: str, default: str = ".jpg") -> str:
    if not url:
        return default
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"):
        if path.endswith(ext):
            return ext
    return default


def _filas_por_ids(foto_ids: set[str]) -> list[dict]:
    conn = get_conn()
    if conn is None or not foto_ids:
        return []
    placeholders = ",".join("?" * len(foto_ids))
    cur = conn.execute(
        f"SELECT id, source, name, thumb_path, url_download, url_original "
        f"FROM fotos WHERE id IN ({placeholders})",
        list(foto_ids),
    )
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def zip_de_thumbs(foto_ids: set[str]) -> tuple[bytes, int]:
    rows = _filas_por_ids(foto_ids)
    buf = io.BytesIO()
    n = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            full = ROOT / r["thumb_path"]
            if not full.exists():
                continue
            arcname = _safe_filename(r["name"], r["id"], ".jpg")
            zf.write(full, arcname=arcname)
            n += 1
    return buf.getvalue(), n


def _bajar_uno(row: dict) -> tuple[str, bytes, str] | None:
    url = row.get("url_download") or row.get("url_original")
    if not url:
        return None
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200 or not r.content:
            return None
    except Exception:
        return None
    ext = _ext_de_url(row.get("url_original") or url)
    arcname = _safe_filename(row["name"], row["id"], ext)
    return (arcname, r.content, row["id"])


def zip_de_originales(foto_ids: set[str], progress_cb=None) -> tuple[bytes, int]:
    rows = _filas_por_ids(foto_ids)
    if not rows:
        return b"", 0
    buf = io.BytesIO()
    ok = 0
    usados: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = [ex.submit(_bajar_uno, r) for r in rows]
            for i, f in enumerate(as_completed(futures), 1):
                if progress_cb:
                    progress_cb(i, len(rows))
                res = f.result()
                if res is None:
                    continue
                arcname, content, fid = res
                if arcname in usados:
                    arcname = f"{fid[:12]}_{arcname}"
                usados.add(arcname)
                zf.writestr(arcname, content)
                ok += 1
    return buf.getvalue(), ok


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
if s["total"] == 0 and s["ocultas"] == 0:
    st.warning("La base de datos está vacía. Corré `python indexador.py` para indexar las fotos.")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Fotos visibles", s["total"])
c2.metric("Del Drive", s["drive"])
c3.metric("Del sitio web", s["web"])
c4.metric("Ocultas", s["ocultas"])

seleccion = get_seleccion()

st.divider()
with st.sidebar:
    st.header("Filtros")

    if persist_habilitada():
        st.caption("✅ Modo persistente activo — los cambios se guardan en GitHub.")
    else:
        st.caption("⚠️ Modo efímero — los cambios se pierden al reiniciar el container.")

    modo_papelera = st.toggle(
        "🗂 Modo papelera",
        value=False,
        help="Mostrar solo las fotos ocultas para poder restaurarlas.",
    )

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
    with st.expander("🔄 Sincronizar con Drive y sitio"):
        st.caption(
            "Re-corre el indexador completo: busca fotos nuevas en el Drive y en el sitio. "
            "Tarda ~25 min, corre en GitHub Actions. Cuando termina, la app se recarga sola."
        )
        run = ultima_corrida()
        if run:
            if run["status"] == "completed":
                emoji = "✅" if run["conclusion"] == "success" else "❌"
                st.caption(f"{emoji} Última corrida: {run['conclusion']} · {run['updated_at']}")
            else:
                st.caption(f"⏳ Corrida en curso ({run['status']})")
            st.markdown(f"[Ver detalle en GitHub]({run['html_url']})")

        if st.button("🔄 Actualizar ahora", use_container_width=True):
            ok, msg = disparar_reindex()
            if ok:
                st.success("Re-indexado disparado. Avísanos en ~25 min cuando se recargue solo.")
                st.markdown(f"[Ver progreso en GitHub Actions]({msg})")
            else:
                st.error(f"No pude disparar el workflow: {msg}")

        with st.expander("🔧 Diagnóstico del PAT"):
            import os as _os
            try:
                _pat = st.secrets.get("github_pat")
            except Exception as _e:
                _pat = None
                st.write(f"Error leyendo secret: {_e}")
            if not _pat:
                st.write("❌ No hay `github_pat` en secrets.")
            else:
                _pat = str(_pat)
                st.write(f"- **Largo:** {len(_pat)} caracteres")
                st.write(f"- **Empieza con:** `{_pat[:14]}…`")
                st.write(f"- **Termina con:** `…{_pat[-4:]}`")
                _strip = _pat.strip()
                if _strip != _pat:
                    st.write(f"⚠️ Tiene espacios o newlines: largo sin trim = {len(_strip)}")
                else:
                    st.write("✓ Sin espacios al inicio/fin.")
                if not _pat.startswith("github_pat_"):
                    st.write("⚠️ NO empieza con `github_pat_` — probablemente está corrupto o es de otro tipo.")
                else:
                    st.write("✓ Formato fine-grained correcto.")
                # Probar el PAT contra /user (endpoint mínimo, solo confirma que es válido)
                try:
                    _test = requests.get(
                        "https://api.github.com/user",
                        headers={"Authorization": f"Bearer {_pat}",
                                 "Accept": "application/vnd.github+json"},
                        timeout=10,
                    )
                    if _test.status_code == 200:
                        st.write(f"✅ El PAT funciona. Usuario: `{_test.json().get('login')}`")
                    else:
                        st.write(f"❌ El PAT NO es válido contra GitHub: HTTP {_test.status_code}")
                        st.write(f"`{_test.text[:200]}`")
                except Exception as _e:
                    st.write(f"⚠️ Error probando el PAT: {_e}")

    st.divider()
    if seleccion:
        st.subheader(f"🗂 Selección ({len(seleccion)})")

        st.text_input("Link compartible", value=f"?sel={','.join(sorted(seleccion))}", disabled=True)
        st.caption("Copialo y pasáselo a tu cliente.")

        if st.button("📥 Descargar thumbs (rápido)", use_container_width=True):
            with st.spinner("Armando ZIP de thumbs…"):
                data, n = zip_de_thumbs(seleccion)
            if n:
                st.session_state["zip_thumbs"] = (data, n)
            else:
                st.warning("No pude armar el zip.")
        if "zip_thumbs" in st.session_state:
            data, n = st.session_state["zip_thumbs"]
            st.download_button(
                f"⬇️ Bajar zip ({n} fotos · {len(data)//1024} KB)",
                data=data,
                file_name="pewen_thumbs.zip",
                mime="application/zip",
                use_container_width=True,
                on_click=lambda: st.session_state.pop("zip_thumbs", None),
            )

        if st.button("📦 Descargar originales (lento)", use_container_width=True):
            prog = st.progress(0.0, text="Bajando originales…")
            def cb(i, total):
                prog.progress(i / max(total, 1), text=f"Bajando originales… {i}/{total}")
            data, n = zip_de_originales(seleccion, progress_cb=cb)
            prog.empty()
            if n:
                st.session_state["zip_orig"] = (data, n)
            else:
                st.warning("No pude bajar ningún original (¿perdiste conexión?).")
        if "zip_orig" in st.session_state:
            data, n = st.session_state["zip_orig"]
            st.download_button(
                f"⬇️ Bajar zip ({n} fotos · {len(data)//1024//1024} MB)",
                data=data,
                file_name="pewen_originales.zip",
                mime="application/zip",
                use_container_width=True,
                on_click=lambda: st.session_state.pop("zip_orig", None),
            )

        confirma = st.checkbox(
            "Confirmar ocultar las seleccionadas",
            value=False,
            help="Tildá esto y después tocá el botón rojo.",
        )
        if st.button("🗑 Ocultar todas las seleccionadas", type="primary",
                     disabled=not confirma, use_container_width=True):
            n = set_hidden_bulk(seleccion, 1)
            set_seleccion(set())
            st.success(f"{n} fotos ocultadas.")
            st.rerun()

        if st.button("Vaciar selección", use_container_width=True):
            set_seleccion(set())
            st.rerun()

resultados = buscar(query, sources, categorias_sel, tonos_sel, color_target, tol_h, modo_papelera)

if modo_papelera:
    st.caption(f"🗂 Modo papelera · {len(resultados)} fotos ocultas")
else:
    st.caption(f"{len(resultados)} resultados")

if not resultados:
    st.info("No encontré fotos con esos filtros." if not modo_papelera
            else "No hay fotos ocultas.")
    st.stop()

cols_per_row = 4
for i in range(0, len(resultados), cols_per_row):
    row = resultados[i:i + cols_per_row]
    cols = st.columns(cols_per_row)
    for col, foto in zip(cols, row):
        with col:
            with st.container(border=True):
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

                b1, b2, b3 = st.columns(3)
                with b1:
                    marcado = foto["id"] in seleccion
                    if st.checkbox("✓", value=marcado, key=f"sel_{foto['id']}",
                                   label_visibility="collapsed",
                                   help="Agregar a la selección"):
                        seleccion.add(foto["id"])
                    else:
                        seleccion.discard(foto["id"])
                with b2:
                    url_dl = foto.get("url_download") or foto.get("url_original")
                    if url_dl:
                        st.link_button("⬇", url_dl, use_container_width=True,
                                       help="Descargar esta foto")
                with b3:
                    if modo_papelera:
                        if st.button("↩", key=f"res_{foto['id']}", help="Restaurar esta foto",
                                     use_container_width=True):
                            set_hidden(foto["id"], 0)
                            st.rerun()
                    else:
                        with st.popover("🗑", use_container_width=True,
                                        help="Ocultar esta foto"):
                            if thumb_path.exists():
                                st.image(str(thumb_path), use_container_width=True)
                            st.markdown(f"**¿Ocultar esta foto?**")
                            st.caption(etiqueta[:80])
                            cc1, cc2 = st.columns(2)
                            with cc1:
                                if st.button("Sí, ocultar", key=f"confirm_hide_{foto['id']}",
                                             type="primary", use_container_width=True):
                                    set_hidden(foto["id"], 1)
                                    seleccion.discard(foto["id"])
                                    st.rerun()
                            with cc2:
                                st.caption("(cerrá el popover para cancelar)")

if seleccion != get_seleccion():
    set_seleccion(seleccion)
