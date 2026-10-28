"""Embudo consultas → negocios → ganados (funciones puras).

Cruza las consultas del mes (bot) con los negocios de Bitrix por teléfono
(dígitos significativos). Para cada consulta derivada se toma el negocio
más avanzado de ese teléfono. Un negocio perdido cuenta como "cotizado" si
su etapa anterior ya era de cotización o posterior.
"""

from __future__ import annotations

import pandas as pd

from .branding import _plain

DERIVADO = "DERIVADO A BITRIX"

STAGES = ["Consultas del mes", "Derivadas a Bitrix", "Cotizadas", "Ganadas"]
# Colores de cada etapa (de claro a azul Cotear; ganadas en verde)
COLORS = ["#9DB9D6", "#4F80B5", "#01498E", "#11734B"]

# Avance de cada etapa de Bitrix (texto sin tildes ni mayúsculas, por prefijo)
_RANK = [
    ("pendiente de cotizar", 1),
    ("cotizado", 2),
    ("en negociacion", 3),
    ("ganado en desarrollo", 4),
    ("cerrado ganado", 5),
]
COTIZADO, GANADO = 2, 4


def stage_rank(etapa, etapa_anterior="") -> int:
    """0 = sin etapa conocida; 1 pendiente … 5 cerrado ganado. Un "Cerrado
    Perdido" vale lo que valía su etapa anterior, sin llegar a ganado."""
    e = _plain(etapa or "")
    if e.startswith("cerrado perdido"):
        return min(stage_rank(etapa_anterior), GANADO - 1) if etapa_anterior else 1
    for prefix, rank in _RANK:
        if e.startswith(prefix):
            return rank
    return 0


def match_deals(consultas: pd.DataFrame, deals: pd.DataFrame) -> pd.DataFrame:
    """Consultas derivadas con el negocio más avanzado de su teléfono.

    Columnas agregadas: Negocio Bitrix, Etapa Bitrix, _rank (0 si no hay)."""
    der = consultas[consultas["Clasificacion interna"].astype(str) == DERIVADO].copy()
    der["Negocio Bitrix"], der["Etapa Bitrix"], der["_rank"] = "", "", 0
    if der.empty or deals is None or deals.empty:
        return der
    d = deals[deals["_phone_sig"].astype(str) != ""].copy()
    if d.empty:
        return der
    d["_rank"] = [
        stage_rank(e, a)
        for e, a in zip(d["Etapa"], d.get("Etapa anterior", pd.Series("", index=d.index)))
    ]
    best = (
        d.sort_values("_rank", ascending=False, kind="stable")
        .drop_duplicates("_phone_sig")
        .set_index("_phone_sig")
    )
    sig = der["_phone_sig"].astype(str)
    hit = sig.isin(best.index) & (sig != "")
    der.loc[hit, "Negocio Bitrix"] = sig[hit].map(best["Nombre negocio"]).values
    der.loc[hit, "Etapa Bitrix"] = sig[hit].map(best["Etapa"]).values
    der.loc[hit, "_rank"] = sig[hit].map(best["_rank"]).astype(int).values
    der["_rank"] = der["_rank"].astype(int)
    return der


def funnel_counts(consultas: pd.DataFrame, matched: pd.DataFrame) -> list[int]:
    """Cantidades de cada etapa de ``STAGES``."""
    return [
        len(consultas),
        len(matched),
        int((matched["_rank"] >= COTIZADO).sum()),
        int((matched["_rank"] >= GANADO).sum()),
    ]
