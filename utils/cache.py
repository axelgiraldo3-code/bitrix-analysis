"""Procesamiento y deduplicación de reportes del bot."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable

import pandas as pd

from .phone_ar import format_ar, is_foreign, only_digits, significant_ar


DERIVADO_BITRIX = "DERIVADO A BITRIX"
DERIVADO_TECNICA = "DERIVADO A TÉCNICA"
SIN_INTERES = "SIN INTERES"
SIN_CLASIFICAR = "SIN CLASIFICAR"


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
        Clasificacion interna, Tipo de contacto, _dt (datetime), _phone_sig
    """
    if raw.empty:
        return pd.DataFrame(columns=[
            "Fecha", "Numero", "Nombre", "Area de interes",
            "Resumen general", "Clasificacion interna", "Tipo de contacto",
            "_dt", "_phone_sig",
        ])

    dt = raw["fecha_hora"].map(_parse_dt)
    fecha = [d.strftime("%d-%m-%y") if d else "" for d in dt]

    digits = raw["wa_link"].map(_wa_link_to_digits)
    numero_fmt = digits.map(format_ar)
    phone_sig = digits.map(significant_ar)

    nombre = raw["nombre"].fillna("").astype(str).str.strip().replace({"-": ""})
    area = raw["area_interes"].fillna("").astype(str).str.strip()
    tipo = raw["tipo_contacto"].fillna("").astype(str).str.strip()

    # Resumen general: unir los 4 resúmenes por agente con '\n', omitiendo vacíos
    resumen_cols = [c for c in ["resumen_1", "resumen_2", "resumen_3", "resumen_4"] if c in raw.columns]
    resumenes = raw[resumen_cols].fillna("").astype(str)
    resumen_general = resumenes.apply(
        lambda row: "\n".join([x for x in (str(v).strip() for v in row) if x]), axis=1
    )

    df = pd.DataFrame({
        "Fecha": fecha,
        "Numero": numero_fmt,
        "Nombre": nombre,
        "Area de interes": area,
        "Resumen general": resumen_general,
        "Clasificacion interna": "",
        "Tipo de contacto": tipo,
        "_dt": dt,
        "_phone_sig": phone_sig,
    })
    return df


def unify_recent(df: pd.DataFrame, window_days: int = 2) -> pd.DataFrame:
    """Unifica recursivamente reportes del mismo número con < window_days de diferencia.

    Se conserva la fila más reciente (por _dt) y se concatenan los resúmenes previos.
    """
    if df.empty:
        return df

    df = df.copy().sort_values("_dt", na_position="first").reset_index(drop=True)
    keep_idx: list[int] = []
    absorbed_by: dict[int, list[int]] = {}

    # Recorremos por número
    for phone, group in df.groupby("_phone_sig", sort=False):
        if not phone:
            keep_idx.extend(group.index.tolist())
            continue
        rows = group.sort_values("_dt").to_dict("index")
        indices = list(rows.keys())
        # Agrupamos secuencialmente por ventana de 2 días
        current_cluster = [indices[0]]
        clusters = []
        for i in indices[1:]:
            prev_dt = df.at[current_cluster[-1], "_dt"]
            cur_dt = df.at[i, "_dt"]
            if prev_dt and cur_dt and (cur_dt - prev_dt) <= timedelta(days=window_days):
                current_cluster.append(i)
            else:
                clusters.append(current_cluster)
                current_cluster = [i]
        clusters.append(current_cluster)
        for cluster in clusters:
            master = cluster[-1]  # el más reciente
            keep_idx.append(master)
            if len(cluster) > 1:
                absorbed_by[master] = cluster[:-1]

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

    result = df.loc[sorted(set(keep_idx))].reset_index(drop=True)
    return result


def apply_auto_rules(df: pd.DataFrame, bitrix_phone_sig: set[str]) -> pd.DataFrame:
    """Aplica las reglas automáticas de clasificación descriptas en los requisitos."""
    if df.empty:
        return df
    out = df.copy()

    # 1) Números extranjeros -> SIN INTERES
    foreign_mask = out["Numero"].map(is_foreign) & (out["_phone_sig"] == "")
    out.loc[foreign_mask & (out["Clasificacion interna"] == ""), "Clasificacion interna"] = SIN_INTERES

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
    """Reemplaza el Nombre por el que figura en Bitrix cuando el teléfono coincide."""
    if df.empty or bitrix_df.empty or "_phone_sig" not in bitrix_df.columns:
        return df
    lookup = (bitrix_df[bitrix_df["_phone_sig"] != ""]
              .drop_duplicates(subset=["_phone_sig"], keep="first")
              .set_index("_phone_sig")["Cliente"].to_dict())
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
