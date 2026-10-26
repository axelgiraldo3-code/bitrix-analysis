"""Clasificación de tipo de maquinaria a partir del nombre del negocio.

El nombre se normaliza (minúsculas, sin tildes, "C.N.C." → "cnc") y se
compara contra patrones ordenados de más específico a más general: el primero
que coincide gana. Para sumar un sinónimo, agregarlo en el patrón de su
categoría, siempre sin tildes.

Referencia: categorías, subcategorías y `aliases` de `Maquinas/` en el vault
de Obsidian (base de conocimiento comercial). Las subcategorías del vault se
agrupan en la categoría de la app:
- Tornos CNC (horizontales, paralelos, tipo suizo, verticales, petroleros CNC)
  → Torno CNC.
- Tornos convencionales (semipesados, pesados, petroleros convencionales)
  → Torno convencional.
- Centros de mecanizado (verticales, 5 ejes) → Centro de mecanizado; centros
  de perforado y roscado → Centro de perforado.
- Fresadoras CNC / convencionales, Alesadoras, Brochadoras (CNC,
  hidráulicas), Curvadoras (CNC, convencionales) y Rectificadoras (planas)
  → su categoría.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


OTHER = "Otro / Sin clasificar"

# Categorías canónicas comercializadas por Cotear
CATEGORIES = [
    "Torno CNC",
    "Torno convencional",
    "Centro de mecanizado",
    "Fresadora convencional",
    "Fresadora CNC",
    "Cortadora de chapa láser",
    "Rectificadora CNC",
    "Curvadora de tubos",
    "Mortajadora",
    "Cortadora de tubo láser",
    "Cortadora láser dual",
    "Cortadora CNC plasma",
    "Sistema de soldadura automática",
    "Cortadora de caños a disco",
    "Alesadora",
    "Centro de perforado",
    "Plegadora",
    "Cortadora guillotina",
    "Brochadora",
    OTHER,
]

_LASER = r"(laser|fibra optica|laser de fibra|fiber)"
_TUBO = r"(tubos?|canos?|perfiles?)"
_CHAPA = r"(chapas?|planchas?|laminas?)"

# (patrón sobre texto normalizado, categoría). Orden = prioridad.
_PATTERNS: list[tuple[str, str]] = [
    # --- Láser: dual antes que tubo, tubo antes que chapa -------------------
    (rf"\b{_LASER}\b.*\bdual\b|\bdual\b.*\b{_LASER}\b", "Cortadora láser dual"),
    (rf"(?=.*\b{_LASER}\b)(?=.*\b{_TUBO}\b)(?=.*\b{_CHAPA}\b)", "Cortadora láser dual"),
    (rf"\b{_LASER}\b.*\b{_TUBO}\b|\b{_TUBO}\b.*\b{_LASER}\b", "Cortadora de tubo láser"),
    (rf"\b{_LASER}\b", "Cortadora de chapa láser"),
    # --- Otros cortes -------------------------------------------------------
    (r"\bplasma\b|\boxicorte\b|\bpantografo\b", "Cortadora CNC plasma"),
    (r"\bguillotina\b|\bcizalla\b|\bcizalladora\b", "Cortadora guillotina"),
    (r"\b(sierra|cortadora|tronzadora)\b.*\b(disco|circular|sensitiva)\b"
     r"|\b(disco|circular)\b.*\bcanos?\b|\btronzadora\b|\bsierra circular\b"
     r"|\bcortadora de canos?\b", "Cortadora de caños a disco"),
    # --- Conformado ---------------------------------------------------------
    (r"\bplegadora\b|\bplegado\b|\bpress ?brake\b|\bdobladora de chapas?\b"
     r"|\bplegadora hidraulica\b", "Plegadora"),
    (r"\bcurvadora\b|\bcurvado\b|\bdobladora( de)? (canos?|tubos?)\b"
     r"|\bdobladora\b|\bcurvatubos?\b|\btube bender\b", "Curvadora de tubos"),
    # --- Soldadura ----------------------------------------------------------
    (r"\bsoldad|\bsoldar\b|\brobot(ica)? de soldadura\b|\bsoldadora\b",
     "Sistema de soldadura automática"),
    # --- Arranque de viruta -------------------------------------------------
    (r"\balesadora\b|\balesado\b|\bmandr(in|il)adora\b|\bmandrinado\b"
     r"|\bboring (mill|machine)\b", "Alesadora"),
    (r"\bmortajadora\b|\bmortajado\b|\bmortaja\b", "Mortajadora"),
    (r"\bbrochad(ora|o)\b|\bbrochar\b|\bbroaching\b", "Brochadora"),
    (r"\brectificadora\b|\brectificado\b|\bamoladora (plana|de precision)\b"
     r"|\bgrinder\b", "Rectificadora CNC"),
    (r"\bperforad(o|ora|ora radial)\b|\bcentro de perforad|\btaladro\b"
     r"|\bagujereadora\b|\btaladro radial\b|\bdrill tap\b|\btapping center\b"
     r"|\bdrilling and tapping\b", "Centro de perforado"),
    # Torneado antes que mecanizado: "centro de torneado" es un torno CNC.
    # "Torno petrolero" / "roscador" es CNC salvo que diga convencional o manual.
    (r"\bcentro (de )?torneado\b|\btorneado\b.*\bcnc\b|\btorno\b.*\bcnc\b"
     r"|\bcnc\b.*\btorno\b|\btorno (automatico|suizo|swiss)\b|\bswiss type\b"
     r"|\btipo suizo\b|\btorno vertical\b|\bvtl\b|\bvertical turning\b"
     r"|\btorno de carrusel\b|\btorno a control numerico\b|\bslant bed\b"
     r"|\bbancada inclinada\b|\btorno multitareas?\b|\bcabezal movil\b"
     r"|\bpipe threading\b"
     r"|\btorno (petrolero|roscador)\b(?!.*\b(convencional|manual)\b)",
     "Torno CNC"),
    (r"\bcentro (de )?(mecanizad|maquinad)|\bmecanizado (vertical|horizontal)\b"
     r"|\b(vmc|hmc|cmv)\b|\bcentro (vertical|horizontal)\b|\b5 ejes\b"
     r"|\bcinco ejes\b|\b5 axis\b|\bmachining center\b", "Centro de mecanizado"),
    (r"\b(fresadora|fresa|milling)\b.*\bcnc\b|\bcnc\b.*\b(fresadora|fresa|milling)\b"
     r"|\bfresadora a control numerico\b|\brouter\b", "Fresadora CNC"),
    (r"\bfresadora\b|\bfresa universal\b|\bfresadora universal\b"
     r"|\bmilling machine\b|\bbridgeport\b", "Fresadora convencional"),
    (r"\btorno\b|\btorneado\b", "Torno convencional"),
]

_COMPILED = [(re.compile(p), cat) for p, cat in _PATTERNS]

# Ejemplos legibles de nombres que reconoce cada categoría (nota "Tipos de
# máquina" de la Ayuda). Las pruebas verifican que cada uno se clasifique en
# su categoría: al cambiar un patrón, ajustar también estos ejemplos.
EXAMPLES: dict[str, list[str]] = {
    "Torno CNC": ["torno CNC", "centro de torneado", "torno tipo suizo", "torno vertical",
                  "VTL", "torno de bancada inclinada", "torno multitarea",
                  "torno petrolero", "torno roscador"],
    "Torno convencional": ["torno", "torno convencional", "torno petrolero convencional"],
    "Centro de mecanizado": ["centro de mecanizado", "VMC", "HMC", "centro vertical",
                             "centro horizontal", "5 ejes"],
    "Fresadora convencional": ["fresadora", "fresadora universal", "Bridgeport"],
    "Fresadora CNC": ["fresadora CNC", "router"],
    "Cortadora de chapa láser": ["láser", "láser de fibra", "fibra óptica"],
    "Rectificadora CNC": ["rectificadora", "amoladora plana"],
    "Curvadora de tubos": ["curvadora", "dobladora de caños", "curvatubos"],
    "Mortajadora": ["mortajadora", "mortaja"],
    "Cortadora de tubo láser": ["láser de tubos", "láser de caños", "láser de perfiles"],
    "Cortadora láser dual": ["láser dual", "láser de chapa y tubo"],
    "Cortadora CNC plasma": ["plasma", "oxicorte", "pantógrafo"],
    "Sistema de soldadura automática": ["soldadora", "robot de soldadura"],
    "Cortadora de caños a disco": ["sierra circular", "tronzadora", "cortadora de caños"],
    "Alesadora": ["alesadora", "mandrinadora"],
    "Centro de perforado": ["centro de perforado", "taladro radial", "agujereadora"],
    "Plegadora": ["plegadora", "dobladora de chapa", "press brake"],
    "Cortadora guillotina": ["guillotina", "cizalla"],
    "Brochadora": ["brochadora"],
}


def examples_table() -> str:
    """Tabla Markdown [Tipo de máquina | Nombres que se reconocen]."""
    rows = [f"| {cat} | {', '.join(EXAMPLES[cat])} |"
            for cat in CATEGORIES if cat in EXAMPLES]
    return "\n".join(["| Tipo de máquina | Nombres que se reconocen |", "|---|---|", *rows])


def normalize(text: str) -> str:
    """Minúsculas, sin tildes, 'ñ' → 'n', 'C.N.C.' → 'cnc', espacios simples."""
    t = unicodedata.normalize("NFKD", str(text).lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"\bc\s*\.?\s*n\s*\.?\s*c\b\.?", "cnc", t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def classify_machinery(deal_name: Optional[str]) -> str:
    if not deal_name:
        return OTHER
    text = normalize(deal_name)
    for rx, cat in _COMPILED:
        if rx.search(text):
            return cat
    return OTHER
