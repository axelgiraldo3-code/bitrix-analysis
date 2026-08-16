"""
Módulo de integración con Google Sheets: carga y sanitiza las consultas
capturadas por el bot de WhatsApp desde la spreadsheet configurada.
"""

import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

from .helpers import sanitize_text, clean_phone


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

        # dayfirst=True porque el bot escribe fechas en formato DD/MM/AAAA (locale
        # español de Google Sheets). Sin este flag, pandas defaultea a MM/DD/AAAA y
        # una fecha como "12/08/2026" (12 de agosto) se lee como "8 de diciembre"
        # -> aparece en el desplegable como AñoMes 2026-12 (mes futuro inexistente).
        # dayfirst NO rompe fechas ISO (2026-08-15): pandas las reconoce igual.
        df["FechaHora"] = pd.to_datetime(df["FechaHora"], errors="coerce", dayfirst=True)
        df["AñoMes"] = df["FechaHora"].dt.strftime("%Y-%m").fillna("Sin Fecha")

        if "Enlace de Whatsapp" in df.columns:
            df["Telefono_Limpio"] = df["Enlace de Whatsapp"].apply(clean_phone)

        df = deduplicate_bot_queries(df)
        return df

    except Exception as e:
        st.error(f"Error al conectar con Google Sheets: {e}")
        return pd.DataFrame()
