"""
Módulo de integración con Google Sheets: carga y sanitiza las consultas
capturadas por el bot de WhatsApp desde la spreadsheet configurada.
"""

import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

from .helpers import sanitize_text, clean_phone


# Epoch de Google Sheets para serial numbers de fechas (mismo que Excel).
# Un valor 45000.5 significa "45000 días y 12hs desde 1899-12-30".
_SHEETS_EPOCH = pd.Timestamp("1899-12-30")


def _parse_fecha_bot(val):
    """
    Parseo robusto de un valor de FechaHora que puede venir en varios formatos,
    porque el bot y/o la configuración de la Sheet fueron cambiando en el tiempo:

    - Serial number de Sheets (int/float, ej. 45876.65): fecha nativa de Sheets;
      se convierte contra el epoch 1899-12-30 (idéntico a Excel).
    - String ISO 'YYYY-MM-DD [HH:MM:SS]': se parsea directo, sin ambigüedad.
    - String DD/MM/YYYY o DD-MM-YYYY [HH:MM:SS]: formato locale español (Argentina);
      se parsea con dayfirst=True. NUNCA se intenta MM/DD porque, ante ambigüedad,
      esa interpretación produciría meses futuros inválidos (bug histórico).
    - Cualquier otra cosa: pd.NaT (fila queda como "Sin Fecha").

    Este parseo blindado reemplaza al pd.to_datetime() plano anterior, que fallaba
    con configuraciones mixtas de la Sheet y producía tanto NaT silenciosos como
    fechas invertidas (mes/día).
    """
    # Serial number nativo de Sheets (llega solo cuando pedimos UNFORMATTED_VALUE)
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        # Sheets pone las fechas como número de días desde 1899-12-30.
        # El float con decimales representa la fracción del día (hora).
        try:
            return _SHEETS_EPOCH + pd.Timedelta(days=float(val))
        except (ValueError, OverflowError):
            return pd.NaT

    # String u otro
    if val is None:
        return pd.NaT
    s = str(val).strip()
    if not s:
        return pd.NaT

    # Intento 1: ISO YYYY-MM-DD (unambiguo, no necesita dayfirst)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        parsed = pd.to_datetime(s, errors="coerce")
        if pd.notna(parsed):
            return parsed

    # Intento 2: DD/MM/YYYY o DD-MM-YYYY (locale español)
    parsed = pd.to_datetime(s, errors="coerce", dayfirst=True)
    return parsed  # NaT si tampoco encaja


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

        # Pedimos los valores SIN FORMATEAR (UNFORMATTED_VALUE): las fechas llegan
        # como serial numbers (float), no como strings que dependen de la locale
        # del display. Esto elimina de raiz la ambiguedad DD/MM vs MM/DD que
        # generaba meses futuros en el desplegable. Si el fetch con esta opción
        # falla (versión vieja de gspread), caemos al get_all_values() clásico y
        # confiamos en _parse_fecha_bot() para desambiguar los strings.
        try:
            raw_values = sheet.get_all_values(value_render_option="UNFORMATTED_VALUE")
        except TypeError:
            raw_values = sheet.get_all_values()

        if not raw_values or len(raw_values) < 2:
            return pd.DataFrame()

        # La primera fila que devuelve la Sheet es el header (nombres de columnas).
        # Antes se metía como una fila de datos con FechaHora="FechaHora", lo que
        # producía un contacto fantasma con "Sin Fecha" en el desplegable.
        raw_values = raw_values[1:]

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

        # Parsear FechaHora ANTES de aplicar sanitize_text a todas las columnas.
        # sanitize_text convierte todo a str, lo que perdería el serial number
        # nativo de Sheets si viniera como float. Aplicamos el parser robusto
        # directamente sobre el valor crudo.
        df["FechaHora"] = df["FechaHora"].apply(_parse_fecha_bot)

        # Ahora sí, sanitizar todas las demás columnas (texto)
        for col in df.columns:
            if col == "FechaHora":
                continue
            df[col] = df[col].apply(sanitize_text)

        df["AñoMes"] = df["FechaHora"].dt.strftime("%Y-%m").fillna("Sin Fecha")

        if "Enlace de Whatsapp" in df.columns:
            df["Telefono_Limpio"] = df["Enlace de Whatsapp"].apply(clean_phone)

        df = deduplicate_bot_queries(df)
        return df

    except Exception as e:
        st.error(f"Error al conectar con Google Sheets: {e}")
        return pd.DataFrame()
