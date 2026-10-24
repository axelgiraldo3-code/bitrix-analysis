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


TYPE_MAP = ":material/map:"
TYPE_BAR = ":material/align_horizontal_left:"


def zones_card(key: str, title: str, zones: pd.Series, unit: str, filename: str, *,
               toggle: bool = False, subtitle: str = "", height: int = 420) -> None:
    """Mapa de provincias + ranking, con la tabla de zonas detrás.

    Con ``toggle=True`` (tarjeta de media columna) muestra el mapa por
    defecto y un selector mapa ⇄ barras en lugar de ambos lado a lado."""
    if toggle:
        _zones_toggle_card(key, title, zones, unit, filename, subtitle, height)
        return
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


def _zone_bars(counts: pd.DataFrame, filename: str, height: int | None = None) -> None:
    top = counts.head(10)
    colors = [COTEAR_GRAY if z in geo.NON_PROVINCE_ZONES else COTEAR_BLUE
              for z in top["Zona"]]
    ui.echart(charts.hbar(top["Zona"].tolist(), top["Cantidad"].tolist(), colors, filename),
              height=height or max(220, 34 * len(top) + 40))


@st.fragment
def _zones_toggle_card(key: str, title: str, zones: pd.Series, unit: str, filename: str,
                       subtitle: str, height: int) -> None:
    total = int(len(zones))
    counts = geo.zone_counts(zones, threshold=0)
    note = geo.outside_map_note(counts, total, unit=unit)
    type_key = f"tipo_{key}"

    def controls():
        st.segmented_control("Tipo", [TYPE_MAP, TYPE_BAR], default=TYPE_MAP, required=True,
                             key=type_key, label_visibility="collapsed",
                             persist_state="session", help="Mapa ⇄ barras")

    def chart():
        if st.session_state.get(type_key, TYPE_MAP) == TYPE_BAR:
            _zone_bars(counts, filename, height)
        else:
            fig = geo.province_map(counts, total, unit=unit, height=height)
            if fig.data:
                ui.plotly_map(fig, key=f"map_{key}")
            else:
                st.info(f"Ninguna {unit[:-1]} pudo ubicarse en una provincia.")
        st.caption("Según el código de área del teléfono; % sobre el total."
                   + (f" Fuera del mapa: {note}." if note else ""))

    def data():
        st.dataframe(counts, hide_index=True, width="stretch",
                     column_config={"%": st.column_config.NumberColumn(format="%.1f %%")})

    ui.chart_card(key, title, chart, data, controls=controls, subtitle=subtitle)
