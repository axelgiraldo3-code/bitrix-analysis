"""Campañas de anuncios a partir de la "Información de origen" del contacto.

Cuando el cliente llega por un anuncio, Bitrix guarda un texto libre del tipo
"Anuncio de Facebook, campaña tornos convencionales". Se escribe a mano, así
que llega con variantes ("campaña de tornos convencionales", "torno
convencional", "corte láser" / "cortadoras láser", sin la palabra "campaña"):
la campaña se unifica en singular, sin el "campaña de/del" inicial y con los
sinónimos de ``CAMPAIGN_ALIASES``; ``unify_spelling`` junta además las que
sólo difieren en tildes ("laser" / "láser").
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

NO_CAMPAIGN = "Sin campaña"
OTHER_NETWORK = "Otra"

# Campaña normalizada (sin tildes, minúsculas, singular) → nombre a mostrar
CAMPAIGN_ALIASES = {
    "corte laser": "Cortadora láser",
    "cortadora laser": "Cortadora láser",
    "cortadora de chapa laser": "Cortadora láser",
}

# Palabras que se escriben siempre con tilde (clave sin tildes)
ACCENTED = {"laser": "láser", "maquina": "máquina", "hidraulica": "hidráulica"}

# Marcas que se muestran con su mayúscula (clave sin tildes, en minúscula)
BRANDS = {"topway": "Topway", "turcite": "Turcite"}

_NETWORKS = {"facebook": "Facebook", "instagram": "Instagram"}
_LEADING = re.compile(r"^(campana|campaña)\b\s*|^(de los|de las|de la|del|de)\s+", re.IGNORECASE)


def _plain(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text).strip().lower())
    return " ".join("".join(c for c in t if not unicodedata.combining(c)).split())


def _singular(word: str) -> str:
    """Singular aproximado de una palabra ("tornos" → "torno",
    "convencionales" → "convencional"). Siglas y palabras cortas quedan."""
    if len(word) <= 3 or word.isupper():
        return word
    low = _plain(word)
    if re.search(r"[lrnd]es$", low):
        return word[:-2]
    if low.endswith("s") and not low.endswith("ss"):
        return word[:-1]
    return word


def is_ad(origin) -> bool:
    """El origen describe un anuncio ("Anuncio de …")."""
    return _plain(origin or "").startswith("anuncio")


def ad_network(origin) -> str:
    """Red del anuncio (Facebook, Instagram u "Otra"); "" si no es anuncio."""
    if not is_ad(origin):
        return ""
    head = _plain(origin).split(",", 1)[0]
    for key, name in _NETWORKS.items():
        if key in head:
            return name
    return OTHER_NETWORK


def campaign_name(origin) -> str:
    """Campaña unificada del anuncio; "Sin campaña" si el texto no la dice y
    "" si el origen no es un anuncio."""
    if not is_ad(origin):
        return ""
    parts = str(origin).split(",", 1)
    text = parts[1].strip(" .;:-") if len(parts) > 1 else ""
    while True:
        stripped = _LEADING.sub("", text, count=1).strip()
        if stripped == text:
            break
        text = stripped
    words = [_singular(w) for w in text.split()]
    if not words:
        return NO_CAMPAIGN
    key = _plain(" ".join(words))
    if key in CAMPAIGN_ALIASES:
        return CAMPAIGN_ALIASES[key]
    # En minúscula (no depende de cómo se tipeó), salvo siglas ("CNC") y
    # marcas; la primera palabra con mayúscula
    known = {**ACCENTED, **BRANDS}
    out = [known.get(_plain(w)) or (w if w.isupper() and len(w) > 1 else w.lower()) for w in words]
    out[0] = out[0][:1].upper() + out[0][1:]
    return " ".join(out)


def _accents(text: str) -> int:
    return sum(unicodedata.combining(c) > 0 for c in unicodedata.normalize("NFKD", text))


def unify_spelling(names: pd.Series) -> pd.Series:
    """Une las campañas que sólo difieren en tildes ("Tubo laser" y "Tubo
    láser"): todas toman la escritura con más tildes y, a igualdad, la más
    frecuente."""
    names = names.fillna("").astype(str)
    counts = names[names != ""].value_counts()
    best: dict[str, str] = {}
    for name, n in counts.items():
        key = _plain(name)
        cur = best.get(key)
        if cur is None or (_accents(name), n) > (_accents(cur), counts[cur]):
            best[key] = name
    return names.map(lambda s: best.get(_plain(s), s) if s else s)
