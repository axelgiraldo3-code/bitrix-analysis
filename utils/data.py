"""Carga y procesamiento de datos compartido por las páginas.

Lectura con caché de reportes del bot, negocios de Bitrix (snapshot-first),
índice de teléfonos y armado del mes procesado (reglas automáticas,
clasificaciones persistidas y cola de pendientes).
"""
from __future__ import annotations

import time
from datetime import datetime

import pandas as pd
import streamlit as st

from . import bitrix, cache, pending, periods, sheets
from .machinery import classify_machinery
from .phone_ar import province_of, significant_ar

BITRIX_SNAPSHOT_TTL_DAYS = 7
PHONE_INDEX_TTL_DAYS = 7
BITRIX_MEMO_TTL_SEC = 600

_FLAGS_KEY = "_run_flags"


# -----------------------------------------------------------------------------
# Pedidos de recarga (botones del panel lateral)
# -----------------------------------------------------------------------------
def consume_flags() -> None:
    """Se llama una vez por ejecución: toma los pedidos de recarga que dejaron
    los botones del panel lateral en la ejecución anterior."""
    st.session_state[_FLAGS_KEY] = {
        k: st.session_state.pop(k, False)
        for k in ("_force_month", "_force_period", "_force_index")
    }


def flag(name: str) -> bool:
    return bool(st.session_state.get(_FLAGS_KEY, {}).get(name, False))


# -----------------------------------------------------------------------------
# Lectura
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
    # El tipo se recalcula siempre: el snapshot puede haberse guardado con
    # una versión anterior del clasificador.
    df["Tipo maquinaria"] = df["Nombre negocio"].map(classify_machinery)
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
    # Índices guardados antes de existir la columna Negocio: refrescar una vez
    if not df.empty and not df.get("Negocio", pd.Series(dtype=str)).astype(str).str.strip().any():
        stale = True
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


def apply_persisted(df: pd.DataFrame, year_month: str,
                    sheet_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Superpone las clasificaciones guardadas en la hoja del mes y después la
    cola de cambios pendientes (la cola pisa a lo persistido). ``sheet_df``:
    pestaña del mes ya leída (lectura en lote de varios meses)."""
    try:
        persisted = sheets.load_persisted_classifications(year_month, sheet_df)
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
# Contexto mensual de consultas
# -----------------------------------------------------------------------------
def load_ignored() -> set[str]:
    try:
        return sheets.load_ignored_phones()
    except Exception as e:
        st.warning(f"No se pudo leer la lista de números ignorados: {e}")
        return set()


def lookups(selected_month: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(teléfono → nombre, teléfono → negocio) con los negocios del mes primero
    (más actuales) y después el índice de todos los negocios de venta."""
    bitrix_df, _src, bitrix_warn = load_bitrix_month(selected_month, force_refresh=flag("_force_month"))
    if bitrix_warn:
        st.warning(bitrix_warn)
    phone_index, index_warn = load_phone_index(force_refresh=flag("_force_index"))
    if index_warn:
        st.warning(index_warn)

    lookup = pd.concat(
        [bitrix_df.reindex(columns=["_phone_sig", "Cliente"]),
         phone_index.reindex(columns=["_phone_sig", "Cliente"])],
        ignore_index=True,
    ).fillna("")
    lookup = lookup[lookup["_phone_sig"] != ""].drop_duplicates("_phone_sig", keep="first")

    month_deals = (bitrix_df[bitrix_df["_phone_sig"].astype(str) != ""]
                   .groupby("_phone_sig")["Nombre negocio"]
                   .agg(lambda t: " | ".join(dict.fromkeys(x for x in t if x)))
                   .reset_index().rename(columns={"Nombre negocio": "Negocio"})
                   if not bitrix_df.empty else pd.DataFrame(columns=["_phone_sig", "Negocio"]))
    deal_lookup = pd.concat(
        [month_deals, phone_index.reindex(columns=["_phone_sig", "Negocio"])],
        ignore_index=True,
    ).fillna("")
    deal_lookup = deal_lookup[deal_lookup["Negocio"].astype(str).str.strip() != ""]
    return lookup.reset_index(drop=True), deal_lookup


def month_data(bot_raw: pd.DataFrame, year_month: str, lookup: pd.DataFrame,
               deal_lookup: pd.DataFrame, ignored: set[str], *, persist: bool = True
               ) -> pd.DataFrame:
    """Reportes del mes procesados: ignorados, unificación, reglas automáticas,
    nombres de Bitrix, clasificaciones guardadas y pendientes, área y negocio.

    ``persist`` sincroniza el mes con Sheets (sólo el mes que se está viendo;
    el mes anterior, usado para comparar KPIs, sólo se lee)."""
    month_bot = cache.filter_by_year_month(bot_raw, year_month)
    df = apply_persisted(process_month(month_bot, lookup, frozenset(ignored)), year_month)
    if persist:
        sync_month_if_changed(year_month, df, ignored)
    df["Area"] = df["Area de interes"].map(cache.area_bucket)
    return cache.attach_deal_names(df, deal_lookup)


def current_month(bot_raw: pd.DataFrame, year_month: str) -> pd.DataFrame:
    lookup, deal_lookup = lookups(year_month)
    return month_data(bot_raw, year_month, lookup, deal_lookup, load_ignored())


def month_with_previous(bot_raw: pd.DataFrame, year_month: str
                        ) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """(mes procesado, mes anterior procesado o None si no tiene reportes).
    El mes anterior se usa sólo para comparar KPIs: se lee, no se sincroniza."""
    lookup, deal_lookup = lookups(year_month)
    ignored = load_ignored()
    current = month_data(bot_raw, year_month, lookup, deal_lookup, ignored)
    prev_ym = periods.shift_months(year_month, -1)
    if cache.filter_by_year_month(bot_raw, prev_ym).empty:
        return current, None
    return current, month_data(bot_raw, prev_ym, lookup, deal_lookup, ignored, persist=False)


TREND_MONTHS = 6


def bot_history(bot_raw: pd.DataFrame, year_month: str, current: pd.DataFrame,
                prev: pd.DataFrame | None, n: int = TREND_MONTHS
                ) -> list[tuple[str, pd.DataFrame | None]]:
    """[(mes, consultas procesadas o None si no hay reportes), ...] de los
    últimos ``n`` meses hasta ``year_month`` (el más viejo primero).

    El mes actual y el anterior ya vienen procesados; los demás se procesan
    acá con sus clasificaciones guardadas, leídas en un solo pedido a
    Sheets. Sólo se leen, no se sincronizan."""
    months = [periods.shift_months(year_month, -i) for i in range(n - 1, -1, -1)]
    known = {year_month: current, periods.shift_months(year_month, -1): prev}
    older = [m for m in months if m not in known
             and not cache.filter_by_year_month(bot_raw, m).empty]
    out = dict(known)
    if older:
        lookup, deal_lookup = lookups(year_month)
        ignored = load_ignored()
        try:
            tabs = sheets.read_months_batch(tuple(older), "Bot")
        except Exception as e:
            st.warning(f"No se pudieron leer las clasificaciones de meses anteriores: {e}")
            tabs = {}
        for m in older:
            month_bot = cache.filter_by_year_month(bot_raw, m)
            df = process_month(month_bot, lookup, frozenset(ignored))
            df = apply_persisted(df, m, tabs.get(m, pd.DataFrame(columns=sheets.BOT_HEADERS)))
            df["Area"] = df["Area de interes"].map(cache.area_bucket)
            out[m] = df
    return [(m, out.get(m)) for m in months]


# -----------------------------------------------------------------------------
# Negocios de un período
# -----------------------------------------------------------------------------
def deals_created_between(start, end, *, force_refresh: bool = False
                          ) -> tuple[pd.DataFrame, dict[str, str], list[str]]:
    """Negocios creados dentro de [start, end] (con su etapa actual), a partir
    de los meses de Bitrix que cubren el período."""
    months = tuple(periods.year_months_spanning(start, end))
    df, sources, warns = load_bitrix_period(months, force_refresh=force_refresh)
    b = df.copy()
    if b.empty:
        return b, sources, warns
    b["_mov_dt"] = pd.to_datetime(b["Fecha movimiento"], format="%d-%m-%y", errors="coerce")
    b["_cre_dt"] = pd.to_datetime(b["Fecha creacion"], format="%d-%m-%y", errors="coerce")
    in_created = (b["_cre_dt"] >= pd.Timestamp(start)) & (b["_cre_dt"] <= pd.Timestamp(end))
    b = b[in_created].sort_values("_mov_dt", ascending=False).copy()
    b["Zona"] = b["Telefono"].map(province_of)
    if "Etapa anterior" not in b.columns:
        b["Etapa anterior"] = ""
    return b, sources, warns
