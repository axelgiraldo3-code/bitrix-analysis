"""Helpers para colorizar DataFrames en Streamlit.

Usa las paletas definidas en utils.branding.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd
from pandas.io.formats.style import Styler

from .branding import BITRIX_STAGE_COLORS, CLASSIFICATION_COLORS


HIGH_ALPHA = 0.55   # celda del campo "clasificacion"/"etapa"
LOW_ALPHA = 0.14    # resto de la fila


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return f"rgba({r},{g},{b},{alpha:.2f})"


def _row_styler(color_hex: str, key_col: str) -> callable:
    def apply_row(row: pd.Series) -> list[str]:
        high = f"background-color: {_rgba(color_hex, HIGH_ALPHA)}; font-weight: 600;"
        low = f"background-color: {_rgba(color_hex, LOW_ALPHA)};"
        return [high if col == key_col else low for col in row.index]
    return apply_row


def style_bot_table(df: pd.DataFrame, class_col: str = "Clasificacion interna") -> Styler:
    """Colorea cada fila según su clasificación."""
    if df.empty or class_col not in df.columns:
        return df.style
    styles = [""] * len(df)

    def apply_all(row: pd.Series) -> list[str]:
        cls = str(row.get(class_col, "")).strip()
        color = CLASSIFICATION_COLORS.get(cls)
        if not color:
            return [""] * len(row)
        return _row_styler(color, class_col)(row)

    return df.style.apply(apply_all, axis=1)


def style_bitrix_table(df: pd.DataFrame, stage_col: str = "Etapa") -> Styler:
    """Colorea cada fila según su etapa Bitrix."""
    if df.empty or stage_col not in df.columns:
        return df.style

    def apply_all(row: pd.Series) -> list[str]:
        stage = str(row.get(stage_col, "")).strip()
        color = BITRIX_STAGE_COLORS.get(stage)
        if not color:
            return [""] * len(row)
        return _row_styler(color, stage_col)(row)

    return df.style.apply(apply_all, axis=1)
