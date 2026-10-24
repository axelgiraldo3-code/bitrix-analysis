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

SIN_CLASIFICAR = "SIN CLASIFICAR"

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
    "Nombre negocio", "Tipo maquinaria", "Etapa", "Etapa anterior",
    "Cliente", "Compania", "Telefono", "Fuente", "Motivo de baja",
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


def _headers_for(kind: str) -> list[str]:
    return BOT_HEADERS if kind == "Bot" else BITRIX_HEADERS


def _ensure_worksheet(sh: gspread.Spreadsheet, title: str, headers: list[str],
                      check_headers: bool = True) -> gspread.Worksheet:
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=200, cols=max(len(headers), 10))
        ws.update(range_name="A1", values=[headers], value_input_option="RAW")
        return ws
    if check_headers and ws.row_values(1) != headers:
        ws.update(range_name="A1", values=[headers], value_input_option="RAW")
    return ws


def _values_to_df(values: list[list[str]], headers: list[str]) -> pd.DataFrame:
    if not values or len(values) == 1:
        return pd.DataFrame(columns=headers)
    hdr, *rows = values
    width = len(hdr)
    rows = [r + [""] * (width - len(r)) for r in rows]
    df = pd.DataFrame(rows, columns=hdr)
    for col in headers:
        if col not in df.columns:
            df[col] = ""
    return df[headers]


def _read_month_fresh(year_month: str, kind: str) -> tuple[Optional[gspread.Worksheet], pd.DataFrame]:
    """Lectura SIN caché (para escribir sobre datos actuales). Devuelve (ws, df);
    ws es None si la pestaña no existe."""
    headers = _headers_for(kind)
    sh = _open_dest()
    try:
        ws = sh.worksheet(_month_tab_name(year_month, kind))
    except gspread.WorksheetNotFound:
        return None, pd.DataFrame(columns=headers)
    return ws, _values_to_df(ws.get_all_values(), headers)


@st.cache_data(ttl=120, show_spinner=False)
def read_month_dataframe(year_month: str, kind: str) -> pd.DataFrame:
    """Lee una pestaña mensual del libro destino. Cacheada 2 min para no
    saturar el rate limit de Google Sheets (60 reads/min por usuario). Sólo
    para MOSTRAR datos; antes de escribir se usa _read_month_fresh()."""
    return _read_month_fresh(year_month, kind)[1]


def _invalidate_month_cache() -> None:
    try:
        read_month_dataframe.clear()
    except Exception:
        pass


def write_month_dataframe(year_month: str, kind: str, df: pd.DataFrame) -> None:
    """Sobrescribe la pestaña mensual completa (snapshot de Bitrix o limpieza
    de filas ignoradas)."""
    headers = _headers_for(kind)
    ws = _ensure_worksheet(_open_dest(), _month_tab_name(year_month, kind), headers,
                           check_headers=False)
    out = df.copy()
    for col in headers:
        if col not in out.columns:
            out[col] = ""
    out = out[headers].fillna("").astype(str)
    ws.resize(rows=max(len(out) + 1, 2), cols=len(headers))
    # RAW: no interpreta el '+' de los números como inicio de fórmula
    ws.update(range_name="A1", values=[headers] + out.values.tolist(),
              value_input_option="RAW")
    _invalidate_month_cache()


def _col_letter(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _apply_row_changes(year_month: str, ws: Optional[gspread.Worksheet],
                       updates: dict[int, list[str]], appends: list[list[str]]) -> None:
    """Escribe sólo las filas que cambiaron (1 batch_update) y agrega las nuevas
    (1 append). `updates` = {indice_0_en_datos: fila}."""
    if not updates and not appends:
        return
    headers = BOT_HEADERS
    if ws is None:
        ws = _ensure_worksheet(_open_dest(), _month_tab_name(year_month, "Bot"), headers,
                               check_headers=False)
    last = _col_letter(len(headers))
    if updates:
        data = [
            {"range": f"A{i + 2}:{last}{i + 2}", "values": [row]}
            for i, row in sorted(updates.items())
        ]
        _with_retry(lambda: ws.batch_update(data, value_input_option="RAW"))
    if appends:
        _with_retry(lambda: ws.append_rows(appends, value_input_option="RAW",
                                           table_range="A1"))
    _invalidate_month_cache()


def _persistable(classification: str) -> str:
    """SIN CLASIFICAR es un placeholder: no se guarda, así las reglas
    automáticas pueden reclasificar el contacto en corridas futuras."""
    c = str(classification or "").strip()
    return "" if c == SIN_CLASIFICAR else c


def batch_upsert_bot_rows(year_month: str, rows: list[dict],
                          key_col: str = "Numero") -> None:
    """Aplica una lista de upserts sobre la pestaña Bot del mes: lectura fresca
    + escritura sólo de las filas afectadas. Usado por el flush de la cola."""
    if not rows:
        return
    ws, df = _with_retry(lambda: _read_month_fresh(year_month, "Bot"))
    idx_by_key = {str(v).strip(): i for i, v in enumerate(df[key_col].astype(str))}
    updates: dict[int, list[str]] = {}
    appends: list[list[str]] = []
    for r in rows:
        key = str(r.get(key_col, "")).strip()
        if not key:
            continue
        r = {**r, "Clasificacion interna": _persistable(r.get("Clasificacion interna", ""))}
        if key in idx_by_key:
            i = idx_by_key[key]
            current = df.iloc[i].astype(str).to_dict()
            merged = {**current, **{k: str(v) for k, v in r.items() if k in BOT_HEADERS}}
            updates[i] = [merged[h] for h in BOT_HEADERS]
        else:
            appends.append([str(r.get(h, "")) for h in BOT_HEADERS])
    _apply_row_changes(year_month, ws, updates, appends)


@st.cache_data(ttl=900, show_spinner=False)
def read_months_batch(year_months: tuple[str, ...], kind: str) -> dict[str, pd.DataFrame]:
    """Varias pestañas mensuales en un solo pedido (para la tendencia de
    meses anteriores): 1 lectura de la lista de pestañas + 1 lectura de
    valores, en lugar de ~3 lecturas por mes. Cacheada 15 min. Los meses sin
    pestaña vuelven vacíos."""
    headers = _headers_for(kind)
    out = {ym: pd.DataFrame(columns=headers) for ym in year_months}
    if not year_months:
        return out
    sh = _open_dest()
    titles = {ws.title for ws in _with_retry(sh.worksheets)}
    wanted = [ym for ym in year_months if _month_tab_name(ym, kind) in titles]
    if not wanted:
        return out
    ranges = [f"'{_month_tab_name(ym, kind)}'" for ym in wanted]
    resp = _with_retry(lambda: sh.values_batch_get(ranges))
    for ym, vr in zip(wanted, resp.get("valueRanges", [])):
        out[ym] = _values_to_df(vr.get("values", []), headers)
    return out


def load_persisted_classifications(year_month: str,
                                   df: Optional[pd.DataFrame] = None) -> dict[str, str]:
    """Devuelve {Numero: Clasificacion interna} de la pestaña mensual,
    ignorando vacíos y el placeholder SIN CLASIFICAR (filas viejas).
    ``df``: pestaña ya leída (ej. con ``read_months_batch``)."""
    if df is None:
        df = read_month_dataframe(year_month, "Bot")
    if df.empty:
        return {}
    out = {}
    for _, r in df.iterrows():
        num = str(r.get("Numero", "")).strip()
        cls = _persistable(r.get("Clasificacion interna", ""))
        if num and cls:
            out[num] = cls
    return out


def sync_month_bot(year_month: str, df: pd.DataFrame,
                   ignored_keys: set[str] | None = None) -> None:
    """Persiste el mes (clasificaciones automáticas incluidas) con un merge
    contra la hoja leída en fresco:

    - Una clasificación ya guardada gana sobre la calculada (es la manual o
      una automática previa). SIN CLASIFICAR no cuenta como guardada.
    - El nombre nuevo gana si no está vacío.
    - Las filas que ya no aparecen se conservan, salvo que su número esté en
      `_ignorados`: en ese caso se reescribe la pestaña sin ellas.
    - Si no hay que borrar nada, sólo se escriben las filas que cambiaron.
    """
    ignored_keys = ignored_keys or set()
    ws, persisted = _with_retry(lambda: _read_month_fresh(year_month, "Bot"))
    persisted = persisted.astype(str)
    idx_by_num = {
        str(n).strip(): i for i, n in enumerate(persisted["Numero"]) if str(n).strip()
    }

    updates: dict[int, list[str]] = {}
    appends: list[list[str]] = []
    for _, r in df.iterrows():
        num = str(r.get("Numero", "")).strip()
        if not num:
            continue
        new_cls = _persistable(r.get("Clasificacion interna", ""))
        if num in idx_by_num:
            i = idx_by_num[num]
            old = persisted.iloc[i].to_dict()
            row = {
                "Fecha": str(r.get("Fecha", "")) or old.get("Fecha", ""),
                "Numero": num,
                "Nombre": str(r.get("Nombre", "")).strip() or old.get("Nombre", ""),
                "Clasificacion interna": _persistable(old.get("Clasificacion interna", "")) or new_cls,
            }
            values = [row[h] for h in BOT_HEADERS]
            if values != [old.get(h, "") for h in BOT_HEADERS]:
                updates[i] = values
        else:
            appends.append([str(r.get("Fecha", "")), num,
                            str(r.get("Nombre", "")).strip(), new_cls])

    to_drop = [i for n, i in idx_by_num.items()
               if ignored_keys and _ignore_key(n) in ignored_keys]
    if to_drop:
        full = persisted.copy()
        for i, values in updates.items():
            full.iloc[i] = values
        full = full.drop(index=to_drop)
        if appends:
            full = pd.concat([full, pd.DataFrame(appends, columns=BOT_HEADERS)],
                             ignore_index=True)
        _with_retry(lambda: write_month_dataframe(year_month, "Bot", full))
    else:
        _apply_row_changes(year_month, ws, updates, appends)


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


@st.cache_data(ttl=60, show_spinner=False)
def _meta_values() -> dict[str, str]:
    """Toda la pestaña _meta en una lectura (cacheada 60 s): las fechas de
    sincronización de varios meses no hacen una lectura cada una."""
    sh = _open_dest()
    try:
        ws = sh.worksheet(_META_TAB)
    except gspread.WorksheetNotFound:
        return {}
    return {row[0]: row[1] for row in ws.get_all_values()[1:] if len(row) >= 2 and row[0]}


def _get_meta(key: str) -> str:
    """Lee una clave arbitraria de la pestaña _meta."""
    return _meta_values().get(key, "")


def _set_meta(key: str, value: str) -> None:
    sh = _open_dest()
    ws = _ensure_worksheet(sh, _META_TAB, _META_HEADERS)
    values = ws.get_all_values()
    for i, row in enumerate(values[1:], start=2):
        if len(row) >= 1 and row[0] == key:
            ws.update(range_name=f"A{i}:B{i}", values=[[key, value]],
                      value_input_option="RAW")
            break
    else:
        ws.append_row([key, value], value_input_option="RAW")
    try:
        _meta_values.clear()
    except Exception:
        pass


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


# ---------------------------------------------------------------------------
# Índice de teléfonos de todos los deals de venta (pestaña _bitrix_telefonos)
# ---------------------------------------------------------------------------
_PHONE_INDEX_TAB = "_bitrix_telefonos"
PHONE_INDEX_HEADERS = ["_phone_sig", "Cliente", "Telefono", "Negocio"]
_PHONE_INDEX_META = "bitrix_phone_index"


@st.cache_data(ttl=600, show_spinner=False)
def read_phone_index() -> tuple[pd.DataFrame, Optional[datetime]]:
    """(df, fecha del último refresco) del índice guardado en el libro destino."""
    sh = _open_dest()
    try:
        ws = sh.worksheet(_PHONE_INDEX_TAB)
    except gspread.WorksheetNotFound:
        return pd.DataFrame(columns=PHONE_INDEX_HEADERS), None
    df = _values_to_df(ws.get_all_values(), PHONE_INDEX_HEADERS)
    raw = _get_meta(_PHONE_INDEX_META)
    try:
        ts = datetime.fromisoformat(raw) if raw else None
    except ValueError:
        ts = None
    return df, ts


def write_phone_index(df: pd.DataFrame) -> None:
    sh = _open_dest()
    ws = _ensure_worksheet(sh, _PHONE_INDEX_TAB, PHONE_INDEX_HEADERS, check_headers=False)
    out = df.reindex(columns=PHONE_INDEX_HEADERS).fillna("").astype(str)
    ws.resize(rows=max(len(out) + 1, 2), cols=len(PHONE_INDEX_HEADERS))
    ws.update(range_name="A1", values=[PHONE_INDEX_HEADERS] + out.values.tolist(),
              value_input_option="RAW")
    _set_meta(_PHONE_INDEX_META, datetime.now().isoformat(timespec="seconds"))
    read_phone_index.clear()
