"""Stock de tinturas — tablero principal.

Levantar con:  streamlit run app.py
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import stock
from src.db import OXIDANTE, TINTURA
from src.ui import barra_alertas, conn, semaforo

st.set_page_config(page_title="Stock de Tinturas", page_icon="🎨", layout="wide")

st.title("🎨 Stock de tinturas")
st.caption("Yellow · Color Master — control de vencimientos, mezclador y verificación de stock")

c = conn()
barra_alertas()

filas = stock.resumen(c)
alertas = stock.alertas(c)

col1, col2, col3, col4 = st.columns(4)
col1.metric("Pomos de tintura", f"{sum(f['unidades'] for f in filas if f['tipo'] == TINTURA):g}")
col2.metric("Oxidante (ml)", f"{sum(f['contenido_total'] for f in filas if f['tipo'] == OXIDANTE):,.0f}")
col3.metric("Vencidos", len(alertas["vencidos"]), delta_color="inverse")
col4.metric("Bajo mínimo", len(alertas["bajo_minimo"]), delta_color="inverse")

st.divider()

izq, der = st.columns([3, 2])

with izq:
    st.subheader("Vencimientos a la vista")
    urgentes = alertas["vencidos"] + alertas["criticos"] + alertas["avisos"]
    if not urgentes:
        st.success("Ningún lote vence en los próximos 90 días.")
    else:
        tabla = pd.DataFrame(
            [
                {
                    "Estado": semaforo(stock.estado_vencimiento(u["vencimiento"])[0], u["dias"]),
                    "Producto": f"{u['marca']} {u['codigo']}",
                    "Lote": u["lote"] or "—",
                    "Vence": u["vencimiento"],
                    "Unidades": u["cantidad"],
                    "Ubicación": u["ubicacion"] or "—",
                }
                for u in urgentes
            ]
        )
        st.dataframe(tabla, hide_index=True, use_container_width=True)

with der:
    st.subheader("Reponer")
    if not alertas["bajo_minimo"]:
        st.success("Todo por encima del mínimo.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Producto": f"{f['marca']} {f['codigo']}",
                        "Hay": f["unidades"],
                        "Mínimo": f["stock_minimo"],
                        "Faltan": round(f["stock_minimo"] - f["unidades"], 2),
                    }
                    for f in alertas["bajo_minimo"]
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

st.divider()
st.subheader("Stock por producto")

con_stock = st.toggle("Mostrar solo lo que tiene stock", value=True)
visibles = [f for f in filas if not con_stock or f["unidades"] or f["vencidas"]]

if not visibles:
    st.info("Todavía no cargaste stock. Andá a **Stock** para ingresar el primer lote.")
else:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "": semaforo(f["estado"]).split(" ")[0],
                    "Marca": f["marca"],
                    "Tipo": f["tipo"],
                    "Código": f["codigo"],
                    "Nombre": f["nombre"],
                    "Unidades": f["unidades"],
                    "Vencidas": f["vencidas"],
                    f"Total": f"{f['contenido_total']:g} {f['unidad']}",
                    "Próx. venc.": f["proximo_vencimiento"] or "—",
                }
                for f in visibles
            ]
        ),
        hide_index=True,
        use_container_width=True,
        height=420,
    )

with st.sidebar:
    st.markdown("### Cómo se usa")
    st.markdown(
        "1. **Stock** — ingresás lo que comprás, con lote y vencimiento.\n"
        "2. **Mezclador** — armás la fórmula y descontás del stock.\n"
        "3. **Verificación** — contás lo físico y ajustás las diferencias.\n"
        "4. **Catálogo** — agregás o editás tonos y mínimos."
    )
    st.caption("El consumo siempre sale del lote que vence primero (FEFO).")
