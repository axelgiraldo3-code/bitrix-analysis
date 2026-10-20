"""Clasificación de tipo de maquinaria a partir del nombre del negocio.

El nombre se normaliza (minúsculas, sin tildes, "C.N.C." → "cnc") y se
compara contra patrones ordenados de más específico a más general: el primero
que coincide gana. Para sumar un sinónimo, agregarlo en el patrón de su
categoría, siempre sin tildes.
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
     r"|\bdobladora\b|\bcurvatubos?\b", "Curvadora de tubos"),
    # --- Soldadura ----------------------------------------------------------
    (r"\bsoldad|\bsoldar\b|\brobot(ica)? de soldadura\b|\bsoldadora\b",
     "Sistema de soldadura automática"),
    # --- Arranque de viruta -------------------------------------------------
    (r"\balesadora\b|\balesado\b|\bmandrinadora\b|\bmandrinado\b", "Alesadora"),
    (r"\bmortajadora\b|\bmortajado\b|\bmortaja\b", "Mortajadora"),
    (r"\brectificadora\b|\brectificado\b|\bamoladora plana\b", "Rectificadora CNC"),
    (r"\bperforad(o|ora|ora radial)\b|\bcentro de perforad|\btaladro\b"
     r"|\bagujereadora\b|\btaladro radial\b", "Centro de perforado"),
    # Torneado antes que mecanizado: "centro de torneado" es un torno CNC
    (r"\bcentro (de )?torneado\b|\btorneado\b.*\bcnc\b|\btorno\b.*\bcnc\b"
     r"|\bcnc\b.*\btorno\b|\btorno (automatico|suizo|swiss)\b|\bswiss type\b"
     r"|\btorno vertical\b", "Torno CNC"),
    (r"\bcentro (de )?mecanizad|\bmecanizado (vertical|horizontal)\b"
     r"|\b(vmc|hmc)\b|\bcentro (vertical|horizontal)\b|\b5 ejes\b"
     r"|\bcinco ejes\b", "Centro de mecanizado"),
    (r"\b(fresadora|fresa)\b.*\bcnc\b|\bcnc\b.*\b(fresadora|fresa)\b|\brouter\b",
     "Fresadora CNC"),
    (r"\bfresadora\b|\bfresa universal\b|\bfresadora universal\b",
     "Fresadora convencional"),
    (r"\btorno\b|\btorneado\b", "Torno convencional"),
]

_COMPILED = [(re.compile(p), cat) for p, cat in _PATTERNS]


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
