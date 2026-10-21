"""Piezas compartidas entre páginas: filtro de mes y tarjeta de provincias."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from utils import charts, geo, periods, ui
from utils.branding import COTEAR_BLUE, COTEAR_GRAY

MONTH_KEY = "mes"


def month_filter(months: list[str]) -> str:
    """Selector de mes en la barra lateral, compartido por las páginas de
    consultas (se conserva al cambiar de página)."""
    if st.session_state.get(MONTH_KEY) not in months:
        st.session_state.pop(MONTH_KEY, None)
    return st.sidebar.selectbox("Mes", months, key=MONTH_KEY, persist_state="session",
                                format_func=lambda ym: periods.month_label(ym, full=True))


def zones_card(key: str, title: str, zones: pd.Series, unit: str, filename: str) -> None:
    """Mapa de provincias + ranking, con la tabla de zonas detrás."""
    total = int(len(zones))
    counts = geo.zone_counts(zones, threshold=0)
    note = geo.outside_map_note(counts, total, unit=unit)

    def chart():
        c_map, c_rank = st.columns([7, 5], vertical_alignment="center")
        with c_map:
            fig = geo.province_map(counts, total, unit=unit, height=420)
            if fig.data:
                ui.plotly_map(fig, key=f"map_{key}")
            else:
                st.info(f"Ninguna {unit[:-1]} pudo ubicarse en una provincia.")
        with c_rank:
            top = counts.head(10)
            colors = [COTEAR_GRAY if z in geo.NON_PROVINCE_ZONES else COTEAR_BLUE
                      for z in top["Zona"]]
            ui.echart(charts.hbar(top["Zona"].tolist(), top["Cantidad"].tolist(), colors,
                                  filename), height=max(220, 34 * len(top) + 40))
        st.caption("Provincia según el código de área del teléfono; el % es sobre el total."
                   + (f" Fuera del mapa: {note}." if note else ""))

    def data():
        st.dataframe(counts, hide_index=True, width="stretch",
                     column_config={"%": st.column_config.NumberColumn(format="%.1f %%")})

    ui.chart_card(key, title, chart, data)
