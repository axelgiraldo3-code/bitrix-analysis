"""Normalización y formateo de números telefónicos argentinos.

Formato objetivo: '+54 9 (XXX) XXXX-XXXX' donde el (XXX) puede ser 2, 3 o 4 dígitos
según el código de área. Si no es argentino, se devuelve el número tal cual
(con '+' inicial si corresponde) sin formateo.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional


_DIGITS = re.compile(r"\D+")
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_CODES_CACHE: Optional[list[str]] = None


def _load_area_codes() -> list[str]:
    global _CODES_CACHE
    if _CODES_CACHE is not None:
        return _CODES_CACHE
    path = _DATA_DIR / "codigos_area_argentina.json"
    if not path.exists():
        _CODES_CACHE = []
        return _CODES_CACHE
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    # Aceptamos tanto {"codes": [...]} como una lista directa o {"XXX": "Ciudad", ...}
    if isinstance(data, dict):
        if "codes" in data and isinstance(data["codes"], list):
            codes = [str(c) for c in data["codes"]]
        else:
            codes = list(data.keys())
    elif isinstance(data, list):
        codes = [str(c) for c in data]
    else:
        codes = []
    # Ordenar por longitud descendente para que el matching prefiera 4>3>2 dígitos
    _CODES_CACHE = sorted({c for c in codes if c.isdigit()}, key=len, reverse=True)
    return _CODES_CACHE


def only_digits(value: str | None) -> str:
    if value is None:
        return ""
    return _DIGITS.sub("", str(value))


def is_argentine(digits: str) -> bool:
    """Heurística: 10 dígitos, o 11 (con 9), o 12 (con 54 9), o 13 (con 549)."""
    if not digits:
        return False
    if digits.startswith("54"):
        # 54 + 9 + 10 = 13, o 54 + 10 = 12
        rest = digits[2:]
        if rest.startswith("9"):
            rest = rest[1:]
        return len(rest) == 10
    if digits.startswith("9") and len(digits) == 11:
        return True
    return len(digits) == 10


def significant_ar(digits: str) -> str:
    """Devuelve los últimos 10 dígitos si el número es argentino, si no ''."""
    d = only_digits(digits)
    if not is_argentine(d):
        return ""
    return d[-10:]


def format_ar(raw: str | None) -> str:
    """Formatea a '+54 9 (XXX) XXXX-XXXX' si es argentino; devuelve original si no."""
    if raw is None:
        return ""
    original = str(raw).strip()
    digits = only_digits(original)
    if not digits:
        return ""

    if not is_argentine(digits):
        # No argentino: preservar '+' si venía
        return f"+{digits}" if original.startswith("+") else original

    local10 = digits[-10:]  # los últimos 10 son AREA(2-4) + LOCAL

    codes = _load_area_codes()
    area = ""
    local = ""
    for code in codes:
        if 2 <= len(code) <= 4 and local10.startswith(code):
            area = code
            local = local10[len(code):]
            break

    if not area:
        # Fallback: asumir 3 dígitos de área
        area = local10[:3]
        local = local10[3:]

    if len(local) == 8:
        local_fmt = f"{local[:4]}-{local[4:]}"
    elif len(local) == 7:
        local_fmt = f"{local[:3]}-{local[3:]}"
    elif len(local) == 6:
        local_fmt = f"{local[:2]}-{local[2:]}"
    else:
        local_fmt = local

    return f"+54 9 {area} {local_fmt}".strip()


def is_foreign(raw: str | None) -> bool:
    """True si el número no es argentino (para clasificar automáticamente como SIN INTERES)."""
    d = only_digits(raw)
    if not d:
        return False
    return not is_argentine(d)
