"""
Funciones auxiliares de limpieza, sanitización y clasificación de texto.
No dependen de Streamlit ni de ninguna API externa: son utilidades puras
reutilizadas por los módulos de Google Sheets, Bitrix24 y la app principal.

Toda la lógica de normalización de teléfonos argentinos vive en
`utils/phone_ar.py` — este módulo solo la EXPONE y agrega los helpers de
DISPLAY (formato visual "+54 9 <area> <local>") que la UI necesita para
las tablas y selectboxes.
"""

import re
import html
import pandas as pd

from .config import STAGE_NAME_ALIASES
from .phone_ar import (
    format_phone_ar_e164,
    is_argentina_e164,
    e164_to_local10,
    e164_to_area_local,
)


def clean_phone(phone_str):
    """
    Devuelve los 10 dígitos canónicos (código de área + número local) de
    un teléfono argentino, o "" si el número no valida como AR.

    Delega la validación en `format_phone_ar_e164()` (O(1) contra los
    sets de códigos de área oficiales) en vez de aplicar la vieja
    heurística de "borrar 549 / 54 / últimos 10 dígitos", que aceptaba
    como AR cualquier basura de 10+ dígitos y podía colisionar contactos
    de distintos países bajo la misma clave.

    Un número internacional NO argentino devuelve "" — antes devolvía
    los "últimos 10 dígitos" del número extranjero, lo que producía
    merges falsos contra el CRM.
    """
    if pd.isna(phone_str) or not phone_str:
        return ""

    e164 = format_phone_ar_e164(phone_str)
    if is_argentina_e164(e164):
        return e164_to_local10(e164)
    return ""


def normalizar_etapa(valor):
    """
    Normaliza el nombre de una etapa de Bitrix24 a su forma canónica
    definida en BITRIX_STAGE_COLORS, usando STAGE_NAME_ALIASES para
    resolver variantes de mayúsculas/tildes/redacción. Evita que una
    etapa quede sin color asignado (cayendo al gris de "Sin Etapa" en el
    gráfico) solo por una diferencia de formato.
    """
    v = re.sub(r"\s+", " ", str(valor).strip())
    return STAGE_NAME_ALIASES.get(v, v)


def sanitize_text(text):
    """
    Sanea de forma extrema cualquier texto eliminando HTML, saltos de
    línea, retornos de carro y tabulaciones que rompen las filas del CSV.
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
    Da formato visual internacional a un teléfono argentino.

    Formato de salida canónico (unificado con `format_phone_full` para
    que las tres tabs muestren siempre lo mismo):
        "+54 9 <codigo_area> <numero_local>"
    Ej.: "+54 9 3496 504147", "+54 9 351 4123456", "+54 9 11 41234567".

    Los tres bloques (`+54 9`, código de área, número local) se separan
    con UN espacio para máxima legibilidad. La partición área/local se
    resuelve contra los sets oficiales (misma lógica O(1) que la
    validación), no se asume ciegamente "3 primeros dígitos".

    - No-AR válido → se devuelve el E164 tal cual (`+56...`, `+34...`),
      para que el operador vea que el contacto es extranjero.
    - Basura sin país reconocible → input original sin modificar.
    """
    if tel_digits is None or str(tel_digits).strip() == "":
        return ""

    e164 = format_phone_ar_e164(tel_digits)

    if is_argentina_e164(e164):
        area, local = e164_to_area_local(e164)
        return f"+54 9 {area} {local}"

    return e164 or str(tel_digits)


def hex_to_rgba(hex_color, alpha=0.08):
    """
    Convierte un color hexadecimal (ej. '#2ECC71') a una cadena rgba()
    con la opacidad indicada. Se usa para pintar el fondo de una fila
    completa con muy baja intensidad, sin competir con el color sólido
    de la celda de clasificación.
    """
    hex_color = str(hex_color).lstrip('#')
    if len(hex_color) != 6:
        return f"rgba(255, 255, 255, {alpha})"
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def format_phone_full(raw_tel):
    """
    Alias funcional de `format_phone_ar` para teléfonos que vienen
    "crudos" (típicamente el campo PHONE de Bitrix24). El formato de
    salida es idéntico — "+54 9 <area> <local>" — porque la app
    unificó el display: no tiene sentido mostrar el mismo contacto con
    dos formatos distintos según de qué tab venga.

    Se conserva la función (en vez de reemplazar las llamadas por
    `format_phone_ar`) para no romper los imports existentes en
    `app.py` y para dejar claro semánticamente cuál es la fuente
    esperada (raw de CRM vs. dígitos ya limpios).
    """
    return format_phone_ar(raw_tel)


MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}


def format_mes_legible(anio_mes):
    """
    Convierte un período "AAAA-MM" (formato interno de AñoMes) en un
    texto legible en español, ej. "2026-07" -> "Julio 2026". Si el valor
    no tiene ese formato (por ejemplo "Sin Fecha"), se devuelve tal cual
    para no romper la UI.
    """
    texto = str(anio_mes or "").strip()
    partes = texto.split("-")
    if len(partes) != 2:
        return texto
    anio, mes = partes
    try:
        nombre_mes = MESES_ES[int(mes)]
    except (ValueError, KeyError):
        return texto
    return f"{nombre_mes} {anio}"
