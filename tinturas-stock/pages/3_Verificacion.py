"""Verificación de stock: conteo físico y ajuste de diferencias."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src import stock, verificacion
from src.ui import barra_alertas, conn, semaforo

st.set_page_config(page_title="Verificación", page_icon="✅", layout="wide")
st.title("✅ Verificación de stock")

c = conn()
barra_alertas()

abierta = verificacion.abierta(c)

if abierta is None:
    st.info(
        "No hay ninguna verificación en curso. Al abrir una, el sistema congela lo que cree que "
        "hay en cada lote y vos vas cargando lo que contás físicamente."
    )
    with st.form("abrir_verificacion"):
        c1, c2 = st.columns(2)
        usuario = c1.text_input("Quién cuenta", placeholder="tu nombre")
        notas = c2.text_input("Notas", placeholder="ej. conteo de fin de mes")
        if st.form_submit_button("Abrir verificación", type="primary"):
            if not stock.lotes(c):
                st.error("No hay lotes con stock para contar.")
            else:
                vid = verificacion.abrir(c, usuario=usuario, notas=notas)
                st.success(f"Verificación #{vid} abierta.")
                st.rerun()
else:
    vid = abierta["id"]
    st.subheader(f"Verificación #{vid} en curso")
    detalle = verificacion.detalle(c, vid)
    resumen = verificacion.resumen(c, vid)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Lotes a contar", resumen["total"])
    k2.metric("Contados", resumen["contados"])
    k3.metric("Pendientes", resumen["pendientes"])
    k4.metric("Con diferencia", resumen["con_diferencia"])

    st.markdown("##### Cargar conteo")
    st.caption("Escribí lo que contaste en la columna **Contado**. Lo que dejes vacío no se toca.")

    tabla = pd.DataFrame(
        [
            {
                "lote_id": f["lote_id"],
                "": semaforo(f["estado_venc"]).split(" ")[0],
                "Producto": f"{f['marca']} {f['codigo']} {f['producto']}".strip(),
                "Lote": f["lote"] or "—",
                "Vence": f["vencimiento"] or "—",
                "Ubicación": f["ubicacion"] or "—",
                "Sistema": f["esperado"],
                "Contado": f["contado"],
            }
            for f in detalle
        ]
    )
    editada = st.data_editor(
        tabla,
        hide_index=True,
        use_container_width=True,
        height=430,
        key="conteo",
        disabled=["lote_id", "", "Producto", "Lote", "Vence", "Ubicación", "Sistema"],
        column_config={
            "lote_id": None,
            "Contado": st.column_config.NumberColumn(
                "Contado", min_value=0.0, step=0.5, format="%.2f"
            ),
        },
    )

    b1, b2, b3 = st.columns(3)
    if b1.button("Guardar conteo", use_container_width=True):
        guardados = 0
        for _, fila in editada.iterrows():
            if pd.isna(fila["Contado"]):
                continue
            verificacion.contar(c, vid, int(fila["lote_id"]), float(fila["Contado"]))
            guardados += 1
        st.success(f"Se guardaron {guardados} conteo(s).")
        st.rerun()

    if resumen["diferencias"]:
        st.markdown("##### Diferencias")
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Producto": f"{d['marca']} {d['codigo']}",
                        "Lote": d["lote"] or "—",
                        "Sistema": d["esperado"],
                        "Contado": d["contado"],
                        "Diferencia": d["diferencia"],
                    }
                    for d in resumen["diferencias"]
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            f"Faltan {resumen['faltantes']:g} u. y sobran {resumen['sobrantes']:g} u. "
            "respecto de lo que dice el sistema."
        )

    if b2.button("Cerrar y ajustar stock", type="primary", use_container_width=True):
        ajustes = verificacion.cerrar(c, vid)
        st.success(f"Verificación cerrada. Se ajustaron {len(ajustes)} lote(s).")
        st.rerun()

    if b3.button("Cerrar sin ajustar", use_container_width=True):
        verificacion.cerrar(c, vid, aplicar_ajustes=False)
        st.info("Verificación cerrada. El stock quedó como estaba.")
        st.rerun()

st.divider()
st.subheader("Historial")
historial = verificacion.listar(c)
if not historial:
    st.caption("Todavía no hiciste ninguna verificación.")
else:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "#": v["id"],
                    "Abierta": v["fecha"][:16],
                    "Cerrada": (v["cerrada"] or "—")[:16],
                    "Quién": v["usuario"] or "—",
                    "Estado": v["estado"],
                    "Notas": v["notas"] or "—",
                }
                for v in historial
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
