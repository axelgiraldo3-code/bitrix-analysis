"""Página "Análisis preliminar": pruebas de gráficos que cruzan el bot con
Bitrix antes de pasarlos al reporte. Hoy: embudo consultas → ganados e
informe del mes descargable (ZIP con Markdown y gráficos)."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from utils import charts, data, funnel, informe, periods, ui
from utils.branding import COTEAR_GRAY
from utils.styling import style_bitrix_table
from views.common import month_filter

def _deals_for(month: str) -> tuple[pd.DataFrame, list[str]]:
    """Negocios con actividad en el mes y en el siguiente (una consulta de
    fin de mes puede generar el negocio a principios del otro)."""
    months = [month]
    nxt = periods.shift_months(month, 1)
    now = datetime.now()
    if nxt <= f"{now.year:04d}-{now.month:02d}":
        months.append(nxt)
    deals, _sources, warns = data.load_bitrix_period(tuple(months))
    return deals, warns


def _embudo_card(counts: list[int], month: str) -> None:
    first = counts[0] or 1
    table_df = pd.DataFrame({
        "Etapa": funnel.STAGES,
        "Cantidad": counts,
        "% de las consultas": [round(c / first * 100, 1) for c in counts],
        "% de la etapa anterior": [None] + [round(c / p * 100, 1) if p else None
                                            for p, c in zip(counts, counts[1:])],
    })

    # Mientras sea la única tarjeta de la sección, gráfico y tabla van lado a
    # lado (sin Gráfico ⇄ Datos) para que el embudo no ocupe todo el ancho.
    with ui.card("embudo", "Embudo de consultas"):
        c_chart, c_table = st.columns([3, 2], vertical_alignment="center")
        with c_chart:
            ui.echart(charts.funnel(funnel.STAGES, counts, funnel.COLORS, f"embudo_{month}"),
                      height=420)
        with c_table:
            st.dataframe(table_df, hide_index=True, width="stretch", column_config={
                "% de las consultas": st.column_config.NumberColumn(format="%.1f %%"),
                "% de la etapa anterior": st.column_config.NumberColumn(format="%.1f %%"),
            })


def _informe_card(df: pd.DataFrame, month: str, funnel_counts: list[int]) -> None:
    """Borrador del reporte de actividad del mes para completar a mano."""
    deals, _src, warn = data.load_bitrix_month(month)
    with ui.card("informe", "Reporte de actividad"):
        st.markdown(
            "Borrador del reporte mensual con las tablas ya armadas: calidad de las "
            "consultas, embudo de la consulta a la venta, fuentes de los negocios, "
            "provincias, motivos de baja, eficiencia por fuente, demanda de productos y "
            "estado del pipeline. Los gráficos se enlazan con el nombre que les pone la "
            "app al descargarlos: guardalos en una carpeta img junto a la nota. Las "
            "conclusiones quedan marcadas para revisar y completar.")
        if warn:
            st.warning(warn)
        st.download_button("Descargar informe (.md)",
                           data=informe.md_builder(df, deals, month, funnel_counts),
                           file_name=informe.file_name(month), mime="text/markdown",
                           icon=":material/download:", on_click="ignore", key="dl_informe")


def render() -> None:
    bot_raw = st.session_state["_bot_raw"]
    month = month_filter(st.session_state["_months_bot"])
    ui.page_header("Análisis preliminar",
                   f"Gráficos en prueba · {periods.month_label(month, full=True)}")

    df = data.current_month(bot_raw, month)
    if df.empty:
        st.info("Sin datos en el mes seleccionado.")
        return
    deals, warns = _deals_for(month)
    for w in warns:
        st.warning(w)

    matched = funnel.match_deals(df, deals)
    counts = funnel.funnel_counts(df, matched)

    ui.section("De la consulta a la venta")
    _embudo_card(counts, month)
    st.markdown(
        f"<div style='color:{COTEAR_GRAY};font-size:.82rem;margin-top:.4rem'>"
        "Las consultas derivadas se cruzan por teléfono con los negocios que tuvieron "
        "actividad en el mes o en el siguiente; si hay varios, cuenta el más avanzado. "
        "<b>Cotizadas</b>: el negocio llegó a <i>Cotizado aguardando devolución</i> o más "
        "(un perdido cuenta si se perdió después de cotizar). "
        "<b>Ganadas</b>: <i>Ganado en Desarrollo</i> o <i>Cerrado Ganado</i>.</div>",
        unsafe_allow_html=True)

    ui.section("Informe del mes")
    _informe_card(df, month, counts)

    listing = matched[["Fecha", "Nombre", "Numero", "Negocio Bitrix", "Etapa Bitrix"]].rename(
        columns={"Negocio Bitrix": "Negocio", "Etapa Bitrix": "Etapa"})
    ui.raw_data("embudo", f"Consultas derivadas y su negocio ({len(listing)})",
                style_bitrix_table(listing), listing,
                f"embudo_consultas_{month}.csv")
