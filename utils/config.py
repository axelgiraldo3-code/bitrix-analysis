"""
Configuración central del proyecto: rutas de archivos y constantes compartidas
entre los distintos módulos (Google Sheets, Bitrix24, caché local, UI).

Mantener todo esto en un solo lugar evita que las rutas y los mapeos de datos
queden duplicados (y potencialmente desalineados) entre app.py y los módulos
de utils/.
"""

import os

# ---------------------------------------------------------
# RUTAS DE ARCHIVOS
# ---------------------------------------------------------
# BASE_DIR = carpeta raíz del proyecto (donde vive app.py), calculada de forma
# relativa a este archivo (utils/config.py) para que funcione sin importar
# desde qué directorio de trabajo se ejecute `streamlit run`.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

# Aseguramos que la carpeta data/ exista (por ejemplo, en un clon nuevo del
# repositorio donde solo se versiona data/.gitkeep).
os.makedirs(DATA_DIR, exist_ok=True)

# Archivos locales para almacenamiento y caché, todos dentro de data/
LOCAL_CLASSIFICATIONS_FILE = os.path.join(DATA_DIR, "clasificaciones_locales.csv")
CACHE_SHEETS_FILE = os.path.join(DATA_DIR, "consultas_bot.csv")
CACHE_BITRIX_FILE = os.path.join(DATA_DIR, "negocios_bitrix.csv")

# ---------------------------------------------------------
# OPCIONES DE CLASIFICACIÓN MANUAL
# ---------------------------------------------------------
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

# ---------------------------------------------------------
# MAPEO DE ETAPAS DE BITRIX24
# ---------------------------------------------------------
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

# MAPEO DE ETAPAS DE RESPALDO (usado si la API de Bitrix24 no responde)
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
# COLORES PARA EL REPORTE DE CLASIFICACIÓN MANUAL (TAB 2)
# ---------------------------------------------------------
REPORT_COLOR_MAP = {
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
