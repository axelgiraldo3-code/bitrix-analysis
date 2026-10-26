"""Cierres de negocios (funciones puras).

Un negocio está cerrado si su etapa empieza con "Cerrado" (ganado o
perdido) y ganado si empieza con "Cerrado Ganado". La fecha de cierre es
la del último movimiento de etapa (``_mov_dt``).

Sirve para las dos lecturas de la página Negocios: por creación (de lo
que entró en el período, qué se cerró) y por cierre (qué se cerró en el
período, sin importar cuándo se creó).
"""
from __future__ import annotations

import pandas as pd


def _stages(df: pd.DataFrame) -> pd.Series:
    return df["Etapa"].astype(str).str.strip().str.lower()


def closed_mask(df: pd.DataFrame) -> pd.Series:
    """Negocios ganados o perdidos."""
    return _stages(df).str.startswith("cerrado")


def won_mask(df: pd.DataFrame) -> pd.Series:
    """Sólo "Cerrado Ganado" ("Ganado en Desarrollo" no cuenta)."""
    return _stages(df).str.startswith("cerrado ganado")


def lifetimes(df: pd.DataFrame) -> pd.Series:
    """Días entre creación y último movimiento (sin fechas inválidas ni negativos)."""
    days = (df["_mov_dt"] - df["_cre_dt"]).dt.days.dropna()
    return days[days >= 0]


def closure_stats(closed: pd.DataFrame | None, start) -> dict:
    """KPIs de los negocios cerrados en un período.

    ``closed`` = negocios cerrados dentro del período; ``start`` = su
    primer día. ``arrastre`` es el % de esos cierres creados antes de
    ``start`` (None si no hay cierres)."""
    if closed is None or closed.empty:
        return {"cerrados": 0, "ganados": 0, "arrastre": None, "vida": None, "n_vida": 0}
    vidas = lifetimes(closed)
    before = (closed["_cre_dt"] < pd.Timestamp(start)).mean() * 100
    return {
        "cerrados": len(closed),
        "ganados": int(won_mask(closed).sum()),
        "arrastre": float(before),
        "vida": float(vidas.mean()) if not vidas.empty else None,
        "n_vida": len(vidas),
    }
