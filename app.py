"""COTEAR — App de análisis de consultas y negociaciones.

Ejecutar localmente:
    streamlit run app.py
"""
from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from utils import bitrix, cache, pending, sheets
from utils.styling import style_bitrix_table, style_bot_table
from utils.branding import (
    BITRIX_STAGE_COLORS,
    BITRIX_STAGE_ORDER,
    CLASSIFICATION_COLORS,
    CLASSIFICATION_OPTIONS,
    COTEAR_BLUE,
    COTEAR_GRAY,
)


st.set_page_config(
    page_title="COTEAR — Análisis de consultas",
    page_icon="📊",
    layout="wide",
)


# --- Estilos globales ---------------------------------------------------------
st.markdown(
    f"""
    <style>
      h1, h2, h3 {{ color: {COTEAR_BLUE}; font-weight: 800; }}
      .stTabs [data-baseweb="tab"] {{ font-weight: 700; }}
      .stTabs [aria-selected="true"] {{ color: {COTEAR_BLUE}; }}
      .cotear-muted {{ color: {COTEAR_GRAY}; font-size: 0.9rem; }}
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
        rc1, rc2, rc3 = st.columns([1, 1, 4])
        with rc1:
            if st.button("Mantener en cola", type="primary",
                         key="pending_recover_keep"):
                st.rerun()
        with rc2:
            if st.button("Descartar todo", key="pending_recover_discard"):
                pending.clear()
                st.rerun()


# -----------------------------------------------------------------------------
# Carga y procesamiento (cacheado)
# -----------------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner="Descargando reportes del bot…")
def load_bot() -> pd.DataFrame:
    raw = sheets.read_source_bot_reports()
    df = cache.clean_source(raw)
    return df


BITRIX_SNAPSHOT_TTL_DAYS = 7


def _bitrix_snapshot_from_sheets(year_month: str) -> pd.DataFrame:
    """Reconstruye el DataFrame Bitrix desde la pestaña YYYY-MM_Bitrix."""
    df = sheets.read_month_dataframe(year_month, "Bitrix")
    if df.empty:
        return df
    from utils.phone_ar import significant_ar
    df = df.copy()
    df["_phone_sig"] = df["Telefono"].map(significant_ar)
    return df


@st.cache_data(ttl=600, show_spinner=False)
def load_bitrix_month(year_month: str, force_refresh: bool = False) -> tuple[pd.DataFrame, str]:
    """Devuelve (df, origen) para un mes. origen ∈ {'snapshot','api','error'}.

    Snapshot-first con TTL de 7 días. force_refresh=True siempre va a la API.
    """
    # 1) Ver si tenemos snapshot fresco
    if not force_refresh:
        last_sync = sheets.get_last_bitrix_sync(year_month)
        if last_sync and (datetime.now() - last_sync).days < BITRIX_SNAPSHOT_TTL_DAYS:
            snap = _bitrix_snapshot_from_sheets(year_month)
            if not snap.empty:
                return snap, "snapshot"

    # 2) Ir a la API (actividad del mes: MOVED_TIME + DATE_CREATE en el mes)
    try:
        with st.spinner(f"Descargando actividad de Bitrix24 ({year_month})…"):
            deals = bitrix.fetch_activity_for_month(year_month)
            df = bitrix.deals_to_dataframe(deals, year_month=year_month)
        if not df.empty:
            to_persist = df.drop(columns=["_phone_sig"], errors="ignore")
            sheets.write_month_dataframe(year_month, "Bitrix", to_persist)
            sheets.set_last_bitrix_sync(year_month)
        return df, "api"
    except Exception as e:
        # 3) Fallback: usar snapshot aunque esté vencido
        snap = _bitrix_snapshot_from_sheets(year_month)
        if not snap.empty:
            st.warning(f"API de Bitrix falló ({e}). Usando snapshot vencido.")
            return snap, "snapshot"
        st.warning(f"No se pudo leer Bitrix: {e}")
        return pd.DataFrame(), "error"


def build_processed(bot_df: pd.DataFrame, bitrix_df: pd.DataFrame) -> pd.DataFrame:
    """Procesamiento base sin realimentación (mucho más barato)."""
    try:
        ignored = sheets.load_ignored_phones()
    except Exception as e:
        st.warning(f"No se pudo leer la lista de números ignorados: {e}")
        ignored = set()
    df = cache.filter_ignored(bot_df, ignored)
    df = cache.unify_recent(df)
    bitrix_sigs = set(bitrix_df["_phone_sig"].tolist()) if not bitrix_df.empty else set()
    df = cache.apply_auto_rules(df, bitrix_sigs)
    df = cache.overwrite_names_from_bitrix(df, bitrix_df)
    return df


def apply_persisted(df: pd.DataFrame, year_month: str) -> pd.DataFrame:
    """Realimenta el df del mes con las clasificaciones guardadas en la hoja
    y luego con la cola de cambios pendientes (session_state).

    Sólo lee la pestaña del mes en foco → 1 read en vez de N.
    La cola pendiente pisa a lo persistido (optimistic UI).
    """
    try:
        persisted = sheets.load_persisted_classifications(year_month)
    except Exception as e:
        st.warning(f"No se pudo leer la hoja del mes {year_month}: {e}")
        persisted = {}
    out = df.copy()
    if persisted:
        for i in out.index:
            num = str(out.at[i, "Numero"])
            if num in persisted and persisted[num]:
                out.at[i, "Clasificacion interna"] = persisted[num]
    # Overlay de cambios en cola (aún no sincronizados a Sheets)
    out = pending.apply_to_df(out)
    return out


# -----------------------------------------------------------------------------
# Datos: primero bot para tener meses disponibles
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

# Sidebar: control de datos + estado de sync Bitrix
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

    force_refresh = st.button("🔄 Recargar Bitrix desde API",
                              help="Fuerza traer los negocios del mes desde Bitrix24 "
                                   "(ignora el snapshot). Se refresca solo cada 7 días.")
    if st.button("🧹 Limpiar caché"):
        st.cache_data.clear()
        st.rerun()

    # --- Cola de cambios pendientes -----------------------------------------
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
                items = list(pending.get().items())
                rows = [
                    {
                        "Fecha": v.get("Fecha", ""),
                        "Numero": num,
                        "Nombre": v.get("Nombre", ""),
                        "Clasificacion interna": v.get("Clasificacion interna", ""),
                    }
                    for num, v in items
                ]
                try:
                    # Agrupar por mes derivado de la Fecha (DD-MM-YY)
                    from collections import defaultdict
                    by_month: dict[str, list[dict]] = defaultdict(list)
                    for r in rows:
                        f = str(r.get("Fecha", ""))
                        try:
                            d = datetime.strptime(f, "%d-%m-%y")
                            ym = f"{d.year:04d}-{d.month:02d}"
                        except ValueError:
                            ym = selected_month  # fallback al mes en foco
                        by_month[ym].append(r)
                    for ym, rs in by_month.items():
                        sheets.batch_upsert_bot_rows(ym, rs, key_col="Numero")
                    pending.clear()
                    st.success(f"Sincronizados {len(rows)} cambios.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al sincronizar (la cola queda intacta): {e}")
        with disc_col:
            if st.button("🗑️ Descartar", key="pending_discard"):
                pending.clear()
                st.rerun()

# Bitrix del mes seleccionado (snapshot-first con TTL 7 días)
bitrix_df, bitrix_source = load_bitrix_month(selected_month, force_refresh=force_refresh)
if force_refresh:
    load_bitrix_month.clear()
    st.rerun()

processed = build_processed(bot_raw, bitrix_df)

# Realimentación de clasificaciones persistidas
processed = apply_persisted(processed, selected_month)


@st.cache_data(ttl=1800, show_spinner=False)
def _sync_month_once(year_month: str, snapshot_hash: str) -> None:
    """Sincroniza el mes a la hoja. Cacheado 30 min con hash: si el snapshot
    no cambia, no vuelve a escribir aunque el usuario recargue."""
    month_df = cache.filter_by_year_month(processed, year_month)
    if not month_df.empty:
        try:
            ignored = sheets.load_ignored_phones()
        except Exception:
            ignored = set()
        try:
            sheets.sync_month_bot(year_month, month_df, ignored_keys=ignored)
        except Exception as e:
            st.warning(f"No se pudo sincronizar el mes {year_month}: {e}")


_month_snapshot = cache.filter_by_year_month(processed, selected_month)
_snapshot_key = str(hash(tuple(
    (str(r["Numero"]), str(r["Clasificacion interna"]))
    for _, r in _month_snapshot.iterrows()
)))
_sync_month_once(selected_month, _snapshot_key)


# -----------------------------------------------------------------------------
# Tabs
# -----------------------------------------------------------------------------
tab_reportes, tab_negocios, tab_clasif = st.tabs([
    "Reportes Mensual (Extracto mensual)",
    "Extracto Negocios (Análisis Bitrix24)",
    "Clasificación Manual",
])


# =============================================================================
# TAB 1 — Clasificación manual
# =============================================================================
@st.fragment
def _tab1_body(month_df: pd.DataFrame, year_month: str) -> None:
    """Renderiza el Tab 1 dentro de un fragmento: los reruns por selección
    de fila, cambio de selectbox o guardado NO re-ejecutan los tabs 2 y 3."""
    st.subheader("Clasificación manual de reportes")
    if month_df.empty:
        st.info("Sin reportes en el mes seleccionado.")
        return

    # Tabla de selección con la clasificación como columna al final
    # (coloreada por su valor). Un click en la fila la selecciona.
    st.caption("Seleccioná un contacto para clasificar")

    picker_cols = ["Fecha", "Nombre", "Numero", "Area de interes",
                   "Clasificacion interna"]
    picker_df = month_df[picker_cols].copy()
    picker_df["Nombre"] = picker_df["Nombre"].replace("", "(sin nombre)")

    # CSS: última columna (clasificación) alineada a la derecha, en gris
    # oscuro cursiva y fuente más chica cuando se ve como texto de la fila.
    st.markdown(
        """
        <style>
          /* Alineación derecha + estilo etiqueta para la última columna
             de la tabla de selección (Clasificacion interna). */
          div[data-testid="stDataFrame"] table td:last-child,
          div[data-testid="stDataFrame"] table th:last-child {
            text-align: right !important;
            font-style: italic;
            font-size: 0.85rem;
            color: #4a4a4a;
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

    idx = sel_rows[0]
    row = month_df.iloc[idx]

    # --- Fila de detalle con clasificador incorporado ------------------------
    # Layout: 4 cols de datos (Numero, Nombre, Fecha, Area) + 1 col con el
    # selectbox de clasificación + 1 col con el botón de guardar. El label
    # del selectbox se colapsa para que la fila quede alineada con la cabecera.
    current_class = row["Clasificacion interna"] or CLASSIFICATION_OPTIONS[-1]
    try:
        default_idx = CLASSIFICATION_OPTIONS.index(current_class)
    except ValueError:
        default_idx = CLASSIFICATION_OPTIONS.index("SIN CLASIFICAR")

    # Layout: tabla markdown (con bordes propios de markdown) a la izquierda
    # con los 4 datos del reporte, y a la derecha el clasificador + botón de
    # guardar como widgets aparte.
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
        new_class = st.selectbox(
            "Clasificación interna",
            CLASSIFICATION_OPTIONS,
            index=default_idx,
            label_visibility="collapsed",
            key=f"class_select_{row['Numero']}",
        )
    with btn_col:
        # Espaciador para alinear el botón con el selectbox (que tiene su
        # propia label chiquita arriba).
        st.markdown(
            "<div style='height:1.35rem'></div>",
            unsafe_allow_html=True,
        )
        if st.button("💾", key=f"save_{row['Numero']}",
                     type="primary", help="Guardar clasificación"):
            # No golpeamos Sheets: encolamos el cambio. La UI ya refleja el
            # valor porque apply_persisted() overlaya la cola en el próximo rerun.
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
    st.text_area(
        "Resumen",
        value=row["Resumen general"],
        height=220,
        label_visibility="collapsed",
        disabled=True,
    )


# =============================================================================
# TAB 1 — Reportes Mensual (extracto mensual + distribución)
# =============================================================================
with tab_reportes:
    st.subheader("Distribución de consultas del mes")
    month_df = cache.filter_by_year_month(processed, selected_month).copy()
    if month_df.empty:
        st.info("Sin datos en el mes seleccionado.")
    else:
        counts = month_df["Clasificacion interna"].value_counts().reset_index()
        counts.columns = ["Clasificación", "Cantidad"]
        counts["%"] = (counts["Cantidad"] / counts["Cantidad"].sum() * 100).round(1)

        c1, c2 = st.columns([2, 1])
        with c1:
            fig = px.pie(
                counts,
                names="Clasificación",
                values="Cantidad",
                color="Clasificación",
                color_discrete_map=CLASSIFICATION_COLORS,
                hole=0.35,
            )
            # fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(
                showlegend=True,
                height=460,
                margin=dict(t=40, b=40, l=40, r=40),
            )
            st.plotly_chart(
                fig,
                width="stretch",
                config={
                    "toImageButtonOptions": {
                        "format": "png",
                        "filename": f"clasificaciones_{selected_month}",
                        "width": 1200,
                        "height": 700,
                        "scale": 2,
                    },
                    "displaylogo": False,
                },
            )
        with c2:
            st.dataframe(counts, hide_index=True, width="stretch")

        st.markdown("### Tabla de datos con clasificación agregada")
        display_cols = ["Fecha", "Nombre", "Numero", "Area de interes", "Clasificacion interna"]
        st.dataframe(
            style_bot_table(month_df[display_cols]),
            hide_index=True,
            width="stretch",
        )

        csv = month_df[display_cols].to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Descargar extracto mensual (CSV)",
            data=csv,
            file_name=f"extracto_{selected_month}.csv",
            mime="text/csv",
        )


# =============================================================================
# TAB 2 — Extracto Negocios (análisis Bitrix24)
# =============================================================================
with tab_negocios:
    st.subheader("Actividad del mes")
    st.caption(
        f"Fuente: {'snapshot local' if bitrix_source == 'snapshot' else 'API Bitrix'}. "
        "Incluye deals **creados** en el mes o **movidos** de etapa en el mes "
        "(los creados este mes se marcan 'Sí' en la columna Nuevo)."
    )
    if bitrix_df.empty:
        st.info("No hay actividad de Bitrix para este mes.")
    else:
        b_month = bitrix_df.copy()
        # Orden por fecha de movimiento descendente
        b_month["_mov_dt"] = pd.to_datetime(
            b_month["Fecha movimiento"], format="%d-%m-%y", errors="coerce"
        )
        b_month = b_month.sort_values("_mov_dt", ascending=False)

        if b_month.empty:
            st.info("Sin negocios en el mes seleccionado.")
        else:
            # Tabla pivote maquinaria x etapa
            pivot = (b_month.groupby(["Tipo maquinaria", "Etapa"]).size()
                     .unstack(fill_value=0))
            # Ordenar columnas por etapa canónica
            ordered_cols = [c for c in BITRIX_STAGE_ORDER if c in pivot.columns] + \
                           [c for c in pivot.columns if c not in BITRIX_STAGE_ORDER]
            pivot = pivot[ordered_cols]
            pivot["Total"] = pivot.sum(axis=1)
            pivot = pivot.sort_values("Total", ascending=False)

            # Gráfico apilado con cantidades absolutas (la altura refleja el
            # volumen real de negocios por tipo de maquinaria)
            long = pivot.drop(columns=["Total"]).reset_index().melt(
                id_vars="Tipo maquinaria", var_name="Etapa", value_name="Cantidad"
            )
            totals_map = pivot["Total"].to_dict()
            long["Total maquinaria"] = long["Tipo maquinaria"].map(totals_map)
            long["% dentro maquinaria"] = (
                long["Cantidad"] / long["Total maquinaria"] * 100
            ).round(1)

            # Etiqueta: mostrar cantidad sólo si es >0
            long["label"] = long["Cantidad"].map(lambda v: str(int(v)) if v > 0 else "")

            fig = px.bar(
                long,
                x="Tipo maquinaria",
                y="Cantidad",
                color="Etapa",
                text="label",
                color_discrete_map=BITRIX_STAGE_COLORS,
                category_orders={"Etapa": BITRIX_STAGE_ORDER},
                custom_data=["% dentro maquinaria", "Total maquinaria"],
            )
            fig.update_layout(
                barmode="stack",
                yaxis_title="Cantidad de negocios",
                xaxis_title="",
                height=500,
                margin=dict(t=40, b=110, l=70, r=40),
                legend=dict(
                    orientation="h",
                    yanchor="bottom", y=-0.30,
                    xanchor="left", x=0,
                ),
                xaxis=dict(tickangle=-25),
            )
            fig.update_traces(
                textposition="inside",
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "Etapa: %{fullData.name}<br>"
                    "Cantidad: %{y}<br>"
                    "%{customdata[0]}% del tipo (total %{customdata[1]})"
                    "<extra></extra>"
                ),
            )
            st.plotly_chart(
                fig,
                width="stretch",
                config={
                    "toImageButtonOptions": {
                        "format": "png",
                        "filename": f"actividad_{selected_month}",
                        "width": 1400,
                        "height": 700,
                        "scale": 2,
                    },
                    "displaylogo": False,
                },
            )

            # --- Distribución de motivos de baja ----------------------------
            # Reemplaza la tabla pivote (ya visible en el gráfico apilado) por
            # un análisis de los deals cerrados perdidos: qué motivos priman.
            st.markdown("### Motivos de baja")
            perdidos = b_month[
                b_month["Motivo de baja"].astype(str).str.strip() != ""
            ]
            if perdidos.empty:
                st.info("No hay deals cerrados perdidos con motivo cargado en el mes.")
            else:
                motivos = (perdidos["Motivo de baja"].astype(str).str.strip()
                           .value_counts().reset_index())
                motivos.columns = ["Motivo", "Cantidad"]
                motivos["%"] = (motivos["Cantidad"] / motivos["Cantidad"].sum()
                                * 100).round(1)

                mc1, mc2 = st.columns([2, 1])
                with mc1:
                    fig_mot = px.pie(
                        motivos,
                        names="Motivo",
                        values="Cantidad",
                        hole=0.35,
                    )
                    fig_mot.update_layout(
                        showlegend=True,
                        height=420,
                        margin=dict(t=40, b=40, l=40, r=40),
                    )
                    st.plotly_chart(
                        fig_mot,
                        width="stretch",
                        config={
                            "toImageButtonOptions": {
                                "format": "png",
                                "filename": f"motivos_baja_{selected_month}",
                                "width": 1200,
                                "height": 700,
                                "scale": 2,
                            },
                            "displaylogo": False,
                        },
                    )
                with mc2:
                    st.dataframe(motivos, hide_index=True, width="stretch")

            st.markdown("### Lista de negociaciones con actividad en el mes")
            # KPIs rápidos
            total = len(b_month)
            nuevos = (b_month["Nuevo"].astype(str) == "Sí").sum()
            k1, k2, k3 = st.columns(3)
            k1.metric("Total con actividad", total)
            k2.metric("Nuevos del mes", int(nuevos))
            k3.metric("Reactivados / movidos", total - int(nuevos))

            listing = b_month[[
                "Nuevo", "Fecha movimiento", "Fecha creacion", "Nombre negocio",
                "Cliente", "Compania", "Etapa", "Motivo de baja", "Telefono",
            ]]
            st.dataframe(
                style_bitrix_table(listing),
                hide_index=True,
                width="stretch",
            )

            csv = listing.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇️ Descargar actividad del mes (CSV)",
                data=csv,
                file_name=f"bitrix_actividad_{selected_month}.csv",
                mime="text/csv",
            )


# =============================================================================
# TAB 3 — Clasificación Manual
# =============================================================================
with tab_clasif:
    _tab1_body(
        cache.filter_by_year_month(processed, selected_month).copy(),
        selected_month,
    )
