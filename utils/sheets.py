"""Google Sheets I/O via gspread.

Convenciones:
- Libro FUENTE: reportes crudos del bot (una sola pestaña, sin cabecera).
- Libro DESTINO: persistencia con pestañas por mes: 'YYYY-MM_Bot' y 'YYYY-MM_Bitrix'.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Optional, TypeVar

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

T = TypeVar("T")

# Snapshot local de lecturas caras a Sheets. Se usa como fallback cuando la
# API falla, y opcionalmente como caché fresco con TTL corto.
_CACHE_DIR = Path("data") / "cache"
_BOT_SNAPSHOT = _CACHE_DIR / "bot_reports.json"
_BOT_SNAPSHOT_TTL_SEC = 120  # 2 min: coherente con el ttl de load_bot()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


# ---------------------------------------------------------------------------
# Wrapper de reintentos: cubre errores transitorios de Sheets (500/503/429)
# ---------------------------------------------------------------------------
def _with_retry(fn: Callable[[], T], retries: int = 3, base_delay: float = 0.5) -> T:
    last_exc: Exception | None = None
    for i in range(retries):
        try:
            return fn()
        except gspread.exceptions.APIError as e:  # 5xx, 429, etc.
            last_exc = e
            time.sleep(base_delay * (2 ** i))
        except Exception as e:
            # Network / transient — retry también
            last_exc = e
            time.sleep(base_delay * (2 ** i))
    assert last_exc is not None
    raise last_exc

# Cabeceras canónicas de las pestañas de destino.
# Bot: sólo lo esencial para persistencia y realimentación. El resto
# (área de interés, resumen, tipo de contacto) se reprocesa cada vez desde el
# libro fuente y no se guarda porque cambia / no aporta valor histórico.
BOT_HEADERS = [
    "Fecha", "Numero", "Nombre", "Clasificacion interna",
]
BITRIX_HEADERS = [
    "ID negocio", "Fecha creacion", "Fecha movimiento", "Nuevo",
    "Nombre negocio", "Tipo maquinaria", "Etapa",
    "Cliente", "Compania", "Telefono", "Motivo de baja",
]


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_client() -> gspread.Client:
    info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)


def _source_cfg() -> dict:
    """Lee [google_sheets.source] o hace fallback a [google_sheets] plano."""
    gs = st.secrets["google_sheets"]
    if "source" in gs:
        return dict(gs["source"])
    return {
        "spreadsheet_id": gs.get("spreadsheet_id"),
        "worksheet_name": gs.get("worksheet_name", ""),
    }


def _dest_cfg() -> dict:
    gs = st.secrets["google_sheets"]
    if "dest" in gs:
        return dict(gs["dest"])
    return {"spreadsheet_id": gs.get("dest_spreadsheet_id")}


# ---------------------------------------------------------------------------
# Lectura libro fuente (bot)
# ---------------------------------------------------------------------------
def _bot_snapshot_read() -> tuple[pd.DataFrame | None, Optional[datetime]]:
    """Lee el snapshot local de reportes del bot. Devuelve (df, ts) o (None, None)."""
    if not _BOT_SNAPSHOT.exists():
        return None, None
    try:
        with _BOT_SNAPSHOT.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        ts = datetime.fromisoformat(payload["ts"])
        df = pd.DataFrame(payload["rows"], columns=payload["cols"])
        return df, ts
    except (json.JSONDecodeError, OSError, KeyError, ValueError):
        return None, None


def _bot_snapshot_write(df: pd.DataFrame) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "cols": list(df.columns),
            "rows": df.values.tolist(),
        }
        tmp = _BOT_SNAPSHOT.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        import os as _os
        _os.replace(tmp, _BOT_SNAPSHOT)
    except OSError:
        pass


def read_source_bot_reports() -> pd.DataFrame:
    """Lee la pestaña fuente completa (sin cabecera) y devuelve un DataFrame crudo.

    Estrategia con snapshot local:
    1. Si hay snapshot local con < 2 min de antigüedad, se usa (evita API).
    2. Si no, se va a la API con retries. Si funciona, se refresca el snapshot.
    3. Si la API falla, se usa el snapshot aunque esté vencido (con warning).
    """
    # 1) Snapshot fresco → usarlo
    snap_df, snap_ts = _bot_snapshot_read()
    if snap_df is not None and snap_ts is not None:
        age = (datetime.now() - snap_ts).total_seconds()
        if age < _BOT_SNAPSHOT_TTL_SEC:
            return snap_df

    # 2) API con retries
    def _fetch() -> pd.DataFrame:
        cfg = _source_cfg()
        sh = get_client().open_by_key(cfg["spreadsheet_id"])
        ws_name = cfg.get("worksheet_name") or ""
        ws = sh.worksheet(ws_name) if ws_name else sh.sheet1
        rows = ws.get_all_values()
        if not rows:
            return pd.DataFrame()
        max_cols = max(len(r) for r in rows)
        max_cols = max(max_cols, 10)
        padded = [r + [""] * (max_cols - len(r)) for r in rows]
        cols = [
            "fecha_hora", "wa_link", "tipo_contacto", "tipo_contacto_dup",
            "area_interes", "nombre",
            "resumen_1", "resumen_2", "resumen_3", "resumen_4",
        ] + [f"extra_{i}" for i in range(max_cols - 10)]
        return pd.DataFrame(padded, columns=cols[:max_cols])

    try:
        df = _with_retry(_fetch)
        if not df.empty:
            _bot_snapshot_write(df)
        return df
    except Exception as e:
        # 3) Fallback a snapshot vencido
        if snap_df is not None and snap_ts is not None:
            st.warning(
                f"API de Google Sheets no responde ({e}). "
                f"Usando snapshot local del {snap_ts.strftime('%d-%m-%y %H:%M')}."
            )
            return snap_df
        raise


# ---------------------------------------------------------------------------
# Libro destino: pestañas mensuales
# ---------------------------------------------------------------------------
def _open_dest() -> gspread.Spreadsheet:
    cfg = _dest_cfg()
    return get_client().open_by_key(cfg["spreadsheet_id"])


def _month_tab_name(year_month: str, kind: str) -> str:
    assert kind in ("Bot", "Bitrix"), kind
    return f"{year_month}_{kind}"


def _ensure_worksheet(sh: gspread.Spreadsheet, title: str, headers: list[str]) -> gspread.Worksheet:
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=200, cols=max(len(headers), 10))
        ws.update(range_name="A1", values=[headers])
        return ws
    # Verificar cabecera
    current = ws.row_values(1)
    if current != headers:
        ws.update(range_name="A1", values=[headers])
    return ws


@st.cache_data(ttl=120, show_spinner=False)
def read_month_dataframe(year_month: str, kind: str) -> pd.DataFrame:
    """Lee una pestaña mensual del libro destino. Cacheada 2 min para no
    saturar el rate limit de Google Sheets (60 reads/min por usuario)."""
    headers = BOT_HEADERS if kind == "Bot" else BITRIX_HEADERS
    sh = _open_dest()
    title = _month_tab_name(year_month, kind)
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        return pd.DataFrame(columns=headers)
    values = ws.get_all_values()
    if not values or len(values) == 1:
        return pd.DataFrame(columns=headers)
    hdr, *rows = values
    df = pd.DataFrame(rows, columns=hdr)
    for col in headers:
        if col not in df.columns:
            df[col] = ""
    return df[headers]


def _invalidate_month_cache(year_month: str, kind: str) -> None:
    """Invalida la caché de una pestaña mensual tras un write."""
    try:
        read_month_dataframe.clear()  # limpia todo el caché de esta función
    except Exception:
        pass


def write_month_dataframe(year_month: str, kind: str, df: pd.DataFrame) -> None:
    """Sobrescribe la pestaña mensual con el DataFrame dado."""
    headers = BOT_HEADERS if kind == "Bot" else BITRIX_HEADERS
    sh = _open_dest()
    title = _month_tab_name(year_month, kind)
    ws = _ensure_worksheet(sh, title, headers)

    out = df.copy()
    for col in headers:
        if col not in out.columns:
            out[col] = ""
    out = out[headers].fillna("").astype(str)

    ws.resize(rows=max(len(out) + 1, 2), cols=len(headers))
    # RAW: no interpreta el '+' de los números como inicio de fórmula
    ws.update(range_name="A1", values=[headers] + out.values.tolist(),
              value_input_option="RAW")
    _invalidate_month_cache(year_month, kind)


def upsert_bot_row(year_month: str, row: dict, key_col: str = "Numero") -> None:
    """Inserta o reemplaza una fila en la pestaña mensual Bot por clave (Numero)."""
    df = read_month_dataframe(year_month, "Bot")
    mask = df[key_col].astype(str) == str(row.get(key_col, ""))
    if mask.any():
        idx = df.index[mask][0]
        for k, v in row.items():
            df.at[idx, k] = v
    else:
        df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    write_month_dataframe(year_month, "Bot", df)


def batch_upsert_bot_rows(year_month: str, rows: list[dict],
                          key_col: str = "Numero") -> None:
    """Aplica una lista de upserts sobre la pestaña Bot del mes en 2 API calls:
    un read + un write. Ideal para hacer flush de la cola de cambios pendientes.

    Cada dict debe traer al menos {key_col}; los demás campos se mergean.
    """
    if not rows:
        return
    df = read_month_dataframe(year_month, "Bot")
    df = df.copy()
    if df.empty:
        df = pd.DataFrame(columns=BOT_HEADERS)

    idx_by_key = {str(v): i for i, v in enumerate(df[key_col].astype(str).tolist())}
    new_rows = []
    for r in rows:
        key = str(r.get(key_col, "")).strip()
        if not key:
            continue
        if key in idx_by_key:
            i = idx_by_key[key]
            for k, v in r.items():
                if k in df.columns:
                    df.at[i, k] = v
        else:
            new_rows.append(r)
    if new_rows:
        df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)

    _with_retry(lambda: write_month_dataframe(year_month, "Bot", df))


def update_bot_classification(year_month: str, numero: str, classification: str) -> None:
    """Actualiza sólo la clasificación interna de un contacto por Numero."""
    df = read_month_dataframe(year_month, "Bot")
    mask = df["Numero"].astype(str) == str(numero)
    if not mask.any():
        return
    df.loc[mask, "Clasificacion interna"] = classification
    write_month_dataframe(year_month, "Bot", df)


def load_persisted_classifications(year_month: str) -> dict[str, str]:
    """Devuelve {Numero: Clasificacion interna} de la pestaña mensual."""
    df = read_month_dataframe(year_month, "Bot")
    if df.empty:
        return {}
    return {
        str(r["Numero"]): str(r["Clasificacion interna"])
        for _, r in df.iterrows()
        if str(r.get("Numero", "")).strip()
    }


def sync_month_bot(year_month: str, df: pd.DataFrame,
                   ignored_keys: set[str] | None = None) -> None:
    """Persiste el snapshot completo del mes (incluye clasificaciones automáticas).

    Merge con lo ya guardado por Numero: las clasificaciones existentes en la
    hoja no se pisan si vienen distintas del snapshot (la hoja es fuente de
    verdad para clasificaciones ya hechas). Sólo se agregan filas nuevas o se
    actualiza el nombre si ahora está poblado.

    Si se pasa ``ignored_keys``, cualquier fila persistida cuyo número matchee
    la lista negra se OMITE del output — así, cuando un número se agrega a
    `_ignorados`, se limpia también del histórico de las pestañas mensuales en
    el próximo sync.
    """
    ignored_keys = ignored_keys or set()
    persisted = read_month_dataframe(year_month, "Bot")
    persisted_map = {
        str(r["Numero"]): dict(r) for _, r in persisted.iterrows()
        if str(r.get("Numero", "")).strip()
    }

    def _is_ignored(numero: str) -> bool:
        if not ignored_keys:
            return False
        return _ignore_key(numero) in ignored_keys

    rows_out = []
    seen_numeros: set[str] = set()
    for _, r in df.iterrows():
        num = str(r.get("Numero", "")).strip()
        if not num:
            continue
        seen_numeros.add(num)
        existing = persisted_map.get(num, {})
        classification = str(existing.get("Clasificacion interna", "")).strip() \
            or str(r.get("Clasificacion interna", "")).strip()
        nombre = str(r.get("Nombre", "")).strip() \
            or str(existing.get("Nombre", "")).strip()
        rows_out.append({
            "Fecha": str(r.get("Fecha", "")),
            "Numero": num,
            "Nombre": nombre,
            "Clasificacion interna": classification,
        })

    # Conservar filas persistidas que ya no aparecen en el snapshot (histórico),
    # salvo que ahora estén en la lista negra.
    for num, existing in persisted_map.items():
        if num in seen_numeros:
            continue
        if _is_ignored(num):
            continue  # limpieza retroactiva: se cae de la hoja del mes
        rows_out.append({
            "Fecha": str(existing.get("Fecha", "")),
            "Numero": num,
            "Nombre": str(existing.get("Nombre", "")),
            "Clasificacion interna": str(existing.get("Clasificacion interna", "")),
        })

    out_df = pd.DataFrame(rows_out, columns=BOT_HEADERS)
    write_month_dataframe(year_month, "Bot", out_df)


_IGNORED_TAB = "_ignorados"
_IGNORED_HEADERS = ["Numero", "Motivo", "Fecha alta"]


def _ignore_key(raw: str) -> str:
    """Clave de matching para un número ignorado.

    Argentino → últimos 10 dígitos (mismo criterio que `_phone_sig`).
    No argentino → todos los dígitos, para poder ignorar cualquier prueba
    con número extranjero también.
    """
    from .phone_ar import only_digits, significant_ar
    sig = significant_ar(raw)
    if sig:
        return sig
    return only_digits(raw)


@st.cache_data(ttl=300, show_spinner=False)
def load_ignored_phones() -> set[str]:
    """Devuelve el set de claves de teléfonos a ignorar.

    Lee la pestaña `_ignorados` del libro destino (columna `Numero`).
    Si la pestaña no existe, se crea vacía y se devuelve un set vacío.
    Cacheado 5 min para no golpear Sheets en cada rerun.
    """
    sh = _open_dest()
    try:
        ws = sh.worksheet(_IGNORED_TAB)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=_IGNORED_TAB, rows=100,
                              cols=len(_IGNORED_HEADERS))
        ws.update(range_name="A1", values=[_IGNORED_HEADERS])
        return set()
    values = ws.get_all_values()
    if not values or len(values) < 2:
        return set()
    hdr, *rows = values
    try:
        idx_num = hdr.index("Numero")
    except ValueError:
        idx_num = 0
    keys: set[str] = set()
    for r in rows:
        if idx_num < len(r):
            key = _ignore_key(r[idx_num])
            if key:
                keys.add(key)
    return keys


_META_TAB = "_meta"
_META_HEADERS = ["clave", "valor"]


def _get_meta(key: str) -> str:
    """Lee una clave arbitraria de la pestaña _meta."""
    sh = _open_dest()
    try:
        ws = sh.worksheet(_META_TAB)
    except gspread.WorksheetNotFound:
        return ""
    for row in ws.get_all_values()[1:]:
        if len(row) >= 2 and row[0] == key:
            return row[1]
    return ""


def _set_meta(key: str, value: str) -> None:
    sh = _open_dest()
    ws = _ensure_worksheet(sh, _META_TAB, _META_HEADERS)
    values = ws.get_all_values()
    for i, row in enumerate(values[1:], start=2):
        if len(row) >= 1 and row[0] == key:
            ws.update(range_name=f"A{i}:B{i}", values=[[key, value]],
                      value_input_option="RAW")
            return
    ws.append_row([key, value], value_input_option="RAW")


@st.cache_data(ttl=60, show_spinner=False)
def get_last_bitrix_sync(year_month: str) -> Optional[datetime]:
    """Devuelve datetime del último sync exitoso desde la API para ese mes.

    Cacheado 60s: en la práctica sólo cambia cuando se sincroniza desde la API,
    y en ese caso invalidamos manualmente. Evita golpear Sheets en cada rerun
    del Tab 1 (selectbox, clicks, guardado)."""
    raw = _get_meta(f"bitrix_sync:{year_month}")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def set_last_bitrix_sync(year_month: str, ts: Optional[datetime] = None) -> None:
    ts = ts or datetime.now()
    _set_meta(f"bitrix_sync:{year_month}", ts.isoformat(timespec="seconds"))
    # Invalidar la caché del lector para que el sidebar refleje el nuevo sync.
    try:
        get_last_bitrix_sync.clear()
    except Exception:
        pass


def list_month_tabs() -> list[str]:
    """Devuelve los meses (YYYY-MM) que tienen alguna pestaña en el destino."""
    sh = _open_dest()
    months: set[str] = set()
    for ws in sh.worksheets():
        title = ws.title
        if len(title) >= 10 and title[4] == "-" and title[7] == "_":
            months.add(title[:7])
    return sorted(months, reverse=True)
