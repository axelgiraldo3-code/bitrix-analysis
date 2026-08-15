"""
Módulo de integración con Bitrix24: extracción de negociaciones (deals),
resolución de contactos/compañías y nombres de etapas, todo vía el webhook
REST configurado en la app.
"""

import requests
from requests.adapters import HTTPAdapter, Retry
import pandas as pd
import streamlit as st

from .helpers import sanitize_text
from .config import STAGE_MAP_BACKUP


def _build_bitrix_session():
    """
    Sesión HTTP compartida con reintentos automáticos (backoff exponencial) para las
    llamadas a la API de Bitrix24. Antes, un timeout o un 429 (rate limit) se perdía
    silenciosamente dentro de un "except: pass" y el registro quedaba con datos
    genéricos ("Sin Nombre") sin dejar rastro de que en realidad fue un fallo de red.
    """
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=0.8,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session


BITRIX_SESSION = _build_bitrix_session()


def bitrix_batch_get(webhook_url, method, ids):
    """
    Resuelve múltiples IDs (contactos, compañías, etc.) contra un método puntual de
    Bitrix24 usando el endpoint batch.json, que admite hasta 50 comandos por request.
    Esto reemplaza el patrón de "1 request por ID" (N+1), que con cientos de negocios
    puede disparar decenas o cientos de llamadas secuenciales y chocar con el rate
    limit de Bitrix24 (~2 req/seg por webhook).
    Devuelve un diccionario {id_str: resultado_o_None}.
    """
    resultados = {}
    if not ids:
        return resultados

    url = webhook_url.rstrip("/") + "/batch.json"
    ids_unicos = [str(i) for i in dict.fromkeys(ids)]  # únicos, preservando orden

    for i in range(0, len(ids_unicos), 50):
        chunk = ids_unicos[i:i + 50]
        cmd = {f"item_{j}": f"{method}?id={cid}" for j, cid in enumerate(chunk)}
        try:
            res = BITRIX_SESSION.post(url, json={"halt": 0, "cmd": cmd}, timeout=20).json()
            result_block = res.get("result", {}).get("result", {})
            for j, cid in enumerate(chunk):
                resultados[cid] = result_block.get(f"item_{j}")
        except Exception as e:
            st.sidebar.warning(f"Fallo al resolver un lote de '{method}' en Bitrix24 ({e}). Esos registros quedarán con datos genéricos.")
            for cid in chunk:
                resultados[cid] = None

    return resultados


def get_bitrix_stage_names(webhook_url):
    """Consulta la API de Bitrix24 para obtener los nombres reales de STAGE_ID."""
    url = webhook_url.rstrip("/")
    endpoint = f"{url}/crm.dealcategory.stage.list.json"
    stages_dict = STAGE_MAP_BACKUP.copy()

    try:
        res = BITRIX_SESSION.get(endpoint, timeout=10).json()
        if "result" in res and res["result"]:
            for item in res["result"]:
                s_id = item.get("STATUS_ID")
                s_name = item.get("NAME")
                if s_id and s_name:
                    stages_dict[s_id] = sanitize_text(s_name)
    except Exception as e:
        # No es crítico: si falla, se sigue trabajando con STAGE_MAP_BACKUP.
        # Se deja constancia visible en vez de fallar en silencio.
        st.sidebar.warning(f"No se pudieron obtener los nombres de etapa desde Bitrix24 ({e}). Se usa el mapeo de respaldo.")
    return stages_dict


@st.cache_data(ttl=1800)
def load_bitrix_deals(webhook_url):
    """
    Extrae negociaciones de Bitrix24, filtra TYPE_ID == 'SALE',
    mapea etapas y normaliza la salida sin arrastrar comentarios multilaboriosos.
    """
    REQUIRED_COLUMNS = [
        "ID", "TITLE", "TYPE_ID", "STAGE_ID", "CATEGORY_ID",
        "OPPORTUNITY", "CURRENCY_ID", "DATE_CREATE", "CONTACT_ID",
        "COMPANY_ID", "Etapa", "AñoMes", "Nombre_Contacto",
        "Compania", "Telefono", "Datos del cliente"
    ]

    if not webhook_url:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

    url = webhook_url.rstrip("/")
    endpoint_deals = f"{url}/crm.deal.list.json"

    try:
        mapa_etapas = get_bitrix_stage_names(webhook_url)

        deals = []
        start = 0
        while True:
            params = {
                "start": start,
                "select": [
                    "ID", "TITLE", "TYPE_ID", "STAGE_ID", "CATEGORY_ID",
                    "OPPORTUNITY", "CURRENCY_ID", "DATE_CREATE",
                    "CONTACT_ID", "COMPANY_ID"
                ]
            }
            res = BITRIX_SESSION.get(endpoint_deals, params=params, timeout=15).json()
            if "result" in res and res["result"]:
                deals.extend(res["result"])
                if "next" in res:
                    start = res["next"]
                else:
                    break
            else:
                break

        if not deals:
            return pd.DataFrame(columns=REQUIRED_COLUMNS)

        clean_deals = []
        for d in deals:
            item = {}
            for k, v in d.items():
                item[k] = sanitize_text(v)
            clean_deals.append(item)

        df_deals = pd.DataFrame(clean_deals)

        for col in ["TITLE", "TYPE_ID", "STAGE_ID", "CONTACT_ID", "COMPANY_ID"]:
            if col not in df_deals.columns:
                df_deals[col] = ""

        df_deals = df_deals[df_deals["TYPE_ID"].str.upper() == "SALE"].copy()

        if df_deals.empty:
            return pd.DataFrame(columns=REQUIRED_COLUMNS)

        df_deals["Etapa"] = df_deals["STAGE_ID"].map(mapa_etapas).fillna(df_deals["STAGE_ID"])

        if "DATE_CREATE" in df_deals.columns:
            df_deals["DATE_CREATE"] = pd.to_datetime(df_deals["DATE_CREATE"], errors="coerce")
            df_deals["AñoMes"] = df_deals["DATE_CREATE"].dt.strftime("%Y-%m").fillna("Sin Fecha")
        else:
            df_deals["DATE_CREATE"] = pd.NaT
            df_deals["AñoMes"] = "Sin Fecha"

        unique_contacts = [cid for cid in df_deals.get("CONTACT_ID", pd.Series()).unique() if str(cid) not in ["0", "", "None"]]
        unique_companies = [compid for compid in df_deals.get("COMPANY_ID", pd.Series()).unique() if str(compid) not in ["0", "", "None"]]

        # Resolución en lote (batch.json) en vez de 1 request HTTP por contacto/compañía:
        # con 333 negocios esto reducía potencialmente 200+ llamadas secuenciales a un
        # puñado de requests, evitando el rate limit de Bitrix24.
        raw_contacts = bitrix_batch_get(webhook_url, "crm.contact.get", unique_contacts)
        raw_companies = bitrix_batch_get(webhook_url, "crm.company.get", unique_companies)

        contacts_cache = {}
        for c_id, data in raw_contacts.items():
            if data:
                nombre = sanitize_text(f"{data.get('NAME', '')} {data.get('LAST_NAME', '')}") or "Sin Nombre"
                tels = data.get("PHONE", [])
                telefono = sanitize_text(tels[0].get("VALUE")) if tels else "Sin Teléfono"
                contacts_cache[c_id] = {"nombre": nombre, "telefono": telefono}
            else:
                contacts_cache[c_id] = {"nombre": "Sin Nombre", "telefono": "Sin Teléfono"}

        companies_cache = {}
        for comp_id, data in raw_companies.items():
            if data:
                companies_cache[comp_id] = sanitize_text(data.get("TITLE", "Sin Compañía"))
            else:
                companies_cache[comp_id] = "Sin Compañía"

        nombres_contacto, telefonos_contacto, nombres_compania = [], [], []

        for _, row in df_deals.iterrows():
            cid = str(row.get("CONTACT_ID", ""))
            compid = str(row.get("COMPANY_ID", ""))

            c_data = contacts_cache.get(cid, {"nombre": "Sin Contacto", "telefono": "Sin Teléfono"})
            nombres_contacto.append(c_data["nombre"])
            telefonos_contacto.append(c_data["telefono"])
            nombres_compania.append(companies_cache.get(compid, "Sin Compañía"))

        df_deals["Nombre_Contacto"] = nombres_contacto
        df_deals["Compania"] = nombres_compania
        df_deals["Telefono"] = telefonos_contacto

        df_deals["Datos del cliente"] = df_deals.apply(
            lambda r: f"Cliente: {r['Nombre_Contacto']} | Empresa: {r['Compania']} | Tel: {r['Telefono']}",
            axis=1
        )

        return df_deals

    except Exception as e:
        st.error(f"Error al extraer datos de Bitrix24: {e}")
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
