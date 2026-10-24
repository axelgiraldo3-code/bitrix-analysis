"""Colores y utilidades de branding de Cotear SRL."""
import hashlib
import re
import unicodedata

COTEAR_BLUE = "#01498E"
COTEAR_GRAY = "#7B868C"

# Paleta para categorías de clasificación interna (10 slots)
CLASSIFICATION_COLORS = {
    "DERIVADO A BITRIX":      "#11734b",
    "VENTA DE REPUESTOS":     "#0a53a8",
    "DERIVADO A RRHH":        "#ee00ff",
    "DERIVADO A TÉCNICA":     "#5a3286",
    "SIN RESPUESTAS":         "#ffe5a0",
    "NECESIDAD INCOMPATIBLE": "#E67E22",
    "SIN INTERES":            "#b10202",
    "SIN CLASIFICAR":         "#BDC3C7",
}

# Etapas de negocio Bitrix ordenadas
BITRIX_STAGE_ORDER = [
    "Pendiente de cotizar",
    "Cotizado aguardando devolución",
    "En negociación",
    "Ganado en Desarrollo",
    "Cerrado Ganado",
    "Cerrado Perdido",
]

BITRIX_STAGE_COLORS = {
    "Pendiente de cotizar":            "#ace9fb",
    "Cotizado aguardando devolución":  "#39a8ef",
    "Cotizado aguardando devolucion":  "#39a8ef",
    "En negociacion":                  "#55d0e0",
    "En negociación":                  "#55d0e0",
    "Ganado en Desarrollo":            "#47e4c2",
    "Ganado en desarrollo":            "#47e4c2",
    "Cerrado Ganado":                  "#7bd500",
    "Cerrado Perdido, motivo?":                 "#f11716",
    "Cerrado Perdido":                 "#f11716",
}


CLASSIFICATION_OPTIONS = list(CLASSIFICATION_COLORS.keys())


# Fuentes de negocio (origen) con color fijo, para que cada fuente mantenga
# su color en todos los meses. "Sin fuente" y las que no están en la lista
# van en gris Cotear.
SOURCE_ORDER = [
    "RRSS",
    "Sitio Web",
    "WhatsApp",
    "Correo",
    "Por Recomendación",
    "Llamada",
    "Derivación de otra area",
    "Cliente existente",
    "Casa matriz",
    "Impulso de venta",
    "Otro",
]

SOURCE_COLORS = {
    "RRSS":                    "#5A3286",
    "Sitio Web":               "#01498E",
    "WhatsApp":                "#11734B",
    "Correo":                  "#E67E22",
    "Por Recomendación":       "#C9A400",
    "Llamada":                 "#39A8EF",
    "Derivación de otra area": "#D35FB7",
    "Cliente existente":       "#2BB3A3",
    "Casa matriz":             "#B10202",
    "Impulso de venta":        "#8E5B2E",
    "Otro":                    "#34495E",
}
SOURCE_OTHER_COLOR = COTEAR_GRAY
SOURCE_EMPTY = "Sin fuente"


def _plain(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text).strip().lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


# Denominaciones alternativas (sin tildes, minúsculas) → fuente canónica
_SOURCE_ALIASES = {
    "rrss": "RRSS", "redes sociales": "RRSS", "redes": "RRSS", "instagram": "RRSS",
    "facebook": "RRSS", "linkedin": "RRSS",
    "sitio web": "Sitio Web", "web": "Sitio Web", "pagina web": "Sitio Web",
    "formulario web": "Sitio Web",
    "whatsapp": "WhatsApp", "wsp": "WhatsApp", "whats app": "WhatsApp",
    "correo": "Correo", "email": "Correo", "e-mail": "Correo", "mail": "Correo",
    "correo electronico": "Correo",
    "por recomendacion": "Por Recomendación", "recomendacion": "Por Recomendación",
    "referido": "Por Recomendación",
    "llamada": "Llamada", "llamado": "Llamada", "telefono": "Llamada",
    "callback": "Llamada",
    "derivacion de otra area": "Derivación de otra area",
    "derivacion de otra area interna": "Derivación de otra area",
    "derivado de otra area": "Derivación de otra area",
    "cliente existente": "Cliente existente", "cliente actual": "Cliente existente",
    "casa matriz": "Casa matriz",
    "impulso de venta": "Impulso de venta", "impulso de ventas": "Impulso de venta",
    "otro": "Otro", "otros": "Otro", "other": "Otro",
}


def canonical_source(value) -> str:
    """Nombre canónico de la fuente (sin depender de tildes ni mayúsculas).
    Vacío → "Sin fuente"; desconocida → se deja como viene."""
    if value is None or str(value).strip() in ("", "nan", "None"):
        return SOURCE_EMPTY
    return _SOURCE_ALIASES.get(_plain(value), str(value).strip())


def source_color(name: str) -> str:
    return SOURCE_COLORS.get(name, SOURCE_OTHER_COLOR)


# Motivos de baja con color fijo. El nombre se unifica sin tildes ni
# mayúsculas y sin la explicación entre paréntesis ("Sin respuesta inicial
# (el interesado no responde...)" → "Sin respuesta inicial"). Se reconocen
# por el comienzo del texto.
MOTIVO_COLORS = {
    "sin respuesta inicial": "#01498E",
    "sin repuestas":         "#E67E22",
    "precio alto":           "#11734B",
    "necesidad de producto": "#39A8EF",
    "sin interes real":      "#B10202",
}
# Motivos nuevos: color estable según el nombre (no según el orden del mes)
_MOTIVO_SPARE = ["#5A3286", "#C9A400", "#2BB3A3", "#D35FB7", "#8E5B2E", "#34495E"]


def canonical_motivo(value) -> str:
    """Motivo sin la explicación entre paréntesis ni espacios de más; vacío → ""."""
    if value is None or str(value).strip() in ("", "nan", "None"):
        return ""
    text = re.sub(r"\s*\(.*$", "", str(value).strip()).strip(" .,;:-")
    text = " ".join(text.split())
    return text[:1].upper() + text[1:] if text else ""


def motivo_color(name: str) -> str:
    key = _plain(name)
    for prefix, color in MOTIVO_COLORS.items():
        if key.startswith(prefix):
            return color
    digest = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)
    return _MOTIVO_SPARE[digest % len(_MOTIVO_SPARE)]


# Acento lateral de los KPI de Negocios: fila "Volumen" (azul) y "Resultado"
KPI_ACCENT_RESULT = "#39A8EF"
