"""
Formateo y validación de números telefónicos argentinos con búsqueda O(1)
sobre los códigos de área oficiales (`data/codigos_area_argentina.json`).

Reglas de negocio (ver ticket de integración):

1. Si el número original viene con prefijo internacional (`+` o `00`) y
   el código de país NO es 54, se IGNORAN todas las reglas argentinas y
   se devuelve el número tal cual, con una limpieza mínima
   (`+<pais><digitos>`). NUNCA se le aplica la normalización AR, para
   no destruir contactos de Chile (+56), Brasil (+55), España (+34), etc.
2. Si el número es local o tiene prefijo +54 / 0054, se normaliza al
   formato E.164 argentino: `+549` + código de área + número local.
3. La validación del código de área se hace contra `set()` (O(1) por
   lookup) en orden jerárquico 4 → 3 → 2 dígitos, verificando que el
   bloque total argentino sea de exactamente 10 dígitos.
4. Si nada valida, se devuelve el input original sin modificar — regla
   defensiva para no perder datos ambiguos.
"""

import json
import re
from pathlib import Path
from functools import lru_cache

from .config import DATA_DIR


_AREA_CODES_FILE = Path(DATA_DIR) / "codigos_area_argentina.json"


@lru_cache(maxsize=1)
def _load_area_code_sets():
    """
    Carga el JSON UNA sola vez (cacheado con lru_cache) y devuelve un
    diccionario `{longitud: frozenset(codigos)}`. Usar frozenset — y no
    listas — es lo que garantiza el O(1) por lookup exigido por el
    ticket: con listas la búsqueda sería O(n) por cada teléfono validado
    y se degradaría linealmente al crecer el catálogo de códigos.

    lru_cache evita releer el archivo en cada llamada (el JSON pesa ~5
    KB pero la app puede validar cientos de teléfonos por rerun de
    Streamlit).
    """
    with open(_AREA_CODES_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    codes = raw.get("argentina_area_codes", {})
    return {
        4: frozenset(codes.get("len_4", [])),
        3: frozenset(codes.get("len_3", [])),
        2: frozenset(codes.get("len_2", [])),
    }


def _international_non_ar(digits):
    """Devuelve la forma canónica `+<pais><resto>` para un número
    internacional que NO es argentino. No intenta re-formatear el bloque
    local del país extranjero — solo garantiza el prefijo '+' y elimina
    separadores raros."""
    return f"+{digits}"


def format_phone_ar_e164(raw):
    """
    Normaliza `raw` a E.164 argentino (`+549XXXXXXXXXX`) cuando
    corresponde. Comportamiento resumido:

    - Extranjero (+/00 + país ≠ 54): se devuelve `+<pais><resto>`.
    - Argentino válido: se devuelve `+549<area><local>` (14 caracteres).
    - Argentino inválido o formato irreconocible: se devuelve `raw` tal
      cual (sin destruir la entrada).
    - `None` o cadena vacía: `""`.
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s:
        return ""

    # ------------------------------------------------------------------
    # 1) DETECCIÓN DE ORIGEN INTERNACIONAL
    # ------------------------------------------------------------------
    # Distinguimos '+' y '00' explícitamente porque son los DOS marcadores
    # estándar de discado internacional; cualquier otra cosa que empiece
    # con dígitos se trata como número local / AR ambiguo y se normaliza
    # más abajo.
    intl_digits = None
    if s.startswith("+"):
        intl_digits = re.sub(r"\D", "", s[1:])
    elif s.startswith("00"):
        intl_digits = re.sub(r"\D", "", s[2:])

    if intl_digits is not None:
        if not intl_digits.startswith("54"):
            # País distinto de Argentina: se IGNORA la lógica AR y se
            # devuelve con formato internacional estándar. Esto respeta
            # números como +56 9 XXXX XXXX (Chile) o +34 6XX XXX XXX
            # (España) sin destrozarlos.
            return _international_non_ar(intl_digits)
        # Sí es +54 / 0054 → se procesa como AR abajo.
        digits = intl_digits
    else:
        # Sin prefijo internacional: tomamos solo dígitos y asumimos AR.
        digits = re.sub(r"\D", "", s)

    if not digits:
        return s

    # ------------------------------------------------------------------
    # 2) NORMALIZACIÓN DEL BLOQUE ARGENTINO
    # ------------------------------------------------------------------
    # Estos strippings son idempotentes y se aplican en orden fijo:
    #   54  → código de país (si venía como +54 ya lo removimos, pero el
    #         usuario puede haber escrito el 54 sin '+').
    #   9   → prefijo de celular que WhatsApp/Bitrix inyectan tras el 54.
    #   0   → "trunk prefix" nacional del código de área.
    if digits.startswith("54"):
        digits = digits[2:]
    if digits.startswith("9"):
        digits = digits[1:]
    if digits.startswith("0"):
        digits = digits[1:]

    # ------------------------------------------------------------------
    # 3) VALIDACIÓN JERÁRQUICA DEL CÓDIGO DE ÁREA (4 → 3 → 2)
    # ------------------------------------------------------------------
    # Orden 4→3→2 es CRÍTICO: "2202" (4 dígitos, San Pedro BA) empieza
    # con "22" (que NO es código válido de 2 dígitos), pero también con
    # "220" (que tampoco lo es); si probáramos primero los de 2 dígitos
    # podríamos aceptar un match falso para números que en realidad son
    # de 4 dígitos. Al ir del más específico al más genérico el primer
    # match verdadero siempre es el correcto.
    area_sets = _load_area_code_sets()
    for length in (4, 3, 2):
        if len(digits) < length + 1:
            # Al menos 1 dígito local además del área.
            continue
        area = digits[:length]
        if area not in area_sets[length]:
            continue

        local = digits[length:]
        # El "15" del celular puede aparecer INTERCALADO entre el código
        # de área y el número local (ej. "011 15 4123-4567" →
        # "01115..." → tras remover el 0 inicial queda "1115...", y al
        # detectar area="11" el "15" queda al principio de `local`).
        if local.startswith("15"):
            local = local[2:]

        if len(area) + len(local) == 10:
            return f"+549{area}{local}"

    # Nada validó → devolvemos el input original tal cual.
    return s


def is_argentina_e164(formatted):
    """True si un string YA normalizado por format_phone_ar_e164 es AR."""
    return str(formatted or "").startswith("+549")


def e164_to_local10(formatted):
    """
    Devuelve los 10 dígitos locales (`<area><local>`) a partir de un
    E.164 argentino ya normalizado. Útil como clave de merge entre
    fuentes (WhatsApp bot ↔ Bitrix) sin arrastrar el "+549".
    Si `formatted` no es AR válido, devuelve "".
    """
    f = str(formatted or "")
    if f.startswith("+549") and len(f) == 14:
        return f[4:]
    return ""


def e164_to_area_local(formatted):
    """
    Devuelve la tupla `(area, local)` para un E.164 argentino ya
    normalizado, detectando la longitud del código de área contra los
    sets oficiales (mismo orden jerárquico 4→3→2 que en la validación).
    Para no-AR o entrada inválida devuelve `("", "")`.

    Se usa para el formato visual "+54 9 <area> <local>" en las tablas.
    """
    local10 = e164_to_local10(formatted)
    if not local10:
        return "", ""
    sets = _load_area_code_sets()
    for length in (4, 3, 2):
        if local10[:length] in sets[length]:
            return local10[:length], local10[length:]
    # Fallback teórico: si un E.164 llegó "validado" pero el área no está
    # en los sets, asumimos 3 dígitos (el caso más frecuente) para no
    # devolver vacío. Este branch no debería dispararse porque
    # `format_phone_ar_e164` solo produce `+549` cuando el área validó.
    return local10[:3], local10[3:]
