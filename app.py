"""COTEAR — App de análisis de consultas y negociaciones.

Ejecutar localmente:
    streamlit run app.py
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from utils import bitrix, cache, geo, pending, periods, sheets
from utils.branding import (
    BITRIX_STAGE_COLORS,
    BITRIX_STAGE_ORDER,
    CLASSIFICATION_COLORS,
    CLASSIFICATION_OPTIONS,
    COTEAR_BLUE,
    COTEAR_GRAY,
)
from utils.phone_ar import province_of, significant_ar
from utils.styling import style_bitrix_table, style_bot_table


st.set_page_config(
    page_title="COTEAR — Análisis de consultas",
    page_icon="📊",
    layout="wide",
)

BITRIX_SNAPSHOT_TTL_DAYS = 7
PHONE_INDEX_TTL_DAYS = 7
BITRIX_MEMO_TTL_SEC = 600
CSV_ENCODING = "utf-8-sig"  # BOM: Excel en español muestra bien las tildes

PLOTLY_CONFIG = {"displaylogo": False}


def _png_config(filename: str) -> dict:
    return {
        **PLOTLY_CONFIG,
        "toImageButtonOptions": {
            "format": "png", "filename": filename,
            "width": 1200, "height": 700, "scale": 2,
        },
    }


def section(name: str):
    """Contenedor con marco y fondo suave para separar visualmente cada sección."""
    return st.container(border=True, key=f"seccion_{name}")


def _csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode(CSV_ENCODING)


# --- Estilos globales ---------------------------------------------------------
st.markdown(
    f"""
    <style>
      h1, h2, h3 {{ color: {COTEAR_BLUE}; font-weight: 800; }}
      .stTabs [data-baseweb="tab"] {{ font-weight: 700; }}
      .stTabs [aria-selected="true"] {{ color: {COTEAR_BLUE}; }}
      .cotear-muted {{ color: {COTEAR_GRAY}; font-size: 0.9rem; }}
      /* Marco de secciones (st.container con key "seccion_*") */
      div[class*="st-key-seccion_"] {{
        background-color: #FAFBFC;
        border: none !important;
        border-radius: 16px !important;
        padding: 1.25rem 1.5rem 1rem 1.5rem;
        margin-bottom: 0.75rem;
      }}
      div[class*="st-key-seccion_"] h3 {{ margin-top: 0; }}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("COTEAR — Panel de consultas y negociaciones")


# --- Recuperación de cola pendiente desde disco (una vez por sesión) ---------
_recovered = pending.load_from_disk_once()
if _recovered:
    with st.container(border=True):
        st.warning(
            f"Se encontraron **{len(_recovered)} cambios sin sincronizar** "
            "de una sesión anterior. Revisá y decidí qué hacer."
        )
        st.dataframe(pending.as_dataframe(), hide_index=True, width="stretch")
        rc1, rc2, _ = st.columns([1, 1, 4])
        with rc1:
            if st.button("Mantener en cola", type="primary", key="pending_recover_keep"):
                st.rerun()
        with rc2:
            if st.button("Descartar todo", key="pending_recover_discard"):
                pending.clear()
                st.rerun()


# -----------------------------------------------------------------------------
# Carga de datos
# -----------------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner="Descargando reportes del bot…")
def load_bot() -> pd.DataFrame:
    return cache.clean_source(sheets.read_source_bot_reports())


def _bitrix_snapshot_from_sheets(year_month: str) -> pd.DataFrame:
    """Reconstruye el DataFrame Bitrix desde la pestaña YYYY-MM_Bitrix."""
    df = sheets.read_month_dataframe(year_month, "Bitrix")
    if df.empty:
        return df
    df = df.copy()
    df["_phone_sig"] = df["Telefono"].map(significant_ar)
    return df


def load_bitrix_month(year_month: str, force_refresh: bool = False) -> tuple[pd.DataFrame, str, str]:
    """(df, origen, aviso) para un mes. origen ∈ {'snapshot','api','error'}.

    Snapshot-first con TTL de 7 días; force_refresh=True va siempre a la API.
    El resultado se memoiza en la sesión (10 min). La escritura en Sheets
    ocurre acá, fuera de cualquier función cacheada.
    """
    memo = st.session_state.setdefault("_bitrix_memo", {})
    hit = memo.get(year_month)
    if hit and not force_refresh and time.time() - hit["t"] < BITRIX_MEMO_TTL_SEC:
        return hit["v"]

    result: tuple[pd.DataFrame, str, str]
    snap_fresh = False
    if not force_refresh:
        last_sync = sheets.get_last_bitrix_sync(year_month)
        snap_fresh = bool(last_sync and (datetime.now() - last_sync).days < BITRIX_SNAPSHOT_TTL_DAYS)
    snap = _bitrix_snapshot_from_sheets(year_month) if snap_fresh else pd.DataFrame()
    if not snap.empty:
        result = (snap, "snapshot", "")
    else:
        try:
            with st.spinner(f"Descargando actividad de Bitrix24 ({year_month})…"):
                deals = bitrix.fetch_activity_for_month(year_month)
                df = bitrix.deals_to_dataframe(deals, year_month=year_month)
            if not df.empty:
                sheets.write_month_dataframe(year_month, "Bitrix",
                                             df.drop(columns=["_phone_sig"], errors="ignore"))
                sheets.set_last_bitrix_sync(year_month)
            result = (df, "api", "")
        except Exception as e:
            snap = _bitrix_snapshot_from_sheets(year_month)
            if not snap.empty:
                result = (snap, "snapshot", f"API de Bitrix falló ({e}). Usando snapshot vencido de {year_month}.")
            else:
                result = (pd.DataFrame(columns=bitrix.DEAL_COLUMNS_OUT), "error",
                          f"No se pudo leer Bitrix ({year_month}): {e}")
    memo[year_month] = {"t": time.time(), "v": result}
    return result


def load_bitrix_period(year_months: tuple[str, ...], force_refresh: bool = False
                       ) -> tuple[pd.DataFrame, dict[str, str], list[str]]:
    """Agrega varios meses de Bitrix y deduplica por 'ID negocio' quedándose
    con la copia del mes más reciente (la más actualizada)."""
    frames, sources, warns = [], {}, []
    for ym in year_months:
        df, src, warn = load_bitrix_month(ym, force_refresh=force_refresh)
        sources[ym] = src
        if warn:
            warns.append(warn)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=bitrix.DEAL_COLUMNS_OUT), sources, warns
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset="ID negocio", keep="last")
    return out, sources, warns


def load_phone_index(force_refresh: bool = False) -> tuple[pd.DataFrame, str]:
    """Índice de teléfonos de todos los deals de venta. Se refresca desde la API
    cada 7 días (o a pedido) y se guarda en la pestaña _bitrix_telefonos."""
    memo = st.session_state.get("_phone_index_memo")
    if memo is not None and not force_refresh:
        return memo
    warn = ""
    try:
        df, ts = sheets.read_phone_index()
    except Exception as e:
        df, ts, warn = pd.DataFrame(columns=sheets.PHONE_INDEX_HEADERS), None, f"No se pudo leer el índice de teléfonos: {e}"
    stale = ts is None or (datetime.now() - ts).days >= PHONE_INDEX_TTL_DAYS
    if force_refresh or stale:
        try:
            with st.spinner("Actualizando índice de teléfonos de Bitrix24 (todos los negocios)…"):
                df = bitrix.fetch_phone_index()
                sheets.write_phone_index(df)
            warn = ""
        except Exception as e:
            warn = f"No se pudo actualizar el índice de teléfonos de Bitrix: {e}"
    result = (df, warn)
    st.session_state["_phone_index_memo"] = result
    return result


@st.cache_data(ttl=600, show_spinner=False)
def process_month(month_bot: pd.DataFrame, lookup: pd.DataFrame,
                  ignored: frozenset[str]) -> pd.DataFrame:
    """Ignorados → unificación por número/mes → reglas automáticas → nombres."""
    df = cache.filter_ignored(month_bot, set(ignored))
    df = cache.unify_recent(df)
    df = cache.apply_auto_rules(df, set(lookup["_phone_sig"]) - {""})
    df = cache.overwrite_names_from_bitrix(df, lookup)
    return df


def apply_persisted(df: pd.DataFrame, year_month: str) -> pd.DataFrame:
    """Superpone las clasificaciones guardadas en la hoja del mes y después la
    cola de cambios pendientes (la cola pisa a lo persistido)."""
    try:
        persisted = sheets.load_persisted_classifications(year_month)
    except Exception as e:
        st.warning(f"No se pudo leer la hoja del mes {year_month}: {e}")
        persisted = {}
    out = df.copy()
    if persisted:
        mapped = out["Numero"].astype(str).map(persisted)
        out["Clasificacion interna"] = mapped.fillna(out["Clasificacion interna"])
    return pending.apply_to_df(out)


def sync_month_if_changed(year_month: str, month_df: pd.DataFrame, ignored: set[str]) -> None:
    """Persiste el mes sólo si cambiaron (número, clasificación, nombre)
    desde la última sincronización de esta sesión."""
    if month_df.empty:
        return
    key = str(hash(tuple(
        month_df[["Numero", "Clasificacion interna", "Nombre"]].astype(str).itertuples(index=False)
    )))
    synced = st.session_state.setdefault("_synced_months", {})
    if synced.get(year_month) == key:
        return
    try:
        sheets.sync_month_bot(year_month, month_df, ignored_keys=ignored)
        synced[year_month] = key
    except Exception as e:
        st.warning(f"No se pudo sincronizar el mes {year_month}: {e}")


# -----------------------------------------------------------------------------
# Datos del bot y selección de mes
# -----------------------------------------------------------------------------
try:
    bot_raw = load_bot()
except Exception as e:
    st.error(f"No se pudieron leer los reportes del bot: {e}")
    st.stop()

months_bot = cache.available_year_months(bot_raw)
if not months_bot:
    st.info("No hay reportes del bot todavía.")
    st.stop()

selected_month = st.selectbox("Filtrar por mes", months_bot, index=0)

# Pedidos de recarga: se guardan como flag y se consumen en el run siguiente
force_month = st.session_state.pop("_force_month", False)
force_period = st.session_state.pop("_force_period", False)
force_index = st.session_state.pop("_force_index", False)

with st.sidebar:
    st.subheader("Datos")
    last_sync = sheets.get_last_bitrix_sync(selected_month)
    if last_sync:
        age_days = (datetime.now() - last_sync).days
        emoji = "🟢" if age_days < BITRIX_SNAPSHOT_TTL_DAYS else "🟡"
        st.caption(f"{emoji} Bitrix {selected_month}: sync {last_sync.strftime('%d-%m-%y %H:%M')} "
                   f"({age_days}d)")
    else:
        st.caption(f"⚪ Bitrix {selected_month}: sin snapshot")

    if st.button("🔄 Recargar Bitrix desde API",
                 help="Fuerza traer los negocios del mes desde Bitrix24 "
                      "(ignora el snapshot). Se refresca solo cada 7 días."):
        st.session_state["_force_month"] = True
        st.rerun()
    if st.button("📇 Actualizar índice de teléfonos",
                 help="Vuelve a leer los teléfonos de todos los negocios de venta "
                      "(se usa para clasificar DERIVADO A BITRIX). Se refresca solo cada 7 días."):
        st.session_state["_force_index"] = True
        st.rerun()
    if st.button("🧹 Limpiar caché"):
        st.cache_data.clear()
        for k in ("_bitrix_memo", "_phone_index_memo", "_synced_months"):
            st.session_state.pop(k, None)
        st.rerun()

    st.divider()
    st.subheader("Cambios pendientes")
    _pending_count = pending.count()
    if _pending_count == 0:
        st.caption("Sin cambios en cola.")
    else:
        st.markdown(
            f"<div style='padding:6px 10px;border-radius:6px;"
            f"background:{COTEAR_BLUE};color:white;display:inline-block;"
            f"font-weight:700;'>{_pending_count} pendientes</div>",
            unsafe_allow_html=True,
        )
        with st.expander("Ver pendientes"):
            st.dataframe(pending.as_dataframe(), hide_index=True, width="stretch")

        sync_col, disc_col = st.columns(2)
        with sync_col:
            if st.button("⬆️ Sincronizar", type="primary", key="pending_sync"):
                by_month: dict[str, list[dict]] = defaultdict(list)
                for num, v in pending.get().items():
                    row = {
                        "Fecha": v.get("Fecha", ""),
                        "Numero": num,
                        "Nombre": v.get("Nombre", ""),
                        "Clasificacion interna": v.get("Clasificacion interna", ""),
                    }
                    try:
                        d = datetime.strptime(str(row["Fecha"]), "%d-%m-%y")
                        ym = f"{d.year:04d}-{d.month:02d}"
                    except ValueError:
                        ym = selected_month
                    by_month[ym].append(row)
                try:
                    for ym, rs in by_month.items():
                        sheets.batch_upsert_bot_rows(ym, rs, key_col="Numero")
                    n = pending.count()
                    pending.clear()
                    st.session_state.pop("_synced_months", None)
                    st.success(f"Sincronizados {n} cambios.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al sincronizar (la cola queda intacta): {e}")
        with disc_col:
            if st.button("🗑️ Descartar", key="pending_discard"):
                pending.clear()
                st.rerun()

# Bitrix del mes + índice de teléfonos de todos los deals
bitrix_df, bitrix_source, bitrix_warn = load_bitrix_month(selected_month, force_refresh=force_month)
if bitrix_warn:
    st.warning(bitrix_warn)
phone_index, index_warn = load_phone_index(force_refresh=force_index)
if index_warn:
    st.warning(index_warn)

# Lookup teléfono → nombre: primero los deals del mes (más actuales), después el índice
lookup = pd.concat(
    [bitrix_df.reindex(columns=["_phone_sig", "Cliente"]),
     phone_index.reindex(columns=["_phone_sig", "Cliente"])],
    ignore_index=True,
).fillna("")
lookup = lookup[lookup["_phone_sig"] != ""].drop_duplicates("_phone_sig", keep="first")

try:
    ignored = sheets.load_ignored_phones()
except Exception as e:
    st.warning(f"No se pudo leer la lista de números ignorados: {e}")
    ignored = set()

month_bot = cache.filter_by_year_month(bot_raw, selected_month)
month_df = apply_persisted(
    process_month(month_bot, lookup.reset_index(drop=True), frozenset(ignored)),
    selected_month,
)
sync_month_if_changed(selected_month, month_df, ignored)
month_df["Area"] = month_df["Area de interes"].map(cache.area_bucket)


# -----------------------------------------------------------------------------
# Tabs
# -----------------------------------------------------------------------------
tab_reportes, tab_negocios, tab_clasif = st.tabs([
    "Reporte mensual",
    "Negocios Bitrix24",
    "Clasificación Manual",
])


def _zone_pie(counts: pd.DataFrame, filename: str, height: int = 420) -> None:
    """Torta de zonas + tabla al costado."""
    c1, c2 = st.columns([2, 1])
    with c1:
        colors = {z: COTEAR_GRAY for z in (geo.OTHERS,)}
        fig = px.pie(counts, names="Zona", values="Cantidad", hole=0.35,
                     color="Zona", color_discrete_map=colors,
                     color_discrete_sequence=px.colors.qualitative.Safe)
        fig.update_traces(sort=False)
        fig.update_layout(height=height, margin=dict(t=30, b=30, l=30, r=30),
                          paper_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig, width="stretch", config=_png_config(filename))
    with c2:
        st.dataframe(counts, hide_index=True, width="stretch")


# =============================================================================
# TAB — Reporte mensual
# =============================================================================
with tab_reportes:
    st.subheader("Reporte mensual de consultas")
    if month_df.empty:
        st.info("Sin datos en el mes seleccionado.")
    else:
        total = len(month_df)
        cls = month_df["Clasificacion interna"].astype(str)
        pct_sin_interes_real = cls.isin(["SIN RESPUESTAS", "SIN INTERES"]).mean() * 100
        zona_top, zona_n = geo.top_province(month_df["Zona"])
        areas_id = month_df.loc[month_df["Area"] != cache.AREA_NO_IDENTIFICADA, "Area"]
        if areas_id.empty:
            area_top, area_n = "—", 0
        else:
            vc = areas_id.value_counts()
            area_top, area_n = str(vc.index[0]), int(vc.iloc[0])

        with section("kpis_reporte"):
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Consultas del mes", total)
            k2.metric("Provincia con más consultas", zona_top,
                      delta=f"{zona_n} consultas" if zona_n else None, delta_color="off")
            k3.metric("Área de interés principal", area_top,
                      delta=f"{area_n} consultas" if area_n else None, delta_color="off")
            k4.metric("Sin interés real", f"{pct_sin_interes_real:.1f} %",
                      help="% de consultas clasificadas SIN RESPUESTAS o SIN INTERES")

        # --- Distribución por clasificación ------------------------------
        with section("distribucion"):
            st.markdown("### Distribución por clasificación")
            counts = cls.value_counts().reset_index()
            counts.columns = ["Clasificación", "Cantidad"]
            counts["%"] = (counts["Cantidad"] / counts["Cantidad"].sum() * 100).round(1)
            c1, c2 = st.columns([2, 1])
            with c1:
                fig = px.pie(counts, names="Clasificación", values="Cantidad",
                             color="Clasificación", color_discrete_map=CLASSIFICATION_COLORS,
                             hole=0.35)
                fig.update_layout(height=440, margin=dict(t=30, b=30, l=30, r=30),
                                  paper_bgcolor="rgba(0,0,0,0)")
                st.plotly_chart(fig, width="stretch",
                                config=_png_config(f"clasificaciones_{selected_month}"))
            with c2:
                st.dataframe(counts, hide_index=True, width="stretch")

        # --- Área de interés × clasificación -----------------------------
        with section("area"):
            st.markdown("### Área de interés por clasificación")
            area_pivot = (month_df.groupby(["Area", "Clasificacion interna"]).size()
                          .unstack(fill_value=0)
                          .reindex(index=cache.AREA_BUCKETS, fill_value=0))
            area_pivot = area_pivot[[c for c in CLASSIFICATION_OPTIONS if c in area_pivot.columns]]
            area_long = area_pivot.reset_index().melt(
                id_vars="Area", var_name="Clasificación", value_name="Cantidad")
            area_long["label"] = area_long["Cantidad"].map(lambda v: str(int(v)) if v > 0 else "")
            fig_area = px.bar(
                area_long, x="Area", y="Cantidad", color="Clasificación", text="label",
                color_discrete_map=CLASSIFICATION_COLORS,
                category_orders={"Area": cache.AREA_BUCKETS,
                                 "Clasificación": CLASSIFICATION_OPTIONS},
            )
            fig_area.update_layout(barmode="stack", height=460, xaxis_title="",
                                   yaxis_title="Consultas",
                                   margin=dict(t=30, b=40, l=60, r=30),
                                   paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            fig_area.update_traces(textposition="inside")
            st.plotly_chart(fig_area, width="stretch",
                            config=_png_config(f"area_clasificacion_{selected_month}"))
            area_table = area_pivot.copy()
            area_table["Total"] = area_table.sum(axis=1)
            st.dataframe(area_table.reset_index().rename(columns={"Area": "Área de interés"}),
                         hide_index=True, width="stretch")
            st.caption("Áreas sin texto o sin coincidencia con Máquinas, Repuestos o "
                       "Servicio Técnico se cuentan como No identificado.")

        # --- Zonas geográficas -------------------------------------------
        with section("zonas_consultas"):
            st.markdown("### Consultas por provincia")
            _zone_pie(geo.zone_counts(month_df["Zona"]), f"zonas_consultas_{selected_month}")
            st.caption("Provincia según el código de área del teléfono. Las provincias "
                       "más chicas se agrupan en Otros mientras sumen menos del 10 %.")

        # --- Tabla de datos ----------------------------------------------
        with section("tabla_consultas"):
            st.markdown(f"### Tabla de datos con clasificación agregada ({total} consultas)")
            display_cols = ["Fecha", "Nombre", "Numero", "Zona", "Area de interes",
                            "Clasificacion interna"]
            st.dataframe(style_bot_table(month_df[display_cols]),
                         hide_index=True, width="stretch")
            st.download_button(
                "⬇️ Descargar extracto mensual (CSV)",
                data=_csv(month_df[display_cols + ["Area"]]),
                file_name=f"extracto_{selected_month}.csv",
                mime="text/csv",
            )


# =============================================================================
# TAB — Negocios Bitrix24
# =============================================================================
with tab_negocios:
    st.subheader("Actividad del período")

    period_type = st.radio(
        "Período",
        ["Mes", "Trimestre", "Año", "Rango personalizado"],
        horizontal=True,
        key="bitrix_period_type",
    )

    today = datetime.now().date()
    valid_range = True

    if period_type == "Mes":
        pmonth = st.selectbox("Mes", months_bot, index=0, key="bitrix_period_month")
        range_start, range_end = periods.month_bounds(pmonth)
    elif period_type == "Trimestre":
        qc1, qc2 = st.columns(2)
        with qc1:
            pyear = int(st.number_input("Año", min_value=2015, max_value=today.year + 1,
                                        value=today.year, step=1, key="bitrix_q_year"))
        with qc2:
            pquarter = st.selectbox("Trimestre", [1, 2, 3, 4],
                                    index=periods.current_quarter(today) - 1,
                                    format_func=lambda q: f"T{q}", key="bitrix_q_num")
        range_start, range_end = periods.quarter_bounds(pyear, pquarter)
    elif period_type == "Año":
        pyear = int(st.number_input("Año", min_value=2015, max_value=today.year + 1,
                                    value=today.year, step=1, key="bitrix_y_year"))
        range_start, range_end = periods.year_bounds(pyear)
    else:
        rc1, rc2 = st.columns(2)
        with rc1:
            range_start = st.date_input("Desde", value=today.replace(day=1),
                                        key="bitrix_range_start")
        with rc2:
            range_end = st.date_input("Hasta", value=today, key="bitrix_range_end")
        if range_start > range_end:
            st.error("'Desde' no puede ser posterior a 'Hasta'.")
            valid_range = False

    if valid_range:
        period_months = tuple(periods.year_months_spanning(range_start, range_end))
        period_label = f"{range_start.strftime('%d-%m-%y')}_a_{range_end.strftime('%d-%m-%y')}"

        if st.button("🔄 Recargar período desde API",
                     help="Fuerza traer todos los meses del período desde Bitrix24 "
                          "(ignora snapshots). Puede tardar si el período es largo.",
                     key="bitrix_period_refresh"):
            st.session_state["_force_period"] = True
            st.rerun()

        with st.spinner(f"Cargando {len(period_months)} mes(es) de Bitrix…"):
            period_df, period_sources, period_warns = load_bitrix_period(
                period_months, force_refresh=force_period)
        for w in period_warns:
            st.warning(w)

        _n_api = sum(1 for s in period_sources.values() if s == "api")
        _n_snap = sum(1 for s in period_sources.values() if s == "snapshot")
        st.caption(
            f"Período: {range_start.strftime('%d-%m-%y')} a {range_end.strftime('%d-%m-%y')} "
            f"({len(period_months)} mes(es) — {_n_snap} desde snapshot, {_n_api} desde API). "
            "Incluye negocios **creados** o **movidos** de etapa dentro del período "
            "(los creados en el período se marcan 'Sí' en la columna Nuevo)."
        )

        b = period_df.copy()
        if not b.empty:
            b["_mov_dt"] = pd.to_datetime(b["Fecha movimiento"], format="%d-%m-%y", errors="coerce")
            b["_cre_dt"] = pd.to_datetime(b["Fecha creacion"], format="%d-%m-%y", errors="coerce")
            _start_ts, _end_ts = pd.Timestamp(range_start), pd.Timestamp(range_end)
            in_created = (b["_cre_dt"] >= _start_ts) & (b["_cre_dt"] <= _end_ts)
            in_moved = (b["_mov_dt"] >= _start_ts) & (b["_mov_dt"] <= _end_ts)
            b = b[in_created | in_moved].copy()
            b["Nuevo"] = ((b["_cre_dt"] >= _start_ts) & (b["_cre_dt"] <= _end_ts)).map({True: "Sí", False: ""})
            b = b.sort_values("_mov_dt", ascending=False)
            b["Zona"] = b["Telefono"].map(province_of)
            if "Etapa anterior" not in b.columns:
                b["Etapa anterior"] = ""

        if b.empty:
            st.info("No hay actividad de Bitrix para este período.")
        else:
            etapas_norm = b["Etapa"].astype(str).str.strip().str.lower()
            mask_ganado = etapas_norm.str.startswith("cerrado ganado")
            mask_perdido = etapas_norm.str.startswith("cerrado perdido")
            mask_cerrado = mask_ganado | mask_perdido

            fuentes = b.get("Fuente", pd.Series(dtype=str)).astype(str).str.strip()
            fuentes = fuentes[fuentes != ""]
            fuente_top, fuente_n = ((str(fuentes.value_counts().index[0]), int(fuentes.value_counts().iloc[0]))
                                    if not fuentes.empty else ("—", 0))

            motivos_s = b.loc[mask_perdido, "Motivo de baja"].astype(str).str.strip()
            motivos_s = motivos_s[motivos_s != ""]
            motivo_top, motivo_n = ((str(motivos_s.value_counts().index[0]), int(motivos_s.value_counts().iloc[0]))
                                    if not motivos_s.empty else ("—", 0))

            cerrados_df = b[mask_cerrado]
            vidas = (cerrados_df["_mov_dt"] - cerrados_df["_cre_dt"]).dt.days.dropna()
            vidas = vidas[vidas >= 0]
            vida_label = f"{vidas.mean():.1f} días" if not vidas.empty else "—"
            vida_help = (f"Promedio sobre {len(vidas)} negocios cerrados (creación → último movimiento)"
                         if not vidas.empty else "Sin negocios cerrados con fechas válidas")

            zona_top_b, zona_n_b = geo.top_province(b["Zona"])

            with section("kpis_negocios"):
                r1 = st.columns(4)
                r1[0].metric("Total con actividad", len(b))
                r1[1].metric("Nuevos del período", int((b["Nuevo"] == "Sí").sum()))
                r1[2].metric("Fuente destacada", fuente_top,
                             delta=f"{fuente_n} negocios" if fuente_n else None, delta_color="off")
                r1[3].metric("Provincia con más negocios", zona_top_b,
                             delta=f"{zona_n_b} negocios" if zona_n_b else None, delta_color="off")
                r2 = st.columns(4)
                r2[0].metric("Negocios cerrados", int(mask_cerrado.sum()))
                r2[1].metric("Ganados", int(mask_ganado.sum()))
                r2[2].metric("Motivo de baja más frecuente", motivo_top,
                             delta=f"{motivo_n} casos" if motivo_n else None, delta_color="off")
                r2[3].metric("Vida de negocio", vida_label, help=vida_help)

            # --- Tipo de máquina × etapa -------------------------------------
            with section("maquina_etapa"):
                st.markdown("### Negocios por tipo de máquina y etapa")
                pivot = b.groupby(["Tipo maquinaria", "Etapa"]).size().unstack(fill_value=0)
                ordered = [c for c in BITRIX_STAGE_ORDER if c in pivot.columns] + \
                          [c for c in pivot.columns if c not in BITRIX_STAGE_ORDER]
                pivot = pivot[ordered]
                pivot["Total"] = pivot.sum(axis=1)
                pivot = pivot.sort_values("Total", ascending=False)

                modo = st.radio("Mostrar", ["Porcentaje", "Cantidad"], horizontal=True,
                                key="bitrix_bar_mode")
                long = pivot.drop(columns=["Total"]).reset_index().melt(
                    id_vars="Tipo maquinaria", var_name="Etapa", value_name="Cantidad")
                long["Total maquinaria"] = long["Tipo maquinaria"].map(pivot["Total"].to_dict())
                long["%"] = (long["Cantidad"] / long["Total maquinaria"] * 100).round(1)
                if modo == "Porcentaje":
                    long["label"] = long["%"].map(lambda v: f"{v:.0f}%" if v > 0 else "")
                else:
                    long["label"] = long["Cantidad"].map(lambda v: str(int(v)) if v > 0 else "")
                fig = px.bar(
                    long, x="Tipo maquinaria", y="%" if modo == "Porcentaje" else "Cantidad",
                    color="Etapa", text="label", color_discrete_map=BITRIX_STAGE_COLORS,
                    category_orders={"Etapa": BITRIX_STAGE_ORDER,
                                     "Tipo maquinaria": pivot.index.tolist()},
                    custom_data=["Cantidad", "%", "Total maquinaria"],
                )
                fig.update_layout(
                    barmode="stack", height=500, xaxis_title="",
                    yaxis_title="% dentro del tipo" if modo == "Porcentaje" else "Cantidad de negocios",
                    margin=dict(t=40, b=110, l=70, r=40),
                    legend=dict(orientation="h", yanchor="bottom", y=-0.35, xanchor="left", x=0),
                    xaxis=dict(tickangle=-25),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                )
                fig.update_traces(
                    textposition="inside",
                    hovertemplate=("<b>%{x}</b><br>Etapa: %{fullData.name}<br>"
                                   "Cantidad: %{customdata[0]} de %{customdata[2]}<br>"
                                   "%{customdata[1]}% del tipo<extra></extra>"),
                )
                st.plotly_chart(fig, width="stretch", config=_png_config(f"actividad_{period_label}"))
                st.dataframe(pivot.reset_index(), hide_index=True, width="stretch")

            # --- Motivos de baja ---------------------------------------------
            with section("motivos"):
                st.markdown("### Motivos de baja")
                perdidos = b[b["Motivo de baja"].astype(str).str.strip() != ""]
                if perdidos.empty:
                    st.info("No hay negocios perdidos con motivo cargado en el período.")
                else:
                    motivos = (perdidos["Motivo de baja"].astype(str).str.strip()
                               .value_counts().reset_index())
                    motivos.columns = ["Motivo", "Cantidad"]
                    motivos["%"] = (motivos["Cantidad"] / motivos["Cantidad"].sum() * 100).round(1)
                    mc1, mc2 = st.columns([2, 1])
                    with mc1:
                        fig_mot = px.pie(motivos, names="Motivo", values="Cantidad", hole=0.35)
                        fig_mot.update_layout(height=420, margin=dict(t=30, b=30, l=30, r=30),
                                              paper_bgcolor="rgba(0,0,0,0)")
                        st.plotly_chart(fig_mot, width="stretch",
                                        config=_png_config(f"motivos_baja_{period_label}"))
                    with mc2:
                        st.dataframe(motivos, hide_index=True, width="stretch")

            # --- Zonas geográficas -------------------------------------------
            with section("zonas_negocios"):
                st.markdown("### Negocios por provincia")
                _zone_pie(geo.zone_counts(b["Zona"]), f"zonas_negocios_{period_label}")
                st.caption("Provincia según el código de área del teléfono del contacto. "
                           "Sin identificar incluye contactos sin teléfono o con email.")

            # --- Lista --------------------------------------------------------
            with section("lista_negocios"):
                listing_cols = [
                    "Nuevo", "Fecha movimiento", "Fecha creacion", "Nombre negocio",
                    "Cliente", "Compania", "Etapa", "Etapa anterior", "Fuente",
                    "Motivo de baja", "Telefono", "Zona",
                ]
                listing = b[[c for c in listing_cols if c in b.columns]]
                st.markdown(f"### Lista de negociaciones con actividad en el período ({len(listing)})")
                st.dataframe(style_bitrix_table(listing), hide_index=True, width="stretch")
                st.download_button(
                    "⬇️ Descargar actividad del período (CSV)",
                    data=_csv(listing),
                    file_name=f"bitrix_actividad_{period_label}.csv",
                    mime="text/csv",
                )


# =============================================================================
# TAB — Clasificación Manual
# =============================================================================
@st.fragment
def _clasificacion_body(month_df: pd.DataFrame) -> None:
    """Fragmento: los reruns por selección o cambio de desplegable no
    re-ejecutan los otros tabs."""
    st.subheader("Clasificación manual de reportes")
    if month_df.empty:
        st.info("Sin reportes en el mes seleccionado.")
        return

    st.caption("Seleccioná un contacto para clasificar")
    picker_cols = ["Fecha", "Nombre", "Numero", "Area de interes", "Clasificacion interna"]
    picker_df = month_df[picker_cols].copy()
    picker_df["Nombre"] = picker_df["Nombre"].replace("", "(sin nombre)")

    st.markdown(
        """
        <style>
          div[data-testid="stDataFrame"] table td:last-child,
          div[data-testid="stDataFrame"] table th:last-child {
            text-align: right !important; font-style: italic;
            font-size: 0.85rem; color: #4a4a4a;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )

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
        st.info("Elegí una fila de la tabla para ver el detalle.")
        return

    row = month_df.iloc[sel_rows[0]]
    current_class = row["Clasificacion interna"] or cache.SIN_CLASIFICAR
    try:
        default_idx = CLASSIFICATION_OPTIONS.index(current_class)
    except ValueError:
        default_idx = CLASSIFICATION_OPTIONS.index(cache.SIN_CLASIFICAR)

    tbl_col, cls_col, btn_col = st.columns([6, 3, 1])
    with tbl_col:
        st.markdown(
            f"""
| Número | Nombre | Fecha | Área de interés |
|---|---|---|---|
| **{row['Numero']}** | {row['Nombre'] or '—'} | {row['Fecha']} | {row['Area de interes'] or '—'} |
"""
        )
    with cls_col:
        st.markdown(
            f"<div style='font-weight:700;color:{COTEAR_BLUE};"
            f"font-size:0.85rem;margin-bottom:4px;'>Clasificación interna</div>",
            unsafe_allow_html=True,
        )
        new_class = st.selectbox("Clasificación interna", CLASSIFICATION_OPTIONS,
                                 index=default_idx, label_visibility="collapsed",
                                 key=f"class_select_{row['Numero']}")
    with btn_col:
        st.markdown("<div style='height:1.35rem'></div>", unsafe_allow_html=True)
        if st.button("💾", key=f"save_{row['Numero']}", type="primary",
                     help="Guardar clasificación"):
            pending.add(str(row["Numero"]), {
                "Fecha": row["Fecha"],
                "Nombre": row["Nombre"],
                "Clasificacion interna": new_class,
            })
            st.toast(f"En cola: {row['Numero']} → {new_class}", icon="📥")
            st.rerun(scope="app")

    num_key = str(row["Numero"])
    if num_key in pending.get():
        if st.button("↩️ Quitar de la cola", key=f"unqueue_{num_key}"):
            pending.remove([num_key])
            st.rerun(scope="app")

    st.markdown("**Resumen de la consulta**")
    st.text_area("Resumen", value=row["Resumen general"], height=220,
                 label_visibility="collapsed", disabled=True)


with tab_clasif:
    _clasificacion_body(month_df.copy())
