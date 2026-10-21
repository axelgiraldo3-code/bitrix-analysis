"""Variación de los KPI respecto del período anterior (funciones puras).

Cada KPI tiene una polaridad:
* ``UP_GOOD``   — subir es bueno (verde al subir, rojo al bajar).
* ``DOWN_GOOD`` — indicador "negativo": bajar es bueno (verde al bajar).
* ``NEUTRAL``   — la variación se informa en gris.

``delta_kwargs`` devuelve los argumentos ``delta``, ``delta_color`` y
``delta_description`` listos para ``st.metric``.
"""
from __future__ import annotations

from typing import Optional

import pandas as pd

UP_GOOD = "up_good"
DOWN_GOOD = "down_good"
NEUTRAL = "neutral"

_COLOR = {UP_GOOD: "normal", DOWN_GOOD: "inverse", NEUTRAL: "off"}
NO_PREVIOUS = "sin datos del período anterior"


def _fmt_num(v: float, decimals: int) -> str:
    return f"{v:+.{decimals}f}" if decimals else f"{int(round(v)):+d}"


def delta_kwargs(current: Optional[float], previous: Optional[float], polarity: str,
                 *, vs: str = "", unit: str = "", decimals: int = 0,
                 extra: str = "") -> dict:
    """Variación ``current - previous``.

    ``unit`` se agrega al número (ej. " p.p.", " días"); ``vs`` es el
    período de comparación ("vs. sep-26"); ``extra`` es texto adicional
    para la descripción (ej. "7 consultas · antes Córdoba").
    """
    if current is None or previous is None or pd.isna(current) or pd.isna(previous):
        return {"delta": None, "delta_color": "off",
                "delta_description": " · ".join(t for t in (extra, NO_PREVIOUS) if t) or None}
    diff = round(float(current) - float(previous), decimals)
    if diff == 0:
        delta: object = 0
        desc = " · ".join(t for t in (extra, "sin cambios", vs) if t)
    else:
        delta = _fmt_num(diff, decimals) + unit
        desc = " · ".join(t for t in (extra, vs) if t)
    return {"delta": delta, "delta_color": _COLOR[polarity], "delta_description": desc or None}


def top_category(values: pd.Series, exclude: set[str] | None = None) -> tuple[str, int]:
    """(categoría más frecuente, cantidad). Ignora vacíos y ``exclude``."""
    s = values.fillna("").astype(str).str.strip()
    s = s[(s != "") & ~s.isin(exclude or set())]
    if s.empty:
        return "—", 0
    vc = s.value_counts()
    return str(vc.index[0]), int(vc.iloc[0])


def category_kwargs(current: pd.Series, previous: Optional[pd.Series], polarity: str,
                    unit: str, *, vs: str = "", exclude: set[str] | None = None) -> tuple[str, dict]:
    """KPI de categoría líder (provincia, área, fuente, motivo).

    Devuelve (valor a mostrar, kwargs de delta). La variación es la de la
    cantidad de esa categoría contra el período anterior; si el líder
    cambió, la descripción dice cuál era el anterior.
    """
    top, n = top_category(current, exclude)
    if top == "—":
        return top, {"delta": None, "delta_color": "off", "delta_description": None}
    label = f"{n} {unit if n != 1 else unit.rstrip('s')}"
    if previous is None:
        return top, delta_kwargs(n, None, polarity, extra=label)
    prev_s = previous.fillna("").astype(str).str.strip()
    prev_n = int((prev_s == top).sum())
    prev_top, _ = top_category(previous, exclude)
    if prev_top not in ("—", top):
        label += f" · antes {prev_top}"
    return top, delta_kwargs(n, prev_n, polarity, vs=vs, extra=label)
