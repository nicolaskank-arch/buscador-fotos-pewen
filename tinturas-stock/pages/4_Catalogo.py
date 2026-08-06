"""Catálogo: marcas, tonos, oxidantes y stock mínimo."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import catalogo, stock
from src.db import TIPOS
from src.ui import conn

st.set_page_config(page_title="Catálogo", page_icon="📚", layout="wide")
st.title("📚 Catálogo")
st.caption(
    "Los tonos vienen precargados con la numeración internacional (altura.reflejo). "
    "Ajustá acá lo que no coincida con la carta real de tu proveedor."
)

c = conn()
marcas = catalogo.marcas(c)
mapa_marcas = {m["id"]: m["nombre"] for m in marcas}

listado, alta, marcas_tab = st.tabs(["📋 Productos", "➕ Nuevo producto", "🏷️ Marcas"])

# --------------------------------------------------------------------------- #
with listado:
    f1, f2, f3 = st.columns(3)
    marca_id = f1.selectbox(
        "Marca", [None, *mapa_marcas],
        format_func=lambda i: "Todas" if i is None else mapa_marcas[i],
    )
    tipo = f2.selectbox("Tipo", [None, *TIPOS], format_func=lambda t: "Todos" if t is None else t)
    ver_inactivos = f3.toggle("Incluir inactivos")

    productos = catalogo.productos(c, tipo=tipo, marca_id=marca_id, solo_activos=not ver_inactivos)
    if not productos:
        st.info("No hay productos con esos filtros.")
    else:
        disponibles = {p["id"]: stock.disponible(c, p["id"]) for p in productos}
        tabla = pd.DataFrame(
            [
                {
                    "id": p["id"],
                    "Marca": p["marca"],
                    "Tipo": p["tipo"],
                    "Código": p["codigo"],
                    "Nombre": p["nombre"],
                    "Contenido": p["contenido"],
                    "Un.": p["unidad"],
                    "Stock": disponibles[p["id"]],
                    "Mínimo": p["stock_minimo"],
                    "Activo": bool(p["activo"]),
                }
                for p in productos
            ]
        )
        editada = st.data_editor(
            tabla,
            hide_index=True,
            use_container_width=True,
            height=460,
            key="catalogo",
            disabled=["id", "Marca", "Tipo", "Stock"],
            column_config={
                "id": None,
                "Contenido": st.column_config.NumberColumn(min_value=1.0, step=5.0),
                "Mínimo": st.column_config.NumberColumn(
                    min_value=0.0, step=1.0,
                    help="Debajo de este valor el producto aparece en 'Reponer'.",
                ),
            },
        )
        if st.button("Guardar cambios", type="primary"):
            originales = {p["id"]: p for p in productos}
            cambios = 0
            for _, fila in editada.iterrows():
                orig = originales[int(fila["id"])]
                nuevos = {
                    "codigo": str(fila["Código"]).strip(),
                    "nombre": str(fila["Nombre"]).strip(),
                    "contenido": float(fila["Contenido"]),
                    "unidad": str(fila["Un."]).strip(),
                    "stock_minimo": float(fila["Mínimo"]),
                    "activo": int(bool(fila["Activo"])),
                }
                distintos = {
                    k: v for k, v in nuevos.items()
                    if (orig[k] if k != "activo" else int(orig["activo"])) != v
                }
                if distintos:
                    catalogo.actualizar_producto(c, int(fila["id"]), **distintos)
                    cambios += 1
            if cambios:
                st.success(f"Se actualizaron {cambios} producto(s).")
            else:
                st.info("No hubo cambios.")
            st.rerun()

# --------------------------------------------------------------------------- #
with alta:
    with st.form("nuevo_producto"):
        c1, c2, c3 = st.columns(3)
        n_marca = c1.selectbox(
            "Marca", list(mapa_marcas), format_func=lambda i: mapa_marcas[i], key="n_marca"
        )
        n_tipo = c2.selectbox("Tipo", TIPOS, key="n_tipo")
        n_linea = c3.text_input("Línea", placeholder="ej. Coloración")

        c4, c5 = st.columns(2)
        n_codigo = c4.text_input("Código", placeholder="ej. 9.13 o 20 vol")
        n_nombre = c5.text_input("Nombre", placeholder="ej. Rubio Muy Claro Ceniza Dorado")

        c6, c7, c8 = st.columns(3)
        n_contenido = c6.number_input("Contenido por unidad", min_value=1.0, value=60.0, step=5.0)
        n_unidad = c7.selectbox("Unidad", ["g", "ml"])
        n_minimo = c8.number_input("Stock mínimo (unidades)", min_value=0.0, value=0.0, step=1.0)

        if st.form_submit_button("Crear", type="primary"):
            if not n_codigo.strip():
                st.error("El código es obligatorio.")
            else:
                try:
                    catalogo.crear_producto(
                        c, n_marca, n_tipo, n_codigo, n_nombre, n_linea,
                        n_contenido, n_unidad, n_minimo,
                    )
                    st.success(f"Producto {n_codigo} creado.")
                    st.rerun()
                except Exception as e:  # UNIQUE violado, típicamente
                    st.error(f"No se pudo crear: {e}")

# --------------------------------------------------------------------------- #
with marcas_tab:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Marca": m["nombre"],
                    "Productos": len(catalogo.productos(c, marca_id=m["id"], solo_activos=False)),
                }
                for m in marcas
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
    nueva = st.text_input("Nueva marca", placeholder="ej. Igora")
    if st.button("Agregar marca") and nueva.strip():
        c.execute("INSERT OR IGNORE INTO marcas (nombre) VALUES (?)", (nueva.strip(),))
        c.commit()
        st.success(f"Marca «{nueva.strip()}» agregada.")
        st.rerun()
