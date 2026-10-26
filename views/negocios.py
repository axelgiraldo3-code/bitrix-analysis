"""Página "Negocios": negocios de venta de máquinas creados en el período."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from utils import charts, data, geo, kpis, periods, trends, ui
from utils.branding import (BITRIX_STAGE_COLORS, BITRIX_STAGE_ORDER, COTEAR_BLUE,
                            COTEAR_GRAY, canonical_motivo, canonical_source, motivo_color,
                            source_color)
from utils.styling import style_bitrix_table
from views.common import zones_card

TYPE_PIE = ":material/donut_large:"
TYPE_BAR = ":material/align_horizontal_left:"
MODE_COUNT = "Cantidad"
MODE_PCT = "Porcentaje"
TYPE_LINE = ":material/show_chart:"
TYPE_COLS = ":material/bar_chart:"
# Tipos de máquina que se dibujan por separado; el resto va en "Otros"
TOP_MACHINES = 6
# Altura común de las tarjetas "tipo de máquina" y "motivos de baja"
CHART_H = 500
# Altura común de "mes a mes" y "fuente principal"
EVOL_H = 340
# Altura común de "por fuente" y "por provincia"
BOTTOM_H = 380
PERIOD_KINDS = ["Mes", "Trimestre", "Semestre", "Año", "Rango personalizado"]


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
    elif kind == "Semestre":
        c1, c2 = sb.columns(2)
        year = int(c1.number_input("Año", min_value=2015, max_value=today.year + 1,
                                   value=today.year, step=1, key="bitrix_s_year",
                                   persist_state="session"))
        sem = c2.selectbox("Semestre", [1, 2], index=periods.current_semester(today) - 1,
                           format_func=lambda n: f"S{n}", key="bitrix_s_num",
                           persist_state="session")
        start, end = periods.semester_bounds(year, sem)
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
    if sb.button("Recargar período desde API",
                 help="Fuerza traer todos los meses del período desde Bitrix24 "
                      "(ignora snapshots). Puede tardar si el período es largo.",
                 key="bitrix_period_refresh", width="stretch"):
        st.session_state["_force_period"] = True
        st.rerun()
    return kind, start, end


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------
def _stats(b: pd.DataFrame | None) -> dict:
    """Valores de los KPI de un conjunto de negocios (vacío → ceros/None)."""
    if b is None or b.empty:
        return {"n": 0, "en_curso": 0, "cerrados": 0, "ganados": 0, "vida": None,
                "n_vida": 0, "fuente": pd.Series(dtype=str), "zona": pd.Series(dtype=str),
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


def _trends(monthly: list[dict] | None, months: list[str] | None = None) -> dict[str, list]:
    """Mini líneas de los KPI (un valor por mes, el último es el actual)."""
    if not monthly:
        return {}
    out = {k: [m[k] for m in monthly] for k in ("n", "en_curso", "cerrados", "ganados")}
    out["_months"] = list(months or [])
    out["vida"] = [round(m["vida"], 1) if m["vida"] is not None else None for m in monthly]
    out["fuente"] = trends.leader_trend([m["fuente"] for m in monthly])
    out["zona"] = trends.leader_trend([m["zona"] for m in monthly], geo.NON_PROVINCE_ZONES)
    out["motivo"] = trends.leader_trend([m["motivo"] for m in monthly])
    return out


def _kpis(cur: dict, prev: dict | None, vs: str, trend: dict[str, list]) -> None:
    def d(key, polarity, **kw):
        return kpis.delta_kwargs(cur[key], prev[key] if prev else None, polarity, vs=vs, **kw)

    fuente, fuente_kw = kpis.category_kwargs(cur["fuente"], prev["fuente"] if prev else None,
                                             kpis.UP_GOOD, "negocios")
    zona, zona_kw = kpis.category_kwargs(cur["zona"], prev["zona"] if prev else None,
                                         kpis.UP_GOOD, "negocios",
                                         exclude=geo.NON_PROVINCE_ZONES)
    motivo, motivo_kw = kpis.category_kwargs(cur["motivo"], prev["motivo"] if prev else None,
                                             kpis.DOWN_GOOD, "casos")
    vida_txt = f"{charts.fmt_dec(cur['vida'])} días" if cur["vida"] is not None else "—"
    months = trend.get("_months")

    def t(key):
        return {"trend": trend.get(key), "months": months}

    r1 = ui.kpi_row("volumen")
    ui.kpi(r1[0], "Negocios del período", cur["n"], d("n", kpis.UP_GOOD), **t("n"))
    ui.kpi(r1[1], "En curso", cur["en_curso"], d("en_curso", kpis.NEUTRAL),
           help="Negocios del período que todavía no están cerrados", **t("en_curso"))
    ui.kpi(r1[2], "Fuente destacada", fuente, fuente_kw, **t("fuente"))
    ui.kpi(r1[3], "Provincia con más negocios", zona, zona_kw, **t("zona"))
    r2 = ui.kpi_row("resultado")
    ui.kpi(r2[0], "Negocios cerrados", cur["cerrados"], d("cerrados", kpis.UP_GOOD),
           **t("cerrados"))
    ui.kpi(r2[1], "Ganados", cur["ganados"], d("ganados", kpis.UP_GOOD), **t("ganados"))
    ui.kpi(r2[2], "Motivo de baja más frecuente", motivo, motivo_kw, **t("motivo"))
    ui.kpi(r2[3], "Vida de negocio", vida_txt,
           d("vida", kpis.NEUTRAL, unit=" días", decimals=1), **t("vida"),
           help=(f"Días promedio entre la creación y el cierre (último movimiento) de "
                 f"los {cur['n_vida']} negocios cerrados del período, ganados y perdidos.")
           if cur["vida"] is not None else "Sin negocios cerrados con fechas válidas")


# ---------------------------------------------------------------------------
# Tarjetas
# ---------------------------------------------------------------------------
@st.fragment
def _evolucion_card(b: pd.DataFrame, months: list[str], label: str) -> None:
    """Negocios creados y cerrados en cada mes del período (cerrados: de los
    negocios creados ese mes, como en los KPI)."""
    created = trends.by_month(b["_cre_dt"], months)
    etapas = b["Etapa"].astype(str).str.strip().str.lower()
    closed_mask = etapas.str.startswith("cerrado")
    closed = trends.by_month(b.loc[closed_mask, "_cre_dt"], months)
    cats = [periods.month_label(m) for m in months]
    table_df = pd.DataFrame({"Mes": cats, "Negocios del período": created,
                             "Cerrados": closed})

    def controls():
        st.segmented_control("Tipo", [TYPE_LINE, TYPE_COLS], default=TYPE_LINE,
                             required=True, key="tipo_evolucion",
                             label_visibility="collapsed", persist_state="session")

    def chart():
        kind = "bar" if st.session_state.get("tipo_evolucion", TYPE_LINE) == TYPE_COLS \
            else "line"
        series = [("Negocios del período", created, COTEAR_BLUE),
                  ("Cerrados", closed, COTEAR_GRAY)]
        ui.echart(charts.timeseries(cats, series,
                                    f"evolucion_negocios_{label}", kind=kind,
                                    y_name="Negocios", width=620),
                  height=EVOL_H)

    def table():
        st.dataframe(table_df, hide_index=True, width="stretch")

    ui.chart_card("evolucion", "Mes a mes", chart, table, controls=controls)


@st.fragment
def _fuente_mes_card(b: pd.DataFrame, months: list[str], label: str) -> None:
    """La fuente con más negocios creados en cada mes, en su color."""
    leaders = trends.leader_by_month(b["_cre_dt"], b["Fuente"], months)
    cats = [periods.month_label(m) for m in months]
    colors = {name: source_color(name) for name, _, _ in leaders}
    table_df = pd.DataFrame({
        "Mes": cats, "Fuente principal": [n for n, _, _ in leaders],
        "Negocios": [v for _, v, _ in leaders],
        "Negocios del mes": [t for _, _, t in leaders],
        "%": [round(v / t * 100, 1) if t else None for _, v, t in leaders]})

    def chart():
        ui.echart(charts.leader_bars(cats, leaders, colors, f"fuente_principal_{label}",
                                     y_name="Negocios", width=440),
                  height=EVOL_H)

    def table():
        st.dataframe(table_df, hide_index=True, width="stretch",
                     column_config={"%": st.column_config.NumberColumn(format="%.1f %%")})

    ui.chart_card("fuente_mes", "Fuente principal", chart, table)


@st.fragment
def _maquina_card(b: pd.DataFrame, label: str) -> None:
    pivot = b.groupby(["Tipo maquinaria", "Etapa"]).size().unstack(fill_value=0)
    ordered = [c for c in BITRIX_STAGE_ORDER if c in pivot.columns] + \
              [c for c in pivot.columns if c not in BITRIX_STAGE_ORDER]
    pivot = pivot[ordered]
    total = pivot.sum(axis=1)
    pivot = pivot.loc[total.sort_values(ascending=False).index]
    # El gráfico muestra los principales y agrupa el resto; la tabla, todos
    chart_pivot = trends.top_with_others(pivot, TOP_MACHINES)

    def controls():
        st.segmented_control("Mostrar", [MODE_COUNT, MODE_PCT], default=MODE_COUNT,
                             required=True, key="bitrix_bar_mode",
                             label_visibility="collapsed", persist_state="session")

    def chart():
        pct = st.session_state.get("bitrix_bar_mode", MODE_COUNT) == MODE_PCT
        values = chart_pivot.div(chart_pivot.sum(axis=1), axis=0) * 100 if pct \
            else chart_pivot
        series = [(e, values[e].tolist(), BITRIX_STAGE_COLORS.get(e, "#BDC3C7"))
                  for e in chart_pivot.columns]
        ui.echart(charts.stacked_bars(chart_pivot.index.tolist(), series, f"actividad_{label}",
                                      y_name="% dentro del tipo" if pct else "Negocios",
                                      percent=pct, rotate=90, width=600,
                                      label_width=130),
                  height=CHART_H)

    def table():
        t = pivot.copy()
        t["Total"] = t.sum(axis=1)
        st.dataframe(t.reset_index(), hide_index=True, width="stretch")

    ui.chart_card("maquina_etapa", "Por máquina y etapa", chart, table, controls=controls)


@st.fragment
def _motivos_card(b: pd.DataFrame, label: str) -> None:
    perdidos = b[b["Motivo de baja"].astype(str).str.strip() != ""]
    motivos = perdidos["Motivo de baja"].astype(str).str.strip().value_counts().reset_index()
    motivos.columns = ["Motivo", "Cantidad"]
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
        names = motivos["Motivo"].tolist()
        values = motivos["Cantidad"].tolist()
        colors = [motivo_color(n) for n in names]
        if st.session_state.get("tipo_motivos", TYPE_PIE) == TYPE_BAR:
            opt = charts.hbar(names, values, colors, f"motivos_baja_{label}", label_width=140)
        else:
            opt = charts.donut(names, values, colors, f"motivos_baja_{label}", width=400,
                               height=CHART_H, label_width=130)
        ui.echart(opt, height=CHART_H)

    def table():
        st.dataframe(motivos, hide_index=True, width="stretch",
                     column_config={"%": st.column_config.NumberColumn(format="%.1f %%")})

    ui.chart_card("motivos", "Motivos de baja", chart, table, controls=controls)


def _canonicalize(df: pd.DataFrame | None) -> pd.DataFrame | None:
    """Unifica fuentes ("Email" → "Correo") y motivos de baja (sin la
    explicación entre paréntesis)."""
    if df is None or df.empty:
        return df
    df = df.copy()
    src = df["Fuente"] if "Fuente" in df else pd.Series("", index=df.index)
    df["Fuente"] = src.map(canonical_source)
    if "Motivo de baja" in df:
        df["Motivo de baja"] = df["Motivo de baja"].map(canonical_motivo)
    return df


@st.fragment
def _fuentes_card(b: pd.DataFrame, label: str) -> None:
    counts = b["Fuente"].value_counts()
    names = counts.index.tolist()          # sólo las fuentes con negocios, de mayor a menor
    values = [int(v) for v in counts.values]
    total = sum(values) or 1
    table_df = pd.DataFrame({"Fuente": names, "Cantidad": values,
                             "%": [round(v / total * 100, 1) for v in values]})

    def chart():
        ui.echart(charts.hbar(names, values, [source_color(n) for n in names],
                              f"negocios_por_fuente_{label}", label_width=170),
                  height=BOTTOM_H)

    def table():
        st.dataframe(table_df, hide_index=True, width="stretch",
                     column_config={"%": st.column_config.NumberColumn(format="%.1f %%")})

    ui.chart_card("fuentes", "Por fuente", chart, table)


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------
def _load(kind: str, start, end, p_start, p_end):
    """(negocios del período, del período anterior o None, KPIs por mes para
    la tendencia o None, sus meses o None, orígenes de lectura, avisos).

    En "Mes" se leen los últimos 6 meses de una vez: el anterior y la
    tendencia salen de ahí. En los demás períodos no hay mini línea (la
    evolución se ve en la tarjeta "Mes a mes")."""
    force = data.flag("_force_period")
    b, sources, warns = data.deals_created_between(start, end, force_refresh=force)
    if kind != "Mes":
        prev_b, prev_sources, prev_warns = data.deals_created_between(p_start, p_end)
        prev_ok = any(src != "error" for src in prev_sources.values())
        return (_canonicalize(b), _canonicalize(prev_b) if prev_ok else None, None, None,
                sources, warns + prev_warns)

    ym = f"{start.year:04d}-{start.month:02d}"
    months = [periods.shift_months(ym, -i) for i in range(data.TREND_MONTHS - 1, -1, -1)]
    h_start = periods.month_bounds(months[0])[0]
    hist, h_sources, h_warns = data.deals_created_between(h_start, end)
    hist = _canonicalize(hist)
    by_m = {m: (hist[hist["_cre_dt"].map(trends.month_key) == m] if not hist.empty
                else hist) for m in months}
    # Un mes sin lectura posible no tiene datos (no "0 negocios")
    monthly = [_stats(by_m[m]) if h_sources.get(m) != "error" else None for m in months]
    prev_ym = months[-2]
    prev_b = by_m[prev_ym] if h_sources.get(prev_ym) != "error" else None
    trend = [m if m is not None else _stats(None) for m in monthly]
    return (_canonicalize(b), prev_b, trend, months, {**h_sources, **sources},
            warns + [w for w in h_warns if w not in warns])


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
                   f"{prev_label[0].lower() + prev_label[1:] if kind == 'Mes' else prev_label}")

    with st.spinner("Cargando negocios de Bitrix…"):
        b, prev_b, monthly, trend_months, sources, warns = _load(kind, start, end,
                                                                 p_start, p_end)
    for w in warns:
        st.warning(w)

    if b.empty:
        st.info("No hay negocios de Bitrix creados en este período.")
        return

    _kpis(_stats(b), _stats(prev_b) if prev_b is not None else None, f"vs. {prev_short}",
          _trends(monthly, trend_months))

    # Los meses que todavía no empezaron no se dibujan (quedarían en 0)
    today = datetime.now().date()
    period_months = periods.year_months_spanning(start, min(end, today))
    if len(period_months) > 1:
        ui.section("Evolución del período")
        e1, e2 = st.columns([7, 5])
        with e1:
            _evolucion_card(b, period_months, label)
        with e2:
            _fuente_mes_card(b, period_months, label)

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
                   f"provincias_negocios_{label}", toggle=True, height=BOTTOM_H)

    listing_cols = ["Fecha movimiento", "Fecha creacion", "Nombre negocio", "Tipo maquinaria",
                    "Cliente", "Compania", "Etapa", "Etapa anterior", "Fuente",
                    "Motivo de baja", "Telefono", "Zona"]
    listing = b[[c for c in listing_cols if c in b.columns]]
    ui.raw_data("negocios", f"Lista de negocios del período ({len(listing)})",
                style_bitrix_table(listing), listing,
                f"actividad_comercial_negocios_{label}.csv",
                column_config={"Tipo maquinaria": {"hidden": True}})
