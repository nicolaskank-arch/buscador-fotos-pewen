"""Historial de movimientos: todo lo que entró, salió y se ajustó."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import stock
from src.ui import conn, selector_producto

st.set_page_config(page_title="Movimientos", page_icon="📜", layout="wide")
st.title("📜 Movimientos")
st.caption("Cada ingreso, consumo, ajuste y descarte queda registrado con su lote.")

c = conn()

ICONO = {"ingreso": "⬆️", "consumo": "⬇️", "ajuste": "🔧", "descarte": "🗑️"}

f1, f2 = st.columns([3, 1])
with f1:
    filtrar = st.checkbox("Filtrar por producto")
    producto_id = selector_producto("Producto", key="mov_producto") if filtrar else None
limite = f2.number_input("Últimos", min_value=20, max_value=2000, value=200, step=50)

movimientos = stock.movimientos(c, limite=int(limite), producto_id=producto_id)

if not movimientos:
    st.info("Todavía no hay movimientos.")
    st.stop()

tabla = pd.DataFrame(
    [
        {
            "Fecha": m["fecha"][:16],
            "": ICONO.get(m["tipo"], ""),
            "Tipo": m["tipo"],
            "Producto": f"{m['marca']} {m['codigo']}",
            "Lote": m["lote"] or "—",
            "Vence": m["vencimiento"] or "—",
            "Unidades": m["cantidad"],
            "Motivo": m["motivo"] or "—",
            "Ref.": m["referencia"] or "—",
        }
        for m in movimientos
    ]
)
st.dataframe(tabla, hide_index=True, use_container_width=True, height=520)

st.download_button(
    "Descargar CSV",
    tabla.to_csv(index=False).encode("utf-8-sig"),
    file_name="movimientos-tinturas.csv",
    mime="text/csv",
)

st.divider()
resumen = tabla.groupby("Tipo")["Unidades"].agg(["count", "sum"]).reset_index()
resumen.columns = ["Tipo", "Movimientos", "Unidades netas"]
st.dataframe(resumen, hide_index=True, use_container_width=True)
