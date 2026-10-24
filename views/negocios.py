"""Página "Negocios": negocios de venta de máquinas creados en el período."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from utils import charts, data, geo, kpis, periods, ui
from utils.branding import (BITRIX_STAGE_COLORS, BITRIX_STAGE_ORDER, SOURCE_ORDER,
                            canonical_source, source_color)
from utils.styling import style_bitrix_table
from views.common import zones_card

TYPE_PIE = ":material/donut_large:"
TYPE_BAR = ":material/align_horizontal_left:"
MODE_COUNT = "Cantidad"
MODE_PCT = "Porcentaje"
# Altura común de las tarjetas "tipo de máquina" y "motivos de baja"
CHART_H = 500
# Altura común de "por fuente" y "por provincia"
BOTTOM_H = 380
PERIOD_KINDS = ["Mes", "Trimestre", "Año", "Rango personalizado"]


# ---------------------------------------------------------------------------
# Filtro de período (barra lateral)
# ---------------------------------------------------------------------------
def _period_filter(months: list[str]):
    today = datetime.now().date()
    sb = st.sidebar
    kind = sb.selectbox("Período", PERIOD_KINDS, key="bitrix_period_type",
                        persist_state="session")
    if kind == "Mes":
        ym = sb.selectbox("Mes", months, key="bitrix_period_month", persist_state="session",
                          format_func=lambda m: periods.month_label(m, full=True))
        start, end = periods.month_bounds(ym)
    elif kind == "Trimestre":
        c1, c2 = sb.columns(2)
        year = int(c1.number_input("Año", min_value=2015, max_value=today.year + 1,
                                   value=today.year, step=1, key="bitrix_q_year",
                                   persist_state="session"))
        q = c2.selectbox("Trimestre", [1, 2, 3, 4], index=periods.current_quarter(today) - 1,
                         format_func=lambda n: f"T{n}", key="bitrix_q_num",
                         persist_state="session")
        start, end = periods.quarter_bounds(year, q)
    elif kind == "Año":
        year = int(sb.number_input("Año", min_value=2015, max_value=today.year + 1,
                                   value=today.year, step=1, key="bitrix_y_year",
                                   persist_state="session"))
        start, end = periods.year_bounds(year)
    else:
        start = sb.date_input("Desde", value=today.replace(day=1), key="bitrix_range_start",
                              format="DD/MM/YYYY", persist_state="session")
        end = sb.date_input("Hasta", value=today, key="bitrix_range_end",
                            format="DD/MM/YYYY", persist_state="session")
        if start > end:
            sb.error("'Desde' no puede ser posterior a 'Hasta'.")
            return None
    if sb.button("Recargar período desde API", icon=":material/sync:",
                 help="Fuerza traer todos los meses del período desde Bitrix24 "
                      "(ignora snapshots). Puede tardar si el período es largo.",
                 key="bitrix_period_refresh", width="stretch"):
        st.session_state["_force_period"] = True
        st.rerun()
    return kind, start, end


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------
def _stats(b: pd.DataFrame) -> dict:
    """Valores de los KPI de un conjunto de negocios (vacío → ceros/None)."""
    if b is None or b.empty:
        return {"n": 0, "en_curso": 0, "cerrados": 0, "ganados": 0, "vida": None,
                "fuente": pd.Series(dtype=str), "zona": pd.Series(dtype=str),
                "motivo": pd.Series(dtype=str)}
    etapas = b["Etapa"].astype(str).str.strip().str.lower()
    ganado = etapas.str.startswith("cerrado ganado")
    perdido = etapas.str.startswith("cerrado perdido")
    cerrado = ganado | perdido
    vidas = (b.loc[cerrado, "_mov_dt"] - b.loc[cerrado, "_cre_dt"]).dt.days.dropna()
    vidas = vidas[vidas >= 0]
    return {
        "n": len(b), "en_curso": int((~cerrado).sum()), "cerrados": int(cerrado.sum()),
        "ganados": int(ganado.sum()), "vida": float(vidas.mean()) if not vidas.empty else None,
        "n_vida": len(vidas),
        "fuente": b.get("Fuente", pd.Series(dtype=str)),
        "zona": b["Zona"],
        "motivo": b.loc[perdido, "Motivo de baja"] if "Motivo de baja" in b else pd.Series(dtype=str),
    }


def _kpis(cur: dict, prev: dict | None, vs: str) -> None:
    def d(key, polarity, **kw):
        return kpis.delta_kwargs(cur[key], prev[key] if prev else None, polarity, vs=vs, **kw)

    fuente, fuente_kw = kpis.category_kwargs(cur["fuente"], prev["fuente"] if prev else None,
                                             kpis.UP_GOOD, "negocios")
    zona, zona_kw = kpis.category_kwargs(cur["zona"], prev["zona"] if prev else None,
                                         kpis.UP_GOOD, "negocios",
                                         exclude=geo.NON_PROVINCE_ZONES)
    motivo, motivo_kw = kpis.category_kwargs(cur["motivo"], prev["motivo"] if prev else None,
                                             kpis.DOWN_GOOD, "casos")
    vida_txt = f"{cur['vida']:.1f} días" if cur["vida"] is not None else "—"

    r1 = st.columns(4)
    ui.kpi(r1[0], "Negocios del período", cur["n"], d("n", kpis.UP_GOOD))
    ui.kpi(r1[1], "En curso", cur["en_curso"], d("en_curso", kpis.NEUTRAL),
           help="Negocios del período que todavía no están cerrados")
    ui.kpi(r1[2], "Fuente destacada", fuente, fuente_kw)
    ui.kpi(r1[3], "Provincia con más negocios", zona, zona_kw)
    r2 = st.columns(4)
    ui.kpi(r2[0], "Negocios cerrados", cur["cerrados"], d("cerrados", kpis.UP_GOOD))
    ui.kpi(r2[1], "Ganados", cur["ganados"], d("ganados", kpis.UP_GOOD))
    ui.kpi(r2[2], "Motivo de baja más frecuente", motivo, motivo_kw,
           help="Indicador negativo: que baje la cantidad de casos es bueno.")
    ui.kpi(r2[3], "Vida de negocio", vida_txt,
           d("vida", kpis.NEUTRAL, unit=" días", decimals=1),
           help=(f"Días promedio entre la creación y el cierre (último movimiento) de "
                 f"los {cur['n_vida']} negocios cerrados del período, ganados y perdidos.")
           if cur["vida"] is not None else "Sin negocios cerrados con fechas válidas")


# ---------------------------------------------------------------------------
# Tarjetas
# ---------------------------------------------------------------------------
@st.fragment
def _maquina_card(b: pd.DataFrame, label: str) -> None:
    pivot = b.groupby(["Tipo maquinaria", "Etapa"]).size().unstack(fill_value=0)
    ordered = [c for c in BITRIX_STAGE_ORDER if c in pivot.columns] + \
              [c for c in pivot.columns if c not in BITRIX_STAGE_ORDER]
    pivot = pivot[ordered]
    total = pivot.sum(axis=1)
    pivot = pivot.loc[total.sort_values(ascending=False).index]

    def controls():
        st.segmented_control("Mostrar", [MODE_COUNT, MODE_PCT], default=MODE_COUNT,
                             required=True, key="bitrix_bar_mode",
                             label_visibility="collapsed", persist_state="session")

    def chart():
        pct = st.session_state.get("bitrix_bar_mode", MODE_COUNT) == MODE_PCT
        values = pivot.div(pivot.sum(axis=1), axis=0) * 100 if pct else pivot
        series = [(e, values[e].tolist(), BITRIX_STAGE_COLORS.get(e, "#BDC3C7"))
                  for e in pivot.columns]
        ui.echart(charts.stacked_bars(pivot.index.tolist(), series, f"actividad_{label}",
                                      y_name="% dentro del tipo" if pct else "Negocios",
                                      percent=pct, rotate=90, width=600,
                                      label_width=130),
                  height=CHART_H)

    def table():
        t = pivot.copy()
        t["Total"] = t.sum(axis=1)
        st.dataframe(t.reset_index(), hide_index=True, width="stretch")

    ui.chart_card("maquina_etapa", "Por máquina y etapa", chart, table,
                  controls=controls,
                  subtitle="Etapa actual de cada negocio, por tipo de máquina.")


@st.fragment
def _motivos_card(b: pd.DataFrame, label: str) -> None:
    perdidos = b[b["Motivo de baja"].astype(str).str.strip() != ""]
    motivos = (perdidos["Motivo de baja"].astype(str).str.strip()
               .value_counts().reset_index())
    motivos.columns = ["Motivo completo", "Cantidad"]
    motivos["%"] = (motivos["Cantidad"] / motivos["Cantidad"].sum() * 100).round(1) \
        if not motivos.empty else []

    def controls():
        st.segmented_control("Tipo", [TYPE_PIE, TYPE_BAR], default=TYPE_PIE, required=True,
                             key="tipo_motivos", label_visibility="collapsed",
                             persist_state="session")

    def chart():
        if motivos.empty:
            st.info("No hay negocios perdidos con motivo cargado en el período.")
            return
        names = motivos["Motivo completo"].tolist()
        values = motivos["Cantidad"].tolist()
        colors = [charts.series_color(i) for i in range(len(names))]
        if st.session_state.get("tipo_motivos", TYPE_PIE) == TYPE_BAR:
            opt = charts.hbar(names, values, colors, f"motivos_baja_{label}", label_width=140)
        else:
            opt = charts.donut(names, values, colors, f"motivos_baja_{label}", width=400,
                               height=CHART_H, label_width=130)
        ui.echart(opt, height=CHART_H)

    def table():
        st.dataframe(motivos[["Motivo completo", "Cantidad", "%"]].rename(
            columns={"Motivo completo": "Motivo"}), hide_index=True, width="stretch",
            column_config={"%": st.column_config.NumberColumn(format="%.1f %%")})

    ui.chart_card("motivos", "Motivos de baja", chart, table, controls=controls,
                  subtitle="Por qué se perdieron los negocios.")


def _canon_sources(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Unifica los nombres de fuente (ej. "Email" → "Correo")."""
    if df is None or df.empty:
        return df
    df = df.copy()
    src = df["Fuente"] if "Fuente" in df else pd.Series("", index=df.index)
    df["Fuente"] = src.map(canonical_source)
    return df


@st.fragment
def _fuentes_card(b: pd.DataFrame, label: str) -> None:
    counts = b["Fuente"].value_counts()
    # Siempre las fuentes oficiales (aunque estén en 0) para comparar entre meses;
    # al final, las que no están en la lista.
    names = SOURCE_ORDER + [n for n in counts.index if n not in SOURCE_ORDER]
    # Mayor a menor; a igual cantidad se respeta el orden de la lista
    names = sorted(names, key=lambda n: -int(counts.get(n, 0)))
    values = [int(counts.get(n, 0)) for n in names]
    total = sum(values) or 1
    table_df = pd.DataFrame({"Fuente": names, "Cantidad": values,
                             "%": [round(v / total * 100, 1) for v in values]})

    def chart():
        ui.echart(charts.hbar(names, values, [source_color(n) for n in names],
                              f"negocios_por_fuente_{label}", label_width=170),
                  height=BOTTOM_H)
        st.caption("Siempre se muestran todas las fuentes, aunque estén en 0. "
                   "Sin fuente u otras no listadas, en gris.")

    def table():
        st.dataframe(table_df, hide_index=True, width="stretch",
                     column_config={"%": st.column_config.NumberColumn(format="%.1f %%")})

    ui.chart_card("fuentes", "Por fuente", chart, table,
                  subtitle="Canal por el que llegó cada negocio.")


# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------
def render() -> None:
    sel = _period_filter(st.session_state["_months_bot"])
    if sel is None:
        ui.page_header("Negocios Bitrix24")
        st.info("Elegí un rango válido en la barra lateral.")
        return
    kind, start, end = sel
    p_start, p_end = periods.previous_period(start, end, kind)
    label = f"{start.strftime('%d-%m-%y')}_a_{end.strftime('%d-%m-%y')}"
    prev_label = periods.period_label(p_start, p_end, kind)
    prev_short = periods.period_label(p_start, p_end, kind, short=True)

    ui.page_header("Negocios Bitrix24",
                   f"Negocios de venta de máquinas creados en el período · "
                   f"{periods.period_label(start, end, kind)} comparado con "
                   f"{prev_label[0].lower() + prev_label[1:]}")

    force = data.flag("_force_period")
    with st.spinner("Cargando negocios de Bitrix…"):
        b, sources, warns = data.deals_created_between(start, end, force_refresh=force)
        prev_b, prev_sources, prev_warns = data.deals_created_between(p_start, p_end)
    b, prev_b = (_canon_sources(df) for df in (b, prev_b))
    for w in warns + prev_warns:
        st.warning(w)

    n_api = sum(1 for s in sources.values() if s == "api")
    n_snap = sum(1 for s in sources.values() if s == "snapshot")
    st.caption(f"{len(sources)} mes(es) leídos — {n_snap} desde snapshot, {n_api} desde API.")

    if b.empty:
        st.info("No hay negocios de Bitrix creados en este período.")
        return

    prev_ok = any(src != "error" for src in prev_sources.values())
    _kpis(_stats(b), _stats(prev_b) if prev_ok else None, f"vs. {prev_short}")

    ui.section("Estado del pipeline")
    c1, c2 = st.columns([7, 5])
    with c1:
        _maquina_card(b, label)
    with c2:
        _motivos_card(b, label)

    ui.section("Distribución de negocios")
    c3, c4 = st.columns(2)
    with c3:
        _fuentes_card(b, label)
    with c4:
        zones_card("zonas_negocios", "Por provincia", b["Zona"], "negocios",
                   f"provincias_negocios_{label}", toggle=True, height=BOTTOM_H,
                   subtitle="Provincia según el teléfono del cliente.")

    listing_cols = ["Fecha movimiento", "Fecha creacion", "Nombre negocio", "Tipo maquinaria",
                    "Cliente", "Compania", "Etapa", "Etapa anterior", "Fuente",
                    "Motivo de baja", "Telefono", "Zona"]
    listing = b[[c for c in listing_cols if c in b.columns]]
    ui.raw_data("negocios", f"Lista de negocios del período ({len(listing)})",
                style_bitrix_table(listing), listing,
                f"actividad_comercial_negocios_{label}.csv",
                column_config={"Tipo maquinaria": {"hidden": True}})
