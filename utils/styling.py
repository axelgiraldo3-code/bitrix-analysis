"""Helpers para colorizar DataFrames en Streamlit.

Usa las paletas definidas en utils.branding.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
from pandas.io.formats.style import Styler

from .branding import BITRIX_STAGE_COLORS, CLASSIFICATION_COLORS

HIGH_ALPHA = 0.55  # celda del campo "clasificacion"/"etapa"
LOW_ALPHA = 0.14  # resto de la fila


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


def short_labels(labels: Iterable[str], max_len: int = 20) -> list[str]:
    """Acorta etiquetas largas para leyendas: saca el texto entre paréntesis y
    el punto final, y corta en el último espacio antes de ``max_len`` con "…".
    Si dos etiquetas quedan iguales, les agrega un número para distinguirlas."""
    import re

    out: list[str] = []
    seen: dict[str, int] = {}
    for raw in labels:
        t = re.sub(r"\s*\([^)]*\)", "", str(raw)).strip().rstrip(".").strip() or str(raw).strip()
        if len(t) > max_len:
            cut = t[:max_len]
            # Cortar en un espacio sólo si no se pierden más de 6 caracteres;
            # si no, cortar dentro de la palabra ("Sin respuesta inicia…").
            if t[max_len] != " " and " " in cut and len(cut.rsplit(" ", 1)[0]) >= max_len - 6:
                cut = cut.rsplit(" ", 1)[0]
            t = cut.rstrip(" ,;:-") + "…"
        n = seen.get(t, 0)
        seen[t] = n + 1
        out.append(t if n == 0 else f"{t} ({n + 1})")
    return out
