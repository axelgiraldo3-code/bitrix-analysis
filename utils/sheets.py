"""Google Sheets I/O via gspread.

Convenciones:
- Libro FUENTE: reportes crudos del bot (una sola pestaña, sin cabecera).
- Libro DESTINO: persistencia con pestañas por mes: 'YYYY-MM_Bot' y 'YYYY-MM_Bitrix'.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

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
def read_source_bot_reports() -> pd.DataFrame:
    """Lee la pestaña fuente completa (sin cabecera) y devuelve un DataFrame crudo."""
    cfg = _source_cfg()
    sh = get_client().open_by_key(cfg["spreadsheet_id"])
    ws_name = cfg.get("worksheet_name") or ""
    ws = sh.worksheet(ws_name) if ws_name else sh.sheet1
    rows = ws.get_all_values()
    if not rows:
        return pd.DataFrame()
    # Normalizar a 10 columnas
    max_cols = max(len(r) for r in rows)
    max_cols = max(max_cols, 10)
    padded = [r + [""] * (max_cols - len(r)) for r in rows]
    cols = [
        "fecha_hora", "wa_link", "tipo_contacto", "tipo_contacto_dup",
        "area_interes", "nombre",
        "resumen_1", "resumen_2", "resumen_3", "resumen_4",
    ] + [f"extra_{i}" for i in range(max_cols - 10)]
    return pd.DataFrame(padded, columns=cols[:max_cols])


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


def sync_month_bot(year_month: str, df: pd.DataFrame) -> None:
    """Persiste el snapshot completo del mes (incluye clasificaciones automáticas).

    Merge con lo ya guardado por Numero: las clasificaciones existentes en la
    hoja no se pisan si vienen distintas del snapshot (la hoja es fuente de
    verdad para clasificaciones ya hechas). Sólo se agregan filas nuevas o se
    actualiza el nombre si ahora está poblado.
    """
    persisted = read_month_dataframe(year_month, "Bot")
    persisted_map = {
        str(r["Numero"]): dict(r) for _, r in persisted.iterrows()
        if str(r.get("Numero", "")).strip()
    }

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

    # Conservar filas persistidas que ya no aparecen en el snapshot (histórico)
    for num, existing in persisted_map.items():
        if num not in seen_numeros:
            rows_out.append({
                "Fecha": str(existing.get("Fecha", "")),
                "Numero": num,
                "Nombre": str(existing.get("Nombre", "")),
                "Clasificacion interna": str(existing.get("Clasificacion interna", "")),
            })

    out_df = pd.DataFrame(rows_out, columns=BOT_HEADERS)
    write_month_dataframe(year_month, "Bot", out_df)


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


def get_last_bitrix_sync(year_month: str) -> Optional[datetime]:
    """Devuelve datetime del último sync exitoso desde la API para ese mes."""
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


def list_month_tabs() -> list[str]:
    """Devuelve los meses (YYYY-MM) que tienen alguna pestaña en el destino."""
    sh = _open_dest()
    months: set[str] = set()
    for ws in sh.worksheets():
        title = ws.title
        if len(title) >= 10 and title[4] == "-" and title[7] == "_":
            months.add(title[:7])
    return sorted(months, reverse=True)
