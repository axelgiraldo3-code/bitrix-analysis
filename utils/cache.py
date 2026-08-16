"""
Capa de caché local y automatizaciones: combina los datos de Google Sheets y
Bitrix24, aplica las reglas de clasificación automática, y persiste/lee las
clasificaciones manuales en una pestaña dedicada de la spreadsheet
(configurada en utils/config.CLASSIFICATIONS_WORKSHEET).

Las clasificaciones se guardan en la Sheet — no en un CSV local — para que el
trabajo manual sobreviva a reinicios de la app y esté disponible al mismo
tiempo para múltiples usuarios en el deploy compartido.
"""

import os
from datetime import datetime

import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

from .config import (
    CACHE_SHEETS_FILE,
    CACHE_BITRIX_FILE,
    CLASSIFICATIONS_WORKSHEET,
    CLASSIFICATIONS_HEADERS,
)
from .helpers import clean_phone
from .google_sheets import load_google_sheets_data
from .bitrix import load_bitrix_deals


# ---------------------------------------------------------------------------
# CLASIFICACIONES MANUALES  (persistencia en Google Sheets)
# ---------------------------------------------------------------------------

_GSPREAD_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _get_gspread_client():
    """
    Autentica contra Google usando el service account. Preferimos las credenciales
    embebidas en st.secrets (necesarias en el deploy de Streamlit Cloud, donde
    no hay archivos locales); si no están, caemos a credentials.json (uso local).
    """
    if "gcp_service_account" in st.secrets:
        creds = Credentials.from_service_account_info(
            dict(st.secrets["gcp_service_account"]), scopes=_GSPREAD_SCOPES
        )
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=_GSPREAD_SCOPES)
    return gspread.authorize(creds)


def _open_classifications_worksheet():
    """
    Abre (y devuelve) el worksheet de clasificaciones. La spreadsheet_id se lee
    de st.secrets['google_sheets']['spreadsheet_id'], que es la misma fuente
    que ya usa el resto de la app.
    """
    spreadsheet_id = st.secrets.get("google_sheets", {}).get("spreadsheet_id", "")
    if not spreadsheet_id:
        raise RuntimeError(
            "No se encontró 'google_sheets.spreadsheet_id' en los secrets. "
            "Configuralo en .streamlit/secrets.toml (local) o en el panel de "
            "Secrets de Streamlit Cloud."
        )

    client = _get_gspread_client()

    if spreadsheet_id.startswith("http") or len(spreadsheet_id) > 30:
        sh = client.open_by_key(spreadsheet_id)
    else:
        sh = client.open(spreadsheet_id)

    return sh.worksheet(CLASSIFICATIONS_WORKSHEET)


@st.cache_data(ttl=60, show_spinner=False)
def _fetch_classifications_records():
    """
    Trae todas las filas de la pestaña Clasificaciones. Se cachea 60s para no
    golpear la API en cada rerun de Streamlit. Se invalida manualmente después
    de cada save_classification() vía st.cache_data.clear() sobre esta función.
    """
    ws = _open_classifications_worksheet()
    return ws.get_all_records()


def get_saved_classifications():
    """
    Devuelve un DataFrame con las columnas ['Enlace de Whatsapp', 'Clasificacion_Manual']
    (las otras columnas del sheet — Fecha, Usuario — no las necesita el merge de app.py).
    Si la pestaña está vacía o falla la conexión, devuelve un DataFrame vacío para
    que la app siga arrancando (con todos los contactos como 'Pendiente').
    """
    try:
        records = _fetch_classifications_records()
    except Exception as e:
        st.sidebar.warning(
            f"No se pudieron leer las clasificaciones guardadas ({e}). "
            "Todos los contactos aparecerán como Pendiente hasta resolver la conexión."
        )
        return pd.DataFrame(columns=["Enlace de Whatsapp", "Clasificacion_Manual"])

    if not records:
        return pd.DataFrame(columns=["Enlace de Whatsapp", "Clasificacion_Manual"])

    df = pd.DataFrame(records, dtype=str)

    # Aseguramos que estén las dos columnas que espera el resto de la app.
    for col in ["Enlace de Whatsapp", "Clasificacion_Manual"]:
        if col not in df.columns:
            df[col] = ""

    return df[["Enlace de Whatsapp", "Clasificacion_Manual"]]


def save_classification(link, classification, usuario="app"):
    """
    Guarda (o actualiza) la clasificación manual de un contacto en la pestaña
    Clasificaciones de la spreadsheet. Si el 'link' ya existe, actualiza la fila
    (clasificación + fecha + usuario). Si no, la agrega al final.

    - link: valor de 'Enlace de Whatsapp' (clave única del contacto).
    - classification: string, alguna de OPCIONES_CLASIFICACION.
    - usuario: quién hizo la clasificación (default 'app'). En Streamlit Cloud
      con auth privada, la app puede pasar st.experimental_user.email.
    """
    ws = _open_classifications_worksheet()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Buscamos el link en la columna A (Enlace de Whatsapp). find() devuelve el
    # primer match o levanta CellNotFound.
    try:
        cell = ws.find(link, in_column=1)
    except gspread.exceptions.CellNotFound:
        cell = None

    if cell is not None:
        # Update en una sola llamada batch (B, C, D de la fila encontrada).
        row_num = cell.row
        ws.update(
            range_name=f"B{row_num}:D{row_num}",
            values=[[classification, fecha, usuario]],
        )
    else:
        # Append de una fila nueva. value_input_option='USER_ENTERED' respeta
        # tipos como fechas si algún día formateamos la columna C.
        ws.append_row(
            [link, classification, fecha, usuario],
            value_input_option="USER_ENTERED",
        )

    # Invalidar el cache de lectura para que el próximo rerun vea el cambio.
    _fetch_classifications_records.clear()


# ---------------------------------------------------------------------------
# CACHÉ DE DATOS FUENTE  (Google Sheets del bot + Bitrix)
# ---------------------------------------------------------------------------

def apply_automatic_classifications(df_sheets, df_bitrix):
    """
    Aplica las reglas automáticas de clasificación y estandarización de datos:
    1. Negocio en Bitrix: Coincidencia de teléfono Y negocio del mismo mes o posterior.
    2. Sobreescritura de Nombre: Estandariza el Nombre con el dato de Bitrix24 siempre que exista.
    3. Área técnica: Si 'Clasificación' origen es 'SI_RESUMEN_G2'.

    Devuelve una tupla (df_sheets, cambios), donde `cambios` es una lista de tuplas
    (enlace, clasificacion, regla_usuario) con TODAS las filas que la función auto-clasificó
    en esta corrida. `regla_usuario` es el string que se debe grabar en la columna
    "Usuario" de la Sheet (ej. "auto (Bitrix)"), para poder distinguir después
    entre clasificaciones manuales y derivadas por regla.

    Las reglas SOLO tocan contactos que están en Pendiente — nunca pisan clasificaciones
    manuales existentes.
    """
    cambios = []

    if df_sheets.empty:
        return df_sheets, cambios

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
            enlace = str(row.get("Enlace de Whatsapp", "")).strip()

            # Regla 1: Negocio válido en Bitrix (mismo mes o posterior)
            if tiene_negocio_valido:
                df_sheets.loc[idx, "Clasificacion_Manual"] = "Negocio en Bitrix"
                if enlace:
                    cambios.append((enlace, "Negocio en Bitrix", "auto (Bitrix)"))
                continue

            # Regla 2: Clasificación de origen igual a SI_RESUMEN_G2
            clasificacion_origen = str(row.get("Clasificación", "")).strip()
            if clasificacion_origen == "SI_RESUMEN_G2":
                df_sheets.loc[idx, "Clasificacion_Manual"] = "Derivado al área técnica"
                if enlace:
                    cambios.append((enlace, "Derivado al área técnica", "auto (SI_RESUMEN_G2)"))
                continue

    return df_sheets, cambios


def persist_automatic_classifications(cambios, df_class_existente):
    """
    Vuelca a la pestaña "Clasificaciones" las clasificaciones derivadas por
    apply_automatic_classifications() que todavía no estén registradas allí (o
    que estén registradas con un valor distinto).

    - `cambios`: lista [(enlace, clasificacion, usuario), ...] devuelta por
      apply_automatic_classifications().
    - `df_class_existente`: DataFrame ya cargado con lo que hay HOY en la Sheet
      (columnas 'Enlace de Whatsapp' y 'Clasificacion_Manual'). Se pasa desde
      afuera para no hacer una segunda lectura innecesaria.

    Retorna la cantidad de filas efectivamente escritas (nuevas + actualizadas).
    Si no hay nada que escribir, retorna 0 sin tocar la API.

    Las escrituras se hacen en dos batches: append_rows() para todas las filas
    nuevas y update() por celda para las que hay que actualizar (caso raro:
    contactos que estaban en la Sheet como 'Pendiente' explícito).
    """
    if not cambios:
        return 0

    # Índice rápido de lo que ya está en la Sheet:
    #   enlace -> clasificacion actual en la Sheet
    ya_en_sheet = {}
    if df_class_existente is not None and not df_class_existente.empty:
        for _, r in df_class_existente.iterrows():
            k = str(r.get("Enlace de Whatsapp", "")).strip()
            v = str(r.get("Clasificacion_Manual", "")).strip()
            if k:
                ya_en_sheet[k] = v

    a_agregar = []   # (enlace, clasif, usuario) — filas nuevas
    a_actualizar = []  # (enlace, clasif, usuario) — ya están en la Sheet con otro valor

    for enlace, clasif, usuario in cambios:
        if enlace not in ya_en_sheet:
            a_agregar.append((enlace, clasif, usuario))
        elif ya_en_sheet[enlace] != clasif:
            a_actualizar.append((enlace, clasif, usuario))
        # else: ya está registrada con el mismo valor -> no hacemos nada

    if not a_agregar and not a_actualizar:
        return 0

    ws = _open_classifications_worksheet()
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    escritas = 0

    # --- Append batch de las nuevas ---
    if a_agregar:
        rows = [[enlace, clasif, fecha, usuario] for enlace, clasif, usuario in a_agregar]
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        escritas += len(a_agregar)

    # --- Update una a una para las que ya existían (raro) ---
    for enlace, clasif, usuario in a_actualizar:
        try:
            cell = ws.find(enlace, in_column=1)
            ws.update(
                range_name=f"B{cell.row}:D{cell.row}",
                values=[[clasif, fecha, usuario]],
            )
            escritas += 1
        except gspread.exceptions.CellNotFound:
            # Race condition raro: el enlace desapareció entre la lectura y ahora.
            # Lo agregamos como fila nueva y seguimos.
            ws.append_row([enlace, clasif, fecha, usuario], value_input_option="USER_ENTERED")
            escritas += 1

    # Invalidar el cache de lectura para que el próximo rerun vea todo.
    _fetch_classifications_records.clear()

    return escritas


def get_data_with_local_cache(sheet_id, sheet_name, webhook_url, force_refresh=False):
    """Carga datos locales (desde data/) o los reconstruye limpiamente si es necesario."""
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
