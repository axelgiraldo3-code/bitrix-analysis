"""Cliente REST para la API de Bitrix24 (Webhook entrante)."""
from __future__ import annotations

import time
from typing import Any, Optional

import pandas as pd
import requests
import streamlit as st

from .machinery import classify_machinery
from .phone_ar import format_ar, significant_ar

# Rate limit: 2 req/sec según Bitrix. Usamos 0.5s entre llamadas.
_RATE_SLEEP = 0.5


# Normalización de nombres de etapa que llegan desde Bitrix (sin tildes, con
# capitalización inconsistente, o con sufijos como ", motivo?") a los nombres
# canónicos usados en branding.py (BITRIX_STAGE_ORDER / BITRIX_STAGE_COLORS).
# Sin esto los colores del gráfico caen a la paleta default de Plotly.
STAGE_NAME_NORMALIZE = {
    "Cotizado aguardando devolucion": "Cotizado aguardando devolución",
    "En negociacion":                 "En negociación",
    "En Negociacion":                 "En negociación",
    "Ganado en desarrollo":           "Ganado en Desarrollo",
    "Cerrado Perdido, motivo?":       "Cerrado Perdido",
}


# Mapa hardcodeado del pipeline de VENTA DE MÁQUINAS (CATEGORY_ID=0) según
# el portal de Cotear. Se usa como fallback si `fetch_stage_map()` falla.
STAGE_NAME_ALIASES = {
    # Pipeline 0 - Ventas de máquinas
    "UC_U0Q3CX":          "Pendiente de cotizar",
    "NEW":                "Cotizado aguardando devolución",
    "PREPAYMENT_INVOICE": "En negociación",
    "EXECUTING":          "Ganado en Desarrollo",
    "WON":                "Cerrado Ganado",
    "LOSE":               "Cerrado Perdido",
    # Pipeline 15 - Archivadas (donde también hay deals viejos de venta)
    "C15:NEW":            "No Aprobados",
    "C15:WON":            "Cerrado Ganado",
    "C15:LOSE":           "Cerrado Perdido",
    "C15:APOLOGY":        "Analizar la falla",
}

# Categorías (pipelines) que corresponden a "Venta de máquinas".
# Se filtra por el nombre del negocio o el CATEGORY_ID si el portal lo mapea así.
SALES_TYPE_IDS = {"SALE", "SALES"}

# CATEGORY_ID (pipeline) que corresponde a "Pipeline venta de maquinas" en el
# portal de Cotear. En Bitrix el pipeline por defecto tiene ID "0". Este filtro
# se aplica junto con TYPE_ID: un deal debe estar en este pipeline Y ser de
# tipo Venta de máquinas para aparecer en la app.
SALES_CATEGORY_ID = "0"

# UF que contiene el motivo de baja en el portal Cotear (lista enumerada:
# 197=Precio alto, 249=Sin interes real, 251=Sin repuestas, etc.).
# El ID numérico se resuelve al label vía fetch_userfield_options().
REASON_UF_CANDIDATES: list[str] = [
    "UF_CRM_1774960743170",
]


def _webhook_base() -> str:
    url = st.secrets["bitrix24"]["webhook_url"].rstrip("/")
    return url + "/"


def _call(method: str, params: dict[str, Any]) -> dict:
    url = _webhook_base() + method + ".json"
    resp = requests.post(url, json=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _batch_call(commands: dict[str, tuple[str, dict]], chunk_size: int = 50) -> dict[str, Any]:
    """Ejecuta múltiples métodos en batch. commands = {key: (method, params)}.

    Devuelve {key: result} agregado. Chunkea de a 50 (límite Bitrix).
    Aplica rate limit entre chunks.
    """
    results: dict[str, Any] = {}
    keys = list(commands.keys())
    for i in range(0, len(keys), chunk_size):
        chunk = keys[i:i + chunk_size]
        cmd = {}
        for key in chunk:
            method, params = commands[key]
            # Serializar params estilo query-string (formato batch de Bitrix)
            qs_parts = []
            for pk, pv in (params or {}).items():
                if isinstance(pv, (list, tuple)):
                    for v in pv:
                        qs_parts.append(f"{pk}[]={v}")
                else:
                    qs_parts.append(f"{pk}={pv}")
            cmd[key] = method + ("?" + "&".join(qs_parts) if qs_parts else "")
        data = _call("batch", {"cmd": cmd, "halt": 0})
        batch_result = (data.get("result") or {}).get("result") or {}
        for key in chunk:
            results[key] = batch_result.get(key)
        if i + chunk_size < len(keys):
            time.sleep(_RATE_SLEEP)
    return results


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_stage_map() -> dict[str, str]:
    """Trae {STAGE_ID: NAME} de todos los pipelines en una llamada batch."""
    mp: dict[str, str] = {}
    try:
        cats = _call("crm.dealcategory.list", {"select": ["ID", "NAME"]}).get("result", [])
        cat_ids = ["0"] + [str(c["ID"]) for c in cats]
        commands = {f"s{cid}": ("crm.dealcategory.stage.list", {"id": cid}) for cid in cat_ids}
        results = _batch_call(commands)
        for cid in cat_ids:
            for s in (results.get(f"s{cid}") or []):
                mp[str(s["STATUS_ID"])] = str(s.get("NAME", ""))
    except Exception:
        pass
    return mp


def _stage_label(stage_id: str, semantic: str = "", dyn_map: Optional[dict[str, str]] = None) -> str:
    """Traduce STAGE_ID a nombre canónico (normalizado)."""
    raw = _stage_label_raw(stage_id, semantic, dyn_map)
    return STAGE_NAME_NORMALIZE.get(raw, raw)


def _stage_label_raw(stage_id: str, semantic: str = "", dyn_map: Optional[dict[str, str]] = None) -> str:
    """Traduce STAGE_ID a nombre. Usa mapa dinámico > aliases hardcoded > semantic."""
    if not stage_id and not semantic:
        return ""
    if stage_id:
        # 1) Mapa dinámico exacto
        if dyn_map and stage_id in dyn_map:
            return dyn_map[stage_id]
        # 2) Aliases hardcoded con clave completa (ej. 'C15:LOSE')
        if stage_id in STAGE_NAME_ALIASES:
            return STAGE_NAME_ALIASES[stage_id]
        # 3) Aliases por sufijo (pipeline default, ej. 'LOSE')
        key = stage_id.split(":")[-1].upper()
        if key in STAGE_NAME_ALIASES:
            return STAGE_NAME_ALIASES[key]
    # 4) Fallback por semántica (F=fail, S=success, P=in-progress)
    sem = (semantic or "").upper()
    if sem == "F":
        return "Cerrado Perdido"
    if sem == "S":
        return "Cerrado Ganado"
    if sem == "P":
        return "En negociación"
    return stage_id or ""


def _extract_phone(deal: dict) -> str:
    """Prioridad: WORK > MOBILE > cualquier otro. Fallback a email si nada."""
    # Bitrix suele exponer 'PHONE' como multifield en crm.contact; en crm.deal
    # el número viene por el contacto asociado. Aquí probamos varias claves.
    for key in ("PHONE_WORK", "WORK_PHONE", "PHONE", "MOBILE"):
        val = deal.get(key)
        if isinstance(val, list) and val:
            v = val[0].get("VALUE") if isinstance(val[0], dict) else val[0]
            if v:
                return str(v)
        elif val:
            return str(val)
    return ""


def _month_bounds(year_month: str) -> tuple[str, str]:
    year, month = year_month.split("-")
    year, month = int(year), int(month)
    ny = year + (1 if month == 12 else 0)
    nm = 1 if month == 12 else month + 1
    return (f"{year:04d}-{month:02d}-01T00:00:00",
            f"{ny:04d}-{nm:02d}-01T00:00:00")


def _paginate_deals(filter_dict: dict) -> list[dict]:
    """Pagina crm.deal.list con un filtro dado."""
    deals: list[dict] = []
    start = 0
    while True:
        data = _call("crm.deal.list", {
            "start": start,
            "order": {"DATE_CREATE": "DESC"},
            "filter": filter_dict,
            "select": ["*", "UF_*"],
        })
        page = data.get("result", [])
        deals.extend(page)
        nxt = data.get("next")
        if nxt is None:
            break
        start = nxt
        time.sleep(_RATE_SLEEP)
    return deals


def fetch_activity_for_month(year_month: str) -> list[dict]:
    """Trae la 'actividad del mes' filtrando server-side por pipeline Venta de
    máquinas (CATEGORY_ID=0) + tipo SALE, y MOVED_TIME o DATE_CREATE en el mes.
    """
    date_from, date_to = _month_bounds(year_month)
    base = {"CATEGORY_ID": SALES_CATEGORY_ID, "TYPE_ID": "SALE"}

    moved = _paginate_deals({**base, ">=MOVED_TIME": date_from, "<MOVED_TIME": date_to})
    created = _paginate_deals({**base, ">=DATE_CREATE": date_from, "<DATE_CREATE": date_to})

    by_id: dict[str, dict] = {}
    for d in moved + created:
        by_id[str(d.get("ID"))] = d
    return list(by_id.values())


# Alias de compatibilidad
def fetch_deals_for_month(year_month: str) -> list[dict]:
    return fetch_activity_for_month(year_month)


def fetch_all_deals(progress: Optional[callable] = None) -> list[dict]:
    """Trae todos los deals. Primera llamada da 'total'; el resto va en batch."""
    first = _call("crm.deal.list", {
        "start": 0,
        "order": {"DATE_CREATE": "DESC"},
        "select": ["*", "UF_*"],
    })
    deals: list[dict] = list(first.get("result", []))
    total = int(first.get("total", len(deals)))
    if progress:
        progress(len(deals))

    if total <= len(deals):
        return deals

    # Construir el resto de las páginas (start=50, 100, 150…) en batch
    remaining_starts = list(range(len(deals), total, 50))
    time.sleep(_RATE_SLEEP)
    commands = {
        f"p{s}": ("crm.deal.list", {
            "start": s,
            "order[DATE_CREATE]": "DESC",
            "select[]": "*",
        }) for s in remaining_starts
    }
    # Nota: en batch los UF hay que pedirlos con select[]=UF_*
    for k in commands:
        commands[k] = (commands[k][0], {**commands[k][1], "select[]": ["*", "UF_*"]})

    results = _batch_call(commands)
    for s in remaining_starts:
        page = results.get(f"p{s}") or []
        if isinstance(page, dict):
            page = page.get("result", [])
        deals.extend(page)
        if progress:
            progress(len(deals))
    return deals


def _parse_contact(c: dict) -> dict:
    phone = ""
    for entry in (c.get("PHONE") or []):
        v = entry.get("VALUE") if isinstance(entry, dict) else ""
        if v:
            phone = str(v)
            break
    if not phone:
        for entry in (c.get("EMAIL") or []):
            v = entry.get("VALUE") if isinstance(entry, dict) else ""
            if v:
                phone = str(v)
                break
    name = " ".join(
        str(x).strip()
        for x in (c.get("NAME", ""), c.get("SECOND_NAME", ""), c.get("LAST_NAME", ""))
        if x
    ).strip()
    return {"name": name, "phone": phone}


def fetch_contacts(contact_ids: list[str]) -> dict[str, dict]:
    """Trae {id: {name, phone}} de contactos en batch."""
    valid = [str(c) for c in contact_ids if c and str(c) != "0"]
    if not valid:
        return {}
    commands = {f"c{cid}": ("crm.contact.get", {"id": cid}) for cid in valid}
    results = _batch_call(commands)
    out: dict[str, dict] = {}
    for cid in valid:
        c = results.get(f"c{cid}") or {}
        if isinstance(c, dict):
            out[cid] = _parse_contact(c)
        else:
            out[cid] = {"name": "", "phone": ""}
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_userfield_options() -> dict[str, dict[str, str]]:
    """Trae {UF_NAME: {ID_opcion: LABEL}} para los userfields tipo lista de deals."""
    out: dict[str, dict[str, str]] = {}
    try:
        data = _call("crm.deal.userfield.list", {})
        for f in data.get("result", []):
            if f.get("USER_TYPE_ID") != "enumeration":
                continue
            fname = f.get("FIELD_NAME", "")
            items = f.get("LIST") or []
            out[fname] = {str(it["ID"]): str(it.get("VALUE", "")) for it in items}
    except Exception:
        pass
    return out


def fetch_companies(company_ids: list[str]) -> dict[str, str]:
    """Trae {id: TITLE} de compañías en batch."""
    valid = [str(c) for c in company_ids if c and str(c) != "0"]
    if not valid:
        return {}
    commands = {f"co{cid}": ("crm.company.get", {"id": cid}) for cid in valid}
    results = _batch_call(commands)
    out: dict[str, str] = {}
    for cid in valid:
        c = results.get(f"co{cid}") or {}
        if isinstance(c, dict):
            out[cid] = str(c.get("TITLE", "") or "")
        else:
            out[cid] = ""
    return out


DEAL_COLUMNS_OUT = [
    "ID negocio", "Fecha creacion", "Fecha movimiento", "Nuevo",
    "Nombre negocio", "Tipo maquinaria", "Etapa",
    "Cliente", "Compania", "Telefono", "Motivo de baja",
    "_phone_sig",
]


def deals_to_dataframe(deals: list[dict], year_month: Optional[str] = None) -> pd.DataFrame:
    """Filtra a 'Venta de máquinas' y normaliza campos.

    year_month (YYYY-MM): si se pasa, la columna 'Nuevo' marca los deals cuya
    DATE_CREATE cae dentro de ese mes.
    """
    if not deals:
        return pd.DataFrame(columns=DEAL_COLUMNS_OUT)

    df = pd.DataFrame(deals)

    def col(name: str) -> pd.Series:
        if name in df.columns:
            return df[name].fillna("").astype(str)
        return pd.Series([""] * len(df), index=df.index, dtype=str)

    # Doble filtro: TYPE_ID en SALES_TYPE_IDS Y CATEGORY_ID == SALES_CATEGORY_ID.
    # Esto excluye deals que son "Ventas de máquinas" por tipo pero que fueron
    # cargados en pipelines equivocados (asistencia técnica, archivadas, etc.).
    type_col = col("TYPE_ID").str.upper()
    cat_col = col("CATEGORY_ID")
    mask = type_col.isin(SALES_TYPE_IDS) & (cat_col == SALES_CATEGORY_ID)
    df = df[mask].copy()

    if df.empty:
        return pd.DataFrame(columns=DEAL_COLUMNS_OUT)

    contact_ids = col("CONTACT_ID").reindex(df.index).fillna("").astype(str).tolist()
    company_ids = col("COMPANY_ID").reindex(df.index).fillna("").astype(str).tolist()

    contacts = fetch_contacts(sorted({c for c in contact_ids if c and c != "0"}))
    companies = fetch_companies(sorted({c for c in company_ids if c and c != "0"}))

    fecha_series = pd.to_datetime(col("DATE_CREATE").reindex(df.index), errors="coerce")
    moved_series = pd.to_datetime(col("MOVED_TIME").reindex(df.index), errors="coerce")

    # Flag Nuevo: DATE_CREATE cae en el mes especificado
    if year_month:
        y, m = year_month.split("-")
        y, m = int(y), int(m)
        nuevos = fecha_series.map(lambda d: bool(d) and d.year == y and d.month == m)
    else:
        nuevos = pd.Series([False] * len(df), index=df.index)

    clientes = [contacts.get(c, {}).get("name", "") for c in contact_ids]
    companias = [companies.get(c, "") for c in company_ids]

    # Etapa: mapa dinámico + STAGE_ID + STAGE_SEMANTIC_ID
    stage_map = fetch_stage_map()
    stage_ids = col("STAGE_ID").reindex(df.index).fillna("").tolist()
    semantics = col("STAGE_SEMANTIC_ID").reindex(df.index).fillna("").tolist()
    etapas = [_stage_label(sid, sem, stage_map) for sid, sem in zip(stage_ids, semantics)]

    # Motivo de baja: probar REASON y luego los UF configurados (resolviendo listas)
    uf_options = fetch_userfield_options()
    motivos = []
    reason_series = col("REASON").reindex(df.index).fillna("").tolist()
    uf_series = {uf: col(uf).reindex(df.index).fillna("").tolist() for uf in REASON_UF_CANDIDATES}
    for i in range(len(df)):
        m = reason_series[i]
        if not m:
            for uf in REASON_UF_CANDIDATES:
                v = uf_series[uf][i]
                if v and v != "False":
                    # Si es una lista enumerada, resolver ID → label
                    if uf in uf_options and v in uf_options[uf]:
                        m = uf_options[uf][v]
                    else:
                        m = v
                    break
        motivos.append(m)

    out = pd.DataFrame({
        "ID negocio":       col("ID").reindex(df.index).fillna("").tolist(),
        "Fecha creacion":   fecha_series.dt.strftime("%d-%m-%y").fillna("").tolist(),
        "Fecha movimiento": moved_series.dt.strftime("%d-%m-%y").fillna("").tolist(),
        "Nuevo":            ["Sí" if n else "" for n in nuevos.tolist()],
        "Nombre negocio":   col("TITLE").reindex(df.index).fillna("").tolist(),
        "Etapa":            etapas,
        "Cliente":          clientes,
        "Compania":         companias,
        "Motivo de baja":   motivos,
    })

    out["Tipo maquinaria"] = out["Nombre negocio"].map(classify_machinery)

    raw_phones = df.apply(_extract_phone, axis=1).tolist()
    phones = []
    for i, raw in enumerate(raw_phones):
        if not raw:
            raw = contacts.get(contact_ids[i], {}).get("phone", "")
        phones.append(format_ar(raw))
    out["Telefono"] = phones
    out["_phone_sig"] = [significant_ar(p) for p in phones]

    return out[DEAL_COLUMNS_OUT]
