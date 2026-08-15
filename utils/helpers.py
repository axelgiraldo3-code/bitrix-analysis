"""
Funciones auxiliares de limpieza, sanitización y clasificación de texto.
No dependen de Streamlit ni de ninguna API externa: son utilidades puras
reutilizadas por los módulos de Google Sheets, Bitrix24 y la app principal.
"""

import re
import html
import pandas as pd

from .config import STAGE_NAME_ALIASES


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


def format_phone_ar(tel_digits):
    """
    Da formato visual argentino a un número de 10 dígitos ya limpio (sin 54/549):
    "3496504147" -> "349 650-4147" (espacio tras el 3er dígito, guión tras el 6to).
    Si no tiene exactamente 10 dígitos, se devuelve el valor original sin modificar,
    para no inventar un formato sobre datos incompletos o mal capturados.
    """
    digits = re.sub(r"\D", "", str(tel_digits or ""))
    if len(digits) != 10:
        return str(tel_digits or "")
    return f"{digits[0:3]} {digits[3:6]}-{digits[6:10]}"


def hex_to_rgba(hex_color, alpha=0.08):
    """
    Convierte un color hexadecimal (ej. '#2ECC71') a una cadena rgba() con la
    opacidad indicada. Se usa para pintar el fondo de una fila completa con muy
    baja intensidad, sin competir con el color sólido de la celda de clasificación.
    """
    hex_color = str(hex_color).lstrip('#')
    if len(hex_color) != 6:
        return f"rgba(255, 255, 255, {alpha})"
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"
