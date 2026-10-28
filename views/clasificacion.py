"""Página "Clasificación manual": revisar y reclasificar los reportes del mes."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from utils import cache, data, pending, periods, ui
from utils.branding import CLASSIFICATION_OPTIONS
from utils.styling import style_bot_table
from views.common import month_filter


@st.fragment
def _body(month_df: pd.DataFrame) -> None:
    """Fragmento: seleccionar filas o cambiar el desplegable no re-ejecuta la
    página completa."""
    picker_cols = ["Fecha", "Nombre", "Numero", "Area de interes", "Clasificacion interna"]
    picker_df = month_df[picker_cols].copy()
    picker_df["Nombre"] = picker_df["Nombre"].replace("", "(sin nombre)")

    with ui.card("picker", "Reportes del mes", "Seleccioná un contacto para clasificar"):
        event = st.dataframe(
            style_bot_table(picker_df),
            hide_index=True,
            width="stretch",
            height=min(38 * (len(picker_df) + 1) + 3, 420),
            on_select="rerun",
            selection_mode="single-row",
            key="picker_table",
        )
    sel_rows = event.selection.rows if event.selection else []
    if not sel_rows:
        st.info("Elegí una fila de la tabla para ver el detalle.", icon=":material/touch_app:")
        return

    row = month_df.iloc[sel_rows[0]]
    current_class = row["Clasificacion interna"] or cache.SIN_CLASIFICAR
    try:
        default_idx = CLASSIFICATION_OPTIONS.index(current_class)
    except ValueError:
        default_idx = CLASSIFICATION_OPTIONS.index(cache.SIN_CLASIFICAR)

    with ui.card("detalle", "Detalle de la consulta"):
        tbl_col, cls_col, btn_col = st.columns([6, 3, 1.4], vertical_alignment="bottom")
        with tbl_col:
            st.markdown(
                f"""
| Número | Nombre | Fecha | Área de interés |
|---|---|---|---|
| **{row["Numero"]}** | {row["Nombre"] or "—"} | {row["Fecha"]} | {row["Area de interes"] or "—"} |
"""
            )
        with cls_col:
            new_class = st.selectbox(
                "Clasificación interna",
                CLASSIFICATION_OPTIONS,
                index=default_idx,
                key=f"class_select_{row['Numero']}",
            )
        with btn_col:
            if st.button(
                "Guardar",
                icon=":material/save:",
                key=f"save_{row['Numero']}",
                type="primary",
                help="Guardar clasificación",
            ):
                pending.add(
                    str(row["Numero"]),
                    {
                        "Fecha": row["Fecha"],
                        "Nombre": row["Nombre"],
                        "Clasificacion interna": new_class,
                    },
                )
                st.toast(f"En cola: {row['Numero']} → {new_class}", icon=":material/inbox:")
                st.rerun(scope="app")

        num_key = str(row["Numero"])
        if num_key in pending.get():
            if st.button("Quitar de la cola", key=f"unqueue_{num_key}"):
                pending.remove([num_key])
                st.rerun(scope="app")

        st.markdown("**Resumen de la consulta**")
        st.text_area(
            "Resumen",
            value=row["Resumen general"],
            height=220,
            label_visibility="collapsed",
            disabled=True,
        )


def render() -> None:
    month = month_filter(st.session_state["_months_bot"])
    ui.page_header(
        "Clasificación manual", f"Reportes del bot · {periods.month_label(month, full=True)}"
    )
    month_df = data.current_month(st.session_state["_bot_raw"], month)
    if month_df.empty:
        st.info("Sin reportes en el mes seleccionado.")
        return
    _body(month_df.copy())
