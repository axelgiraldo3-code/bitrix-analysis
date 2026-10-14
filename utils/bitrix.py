"""Cliente REST para la API de Bitrix24 (Webhook entrante)."""
from __future__ import annotations

import time
from typing import Any, Optional
from urllib.parse import urlencode

import pandas as pd
import requests
import streamlit as st

from .machinery import classify_machinery
from .phone_ar import format_ar, significant_ar

# Rate limit: 2 req/sec según Bitrix. _call garantiza >= 0,5 s entre llamadas.
_RATE_SLEEP = 0.5
_last_call_ts = 0.0


# Normalización de nombres de etapa que llegan desde Bitrix (sin tildes, con
# capitalización inconsistente, o con sufijos como ", motivo?") a los nombres
# canónicos usados en branding.py (BITRIX_STAGE_ORDER / BITRIX_STAGE_COLORS).
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

# Tipo de negociación y pipeline de "Venta de máquinas".
SALES_TYPE_IDS = {"SALE", "SALES"}
SALES_CATEGORY_ID = "0"

# UF que contiene el motivo de baja en el portal Cotear (lista enumerada).
# El ID numérico se resuelve al label vía fetch_userfield_options().
REASON_UF_CANDIDATES: list[str] = [
    "UF_CRM_1774960743170",
]

# Campos que la app usa de cada deal (pedir "*" + "UF_*" multiplicaba el
# tamaño de cada respuesta).
DEAL_SELECT = [
    "ID", "TITLE", "TYPE_ID", "CATEGORY_ID", "STAGE_ID", "STAGE_SEMANTIC_ID",
    "DATE_CREATE", "MOVED_TIME", "CONTACT_ID", "COMPANY_ID", "SOURCE_ID",
    *REASON_UF_CANDIDATES,
]

# Prioridad de tipos de teléfono del contacto (requisito: trabajo > móvil > resto).
PHONE_TYPE_PRIORITY = ["WORK", "MOBILE"]


# ---------------------------------------------------------------------------
# Transporte
# ---------------------------------------------------------------------------
def _webhook_base() -> str:
    url = st.secrets["bitrix24"]["webhook_url"].rstrip("/")
    return url + "/"


def _throttle() -> None:
    global _last_call_ts
    wait = _RATE_SLEEP - (time.monotonic() - _last_call_ts)
    if wait > 0:
        time.sleep(wait)
    _last_call_ts = time.monotonic()


def _call(method: str, params: dict[str, Any]) -> dict:
    _throttle()
    url = _webhook_base() + method + ".json"
    resp = requests.post(url, json=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _flatten(params: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    """Aplana params anidados al formato query-string de PHP que usa batch:
    {"filter": {">=X": 1}, "select": ["A","B"]} →
    [("filter[>=X]", "1"), ("select[0]", "A"), ("select[1]", "B")]."""
    pairs: list[tuple[str, str]] = []
    for k, v in (params or {}).items():
        key = f"{prefix}[{k}]" if prefix else str(k)
        if isinstance(v, dict):
            pairs.extend(_flatten(v, key))
        elif isinstance(v, (list, tuple)):
            pairs.extend(_flatten({str(i): x for i, x in enumerate(v)}, key))
        else:
            pairs.append((key, str(v)))
    return pairs


def _batch_call(commands: dict[str, tuple[str, dict]], chunk_size: int = 50) -> dict[str, Any]:
    """Ejecuta múltiples métodos en batch. commands = {key: (method, params)}.

    Devuelve {key: result}. Chunkea de a 50 (límite Bitrix); el rate limit lo
    aplica _call.
    """
    results: dict[str, Any] = {}
    keys = list(commands.keys())
    for i in range(0, len(keys), chunk_size):
        chunk = keys[i:i + chunk_size]
        cmd = {}
        for key in chunk:
            method, params = commands[key]
            qs = urlencode(_flatten(params))
            cmd[key] = method + ("?" + qs if qs else "")
        data = _call("batch", {"cmd": cmd, "halt": 0})
        batch_result = (data.get("result") or {}).get("result") or {}
        for key in chunk:
            results[key] = batch_result.get(key)
    return results


# ---------------------------------------------------------------------------
# Catálogos (cacheados 1 h)
# ---------------------------------------------------------------------------
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


# Etiquetas para SOURCE_ID estándar de Bitrix cuando el portal no personalizó
# los labels. Se sobreescriben por `fetch_source_map()` si la llamada funciona.
SOURCE_DEFAULT_LABELS = {
    "CALL":        "Llamada",
    "EMAIL":       "Email",
    "WEB":         "Sitio Web",
    "ADVERTISING": "Publicidad",
    "PARTNER":     "Referido",
    "RECOMMENDATION": "Recomendación",
    "TRADE_SHOW":  "Feria / Exposición",
    "WEBFORM":     "Formulario web",
    "CALLBACK":    "Callback",
    "RSS":         "RRSS",
    "OTHER":       "Otro",
    "UC_MOB_APP":  "App móvil",
    "STORE":       "Tienda",
    "SELF":        "Propio",
}


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_source_map() -> dict[str, str]:
    """Devuelve {SOURCE_ID: label} desde crm.status.list (ENTITY_ID=SOURCE)."""
    mp: dict[str, str] = dict(SOURCE_DEFAULT_LABELS)
    try:
        data = _call("crm.status.list", {"filter": {"ENTITY_ID": "SOURCE"}})
        for s in data.get("result", []):
            sid = str(s.get("STATUS_ID", "")).strip()
            name = str(s.get("NAME", "")).strip()
            if sid:
                mp[sid] = name or mp.get(sid, sid)
    except Exception:
        pass
    return mp


# ---------------------------------------------------------------------------
# Etapas
# ---------------------------------------------------------------------------
def _stage_label(stage_id: str, semantic: str = "", dyn_map: Optional[dict[str, str]] = None) -> str:
    """Traduce STAGE_ID a nombre canónico (normalizado)."""
    raw = _stage_label_raw(stage_id, semantic, dyn_map)
    return STAGE_NAME_NORMALIZE.get(raw, raw)


def _stage_label_raw(stage_id: str, semantic: str = "", dyn_map: Optional[dict[str, str]] = None) -> str:
    """Traduce STAGE_ID a nombre. Usa mapa dinámico > aliases hardcoded > semantic."""
    if not stage_id and not semantic:
        return ""
    if stage_id:
        if dyn_map and stage_id in dyn_map:
            return dyn_map[stage_id]
        if stage_id in STAGE_NAME_ALIASES:
            return STAGE_NAME_ALIASES[stage_id]
        key = stage_id.split(":")[-1].upper()
        if key in STAGE_NAME_ALIASES:
            return STAGE_NAME_ALIASES[key]
    sem = (semantic or "").upper()
    if sem == "F":
        return "Cerrado Perdido"
    if sem == "S":
        return "Cerrado Ganado"
    if sem == "P":
        return "En negociación"
    return stage_id or ""


def fetch_previous_stages(deals: list[dict]) -> dict[str, str]:
    """{deal_id: STAGE_ID anterior} vía crm.stagehistory.list (un comando por
    deal, en batch de 50). Vacío si el deal nunca cambió de etapa o si la
    llamada falla."""
    current = {str(d.get("ID")): str(d.get("STAGE_ID") or "") for d in deals if d.get("ID")}
    if not current:
        return {}
    commands = {
        f"h{did}": ("crm.stagehistory.list", {
            "entityTypeId": 2,
            "order": {"ID": "DESC"},
            "filter": {"OWNER_ID": did},
            "select": ["ID", "STAGE_ID"],
        })
        for did in current
    }
    out: dict[str, str] = {}
    try:
        results = _batch_call(commands)
    except Exception:
        return out
    for did, cur in current.items():
        res = results.get(f"h{did}") or {}
        items = res.get("items", []) if isinstance(res, dict) else (res or [])
        for it in items:
            sid = str(it.get("STAGE_ID") or "")
            if sid and sid != cur:
                out[did] = sid
                break
    return out


# ---------------------------------------------------------------------------
# Deals, contactos, compañías
# ---------------------------------------------------------------------------
def _month_bounds(year_month: str) -> tuple[str, str]:
    year, month = (int(x) for x in year_month.split("-"))
    ny = year + (1 if month == 12 else 0)
    nm = 1 if month == 12 else month + 1
    return (f"{year:04d}-{month:02d}-01T00:00:00",
            f"{ny:04d}-{nm:02d}-01T00:00:00")


def _paginate_deals(filter_dict: dict, select: Optional[list[str]] = None) -> list[dict]:
    """crm.deal.list completo: la primera página da el total y el resto se
    pide en batch (hasta 50 páginas por llamada)."""
    params = {
        "order": {"DATE_CREATE": "DESC"},
        "filter": filter_dict,
        "select": select or DEAL_SELECT,
    }
    first = _call("crm.deal.list", {**params, "start": 0})
    deals: list[dict] = list(first.get("result", []))
    total = int(first.get("total", len(deals)) or 0)
    starts = list(range(len(deals), total, 50)) if deals else []
    if starts:
        results = _batch_call({f"p{s}": ("crm.deal.list", {**params, "start": s}) for s in starts})
        for s in starts:
            page = results.get(f"p{s}") or []
            if isinstance(page, dict):
                page = page.get("result", [])
            deals.extend(page)
    return deals


def fetch_activity_for_month(year_month: str) -> list[dict]:
    """Deals del pipeline Venta de máquinas (CATEGORY_ID=0, tipo SALE) creados
    o movidos dentro del mes."""
    date_from, date_to = _month_bounds(year_month)
    base = {"CATEGORY_ID": SALES_CATEGORY_ID, "TYPE_ID": "SALE"}

    moved = _paginate_deals({**base, ">=MOVED_TIME": date_from, "<MOVED_TIME": date_to})
    created = _paginate_deals({**base, ">=DATE_CREATE": date_from, "<DATE_CREATE": date_to})

    by_id: dict[str, dict] = {}
    for d in moved + created:
        by_id[str(d.get("ID"))] = d
    return list(by_id.values())


def _pick_phone(entries: list) -> str:
    """Elige el teléfono según PHONE_TYPE_PRIORITY (WORK > MOBILE > resto)."""
    valid = [e for e in (entries or []) if isinstance(e, dict) and e.get("VALUE")]
    for t in PHONE_TYPE_PRIORITY:
        for e in valid:
            if str(e.get("VALUE_TYPE", "")).upper() == t:
                return str(e["VALUE"])
    return str(valid[0]["VALUE"]) if valid else ""


def _parse_contact(c: dict) -> dict:
    phone = _pick_phone(c.get("PHONE") or [])
    if not phone:
        phone = _pick_phone(c.get("EMAIL") or [])
    name = " ".join(
        str(x).strip()
        for x in (c.get("NAME", ""), c.get("SECOND_NAME", ""), c.get("LAST_NAME", ""))
        if x
    ).strip()
    return {"name": name, "phone": phone}


def _list_by_ids(method: str, ids: list[str], select: list[str]) -> list[dict]:
    """crm.<entity>.list filtrando por ID en lotes de 50 (una página por lote)."""
    valid = sorted({str(c) for c in ids if c and str(c) != "0"})
    if not valid:
        return []
    chunks = [valid[i:i + 50] for i in range(0, len(valid), 50)]
    commands = {
        f"q{i}": (method, {"filter": {"ID": chunk}, "select": select})
        for i, chunk in enumerate(chunks)
    }
    results = _batch_call(commands)
    rows: list[dict] = []
    for i in range(len(chunks)):
        page = results.get(f"q{i}") or []
        if isinstance(page, dict):
            page = page.get("result", [])
        rows.extend(page)
    return rows


def fetch_contacts(contact_ids: list[str]) -> dict[str, dict]:
    """Trae {id: {name, phone}} de contactos."""
    rows = _list_by_ids(
        "crm.contact.list", contact_ids,
        ["ID", "NAME", "SECOND_NAME", "LAST_NAME", "PHONE", "EMAIL"],
    )
    return {str(c.get("ID")): _parse_contact(c) for c in rows}


def fetch_companies(company_ids: list[str]) -> dict[str, str]:
    """Trae {id: TITLE} de compañías."""
    rows = _list_by_ids("crm.company.list", company_ids, ["ID", "TITLE"])
    return {str(c.get("ID")): str(c.get("TITLE", "") or "") for c in rows}


DEAL_COLUMNS_OUT = [
    "ID negocio", "Fecha creacion", "Fecha movimiento", "Nuevo",
    "Nombre negocio", "Tipo maquinaria", "Etapa", "Etapa anterior",
    "Cliente", "Compania", "Telefono", "Fuente", "Motivo de baja",
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
    type_col = col("TYPE_ID").str.upper()
    cat_col = col("CATEGORY_ID")
    mask = type_col.isin(SALES_TYPE_IDS) & (cat_col == SALES_CATEGORY_ID)
    df = df[mask].copy()

    if df.empty:
        return pd.DataFrame(columns=DEAL_COLUMNS_OUT)

    contact_ids = col("CONTACT_ID").reindex(df.index).fillna("").astype(str).tolist()
    company_ids = col("COMPANY_ID").reindex(df.index).fillna("").astype(str).tolist()

    contacts = fetch_contacts(contact_ids)
    companies = fetch_companies(company_ids)

    # Bitrix devuelve '2026-10-03T10:00:00+03:00': se usa la hora del portal
    # (primeros 19 caracteres) para no correr la fecha al convertir a UTC.
    fecha_series = pd.to_datetime(col("DATE_CREATE").reindex(df.index).str.slice(0, 19), errors="coerce")
    moved_series = pd.to_datetime(col("MOVED_TIME").reindex(df.index).str.slice(0, 19), errors="coerce")

    if year_month:
        y, m = (int(x) for x in year_month.split("-"))
        nuevos = fecha_series.map(lambda d: pd.notna(d) and d.year == y and d.month == m)
    else:
        nuevos = pd.Series([False] * len(df), index=df.index)

    clientes = [contacts.get(c, {}).get("name", "") for c in contact_ids]
    companias = [companies.get(c, "") for c in company_ids]

    stage_map = fetch_stage_map()
    stage_ids = col("STAGE_ID").reindex(df.index).fillna("").tolist()
    semantics = col("STAGE_SEMANTIC_ID").reindex(df.index).fillna("").tolist()
    etapas = [_stage_label(sid, sem, stage_map) for sid, sem in zip(stage_ids, semantics)]

    prev_ids = fetch_previous_stages(df.to_dict("records"))
    deal_ids = col("ID").reindex(df.index).fillna("").tolist()
    etapas_prev = [
        _stage_label(prev_ids[d], "", stage_map) if d in prev_ids else ""
        for d in deal_ids
    ]

    # Motivo de baja: REASON (si el portal lo expone) y luego los UF configurados
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
                    m = uf_options.get(uf, {}).get(v, v)
                    break
        motivos.append(m)

    source_map = fetch_source_map()
    source_ids = col("SOURCE_ID").reindex(df.index).fillna("").tolist()
    fuentes = [source_map.get(sid, sid) if sid else "" for sid in source_ids]

    out = pd.DataFrame({
        "ID negocio":       deal_ids,
        "Fecha creacion":   fecha_series.dt.strftime("%d-%m-%y").fillna("").tolist(),
        "Fecha movimiento": moved_series.dt.strftime("%d-%m-%y").fillna("").tolist(),
        "Nuevo":            ["Sí" if n else "" for n in nuevos.tolist()],
        "Nombre negocio":   col("TITLE").reindex(df.index).fillna("").tolist(),
        "Etapa":            etapas,
        "Etapa anterior":   etapas_prev,
        "Cliente":          clientes,
        "Compania":         companias,
        "Fuente":           fuentes,
        "Motivo de baja":   motivos,
    })

    out["Tipo maquinaria"] = out["Nombre negocio"].map(classify_machinery)

    phones = [format_ar(contacts.get(c, {}).get("phone", "")) for c in contact_ids]
    out["Telefono"] = phones
    out["_phone_sig"] = [significant_ar(p) for p in phones]

    return out[DEAL_COLUMNS_OUT]


# ---------------------------------------------------------------------------
# Índice de teléfonos de TODOS los deals de venta (para el cruce con el bot)
# ---------------------------------------------------------------------------
PHONE_INDEX_COLUMNS = ["_phone_sig", "Cliente", "Telefono"]


def fetch_phone_index() -> pd.DataFrame:
    """Teléfonos y nombres de los contactos de todos los deals del pipeline
    Venta de máquinas, sin importar cuándo se crearon o movieron."""
    deals = _paginate_deals(
        {"CATEGORY_ID": SALES_CATEGORY_ID, "TYPE_ID": "SALE"},
        select=["ID", "CONTACT_ID"],
    )
    contact_ids = [str(d.get("CONTACT_ID") or "") for d in deals]
    contacts = fetch_contacts(contact_ids)
    rows = []
    for c in contacts.values():
        tel = format_ar(c.get("phone", ""))
        sig = significant_ar(tel)
        if sig:
            rows.append({"_phone_sig": sig, "Cliente": c.get("name", ""), "Telefono": tel})
    if not rows:
        return pd.DataFrame(columns=PHONE_INDEX_COLUMNS)
    return pd.DataFrame(rows).drop_duplicates("_phone_sig")[PHONE_INDEX_COLUMNS]
