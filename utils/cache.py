"""Procesamiento y deduplicación de reportes del bot."""

from __future__ import annotations

import re
from datetime import datetime

import pandas as pd

from .phone_ar import format_ar, is_foreign, only_digits, province_of, significant_ar

DERIVADO_BITRIX = "DERIVADO A BITRIX"
DERIVADO_TECNICA = "DERIVADO A TÉCNICA"
SIN_INTERES = "SIN INTERES"
SIN_CLASIFICAR = "SIN CLASIFICAR"

# Agrupación del "Área de interés" del bot en las 4 áreas del reporte.
AREA_MAQUINAS = "Máquinas"
AREA_REPUESTOS = "Repuestos"
AREA_TECNICA = "Servicio Técnico"
AREA_NO_IDENTIFICADA = "No identificado"
AREA_BUCKETS = [AREA_MAQUINAS, AREA_REPUESTOS, AREA_TECNICA, AREA_NO_IDENTIFICADA]

_AREA_PATTERNS = [
    (re.compile(r"repuest", re.I), AREA_REPUESTOS),
    (re.compile(r"t[eé]cnic|servicio|asistencia|reparaci|mantenim", re.I), AREA_TECNICA),
    (re.compile(r"m[aá]quin|maquinaria|venta|compra|cotiz", re.I), AREA_MAQUINAS),
]


def area_bucket(area: str | None) -> str:
    """Lleva el texto libre de 'Área de interés' a Máquinas / Repuestos /
    Servicio Técnico / No identificado (vacío o sin coincidencia)."""
    text = str(area or "").strip()
    if not text:
        return AREA_NO_IDENTIFICADA
    for rx, bucket in _AREA_PATTERNS:
        if rx.search(text):
            return bucket
    return AREA_NO_IDENTIFICADA


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try:
            return datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            continue
    try:
        return pd.to_datetime(value, errors="coerce").to_pydatetime()
    except Exception:
        return None


def _wa_link_to_digits(link: str) -> str:
    if not link:
        return ""
    return only_digits(link)


def clean_source(raw: pd.DataFrame) -> pd.DataFrame:
    """Convierte el DataFrame crudo del libro fuente al formato procesado.

    Salida (columnas):
        Fecha, Numero, Nombre, Area de interes, Resumen general,
        Clasificacion interna, Tipo de contacto, Zona, _dt (datetime), _phone_sig
    """
    if raw.empty:
        return pd.DataFrame(
            columns=[
                "Fecha",
                "Numero",
                "Nombre",
                "Area de interes",
                "Resumen general",
                "Clasificacion interna",
                "Tipo de contacto",
                "Zona",
                "_dt",
                "_phone_sig",
            ]
        )

    dt = raw["fecha_hora"].map(_parse_dt)
    fecha = [d.strftime("%d-%m-%y") if d else "" for d in dt]

    digits = raw["wa_link"].map(_wa_link_to_digits)
    numero_fmt = digits.map(format_ar)
    phone_sig = digits.map(significant_ar)

    nombre = raw["nombre"].fillna("").astype(str).str.strip().replace({"-": ""})
    area = raw["area_interes"].fillna("").astype(str).str.strip()
    tipo = raw["tipo_contacto"].fillna("").astype(str).str.strip()

    # Resumen general: unir los 4 resúmenes por agente con '\n', omitiendo vacíos
    resumen_cols = [
        c for c in ["resumen_1", "resumen_2", "resumen_3", "resumen_4"] if c in raw.columns
    ]
    resumenes = raw[resumen_cols].fillna("").astype(str)
    resumen_general = resumenes.apply(
        lambda row: "\n".join([x for x in (str(v).strip() for v in row) if x]), axis=1
    )

    df = pd.DataFrame(
        {
            "Fecha": fecha,
            "Numero": numero_fmt,
            "Nombre": nombre,
            "Area de interes": area,
            "Resumen general": resumen_general,
            "Clasificacion interna": "",
            "Tipo de contacto": tipo,
            "Zona": digits.map(province_of),
            "_dt": dt,
            "_phone_sig": phone_sig,
        }
    )
    return df


def filter_ignored(df: pd.DataFrame, ignored_keys: set[str]) -> pd.DataFrame:
    """Elimina del DataFrame los reportes cuyo teléfono esté en la lista negra.

    ``ignored_keys`` es el set de claves normalizadas devuelto por
    ``sheets.load_ignored_phones()``: para números argentinos son los últimos
    10 dígitos; para extranjeros, todos los dígitos.
    """
    if df.empty or not ignored_keys:
        return df
    from .phone_ar import only_digits

    def _key_for(row) -> str:
        sig = str(row.get("_phone_sig", "") or "")
        if sig:
            return sig
        return only_digits(str(row.get("Numero", "") or ""))

    keep_mask = df.apply(lambda r: _key_for(r) not in ignored_keys, axis=1)
    return df[keep_mask].reset_index(drop=True)


def unify_recent(df: pd.DataFrame, window_days: int | None = None) -> pd.DataFrame:
    """Unifica reportes del mismo número dentro del mismo mes calendario.

    Todos los reportes con el mismo _phone_sig y el mismo (año, mes) de _dt se
    colapsan sobre la fila más reciente (por _dt), concatenando los resúmenes
    previos. Filas sin teléfono o sin fecha se dejan tal cual.

    El parámetro ``window_days`` se mantiene por compatibilidad con llamadores
    previos pero ya no se usa: la política vigente es dedup total por número
    dentro del mes.
    """
    if df.empty:
        return df

    df = df.copy().sort_values("_dt", na_position="first").reset_index(drop=True)
    keep_idx: list[int] = []
    absorbed_by: dict[int, list[int]] = {}

    def _ym(dt):
        return (dt.year, dt.month) if dt else None

    df["_ym"] = df["_dt"].map(_ym)

    # Filas sin teléfono o sin fecha: no se tocan (imposible agruparlas).
    no_key_mask = (df["_phone_sig"].astype(str) == "") | df["_ym"].isna()
    keep_idx.extend(df.index[no_key_mask].tolist())

    keyed = df[~no_key_mask]
    for (_phone, _ym_val), group in keyed.groupby(["_phone_sig", "_ym"], sort=False):
        indices = group.sort_values("_dt").index.tolist()
        master = indices[-1]  # el más reciente del mes
        keep_idx.append(master)
        if len(indices) > 1:
            absorbed_by[master] = indices[:-1]

    # Combinar resúmenes de los absorbidos hacia el master
    for master, prev_ids in absorbed_by.items():
        parts = []
        for pid in prev_ids:
            r = str(df.at[pid, "Resumen general"]).strip()
            if r:
                parts.append(r)
        prev_join = "\n---\n".join(parts)
        if prev_join:
            existing = str(df.at[master, "Resumen general"]).strip()
            df.at[master, "Resumen general"] = (
                f"{existing}\n---\n[previos]\n{prev_join}" if existing else prev_join
            )
        # Nombre: si el master no tiene y algún previo sí, usar el más reciente con nombre
        if not str(df.at[master, "Nombre"]).strip():
            for pid in reversed(prev_ids):
                n = str(df.at[pid, "Nombre"]).strip()
                if n:
                    df.at[master, "Nombre"] = n
                    break

    result = df.loc[sorted(set(keep_idx))].drop(columns=["_ym"]).reset_index(drop=True)
    return result


def apply_auto_rules(df: pd.DataFrame, bitrix_phone_sig: set[str]) -> pd.DataFrame:
    """Aplica las reglas automáticas de clasificación descriptas en los requisitos."""
    if df.empty:
        return df
    out = df.copy()

    # 1) Números extranjeros -> SIN INTERES
    foreign_mask = out["Numero"].map(is_foreign) & (out["_phone_sig"] == "")
    out.loc[foreign_mask & (out["Clasificacion interna"] == ""), "Clasificacion interna"] = (
        SIN_INTERES
    )

    # 2) Coincidencia con Bitrix -> DERIVADO A BITRIX
    if bitrix_phone_sig:
        in_bitrix = out["_phone_sig"].isin(bitrix_phone_sig) & (out["_phone_sig"] != "")
        out.loc[in_bitrix, "Clasificacion interna"] = DERIVADO_BITRIX

    # 3) Tipo de contacto SI_RESUMEN_G2 -> DERIVADO A TÉCNICA
    # Corre DESPUÉS de Bitrix para pisarlo: un contacto puede tener negocio en
    # otro pipeline que no seguimos, pero si el bot lo derivó a técnica, la
    # clasificación correcta es DERIVADO A TÉCNICA.
    g2 = out["Tipo de contacto"].astype(str).str.upper() == "SI_RESUMEN_G2"
    out.loc[g2, "Clasificacion interna"] = DERIVADO_TECNICA

    # 4) Resto sin clasificación -> SIN CLASIFICAR
    empty = out["Clasificacion interna"].astype(str).str.strip() == ""
    out.loc[empty, "Clasificacion interna"] = SIN_CLASIFICAR
    return out


def overwrite_names_from_bitrix(df: pd.DataFrame, bitrix_df: pd.DataFrame) -> pd.DataFrame:
    """Reemplaza el Nombre por el que figura en Bitrix cuando el teléfono coincide.

    ``bitrix_df`` necesita las columnas ``_phone_sig`` y ``Cliente`` (sirve
    tanto el df de deals del mes como el índice de teléfonos de todos los deals).
    """
    if df.empty or bitrix_df.empty or "_phone_sig" not in bitrix_df.columns:
        return df
    lookup = (
        bitrix_df[bitrix_df["_phone_sig"] != ""]
        .drop_duplicates(subset=["_phone_sig"], keep="first")
        .set_index("_phone_sig")["Cliente"]
        .to_dict()
    )
    out = df.copy()

    def _pick(row):
        sig = row["_phone_sig"]
        if sig and sig in lookup and lookup[sig]:
            return lookup[sig]
        return row["Nombre"]

    out["Nombre"] = out.apply(_pick, axis=1)
    return out


def filter_by_year_month(df: pd.DataFrame, year_month: str) -> pd.DataFrame:
    """year_month = 'YYYY-MM'."""
    if df.empty or "_dt" not in df.columns:
        return df
    year, month = year_month.split("-")
    year, month = int(year), int(month)
    mask = df["_dt"].map(lambda d: bool(d) and d.year == year and d.month == month)
    return df[mask].reset_index(drop=True)


def available_year_months(df: pd.DataFrame) -> list[str]:
    if df.empty or "_dt" not in df.columns:
        return []
    ym = df["_dt"].dropna().map(lambda d: f"{d.year:04d}-{d.month:02d}")
    return sorted(set(ym.tolist()), reverse=True)


def attach_deal_names(df: pd.DataFrame, lookup: pd.DataFrame) -> pd.DataFrame:
    """Agrega la columna 'Negocio' (nombre del/los negocio(s) de Bitrix del
    contacto) cruzando por teléfono. Vacía si el contacto no tiene negocio."""
    out = df.copy()
    if out.empty:
        out["Negocio"] = pd.Series(dtype=str)
        return out
    if lookup.empty or "Negocio" not in lookup.columns:
        out["Negocio"] = ""
        return out
    m = (
        lookup[lookup["_phone_sig"].astype(str) != ""]
        .drop_duplicates("_phone_sig")
        .set_index("_phone_sig")["Negocio"]
    )
    out["Negocio"] = out["_phone_sig"].astype(str).map(m).fillna("")
    return out
