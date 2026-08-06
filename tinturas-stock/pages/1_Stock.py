"""Ingreso de mercadería, lotes y vencimientos."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from src import stock
from src.ui import barra_alertas, conn, selector_producto, semaforo

st.set_page_config(page_title="Stock", page_icon="📦", layout="wide")
st.title("📦 Stock por lote")

c = conn()
barra_alertas()

ingreso, existencias, vencidos = st.tabs(["➕ Ingresar", "📋 Lotes", "🗑️ Vencidos"])

# --------------------------------------------------------------------------- #
with ingreso:
    st.subheader("Ingresar mercadería")
    producto_id = selector_producto("Producto", key="ing_producto")

    with st.form("form_ingreso"):
        c1, c2, c3 = st.columns(3)
        unidades = c1.number_input(
            "Unidades", min_value=0.0, step=1.0, value=1.0,
            help="Pomos o botellas enteras. Se admiten fracciones (0.5 = medio pomo).",
        )
        lote = c2.text_input("Lote", placeholder="ej. L2411A")
        vencimiento = c3.date_input(
            "Vencimiento", value=date.today() + timedelta(days=365), format="DD/MM/YYYY"
        )
        c4, c5, c6 = st.columns(3)
        sin_fecha = c4.checkbox("Sin fecha de vencimiento")
        costo = c5.number_input("Costo por unidad ($)", min_value=0.0, step=100.0, value=0.0)
        ubicacion = c6.text_input("Ubicación", placeholder="ej. Estante A")

        if st.form_submit_button("Ingresar", type="primary"):
            if not producto_id:
                st.error("Elegí un producto.")
            elif unidades <= 0:
                st.error("Las unidades tienen que ser mayores a 0.")
            else:
                stock.ingresar(
                    c,
                    producto_id,
                    unidades,
                    vencimiento=None if sin_fecha else vencimiento.isoformat(),
                    lote=lote,
                    costo_unit=costo or None,
                    ubicacion=ubicacion,
                )
                st.success(f"Ingresaron {unidades:g} unidad(es).")
                st.rerun()

# --------------------------------------------------------------------------- #
with existencias:
    st.subheader("Lotes en existencia")
    f1, f2 = st.columns([2, 1])
    filtro = f1.text_input("Buscar", placeholder="marca, código o nombre del tono")
    solo_con_stock = f2.toggle("Solo con stock", value=True)

    lotes = stock.lotes(c, con_stock=solo_con_stock)
    if filtro:
        aguja = filtro.lower()
        lotes = [
            l for l in lotes
            if aguja in f"{l['marca']} {l['codigo']} {l['producto']} {l['lote']}".lower()
        ]

    if not lotes:
        st.info("No hay lotes que coincidan.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "": semaforo(*stock.estado_vencimiento(l["vencimiento"])).split(" ")[0],
                        "Producto": f"{l['marca']} {l['codigo']} {l['producto']}".strip(),
                        "Lote": l["lote"] or "—",
                        "Vence": l["vencimiento"] or "—",
                        "Unidades": l["cantidad"],
                        "Contenido": f"{l['cantidad'] * l['contenido']:g} {l['unidad']}",
                        "Ubicación": l["ubicacion"] or "—",
                    }
                    for l in lotes
                ]
            ),
            hide_index=True,
            use_container_width=True,
            height=400,
        )

        st.markdown("##### Corregir un lote")
        opciones = {
            l["id"]: f"{l['marca']} {l['codigo']} · lote {l['lote'] or '—'} · "
                     f"vence {l['vencimiento'] or '—'} · {l['cantidad']:g} u."
            for l in lotes
        }
        elegido = st.selectbox(
            "Lote", list(opciones), format_func=lambda i: opciones[i], key="lote_editar"
        )
        e1, e2 = st.columns([1, 2])
        nueva = e1.number_input("Cantidad real", min_value=0.0, step=0.5, key="lote_cant")
        motivo = e2.text_input("Motivo", value="Corrección manual", key="lote_motivo")
        b1, b2 = st.columns(2)
        if b1.button("Ajustar cantidad"):
            dif = stock.ajustar(c, elegido, nueva, motivo=motivo)
            if dif:
                st.success(f"Ajustado ({dif:+g} unidades).")
            else:
                st.info("Sin cambios.")
            st.rerun()
        if b2.button("Descartar lote entero", type="secondary"):
            sacado = stock.descartar(c, elegido, motivo=motivo or "Descarte")
            st.success(f"Se descartaron {sacado:g} unidad(es).")
            st.rerun()

# --------------------------------------------------------------------------- #
with vencidos:
    st.subheader("Lotes vencidos")
    alertas = stock.alertas(c)
    if not alertas["vencidos"]:
        st.success("No hay nada vencido. 👌")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Producto": f"{v['marca']} {v['codigo']}",
                        "Lote": v["lote"] or "—",
                        "Venció": v["vencimiento"],
                        "Hace (días)": abs(v["dias"]),
                        "Unidades": v["cantidad"],
                    }
                    for v in alertas["vencidos"]
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
        st.caption("El stock vencido no se usa en el mezclador ni cuenta como disponible.")
        if st.button("Descartar todos los vencidos", type="primary"):
            sacados = stock.descartar_vencidos(c)
            st.success(f"Se descartaron {len(sacados)} lote(s).")
            st.rerun()
