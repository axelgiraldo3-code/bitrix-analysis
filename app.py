import re
import os
import time
import html
import requests
from requests.adapters import HTTPAdapter, Retry
import pandas as pd
import plotly.express as px
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# Sesión HTTP compartida con reintentos automáticos (backoff exponencial) para las
# llamadas a la API de Bitrix24. Antes, un timeout o un 429 (rate limit) se perdía
# silenciosamente dentro de un "except: pass" y el registro quedaba con datos
# genéricos ("Sin Nombre") sin dejar rastro de que en realidad fue un fallo de red.
def _build_bitrix_session():
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

# ---------------------------------------------------------
# CONFIGURACIÓN DE PÁGINA Y ESTILOS
# ---------------------------------------------------------
st.set_page_config(
    page_title="Gestión de Consultas & Bitrix24",
    page_icon="📊",
    layout="wide"
)

st.title("Control de Consultas de WhatsApp y CRM Bitrix24")

# Archivos locales para almacenamiento y caché
LOCAL_CLASSIFICATIONS_FILE = "clasificaciones_locales.csv"
CACHE_SHEETS_FILE = "consultas_bot.csv"
CACHE_BITRIX_FILE = "negocios_bitrix.csv"

# Opciones de clasificación manual
OPCIONES_CLASIFICACION = [
    "Negocio en Bitrix",
    "Pendiente",
    "Venta de repuestos",
    "Derivado al área técnica",
    "Derivado a RRHH",
    "Sin respuesta",
    "Consulta incompatible",
    "Sin interés",
    "Spam/Servicios"
]

# Mapeo de colores exactos de las etapas de Bitrix24 (Hexadecimal).
# Cada etapa tiene UNA sola forma canónica; las variantes de mayúsculas/tildes que
# puedan venir de Bitrix se resuelven vía STAGE_NAME_ALIASES + normalizar_etapa(),
# en vez de duplicar entradas por cada variante (lo que antes podía desalinearse
# fácilmente si aparecía una variante no contemplada).
BITRIX_STAGE_COLORS = {
    "Pendiente de cotizar": "#9CE6FE",
    "Cotizado aguardando devolución": "#2FC6F6",
    "En negociación": "#55D4E6",
    "Ganado en desarrollo": "#47E4C2",
    "Ganado / Cerrado": "#7BD100",
    "Perdido": "#FF5752",
    "Sin Etapa": "#A6A6A6",
}

# Variantes conocidas (mayúsculas, sin tilde, redacciones alternativas) que deben
# resolverse a la etapa canónica de arriba.
STAGE_NAME_ALIASES = {
    "PENDIENTE DE COTIZAR": "Pendiente de cotizar",
    "Cotizado aguardando devolucion": "Cotizado aguardando devolución",
    "COTIZADO AGUARDANDO DEVOLUCION": "Cotizado aguardando devolución",
    "En negociacion": "En negociación",
    "EN NEGOCIACION": "En negociación",
    "Cerrado Ganado": "Ganado / Cerrado",
    "Cerrado Perdido, motivo?": "Perdido",
    "Cerrado Perdido": "Perdido",
    "Rechazado": "Perdido",
}

# MAPEO DE ETAPAS DE RESPALDO
STAGE_MAP_BACKUP = {
    "NEW": "Cotizado aguardando devolución",
    "UC_U0Q3CX": "Pendiente de cotizar",
    "PREPARATION": "En Negociación",
    "PREPAYMENT_INVOICE": "Factura Emitida",
    "EXECUTOR": "En Ejecución",
    "FINAL_INVOICE": "Factura Final",
    "WON": "Ganado / Cerrado",
    "LOSE": "Perdido",
    "APOLOGY": "Rechazado"
}

# ---------------------------------------------------------
# CONFIGURACIÓN DE SIDEBAR
# ---------------------------------------------------------
st.sidebar.header("Configuración y Conexiones")

# Google Sheets Config
# Los valores por defecto se leen de st.secrets (.streamlit/secrets.toml), NUNCA hardcodeados
# en el código fuente. Esto evita exponer el Spreadsheet ID y, sobre todo, la URL del
# webhook de Bitrix24 (que da acceso de lectura/escritura al CRM) dentro del repositorio.
st.sidebar.subheader("Google Sheets")
spreadsheet_id = st.sidebar.text_input(
    "ID o Nombre de la Spreadsheet",
    value=st.secrets.get("google_sheets", {}).get("spreadsheet_id", "")
)
worksheet_name = st.sidebar.text_input(
    "Nombre de la Pestaña",
    value=st.secrets.get("google_sheets", {}).get("worksheet_name", "Hoja1")
)

# Bitrix24 Config
st.sidebar.subheader("Bitrix24 Webhook")
bitrix_webhook_url = st.sidebar.text_input(
    "Webhook URL de Bitrix24",
    value=st.secrets.get("bitrix24", {}).get("webhook_url", ""),
    type="password"
)

st.sidebar.markdown("---")
st.sidebar.subheader("Sincronización de Datos")
btn_refresh = st.sidebar.button("🔄 Actualizar Datos desde APIs")

# ---------------------------------------------------------
# FUNCIONES AUXILIARES DE LIMPIEZA Y SANITIZACIÓN
# ---------------------------------------------------------
def clean_phone(phone_str):
    """
    Extrae únicamente dígitos del número de teléfono y normaliza 
    el formato argentino (remueve prefijos 549 / 54) o toma los últimos 10 dígitos.
    """
    if pd.isna(phone_str) or not phone_str:
        return ""
    
    # Dejar solo dígitos
    digits = re.sub(r"\D", "", str(phone_str))
    
    if not digits:
        return ""
    
    # Si empieza con 549 (ej: 5491153407980) -> remover 549
    if digits.startswith("549") and len(digits) >= 12:
        digits = digits[3:]
    # Si empieza con 54 (ej: 541153407980) -> remover 54
    elif digits.startswith("54") and len(digits) >= 11:
        digits = digits[2:]
    
    # Como respaldo adicional, si el número es más largo de 10 dígitos,
    # tomamos únicamente los últimos 10 dígitos (código de área + número)
    if len(digits) > 10:
        digits = digits[-10:]
        
    return digits

def normalizar_etapa(valor):
    """
    Normaliza el nombre de una etapa de Bitrix24 a su forma canónica definida en
    BITRIX_STAGE_COLORS, usando STAGE_NAME_ALIASES para resolver variantes de
    mayúsculas/tildes/redacción. Evita que una etapa quede sin color asignado
    (cayendo al gris de "Sin Etapa" en el gráfico) solo por una diferencia de formato.
    """
    v = re.sub(r"\s+", " ", str(valor).strip())
    return STAGE_NAME_ALIASES.get(v, v)

def sanitize_text(text):
    """
    Sanea de forma extrema cualquier texto eliminando HTML, saltos de línea,
    retornos de carro y tabulaciones que rompen las filas del CSV.
    """
    if pd.isna(text) or text is None:
        return ""
    t = str(text)
    t = html.unescape(t)
    t = re.sub(r'<[^>]+>', ' ', t)        # Quitar etiquetas HTML
    t = re.sub(r'[\r\n\t]+', ' ', t)      # Eliminar \n, \r, \t
    t = t.replace('"', "'")                # Reemplazar comillas dobles por simples
    return " ".join(t.split())            # Normalizar espacios

def deduplicate_bot_queries(df):
    """
    Deduplica las consultas del bot según las siguientes reglas:
    1. Para el mismo contacto (Telefono_Limpio) DENTRO DEL MISMO MES (AñoMes) y con
       la misma 'Área de interés': se reemplaza, conservando únicamente la consulta
       más reciente de ese mes.
    2. NO se deduplica entre meses distintos, aunque sea el mismo contacto y la misma
       área de interés, ya que una misma negociación puede extenderse por varios meses
       y cada mes debe reflejar su propio reporte.
    3. Si dentro del mismo mes cambia el 'Área de interés', ambos registros se conservan
       (se consideran consultas distintas).
    Requiere que "AñoMes" ya esté calculado en el DataFrame antes de llamar esta función.
    """
    if df.empty or "Telefono_Limpio" not in df.columns or "FechaHora" not in df.columns:
        return df

    df_sorted = df.sort_values(by="FechaHora", ascending=True).copy()

    subset_cols = ["Telefono_Limpio", "AñoMes"]
    if "Área de interés" in df_sorted.columns:
        subset_cols.append("Área de interés")

    df_dedup = df_sorted.drop_duplicates(subset=subset_cols, keep="last")

    df_dedup = df_dedup.sort_values(by="FechaHora", ascending=False).reset_index(drop=True)
    return df_dedup

# ---------------------------------------------------------
# FUNCIONES DE EXTRACCIÓN DIRECTA DESDE APIS
# ---------------------------------------------------------
@st.cache_data(ttl=1800)
def load_google_sheets_data(sheet_id, sheet_name):
    """Carga los datos desde Google Sheets sanitizando los campos."""
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        # Las credenciales de la service account se leen desde st.secrets
        # (.streamlit/secrets.toml, sección [gcp_service_account]) en vez de un archivo
        # credentials.json en disco, para no exponer la clave privada en el repositorio.
        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=scopes
            )
        else:
            creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
        client = gspread.authorize(creds)
        
        if sheet_id.startswith("http") or len(sheet_id) > 30:
            sheet = client.open_by_key(sheet_id).worksheet(sheet_name)
        else:
            sheet = client.open(sheet_id).worksheet(sheet_name)
        
        raw_values = sheet.get_all_values()
        
        if not raw_values:
            return pd.DataFrame()

        column_names = [
            "FechaHora", 
            "Enlace de Whatsapp", 
            "Clasificación", 
            "Duplicado_Clasificacion", 
            "Área de interés", 
            "Nombre", 
            "Agente_G", 
            "Agente_H", 
            "Agente_I", 
            "Agente_J", 
            "Agente_K"
        ]
        
        df = pd.DataFrame(raw_values)
        
        if len(df.columns) <= len(column_names):
            df.columns = column_names[:len(df.columns)]
        else:
            df.columns = column_names + [f"Columna_{i+1}" for i in range(len(column_names), len(df.columns))]

        # Concatenación inteligente de agentes para el resumen de consulta
        agentes_cols = [col for col in ["Agente_G", "Agente_H", "Agente_I", "Agente_J", "Agente_K"] if col in df.columns]
        
        def unir_resumenes(row):
            resumenes = []
            for col in agentes_cols:
                val = sanitize_text(row[col])
                if val and val.lower() not in ["nan", "none", "", "null"]:
                    resumenes.append(val)
            return " | ".join(resumenes) if resumenes else "Sin resumen reportado"

        df["Resumen de la consulta"] = df.apply(unir_resumenes, axis=1)

        for col in df.columns:
            df[col] = df[col].apply(sanitize_text)

        df["FechaHora"] = pd.to_datetime(df["FechaHora"], errors="coerce")
        df["AñoMes"] = df["FechaHora"].dt.strftime("%Y-%m").fillna("Sin Fecha")
        
        if "Enlace de Whatsapp" in df.columns:
            df["Telefono_Limpio"] = df["Enlace de Whatsapp"].apply(clean_phone)
            
        df = deduplicate_bot_queries(df)
        return df

    except Exception as e:
        st.error(f"Error al conectar con Google Sheets: {e}")
        return pd.DataFrame()

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

# ---------------------------------------------------------
# CAPA DE CACHÉ LOCAL Y AUTOMATIZACIONES
# ---------------------------------------------------------
def apply_automatic_classifications(df_sheets, df_bitrix):
    """
    Aplica las reglas automáticas de clasificación y estandarización de datos:
    1. Negocio en Bitrix: Coincidencia de teléfono Y negocio del mismo mes o posterior.
    2. Sobreescritura de Nombre: Estandariza el Nombre con el dato de Bitrix24 siempre que exista.
    3. Área técnica: Si 'Clasificación' origen es 'SI_RESUMEN_G2'.
    """
    if df_sheets.empty:
        return df_sheets

    # Indexar los negocios de Bitrix por teléfono normalizado
    bitrix_records = {}
    if not df_bitrix.empty and "Telefono" in df_bitrix.columns:
        for _, row_b in df_bitrix.iterrows():
            tel_b = clean_phone(row_b.get("Telefono"))
            if not tel_b:
                continue
            
            fecha_b = pd.to_datetime(row_b.get("DATE_CREATE"), errors="coerce")
            nombre_b = str(row_b.get("Nombre_Contacto", "")).strip()
            
            # Limpiar valores genéricos o sin datos válidos
            if nombre_b.lower() in ["sin nombre", "none", "nan", "", "null"]:
                nombre_b = ""

            record = {
                "fecha": fecha_b,
                "nombre": nombre_b
            }
            
            if tel_b not in bitrix_records:
                bitrix_records[tel_b] = []
            bitrix_records[tel_b].append(record)

    for idx, row in df_sheets.iterrows():
        # "Telefono_Limpio" ya fue procesado por clean_phone() al cargar los datos del bot;
        # solo se vuelve a limpiar si por algún motivo llega vacío y hay que derivarlo
        # del "Enlace de Whatsapp" crudo.
        tel_limpio = str(row.get("Telefono_Limpio", "")).strip()
        if not tel_limpio:
            tel_limpio = clean_phone(row.get("Enlace de Whatsapp", ""))
        fecha_consulta = pd.to_datetime(row.get("FechaHora"), errors="coerce")
        clasif_actual = str(row.get("Clasificacion_Manual", "Pendiente"))

        # --- EVALUACIÓN DE COINCIDENCIA CON BITRIX ---
        tiene_negocio_valido = False
        nombre_bitrix_encontrado = ""

        if tel_limpio and tel_limpio in bitrix_records:
            negocios_cliente = bitrix_records[tel_limpio]
            
            for neg in negocios_cliente:
                # Guardar el nombre oficial registrado en Bitrix
                if neg["nombre"] and not nombre_bitrix_encontrado:
                    nombre_bitrix_encontrado = neg["nombre"]

                # Regla Temporal: Mes/Año del negocio >= Mes/Año de la consulta
                if pd.notna(fecha_consulta) and pd.notna(neg["fecha"]):
                    periodo_consulta = fecha_consulta.to_period('M')
                    periodo_negocio = neg["fecha"].to_period('M')
                    
                    if periodo_negocio >= periodo_consulta:
                        tiene_negocio_valido = True

        # --- SOBREESCRITURA Y NORMALIZACIÓN DE NOMBRE ---
        # Si se encontró un nombre válido en Bitrix, sobreescribe el capturado por el bot
        if nombre_bitrix_encontrado:
            df_sheets.loc[idx, "Nombre"] = nombre_bitrix_encontrado

        # --- ASIGNACIÓN DE CLASIFICACIÓN AUTOMÁTICA ---
        if clasif_actual in ["Pendiente", "", "nan"]:
            # Regla 1: Negocio válido en Bitrix (mismo mes o posterior)
            if tiene_negocio_valido:
                df_sheets.loc[idx, "Clasificacion_Manual"] = "Negocio en Bitrix"
                continue

            # Regla 2: Clasificación de origen igual a SI_RESUMEN_G2
            clasificacion_origen = str(row.get("Clasificación", "")).strip()
            if clasificacion_origen == "SI_RESUMEN_G2":
                df_sheets.loc[idx, "Clasificacion_Manual"] = "Derivado al área técnica"
                continue

    return df_sheets

def get_data_with_local_cache(sheet_id, sheet_name, webhook_url, force_refresh=False):
    """Carga datos locales o los reconstruye limpiamente si es necesario."""
    cache_valida = False
    
    if os.path.exists(CACHE_SHEETS_FILE) and os.path.exists(CACHE_BITRIX_FILE) and not force_refresh:
        try:
            df_bitrix_check = pd.read_csv(CACHE_BITRIX_FILE, nrows=2)
            df_sheets_check = pd.read_csv(CACHE_SHEETS_FILE, nrows=2)
            bitrix_ok = "TITLE" in df_bitrix_check.columns and "Etapa" in df_bitrix_check.columns
            sheets_ok = "FechaHora" in df_sheets_check.columns and "Telefono_Limpio" in df_sheets_check.columns
            cache_valida = bitrix_ok and sheets_ok
        except Exception:
            cache_valida = False

    if cache_valida:
        df_sheets = pd.read_csv(CACHE_SHEETS_FILE)
        df_bitrix = pd.read_csv(CACHE_BITRIX_FILE)
        
        if "FechaHora" in df_sheets.columns:
            df_sheets["FechaHora"] = pd.to_datetime(df_sheets["FechaHora"], errors="coerce")
        if "DATE_CREATE" in df_bitrix.columns:
            df_bitrix["DATE_CREATE"] = pd.to_datetime(df_bitrix["DATE_CREATE"], errors="coerce")
            
        return df_sheets, df_bitrix
    else:
        with st.spinner("🔄 Conectando y actualizando datos desde Google Sheets y Bitrix24..."):
            df_sheets = load_google_sheets_data(sheet_id, sheet_name)
            df_bitrix = load_bitrix_deals(webhook_url)

            if not df_sheets.empty:
                df_sheets.to_csv(CACHE_SHEETS_FILE, index=False, encoding="utf-8-sig")
            if not df_bitrix.empty:
                df_bitrix.to_csv(CACHE_BITRIX_FILE, index=False, encoding="utf-8-sig")

            st.toast("⚡ Datos sincronizados y caché local reconstruida con éxito", icon="✅")
            return df_sheets, df_bitrix

def classify_machine_type(title):
    """Clasifica el tipo de máquina según el nombre del negocio."""
    if not title or pd.isna(title):
        return "Otros / No especificado"
    
    t = str(title).upper()
    
    if "TORNO" in t and "CNC" in t:
        return "Tornos CNC"
    elif "TORNO" in t:
        return "Tornos convencionales"
    elif "FRESADORA" in t and "CNC" in t:
        return "Fresadoras CNC"
    elif "FRESADORA" in t:
        return "Fresadoras"
    elif "CENTRO" in t or "MECANIZADO" in t:
        return "Centros de Mecanizado"
    elif "RECTIFICADORA" in t:
        return "Rectificadoras CNC"
    elif "ALESADORA" in t:
        return "Alesadoras CNC"
    elif "MORTAJADORA" in t:
        return "Mortajadoras"
    elif "CURVADORA" in t or "DOBLADORA" in t:
        return "Curvadoras de tubos"
    elif "LASER" in t or "LÁSER" in t:
        if "DUAL" in t or ("CHAPA" in t and "TUBO" in t):
            return "Cortadoras Duales láser (chapa y tubo)"
        elif "TUBO" in t or "CAÑO" in t:
            return "Cortadoras de tubo láser"
        else:
            return "Cortadoras de Chapa Láser"
    elif "PLASMA" in t:
        return "Cortadora CNC plasma"
    elif "PLEGADORA" in t:
        return "Plegadoras de chapas"
    elif "GUILLOTINA" in t:
        return "Cortadoras guillotinas"
    elif "SIERRA" in t or "CORTADORA DE CAÑO" in t:
        return "Cortadoras de caños"
    elif "SOLDADURA" in t or "SOLDAR" in t:
        return "Sistemas de soldadura automática"
    else:
        return "Otros / No especificado"

# ---------------------------------------------------------
# MANEJO DE CLASIFICACIONES MANUALES
# ---------------------------------------------------------
def get_saved_classifications():
    if os.path.exists(LOCAL_CLASSIFICATIONS_FILE):
        return pd.read_csv(LOCAL_CLASSIFICATIONS_FILE, dtype=str)
    else:
        return pd.DataFrame(columns=["Enlace de Whatsapp", "Clasificacion_Manual"])

def save_classification(link, classification):
    df_class = get_saved_classifications()
    if link in df_class["Enlace de Whatsapp"].values:
        df_class.loc[df_class["Enlace de Whatsapp"] == link, "Clasificacion_Manual"] = classification
    else:
        new_row = pd.DataFrame([{"Enlace de Whatsapp": link, "Clasificacion_Manual": classification}])
        df_class = pd.concat([df_class, new_row], ignore_index=True)
    
    df_class.to_csv(LOCAL_CLASSIFICATIONS_FILE, index=False, encoding="utf-8-sig")

# ---------------------------------------------------------
# CARGA Y DESPLIEGUE PRINCIPAL
# ---------------------------------------------------------
if spreadsheet_id and bitrix_webhook_url:
    df_sheets, df_bitrix = get_data_with_local_cache(
        spreadsheet_id, 
        worksheet_name, 
        bitrix_webhook_url, 
        force_refresh=btn_refresh
    )

    if not df_sheets.empty:
        df_class = get_saved_classifications()
        df_sheets = pd.merge(df_sheets, df_class, on="Enlace de Whatsapp", how="left")
        df_sheets["Clasificacion_Manual"] = df_sheets["Clasificacion_Manual"].fillna("Pendiente")

        # Aplicar automatizaciones integradas
        df_sheets = apply_automatic_classifications(df_sheets, df_bitrix)

        tab_clasif, tab_reporte_sheets, tab_bitrix = st.tabs([
            "Clasificación Manual (Contacto por Contacto)",
            "Reporte Mensual de Consultas",
            "Análisis de Negociaciones Bitrix24"
        ])

        # =========================================================
        # TAB 1: CLASIFICACIÓN MANUAL
        # =========================================================
        with tab_clasif:
            st.header("Módulo de Clasificación Manual")
            
            meses_disponibles = sorted(df_sheets["AñoMes"].dropna().unique(), reverse=True)
            
            if meses_disponibles:
                mes_sel = st.selectbox("Filtrar por Mes:", meses_disponibles, key="clasif_mes_select")
                df_mes = df_sheets[df_sheets["AñoMes"] == mes_sel].reset_index(drop=True)
                
                if not df_mes.empty:
                    total_mes = len(df_mes)
                    pendientes = (df_mes["Clasificacion_Manual"] == "Pendiente").sum()
                    clasificados = total_mes - pendientes
                    
                    st.progress(clasificados / total_mes if total_mes > 0 else 0)
                    st.info(f"Progreso del mes **{mes_sel}**: **{clasificados}/{total_mes}** clasificados ({pendientes} pendientes).")

                    def generar_etiqueta_contacto(row):
                        tel = str(row.get("Telefono_Limpio", "")).strip()
                        if not tel:
                            tel = str(row.get("Enlace de Whatsapp", "Sin Teléfono"))
                        
                        nombre = str(row.get("Nombre", "")).strip()
                        clasif = str(row.get("Clasificacion_Manual", "Pendiente"))
                        
                        nombre_display = nombre if nombre and nombre.lower() not in ["nan", "none", ""] else "Sin Nombre registrado"
                        indicador_estado = "⏳" if clasif == "Pendiente" else "✅"
                        
                        return f"{indicador_estado} {tel} - {nombre_display} [{clasif}]"

                    opciones_contactos = [generar_etiqueta_contacto(row) for _, row in df_mes.iterrows()]
                    
                    contacto_seleccionado_str = st.selectbox(
                        "Seleccionar Contacto:",
                        options=opciones_contactos,
                        index=0
                    )
                    
                    idx = opciones_contactos.index(contacto_seleccionado_str)
                    contacto = df_mes.iloc[idx]
                    
                    st.markdown("---")
                    col_info, col_form = st.columns([2, 1])
                    
                    with col_info:
                        nombre_contacto = contacto.get('Nombre')
                        nombre_valido = nombre_contacto if pd.notna(nombre_contacto) and str(nombre_contacto).strip() else "No registrado"
                        
                        st.subheader(f"Contacto: {contacto.get('Telefono_Limpio', 'Sin número')}")
                        st.write(f"👤 **Nombre:** {nombre_valido}")
                        st.write(f"📅 **Fecha y Hora:** {contacto.get('FechaHora')}")
                        st.write(f"🔗 **Enlace WhatsApp:** [{contacto.get('Enlace de Whatsapp')}]({contacto.get('Enlace de Whatsapp')})")
                        st.write(f"🏷️ **Área de Interés:** {contacto.get('Área de interés')}")
                        st.write(f"🤖 **Clasificación Bot:** `{contacto.get('Clasificación')}`")
                        
                        st.text_area(
                            "Resumen de la Consulta (Multiagente IA):",
                            value=str(contacto.get("Resumen de la consulta")),
                            height=180,
                            disabled=True
                        )
                    
                    with col_form:
                        st.subheader("Asignar Clasificación Interna")
                        clasif_actual = contacto.get("Clasificacion_Manual", "Pendiente")
                        
                        # Se usa el "Enlace de Whatsapp" como clave estable del form (identificador
                        # único real del contacto), en vez de "idx", que depende del orden/filtro
                        # de df_mes y puede repetirse entre sesiones para contactos distintos.
                        enlace_key = re.sub(r"[^0-9A-Za-z]", "_", str(contacto.get("Enlace de Whatsapp", idx)))
                        with st.form(key=f"form_clasif_{enlace_key}"):
                            nueva_clasif = st.selectbox(
                                "Clasificación interna:",
                                OPCIONES_CLASIFICACION,
                                index=OPCIONES_CLASIFICACION.index(clasif_actual) if clasif_actual in OPCIONES_CLASIFICACION else 0
                            )
                            
                            btn_guardar = st.form_submit_button("💾 Guardar Clasificación")
                            
                            if btn_guardar:
                                save_classification(contacto["Enlace de Whatsapp"], nueva_clasif)
                                st.success(f"¡Guardado correctamente como **{nueva_clasif}**!")
                                st.rerun()
                else:
                    st.warning("No hay consultas registradas para el mes seleccionado.")
            else:
                st.warning("No se encontraron registros de fechas válidas en la hoja.")

        # =========================================================
        # TAB 2: REPORTE MENSUAL DE CONSULTAS
        # =========================================================
        with tab_reporte_sheets:
            st.header("Extracto Mensual y Distribución de Consultas")
            
            mes_reporte = st.selectbox("Seleccionar Mes para el Reporte:", meses_disponibles, key="rep_mes")
            df_reporte = df_sheets[df_sheets["AñoMes"] == mes_reporte].copy()

            COLOR_MAP = {
                "Pendiente": "#D3D3D3",
                "Negocio en Bitrix": "#2ECC71",
                "Venta de repuestos": "#3498DB",
                "Derivado al área técnica": "#8E44AD",
                "Derivado a RRHH": "#FF69B4",
                "Sin respuesta": "#F1C40F",
                "Sin interés": "#E67E22",
                "Consulta incompatible": "#0027D3",
                "Spam/Servicios": "#555555"
            }

            st.subheader(f"Porcentaje por Clasificación Manual - {mes_reporte}")
            
            if not df_reporte.empty:
                df_counts = df_reporte["Clasificacion_Manual"].value_counts().reset_index()
                df_counts.columns = ["Clasificación", "Cantidad"]
                
                fig_pie = px.pie(
                    df_counts,
                    names="Clasificación",
                    values="Cantidad",
                    hole=0.4,
                    color="Clasificación",
                    color_discrete_map=COLOR_MAP
                )
                fig_pie.update_traces(textinfo="percent+label", textposition="outside")
                fig_pie.update_layout(showlegend=True, margin=dict(t=30, b=30, l=10, r=10))
                
                st.plotly_chart(fig_pie, use_container_width=True)

                st.subheader("Tabla de Datos con Clasificación Agregada")

                def color_clasificacion(val):
                    color = COLOR_MAP.get(val, "#FFFFFF")
                    text_color = "#FFFFFF" if val in ["Spam/Servicios", "Derivado al área técnica", "Consulta incompatible"] else "#000000"
                    return f"background-color: {color}; color: {text_color}; font-weight: bold;"

                df_styled = df_reporte.style.map(color_clasificacion, subset=["Clasificacion_Manual"])

                st.dataframe(df_styled, use_container_width=True)

                col_csv, _ = st.columns(2)
                csv_bytes = df_reporte.to_csv(index=False, encoding="utf-8-sig").encode('utf-8-sig')
                col_csv.download_button(
                    label="📥 Descargar Extracto Mensual (CSV)",
                    data=csv_bytes,
                    file_name=f"consultas_whatsapp_{mes_reporte}.csv",
                    mime="text/csv"
                )

        # =========================================================
        # TAB 3: ANÁLISIS DE NEGOCIACIONES BITRIX24 (SALE)
        # =========================================================
        with tab_bitrix:
            st.header("Análisis de Negociaciones Bitrix24 (Tipo: SALE)")
            
            if not df_bitrix.empty:
                meses_bitrix = sorted(df_bitrix["AñoMes"].dropna().unique(), reverse=True)
                
                if meses_bitrix:
                    mes_sel_bitrix = st.selectbox("Seleccionar Mes (Bitrix24):", meses_bitrix, key="bitrix_mes_select")
                    df_bitrix_mes = df_bitrix[df_bitrix["AñoMes"] == mes_sel_bitrix].copy()

                    if not df_bitrix_mes.empty:
                        df_bitrix_mes["Tipo de máquina"] = df_bitrix_mes["TITLE"].apply(classify_machine_type)
                        # Normalizamos la etapa a su forma canónica para que coincida
                        # exactamente con las claves de BITRIX_STAGE_COLORS.
                        df_bitrix_mes["Etapa"] = df_bitrix_mes["Etapa"].apply(normalizar_etapa)

                        df_grouped = df_bitrix_mes.groupby(["Tipo de máquina", "Etapa"]).size().reset_index(name="Cantidad")

                        fig_bitrix = px.bar(
                            df_grouped,
                            x="Tipo de máquina",
                            y="Cantidad",
                            color="Etapa",
                            title=f"Negociaciones TYPE_ID = 'SALE' por Etapa ({mes_sel_bitrix})",
                            labels={"Etapa": "Etapa (Pipeline)", "Tipo de máquina": "Tipo de Máquina"},
                            barmode="group",
                            color_discrete_map=BITRIX_STAGE_COLORS
                        )
                        
                        fig_bitrix.update_layout(
                            xaxis_title="Tipo de Máquina", 
                            yaxis_title="Cantidad de Negociaciones",
                            legend_title_text="Etapa del Pipeline"
                        )
                        
                        st.plotly_chart(fig_bitrix, use_container_width=True)

                        st.subheader("Listado de Negociaciones Extraídas")
                        
                        cols_mostrar = ["TITLE", "TYPE_ID", "Etapa", "Datos del cliente", "Tipo de máquina"]
                        cols_existentes = [c for c in cols_mostrar if c in df_bitrix_mes.columns]
                        
                        st.dataframe(df_bitrix_mes[cols_existentes].rename(columns={"TITLE": "Nombre"}), use_container_width=True)

                        csv_bitrix = df_bitrix_mes[cols_existentes].to_csv(index=False, encoding="utf-8-sig").encode('utf-8-sig')
                        st.download_button(
                            label="📥 Descargar Negociaciones Filtradas (CSV)",
                            data=csv_bitrix,
                            file_name=f"negociaciones_bitrix_{mes_sel_bitrix}.csv",
                            mime="text/csv"
                        )
                    else:
                        st.warning(f"No se encontraron negociaciones con `TYPE_ID == 'SALE'` para el mes **{mes_sel_bitrix}**.")
                else:
                    st.warning("No hay registros con fechas válidas en los datos cargados de Bitrix24.")
            else:
                st.warning("No se obtuvieron datos de Bitrix24. Revisa la URL del Webhook o confirma que existan negociaciones con `TYPE_ID == 'SALE'`.")
else:
    st.info("👈 Por favor, ingresa el **Spreadsheet ID** y la **URL del Webhook de Bitrix24** en el panel izquierdo para comenzar.")
