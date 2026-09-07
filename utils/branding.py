"""Colores y utilidades de branding de Cotear SRL."""

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
    "Ganado en Desarrollo":            "#47e4c2",
    "Ganado en desarrollo":            "#47e4c2",
    "Cerrado Ganado":                  "#7bd500",
    "Cerrado Perdido, motivo?":                 "#f11716",
    "Cerrado Perdido":                 "#f11716",
}


CLASSIFICATION_OPTIONS = list(CLASSIFICATION_COLORS.keys())
