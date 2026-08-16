"""
Script one-off: migra las clasificaciones manuales del CSV legado
(data/clasificaciones_locales.csv) a la pestaña "Clasificaciones" de la
Google Sheet configurada.

Se corre UNA sola vez, en local, antes del deploy:

    python scripts/migrate_classifications.py

Requisitos previos (que ya cumpliste):
  1. Existe una pestaña llamada "Clasificaciones" en la spreadsheet, con los
     headers exactos en la fila 1:
       A: Enlace de Whatsapp
       B: Clasificacion_Manual
       C: Fecha_Ultima_Modificacion
       D: Usuario
  2. El service account (bitrix-spread@...) tiene permiso Editor sobre la
     spreadsheet.
  3. .streamlit/secrets.toml tiene google_sheets.spreadsheet_id + la sección
     [gcp_service_account] (o existe credentials.json en la raíz del proyecto).

El script es idempotente: si un enlace ya está en la pestaña, actualiza esa
fila en vez de duplicarla. Podés correrlo de nuevo sin miedo.
"""

import os
import sys
from datetime import datetime

# Python 3.11+
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials


# ---------------------------------------------------------------------------
# Paths (asumiendo que este script vive en scripts/ dentro del repo)
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPT_DIR)
SECRETS_PATH = os.path.join(BASE_DIR, ".streamlit", "secrets.toml")
CREDENTIALS_PATH = os.path.join(BASE_DIR, "credentials.json")
LEGACY_CSV = os.path.join(BASE_DIR, "data", "clasificaciones_locales.csv")

WORKSHEET_NAME = "Clasificaciones"
GSPREAD_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def load_secrets():
    if not os.path.exists(SECRETS_PATH):
        sys.exit(f"❌ No se encontró {SECRETS_PATH}. Configuralo antes de migrar.")
    with open(SECRETS_PATH, "rb") as f:
        return tomllib.load(f)


def get_client(secrets):
    """Autentica preferentemente con gcp_service_account de secrets.toml; si no,
    cae al archivo credentials.json en la raíz del proyecto."""
    if "gcp_service_account" in secrets:
        creds = Credentials.from_service_account_info(
            secrets["gcp_service_account"], scopes=GSPREAD_SCOPES
        )
    elif os.path.exists(CREDENTIALS_PATH):
        creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=GSPREAD_SCOPES)
    else:
        sys.exit(
            "❌ No hay credenciales: falta la sección [gcp_service_account] en "
            "secrets.toml y tampoco existe credentials.json."
        )
    return gspread.authorize(creds)


def open_worksheet(client, spreadsheet_id):
    if spreadsheet_id.startswith("http") or len(spreadsheet_id) > 30:
        sh = client.open_by_key(spreadsheet_id)
    else:
        sh = client.open(spreadsheet_id)
    try:
        return sh.worksheet(WORKSHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        sys.exit(
            f"❌ No existe la pestaña '{WORKSHEET_NAME}' en la spreadsheet. "
            "Creála a mano con los headers indicados en el docstring y volvé a correr."
        )


def main():
    print("🚀 Migración de clasificaciones locales → Google Sheets")
    print(f"   CSV origen: {LEGACY_CSV}")

    if not os.path.exists(LEGACY_CSV):
        sys.exit(f"❌ No se encontró el CSV legado en {LEGACY_CSV}. Nada para migrar.")

    df = pd.read_csv(LEGACY_CSV, dtype=str)
    df = df.dropna(subset=["Enlace de Whatsapp"])
    if df.empty:
        print("ℹ️  El CSV está vacío. Nada para migrar.")
        return
    print(f"   Filas a migrar: {len(df)}")

    secrets = load_secrets()
    spreadsheet_id = secrets.get("google_sheets", {}).get("spreadsheet_id", "")
    if not spreadsheet_id:
        sys.exit("❌ Falta google_sheets.spreadsheet_id en secrets.toml.")

    client = get_client(secrets)
    ws = open_worksheet(client, spreadsheet_id)
    print(f"   Pestaña destino: '{WORKSHEET_NAME}' ✓")

    # Traemos lo que ya haya en la pestaña para no duplicar.
    existing = ws.get_all_records()
    existing_links = {str(r.get("Enlace de Whatsapp", "")).strip(): r for r in existing}
    print(f"   Filas ya presentes en la Sheet: {len(existing_links)}")

    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    usuario = "migracion-inicial"

    nuevos, actualizados = 0, 0
    filas_para_append = []

    for _, row in df.iterrows():
        link = str(row["Enlace de Whatsapp"]).strip()
        clasif = str(row["Clasificacion_Manual"]).strip()
        if not link:
            continue

        if link in existing_links:
            # Ya existe: solo actualizamos si la clasificación cambió.
            actual = str(existing_links[link].get("Clasificacion_Manual", "")).strip()
            if actual != clasif:
                cell = ws.find(link, in_column=1)
                ws.update(
                    range_name=f"B{cell.row}:D{cell.row}",
                    values=[[clasif, fecha, usuario]],
                )
                actualizados += 1
                print(f"   ↻ Actualizado: {link} ({actual} → {clasif})")
            else:
                print(f"   = Sin cambios:  {link} ({clasif})")
        else:
            filas_para_append.append([link, clasif, fecha, usuario])
            nuevos += 1

    if filas_para_append:
        # append en batch (una sola llamada a la API por todas las filas nuevas).
        ws.append_rows(filas_para_append, value_input_option="USER_ENTERED")
        for fila in filas_para_append:
            print(f"   + Migrado:     {fila[0]} ({fila[1]})")

    print()
    print(f"✅ Terminado. Nuevos: {nuevos} | Actualizados: {actualizados} | Total procesadas: {len(df)}")
    print(f"   El CSV legado quedó intacto en {LEGACY_CSV} (podés borrarlo cuando quieras).")


if __name__ == "__main__":
    main()
