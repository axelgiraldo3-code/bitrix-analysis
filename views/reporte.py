"""Página "Reporte mensual": consultas del bot de WhatsApp."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from utils import cache, charts, data, geo, kpis, periods, ui
from utils.branding import CLASSIFICATION_COLORS, CLASSIFICATION_OPTIONS
from utils.styling import style_bot_table
from views.common import month_filter, zones_card

SIN_INTERES_REAL = ["SIN RESPUESTAS", "SIN INTERES"]
TYPE_PIE = ":material/donut_large:"
TYPE_BAR = ":material/align_horizontal_left:"


def _class_counts(df: pd.DataFrame) -> pd.DataFrame:
    counts = df["Clasificacion interna"].astype(str).value_counts().reset_index()
    counts.columns = ["Clasificación", "Cantidad"]
    counts["%"] = (counts["Cantidad"] / counts["Cantidad"].sum() * 100).round(1)
    return counts


@st.fragment
def _distribucion_card(df: pd.DataFrame, month: str) -> None:
    counts = _class_counts(df)
    colors = [CLASSIFICATION_COLORS.get(c, "#BDC3C7") for c in counts["Clasificación"]]
    filename = f"clasificaciones_{month}"

    def controls():
        st.segmented_control("Tipo", [TYPE_PIE, TYPE_BAR], default=TYPE_PIE, required=True,
                             key="tipo_clasificacion", label_visibility="collapsed",
                             persist_state="session")

    def chart():
        names, values = counts["Clasificación"].tolist(), counts["Cantidad"].tolist()
        if st.session_state.get("tipo_clasificacion", TYPE_PIE) == TYPE_BAR:
            opt = charts.hbar(names, values, colors, filename, label_width=170)
        else:
            opt = charts.donut(names, values, colors, filename, width=480, height=400,
                               label_width=170)
        ui.echart(opt, height=400)

    def table():
        st.dataframe(counts, hide_index=True, width="stretch",
                     column_config={"%": st.column_config.NumberColumn(format="%.1f %%")})

    ui.chart_card("distribucion", "Por clasificación", chart, table,
                  controls=controls)


def _area_card(df: pd.DataFrame, month: str) -> None:
    pivot = (df.groupby(["Area", "Clasificacion interna"]).size()
             .unstack(fill_value=0).reindex(index=cache.AREA_BUCKETS, fill_value=0))
    pivot = pivot[[c for c in CLASSIFICATION_OPTIONS if c in pivot.columns]]
    series = [(c, pivot[c].tolist(), CLASSIFICATION_COLORS[c]) for c in pivot.columns]

    def chart():
        ui.echart(charts.stacked_bars(cache.AREA_BUCKETS, series,
                                      f"area_clasificacion_{month}", y_name="Consultas",
                                      width=480),
                  height=400)

    def table():
        t = pivot.copy()
        t["Total"] = t.sum(axis=1)
        st.dataframe(t.reset_index().rename(columns={"Area": "Área de interés"}),
                     hide_index=True, width="stretch")
        st.caption("Áreas sin texto o sin coincidencia con Máquinas, Repuestos o "
                   "Servicio Técnico se cuentan como No identificado.")

    ui.chart_card("area", "Por área de interés", chart, table)


def _kpis(df: pd.DataFrame, prev: pd.DataFrame | None, prev_month: str) -> None:
    vs = f"vs. {periods.month_label(prev_month)}"
    total = len(df)
    prev_total = len(prev) if prev is not None else None

    def pct_sin_interes(d: pd.DataFrame | None):
        if d is None or d.empty:
            return None
        return d["Clasificacion interna"].astype(str).isin(SIN_INTERES_REAL).mean() * 100

    zona, zona_kw = kpis.category_kwargs(
        df["Zona"], prev["Zona"] if prev is not None else None, kpis.UP_GOOD,
        "consultas", exclude=geo.NON_PROVINCE_ZONES)
    area, area_kw = kpis.category_kwargs(
        df["Area"], prev["Area"] if prev is not None else None, kpis.UP_GOOD,
        "consultas", exclude={cache.AREA_NO_IDENTIFICADA})
    sin = pct_sin_interes(df)

    k1, k2, k3, k4 = st.columns(4)
    ui.kpi(k1, "Consultas del mes", total, kpis.delta_kwargs(total, prev_total, kpis.UP_GOOD, vs=vs))
    ui.kpi(k2, "Provincia con más consultas", zona, zona_kw)
    ui.kpi(k3, "Área de interés principal", area, area_kw)
    ui.kpi(k4, "Sin interés real", f"{sin:.1f} %",
           kpis.delta_kwargs(sin, pct_sin_interes(prev), kpis.DOWN_GOOD,
                             vs=vs, unit=" p.p.", decimals=1),
           help="% de consultas clasificadas SIN RESPUESTAS o SIN INTERES. "
                "Es un indicador negativo: bajar es bueno.")


def render() -> None:
    bot_raw = st.session_state["_bot_raw"]
    month = month_filter(st.session_state["_months_bot"])
    prev_month = periods.shift_months(month, -1)
    df, prev = data.month_with_previous(bot_raw, month)

    ui.page_header("Reporte mensual",
                   f"Consultas recibidas por el bot de WhatsApp · "
                   f"{periods.month_label(month, full=True)} comparado con "
                   f"{periods.month_label(prev_month, full=True).lower()}")
    if df.empty:
        st.info("Sin datos en el mes seleccionado.")
        return

    _kpis(df, prev, prev_month)

    ui.section("Calidad de las consultas")
    c1, c2 = st.columns(2)
    with c1:
        _distribucion_card(df, month)
    with c2:
        _area_card(df, month)

    ui.section("Origen de las consultas")
    zones_card("zonas_consultas", "Por provincia", df["Zona"],
               "consultas", f"provincias_consultas_{month}")

    cols = ["Fecha", "Nombre", "Numero", "Zona", "Area de interes", "Negocio",
            "Clasificacion interna"]
    ui.raw_data("consultas", f"Datos crudos del mes ({ui.plural(len(df), 'consultas')})",
                style_bot_table(df[cols]), df[cols + ["Area"]],
                f"actividad_comercial_consultas_{month}.csv")
