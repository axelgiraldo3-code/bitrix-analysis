"""Crea el libro de Google Sheets destino (persistencia de clasificaciones).

Uso local (una sola vez):
    python -m scripts.create_destination_sheet "COTEAR - Persistencia"

Imprime el spreadsheet_id resultante. Pegarlo en `.streamlit/secrets.toml`:

    [google_sheets.dest]
    spreadsheet_id = "..."

Requiere que la service account de `[gcp_service_account]` tenga permiso para
crear archivos en Drive; si no, crear el libro manualmente en Sheets y
compartirlo con el `client_email` de la service account con permiso de Editor.
"""
from __future__ import annotations

import sys

import gspread
import streamlit as st
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def main() -> None:
    title = sys.argv[1] if len(sys.argv) > 1 else "COTEAR - Persistencia"
    info = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.create(title)
    print(f"Creado: {title}")
    print(f"spreadsheet_id = {sh.id}")
    print(f"URL: https://docs.google.com/spreadsheets/d/{sh.id}")
    # Compartir con el usuario (opcional): sh.share('email@dominio', perm_type='user', role='writer')


if __name__ == "__main__":
    main()
