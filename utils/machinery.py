"""Clasificación de tipo de maquinaria a partir del nombre del negocio."""
from __future__ import annotations

import re
from typing import Optional


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
    "Otro / Sin clasificar",
]


# Patrones (regex, case-insensitive). El primero que matchea gana; orden importa
# — colocar los más específicos arriba.
_PATTERNS: list[tuple[str, str]] = [
    (r"\bl[aá]ser\s*dual\b|\bdual\s*l[aá]ser\b",              "Cortadora láser dual"),
    (r"\bl[aá]ser\b.*\btubo\b|\btubo\b.*\bl[aá]ser\b",         "Cortadora de tubo láser"),
    (r"\bl[aá]ser\b.*\bchapa\b|\bchapa\b.*\bl[aá]ser\b|\bl[aá]ser\b", "Cortadora de chapa láser"),
    (r"\bplasma\b",                                             "Cortadora CNC plasma"),
    (r"\bguillotina\b",                                         "Cortadora guillotina"),
    (r"\bplegadora\b|\bpress\s*brake\b",                        "Plegadora"),
    (r"\balesadora\b|\balesado\b",                              "Alesadora"),
    (r"\bperforad(o|ora)\b|\bcentro\s+de\s+perforad",            "Centro de perforado"),
    (r"\bsoldadur",                                              "Sistema de soldadura automática"),
    (r"\bca[nñ]os?\b.*\bdisco\b|\bdisco\b.*\bca[nñ]os?\b",        "Cortadora de caños a disco"),
    (r"\bmortajadora\b|\bmortajado\b",                           "Mortajadora"),
    (r"\bcurvadora\b|\bcurvado\s+de\s+tubo",                     "Curvadora de tubos"),
    (r"\brectificadora\b",                                       "Rectificadora CNC"),
    (r"\bcentro\s+de\s+mecanizad",                               "Centro de mecanizado"),
    (r"\bfresadora\b.*\bcnc\b|\bcnc\b.*\bfresadora\b",           "Fresadora CNC"),
    (r"\bfresadora\b",                                           "Fresadora convencional"),
    (r"\btorno\b.*\bcnc\b|\bcnc\b.*\btorno\b",                   "Torno CNC"),
    (r"\btorno\b",                                               "Torno convencional"),
]


_COMPILED = [(re.compile(p, re.IGNORECASE), cat) for p, cat in _PATTERNS]


def classify_machinery(deal_name: Optional[str]) -> str:
    if not deal_name:
        return "Otro / Sin clasificar"
    text = str(deal_name)
    for rx, cat in _COMPILED:
        if rx.search(text):
            return cat
    return "Otro / Sin clasificar"
