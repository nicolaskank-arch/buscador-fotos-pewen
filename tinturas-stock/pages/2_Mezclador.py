"""Mezclador: arma la fórmula, la contrasta con el stock y la descuenta."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import catalogo, mezclador, stock
from src.db import OXIDANTE, TINTURA
from src.mezclador import Componente
from src.ui import barra_alertas, conn, selector_producto

st.set_page_config(page_title="Mezclador", page_icon="🧪", layout="wide")
st.title("🧪 Mezclador")

c = conn()
barra_alertas()

tonos = catalogo.productos(c, tipo=TINTURA)
if not tonos:
    st.error("No hay tonos en el catálogo. Cargalos desde la pestaña **Catálogo**.")
    st.stop()

# El data_editor no soporta format_func, así que la columna guarda la etiqueta
# legible y después la traducimos de vuelta al producto_id.
por_etiqueta = {catalogo.etiqueta(t): t["id"] for t in tonos}

st.subheader("1. Tonos de la fórmula")
st.caption(
    "Las **partes** son la proporción entre tonos: 2 y 1 significa dos partes del primero "
    "por una del segundo. No hace falta que sumen 1."
)

base = pd.DataFrame({"Tono": [next(iter(por_etiqueta))], "Partes": [1.0]})
receta = st.data_editor(
    base,
    num_rows="dynamic",
    use_container_width=True,
    key="receta",
    column_config={
        "Tono": st.column_config.SelectboxColumn(
            "Tono", options=list(por_etiqueta), width="large", required=True
        ),
        "Partes": st.column_config.NumberColumn("Partes", min_value=0.0, step=0.5, format="%.2f"),
    },
)

st.subheader("2. Cantidad y oxidante")
c1, c2, c3 = st.columns(3)
gramos = c1.number_input(
    "Gramos de tintura", min_value=1.0, step=10.0, value=60.0,
    help="Total de color de la fórmula, sin contar el oxidante.",
)
proporcion = c2.selectbox(
    "Proporción tintura : oxidante",
    list(mezclador.PROPORCIONES),
    index=list(mezclador.PROPORCIONES).index(mezclador.PROPORCION_DEFAULT),
)
oxidante_id = selector_producto("Oxidante", tipo=OXIDANTE, key="oxi", incluir_vacio=True)

with st.expander("¿Qué volumen usar?"):
    aclarar = st.slider("Tonos de aclaración buscados", 0, 4, 1)
    volumen, detalle = mezclador.sugerir_oxidante(aclarar)
    st.info(f"**{volumen}** — {detalle}")
    st.caption("Orientativo. La tabla del fabricante manda, sobre todo en canas y super aclarantes.")

componentes = [
    Componente(por_etiqueta[fila["Tono"]], float(fila["Partes"]))
    for _, fila in receta.iterrows()
    if fila["Tono"] in por_etiqueta and pd.notna(fila["Partes"]) and float(fila["Partes"]) > 0
]

if not componentes:
    st.warning("Cargá al menos un tono con partes mayores a 0.")
    st.stop()

try:
    mezcla = mezclador.calcular(c, componentes, gramos, proporcion, oxidante_id)
except mezclador.FormulaInvalida as e:
    st.error(str(e))
    st.stop()

st.subheader("3. La mezcla")

m1, m2, m3 = st.columns(3)
m1.metric("Tintura", f"{mezcla.gramos_tintura:g} g")
m2.metric("Oxidante", f"{mezcla.oxidante_ml:g} ml")
m3.metric("Mezcla total", f"{mezcla.total:g} g")

detalle_items = [
    {
        "Producto": i.etiqueta,
        "Partes": i.partes,
        "Cantidad": f"{i.gramos:g} {i.unidad}",
        "Unidades": round(i.unidades, 3),
        "En stock": i.disponible,
        "Falta": i.faltante or "",
    }
    for i in mezcla.items
]
if mezcla.oxidante:
    detalle_items.append(
        {
            "Producto": mezcla.oxidante.etiqueta,
            "Partes": "—",
            "Cantidad": f"{mezcla.oxidante.gramos:g} {mezcla.oxidante.unidad}",
            "Unidades": round(mezcla.oxidante.unidades, 3),
            "En stock": mezcla.oxidante.disponible,
            "Falta": mezcla.oxidante.faltante or "",
        }
    )
st.dataframe(pd.DataFrame(detalle_items), hide_index=True, use_container_width=True)

if mezcla.alcanza:
    st.success("Hay stock para esta fórmula.")
else:
    st.error(
        "Falta stock: "
        + ", ".join(f"{i.etiqueta} — faltan {i.faltante:g} u." for i in mezcla.faltantes)
    )

with st.expander("De qué lotes sale (FEFO)"):
    for item in mezcla.items + ([mezcla.oxidante] if mezcla.oxidante else []):
        asignaciones, faltante = stock.plan_fefo(c, item.producto_id, item.unidades)
        st.markdown(f"**{item.etiqueta}**")
        if not asignaciones:
            st.caption("Sin lotes disponibles.")
        for a in asignaciones:
            st.caption(
                f"· lote {a.lote or '—'} (vence {a.vencimiento or 's/f'}): {a.unidades:g} u."
            )
        if faltante:
            st.caption(f"· ⚠️ faltan {faltante:g} u.")

st.subheader("4. Registrar")
r1, r2 = st.columns(2)
nombre = r1.text_input("Nombre de la fórmula", placeholder="ej. Raíz Ana — 7.3 + 8.1")
cliente = r2.text_input("Cliente", placeholder="opcional")
notas = st.text_area("Notas", placeholder="tiempo de pose, resultado, qué ajustar la próxima…")

b1, b2 = st.columns(2)
if b1.button("Guardar fórmula", use_container_width=True):
    fid = mezclador.guardar_formula(c, nombre, mezcla, cliente=cliente, notas=notas)
    st.success(f"Fórmula guardada (#{fid}). El stock quedó igual.")

if b2.button("Aplicar y descontar del stock", type="primary", use_container_width=True,
             disabled=not mezcla.alcanza):
    fid = mezclador.guardar_formula(c, nombre, mezcla, cliente=cliente, notas=notas)
    try:
        mezclador.aplicar(c, mezcla, formula_id=fid, referencia=cliente or nombre, notas=notas)
        st.success("Aplicada. Se descontó del stock por FEFO.")
        st.rerun()
    except stock.StockInsuficiente as e:
        st.error(str(e))

st.divider()
st.subheader("Fórmulas guardadas")
guardadas = mezclador.formulas(c, limite=25)
if not guardadas:
    st.caption("Todavía no guardaste ninguna.")
else:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "#": f["id"],
                    "Nombre": f["nombre"],
                    "Cliente": f["cliente"] or "—",
                    "Tonos": ", ".join(
                        f"{i['codigo']} ×{i['partes']:g}" for i in mezclador.items_de(c, f["id"])
                    ),
                    "Gramos": f["gramos"],
                    "Proporción": f"1:{f['proporcion']:g}",
                    "Aplicada": f["usos"],
                    "Creada": f["creada"][:10],
                }
                for f in guardadas
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
