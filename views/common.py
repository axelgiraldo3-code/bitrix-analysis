"""Piezas compartidas entre páginas: filtros de mes y de período y tarjeta de
provincias."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

from utils import charts, geo, periods, ui
from utils.branding import COTEAR_BLUE, COTEAR_GRAY

# El mes es el mismo en el filtro de período y en Clasificación manual
MONTH_KEY = "mes"
MIN_YEAR = 2015


def month_filter(months: list[str]) -> str:
    """Selector de mes en la barra lateral (Clasificación manual; se conserva
    al cambiar de página y es el mismo mes del filtro de período)."""
    if st.session_state.get(MONTH_KEY) not in months:
        st.session_state.pop(MONTH_KEY, None)
    return st.sidebar.selectbox(
        "Mes",
        months,
        key=MONTH_KEY,
        persist_state="session",
        format_func=lambda ym: periods.month_label(ym, full=True),
    )


def _year_input(container, key: str, today) -> int:
    return int(
        container.number_input(
            "Año",
            min_value=MIN_YEAR,
            max_value=today.year + 1,
            value=today.year,
            step=1,
            key=key,
            persist_state="session",
        )
    )


def period_filter(months: list[str], *, reload_button: bool = False) -> periods.Period | None:
    """Selector de período en la barra lateral, compartido por Reporte,
    Negocios y Análisis: las mismas keys en las tres páginas, así el período
    se conserva al cambiar de página. ``None`` si el rango no es válido.

    ``reload_button``: "Recargar período desde API" (páginas que leen Bitrix
    por período; deja el pedido en ``_force_period``)."""
    today = datetime.now().date()
    sb = st.sidebar
    kind = sb.selectbox("Período", periods.KINDS, key="periodo_tipo", persist_state="session")
    if kind == "Mes":
        start, end = periods.month_bounds(month_filter(months))
    elif kind == "Trimestre":
        c1, c2 = sb.columns(2)
        year = _year_input(c1, "periodo_t_anio", today)
        q = c2.selectbox(
            "Trimestre",
            [1, 2, 3, 4],
            index=periods.current_quarter(today) - 1,
            format_func=lambda n: f"T{n}",
            key="periodo_t_num",
            persist_state="session",
        )
        start, end = periods.quarter_bounds(year, q)
    elif kind == "Semestre":
        c1, c2 = sb.columns(2)
        year = _year_input(c1, "periodo_s_anio", today)
        sem = c2.selectbox(
            "Semestre",
            [1, 2],
            index=periods.current_semester(today) - 1,
            format_func=lambda n: f"S{n}",
            key="periodo_s_num",
            persist_state="session",
        )
        start, end = periods.semester_bounds(year, sem)
    elif kind == "Año":
        start, end = periods.year_bounds(_year_input(sb, "periodo_anio", today))
    else:
        start = sb.date_input(
            "Desde",
            value=today.replace(day=1),
            key="periodo_desde",
            format="DD/MM/YYYY",
            persist_state="session",
        )
        end = sb.date_input(
            "Hasta", value=today, key="periodo_hasta", format="DD/MM/YYYY", persist_state="session"
        )
        if start > end:
            sb.error("'Desde' no puede ser posterior a 'Hasta'.")
            return None
    if reload_button and sb.button(
        "Recargar período desde API",
        help="Fuerza traer todos los meses del período desde Bitrix24 "
        "(ignora snapshots). Puede tardar si el período es largo.",
        key="periodo_recargar",
        width="stretch",
    ):
        st.session_state["_force_period"] = True
        st.rerun()
    return periods.Period(kind, start, end)


def period_vs(period: periods.Period) -> str:
    """Subtítulo del encabezado: 'Octubre 2026 comparado con septiembre 2026',
    'T3 2026 comparado con T2 2026'."""
    prev = period.previous.label()
    if period.is_month:
        prev = prev[0].lower() + prev[1:]
    return f"{period.label()} comparado con {prev}"


TYPE_MAP = ":material/map:"
TYPE_BAR = ":material/align_horizontal_left:"
PCT_COLUMN = {"%": st.column_config.NumberColumn(format="%.1f %%")}
CLICK_HINT = "Hacé clic en una provincia para ver sus localidades."
LOCALITY_NOTE = (
    "Localidad según el código de área (numeración geográfica del ENACOM): es la "
    "cabecera del área, puede no ser la ciudad exacta; % sobre el total de la provincia."
)


def zones_card(
    key: str,
    title: str,
    zones: pd.Series,
    unit: str,
    filename: str,
    *,
    localities: pd.Series | None = None,
    toggle: bool = False,
    subtitle: str = "",
    height: int = 420,
) -> None:
    """Mapa de provincias + ranking, con la tabla de zonas detrás.

    Con ``toggle=True`` (tarjeta de media columna) muestra el mapa por
    defecto y un selector mapa ⇄ barras en lugar de ambos lado a lado.

    Con ``localities`` (alineada con ``zones``) el mapa es clicable: al
    elegir una provincia, el mapa, el ranking y la tabla pasan a sus
    localidades, con un botón para volver a todas las provincias."""
    if toggle:
        _zones_toggle_card(key, title, zones, localities, unit, filename, subtitle, height)
    else:
        _zones_full_card(key, title, zones, localities, unit, filename, subtitle, height)


# ---------------------------------------------------------------------------
# Provincia elegida (clic en el mapa)
# ---------------------------------------------------------------------------
def _prov_key(key: str) -> str:
    return f"prov_{key}"


def _map_key(key: str) -> str:
    """Key del mapa de provincias. Cambia al volver, para que el widget nuevo
    no arrastre la selección anterior y vuelva a abrir el detalle."""
    return f"map_{key}_{st.session_state.get(f'_mapn_{key}', 0)}"


def _back_to_provinces(key: str) -> None:
    st.session_state.pop(_prov_key(key), None)
    st.session_state[f"_mapn_{key}"] = st.session_state.get(f"_mapn_{key}", 0) + 1


def clicked_province(state, locations: list[str]) -> str | None:
    """Provincia del clic según el estado de selección del mapa: el nombre va
    en ``customdata[0]``; si falta, se toma ``point_index`` sobre
    ``locations`` (el orden de las provincias del coroplético)."""
    try:
        points = state["selection"]["points"]
    except (KeyError, TypeError):
        return None
    for p in points or []:
        if p.get("curve_number", 0) != 0:  # sólo el coroplético (las etiquetas no)
            continue
        cd = p.get("customdata")
        if isinstance(cd, (list, tuple)) and cd and cd[0] in locations:
            return str(cd[0])
        if p.get("location") in locations:
            return str(p["location"])
        idx = p.get("point_index", p.get("point_number"))
        if isinstance(idx, int) and 0 <= idx < len(locations):
            return locations[idx]
    return None


def _selected_province(
    key: str, counts: pd.DataFrame, fig, localities: pd.Series | None
) -> str | None:
    """Provincia en detalle: un clic nuevo en el mapa (estado del widget, que
    se lee antes de dibujarlo) o la ya elegida, si sigue teniendo datos."""
    if localities is None:
        return None
    pkey = _prov_key(key)
    locations = list(fig.data[0].locations) if fig.data else []
    clicked = clicked_province(st.session_state.get(_map_key(key)), locations)
    if clicked:
        st.session_state[pkey] = clicked
        st.session_state[f"_mapn_{key}"] = st.session_state.get(f"_mapn_{key}", 0) + 1
    prov = st.session_state.get(pkey)
    if prov and prov not in set(counts["Zona"]):
        st.session_state.pop(pkey, None)
        return None
    return prov


def _province_header(key: str, prov: str, n: int, unit: str) -> None:
    c1, c2 = st.columns([3, 2], vertical_alignment="center")
    c1.markdown(f"**{prov}** · {ui.plural(n, unit)}")
    c2.button(
        "Todas las provincias",
        key=f"allprov_{key}",
        type="tertiary",
        on_click=_back_to_provinces,
        args=(key,),
        width="stretch",
    )


def _slug(text: str) -> str:
    return "_".join(text.split())


# ---------------------------------------------------------------------------
# Piezas de la tarjeta
# ---------------------------------------------------------------------------
def _rank_bars(
    names: list[str], values: list[int], filename: str, height: int | None = None
) -> None:
    """Ranking (top 10) en barras; lo que no es un lugar (Extranjero, Sin
    verificar, Sin identificar, Otros) va en gris."""
    names, values = names[:10], values[:10]
    colors = [COTEAR_GRAY if z in geo.NON_PROVINCE_ZONES else COTEAR_BLUE for z in names]
    ui.echart(
        charts.hbar(names, values, colors, filename),
        height=height or max(220, 34 * len(names) + 40),
    )


def _province_map(key: str, fig, unit: str, clickable: bool) -> None:
    if fig.data:
        ui.plotly_map(fig, key=_map_key(key), on_select=clickable)
    else:
        st.info(f"Ninguna {unit[:-1]} pudo ubicarse en una provincia.")


def _locality_map(key: str, lcounts: pd.DataFrame, prov: str, unit: str, height: int) -> None:
    fig = geo.locality_map(lcounts, prov, unit=unit, height=height)
    if fig.data:
        ui.plotly_map(fig, key=f"locmap_{key}")
    else:
        st.info(f"Ninguna {unit[:-1]} de {prov} pudo ubicarse en una localidad.")


def _locality_caption(lcounts: pd.DataFrame, prov: str, unit: str) -> None:
    note = geo.outside_locality_note(lcounts, prov, unit=unit)
    st.caption(LOCALITY_NOTE + (f" Fuera del mapa: {note}." if note else ""))


def _table(df: pd.DataFrame) -> None:
    st.dataframe(df, hide_index=True, width="stretch", column_config=PCT_COLUMN)


# ---------------------------------------------------------------------------
# Tarjetas
# ---------------------------------------------------------------------------
@st.fragment
def _zones_full_card(
    key: str,
    title: str,
    zones: pd.Series,
    localities: pd.Series | None,
    unit: str,
    filename: str,
    subtitle: str,
    height: int,
) -> None:
    total = int(len(zones))
    counts = geo.zone_counts(zones, threshold=0)
    note = geo.outside_map_note(counts, total, unit=unit)
    fig = geo.province_map(counts, total, unit=unit, height=height)
    prov = _selected_province(key, counts, fig, localities)
    lcounts = geo.locality_counts(zones, localities, prov) if prov else None

    def chart():
        if prov:
            _province_header(key, prov, int(lcounts["Cantidad"].sum()), unit)
        c_map, c_rank = st.columns([7, 5], vertical_alignment="center")
        with c_map:
            if prov:
                _locality_map(key, lcounts, prov, unit, height)
            else:
                _province_map(key, fig, unit, clickable=localities is not None)
        with c_rank:
            if prov:
                _rank_bars(
                    lcounts["Localidad"].tolist(),
                    lcounts["Cantidad"].tolist(),
                    f"{filename}_{_slug(prov)}",
                )
            else:
                _rank_bars(counts["Zona"].tolist(), counts["Cantidad"].tolist(), filename)
        if prov:
            _locality_caption(lcounts, prov, unit)
        else:
            st.caption(
                "Provincia según el código de área del teléfono; el % es sobre el total."
                + (f" Fuera del mapa: {note}." if note else "")
                + (f" {CLICK_HINT}" if localities is not None and fig.data else "")
            )

    def data():
        if prov:
            st.caption(f"Localidades de {prov}")
            _table(lcounts)
        else:
            _table(counts)

    ui.chart_card(key, title, chart, data, subtitle=subtitle)


@st.fragment
def _zones_toggle_card(
    key: str,
    title: str,
    zones: pd.Series,
    localities: pd.Series | None,
    unit: str,
    filename: str,
    subtitle: str,
    height: int,
) -> None:
    total = int(len(zones))
    counts = geo.zone_counts(zones, threshold=0)
    note = geo.outside_map_note(counts, total, unit=unit)
    fig = geo.province_map(counts, total, unit=unit, height=height)
    type_key = f"tipo_{key}"
    bars = st.session_state.get(type_key, TYPE_MAP) == TYPE_BAR
    # El mapa sólo existe en modo mapa: en barras no hay clic que leer
    prov = _selected_province(key, counts, fig, localities)
    lcounts = geo.locality_counts(zones, localities, prov) if prov else None

    def controls():
        st.segmented_control(
            "Tipo",
            [TYPE_MAP, TYPE_BAR],
            default=TYPE_MAP,
            required=True,
            key=type_key,
            label_visibility="collapsed",
            persist_state="session",
            help="Mapa ⇄ barras",
        )

    def chart():
        if prov:
            n = int(lcounts["Cantidad"].sum())
            _province_header(key, prov, n, unit)
            # El encabezado ocupa un renglón: el gráfico se achica para que la
            # tarjeta mantenga el alto de su vecina
            h = height - 44
            if bars:
                _rank_bars(
                    lcounts["Localidad"].tolist(),
                    lcounts["Cantidad"].tolist(),
                    f"{filename}_{_slug(prov)}",
                    h,
                )
            else:
                _locality_map(key, lcounts, prov, unit, h)
            _locality_caption(lcounts, prov, unit)
            return
        if bars:
            _rank_bars(counts["Zona"].tolist(), counts["Cantidad"].tolist(), filename, height)
        else:
            _province_map(key, fig, unit, clickable=localities is not None)
        st.caption(
            "Según el código de área del teléfono; % sobre el total."
            + (f" Fuera del mapa: {note}." if note else "")
            + (f" {CLICK_HINT}" if localities is not None and fig.data and not bars else "")
        )

    def data():
        if prov:
            st.caption(f"Localidades de {prov}")
            _table(lcounts)
        else:
            _table(counts)

    ui.chart_card(key, title, chart, data, controls=controls, subtitle=subtitle)
