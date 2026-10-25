"""COTEAR · Informe de Actividad Comercial (dashboard Streamlit).

Ejecutar localmente:
    streamlit run app.py

Estructura: este archivo arma la página (estilos, datos comunes, barra
lateral y navegación); cada página está en ``views/``.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

import streamlit as st

from utils import cache, data, pending, sheets, ui
from views import analisis, clasificacion, negocios, reporte

st.set_page_config(
    page_title="COTEAR · Informe de Actividad Comercial",
    page_icon=":material/insights:",
    layout="wide",
    initial_sidebar_state="expanded",
)
ui.inject_css()
data.consume_flags()


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


# --- Reportes del bot (comunes a todas las páginas) -------------------------
try:
    _bot_raw = data.load_bot()
except Exception as e:
    st.error(f"No se pudieron leer los reportes del bot: {e}")
    st.stop()

_months_bot = cache.available_year_months(_bot_raw)
if not _months_bot:
    st.info("No hay reportes del bot todavía.")
    st.stop()
st.session_state["_bot_raw"] = _bot_raw
st.session_state["_months_bot"] = _months_bot


# --- Navegación ---------------------------------------------------------------
page = st.navigation([
    st.Page(reporte.render, title="Reporte mensual", icon=":material/insights:",
            url_path="reporte", default=True),
    st.Page(negocios.render, title="Negocios Bitrix24", icon=":material/handshake:",
            url_path="negocios"),
    st.Page(clasificacion.render, title="Clasificación manual", icon=":material/fact_check:",
            url_path="clasificacion"),
    st.Page(analisis.render, title="Análisis preliminar", icon=":material/science:",
            url_path="analisis"),
])
st.sidebar.markdown("### Filtros")
page.run()


# --- Barra lateral: datos y cambios pendientes ------------------------------
def _sync_pending() -> None:
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
            ym = st.session_state.get("mes", _months_bot[0])
        by_month[ym].append(row)
    try:
        for ym, rs in by_month.items():
            sheets.batch_upsert_bot_rows(ym, rs, key_col="Numero")
        n = pending.count()
        pending.clear()
        st.session_state.pop("_synced_months", None)
        st.toast(f"Sincronizados {n} cambios.", icon=":material/check_circle:")
        st.rerun()
    except Exception as e:
        st.sidebar.error(f"Error al sincronizar (la cola queda intacta): {e}")


with st.sidebar:
    st.divider()
    st.markdown("### Cambios pendientes")
    _pending_count = pending.count()
    if _pending_count == 0:
        st.caption("Sin cambios en cola.")
    else:
        st.badge(f"{_pending_count} pendientes", color="blue")
        with st.expander("Ver pendientes"):
            st.dataframe(pending.as_dataframe(), hide_index=True, width="stretch")
        sync_col, disc_col = st.columns(2)
        if sync_col.button("Sincronizar", icon=":material/upload:", type="primary",
                           key="pending_sync", width="stretch"):
            _sync_pending()
        if disc_col.button("Descartar", key="pending_discard", width="stretch"):
            pending.clear()
            st.rerun()

    st.markdown("### Datos")
    _mes = st.session_state.get("mes", _months_bot[0])
    last_sync = sheets.get_last_bitrix_sync(_mes)
    if last_sync:
        age_days = (datetime.now() - last_sync).days
        if age_days < data.BITRIX_SNAPSHOT_TTL_DAYS:
            icon, state = ":material/check_circle:", "al día"
        else:
            icon, state = ":material/schedule:", "desactualizado"
        st.caption(f"{icon} Bitrix {_mes}: {state} "
                   f"(sync {last_sync.strftime('%d-%m-%y %H:%M')}, hace {age_days} d)")
    else:
        st.caption(f":material/cloud_off: Bitrix {_mes}: sin snapshot")
    if st.button("Recargar Bitrix desde API", width="stretch",
                 help="Fuerza traer los negocios del mes desde Bitrix24 "
                      "(ignora el snapshot). Se refresca solo cada 7 días."):
        st.session_state["_force_month"] = True
        st.rerun()
    if st.button("Actualizar índice de teléfonos", width="stretch",
                 help="Vuelve a leer los teléfonos de todos los negocios de venta "
                      "(se usa para clasificar DERIVADO A BITRIX). Se refresca solo cada 7 días."):
        st.session_state["_force_index"] = True
        st.rerun()
    if st.button("Limpiar caché", width="stretch"):
        st.cache_data.clear()
        for k in ("_bitrix_memo", "_phone_index_memo", "_synced_months"):
            st.session_state.pop(k, None)
        st.rerun()
