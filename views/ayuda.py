"""Página "Ayuda": muestra las notas de ``docs/ayuda/`` (formato Obsidian).

La nota "Ayuda" es el índice; debajo van las notas que enlaza, en ese orden.
Los valores ``{{nombre}}`` de las notas salen de ``values()``.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from utils import data, machinery, notas, ui

HELP_DIR = Path(__file__).resolve().parent.parent / "docs" / "ayuda"
INDEX = "Ayuda"
BACK = "[:material/arrow_upward: Volver al índice](#indice)"


def values() -> dict[str, object]:
    """Valores que las notas toman del código, para que no queden desactualizados."""
    from views import negocios, reporte

    return {
        "meses_tendencia": data.TREND_MONTHS,
        "hora_inicio": reporte.DAY_START_HOUR,
        "tipos_maquina": negocios.TOP_MACHINES,
        "dias_bitrix": data.BITRIX_SNAPSHOT_TTL_DAYS,
        "dias_bitrix_viejos": data.BITRIX_SNAPSHOT_TTL_OLD_DAYS,
        "dias_telefonos": data.PHONE_INDEX_TTL_DAYS,
        "tabla_maquinas": machinery.examples_table(),
    }


def render() -> None:
    ui.page_header("Ayuda", "Qué muestra cada página, cómo leerla y qué tener en cuenta")
    notes = notas.load_notes(HELP_DIR)
    if INDEX not in notes:
        st.error(f"No se encontró la nota índice ({INDEX}.md) en {HELP_DIR}.")
        return
    vals = values()

    ui.section("Índice", anchor="indice")
    with ui.card("ayuda_indice"):
        st.markdown(notas.render(notes[INDEX], vals))

    for name in notas.order(notes, INDEX):
        ui.section(name, anchor=notas.anchor(name))
        with ui.card(f"ayuda_{notas.slug(name)}"):
            st.markdown(notas.render(notes[name], vals))
            st.caption(BACK)
