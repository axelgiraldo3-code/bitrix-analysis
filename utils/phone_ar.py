"""Normalización, formateo y zona geográfica de números telefónicos argentinos.

Formato objetivo: '+54 9 <area> <local>' donde el área puede tener 2, 3 o 4
dígitos según el código. Si no es argentino, se devuelve el número tal cual
(con '+' inicial si corresponde) sin formateo.

`data/codigos_area_argentina.json` mapea cada código de área a su provincia;
`province_of()` usa ese mapa para el análisis geográfico.

`data/localidades_ar.json` (numeración geográfica del ENACOM, generado con
`scripts/build_localidades.py`) mapea cada indicativo a su localidad cabecera;
`locality_of()` lo usa para el detalle por provincia. En el ENACOM cada
indicativo tiene una sola localidad, así que el bloque no se mira.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_DIGITS = re.compile(r"\D+")
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_CODES_CACHE: dict[str, str] | None = None
_SORTED_CODES: list[str] | None = None

ZONE_FOREIGN = "Extranjero"
ZONE_UNKNOWN = "Sin identificar"
# Número argentino cuyo código de área no figura en la numeración del ENACOM
ZONE_UNVERIFIED = "Sin verificar"


def _load_area_codes() -> dict[str, str]:
    """Devuelve {codigo: provincia}. Acepta el formato viejo (lista de códigos)."""
    global _CODES_CACHE, _SORTED_CODES
    if _CODES_CACHE is not None:
        return _CODES_CACHE
    path = _DATA_DIR / "codigos_area_argentina.json"
    data: object = {}
    if path.exists():
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    raw = data.get("codes", data) if isinstance(data, dict) else data
    if isinstance(raw, dict):
        codes = {str(k): str(v) for k, v in raw.items()}
    elif isinstance(raw, list):
        codes = {str(c): "" for c in raw}
    else:
        codes = {}
    _CODES_CACHE = {c: p for c, p in codes.items() if c.isdigit()}
    # Longitud descendente: el matching prefiere 4 > 3 > 2 dígitos
    _SORTED_CODES = sorted(_CODES_CACHE, key=len, reverse=True)
    return _CODES_CACHE


def _sorted_codes() -> list[str]:
    _load_area_codes()
    return _SORTED_CODES or []


def only_digits(value: str | None) -> str:
    if value is None:
        return ""
    return _DIGITS.sub("", str(value))


def is_argentine(digits: str) -> bool:
    """Heurística: 10 dígitos, o 11 (con 9), o 12 (con 54), o 13 (con 549)."""
    if not digits:
        return False
    if digits.startswith("54"):
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


@lru_cache(maxsize=1)
def load_localities() -> dict[str, dict]:
    """{indicativo: {localidad, provincia, lat, lon}} del ENACOM."""
    path = _DATA_DIR / "localidades_ar.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    raw = data.get("codes", data) if isinstance(data, dict) else {}
    return {str(k): v for k, v in raw.items() if str(k).isdigit() and isinstance(v, dict)}


@lru_cache(maxsize=1)
def _area_regex() -> re.Pattern[str]:
    """``^(?P<ind>…)(?P<abonado>\\d+)$`` sobre los 10 dígitos significativos,
    con los indicativos de ambas tablas del más largo al más corto (la
    numeración argentina no tiene un código que sea prefijo de otro, pero así
    no depende de eso)."""
    codes = set(_sorted_codes()) | set(load_localities())
    alternation = "|".join(sorted(codes, key=lambda c: (-len(c), c)))
    return re.compile(rf"^(?P<ind>{alternation or '(?!)'})(?P<abonado>\d+)$")


def area_code_of(raw: str | None) -> str:
    """Código de área del número argentino ('' si no es AR o no matchea)."""
    local10 = significant_ar(raw or "")
    if not local10:
        return ""
    m = _area_regex().match(local10)
    return m.group("ind") if m else ""


def province_of(raw: str | None) -> str:
    """Provincia del número. 'Extranjero' si no es AR, 'Sin identificar' si
    no hay número y 'Sin verificar' si el código de área no está en ninguna
    tabla."""
    d = only_digits(raw)
    if not d:
        return ZONE_UNKNOWN
    if not is_argentine(d):
        return ZONE_FOREIGN
    code = area_code_of(d)
    prov = _load_area_codes().get(code, "")
    if not prov:
        prov = load_localities().get(code, {}).get("provincia", "")
    return prov or ZONE_UNVERIFIED


def locality_of(raw: str | None) -> str:
    """Localidad cabecera del código de área según el ENACOM. 'Extranjero' si
    no es AR, 'Sin identificar' si no hay número y 'Sin verificar' si el
    código no figura en la numeración del ENACOM."""
    d = only_digits(raw)
    if not d:
        return ZONE_UNKNOWN
    if not is_argentine(d):
        return ZONE_FOREIGN
    entry = load_localities().get(area_code_of(d))
    return str(entry.get("localidad", "")) if entry else ZONE_UNVERIFIED


def format_ar(raw: str | None) -> str:
    """Formatea a '+54 9 <area> <local>' si es argentino; devuelve original si no."""
    if raw is None:
        return ""
    original = str(raw).strip()
    digits = only_digits(original)
    if not digits:
        return ""

    if not is_argentine(digits):
        return f"+{digits}" if original.startswith("+") else original

    local10 = digits[-10:]
    area = area_code_of(local10)
    if area:
        local = local10[len(area) :]
    else:
        # Fallback: asumir 3 dígitos de área
        area, local = local10[:3], local10[3:]

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
    """True si el número no es argentino (para clasificar como SIN INTERES)."""
    d = only_digits(raw)
    if not d:
        return False
    return not is_argentine(d)
