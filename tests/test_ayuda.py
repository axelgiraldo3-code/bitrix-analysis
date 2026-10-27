"""Pruebas de la Ayuda: conversión de notas estilo Obsidian y contenido de docs/ayuda."""

import re

import pytest

from utils import machinery, notas
from views import ayuda


# --- conversión ---------------------------------------------------------------
def test_slug_and_anchor():
    assert notas.slug("Navegación y filtros") == "navegacion-y-filtros"
    assert notas.anchor("Prácticas recomendadas") == "nota-practicas-recomendadas"


def test_render_wikilinks():
    out = notas.render("Ver [[Reporte mensual]] y [[Origen de los datos#Clasificación|esto]].", {})
    assert out == (
        "Ver [Reporte mensual](#nota-reporte-mensual) y [esto](#nota-origen-de-los-datos)."
    )


def test_render_placeholders_headings_callouts():
    text = "## Título\n### Sub\nCada {{dias}} días, {{otro}}.\n> [!info] Ojo\n> texto"
    out = notas.render(text, {"dias": 7})
    assert out.splitlines() == [
        "#### Título",
        "##### Sub",
        "Cada 7 días, {{otro}}.",
        "> **Ojo**",
        "> texto",
    ]


def test_order_follows_index_then_rest():
    notes = {"Ayuda": "[[B]] [[A]] [[B]] [[Falta]]", "A": "", "B": "", "C": ""}
    assert notas.order(notes, "Ayuda") == ["B", "A", "C"]


# --- contenido real -----------------------------------------------------------
NOTES = notas.load_notes(ayuda.HELP_DIR)


def test_index_exists_and_links_every_note():
    assert ayuda.INDEX in NOTES
    linked = set(notas.linked_notes(NOTES[ayuda.INDEX]))
    assert set(NOTES) - {ayuda.INDEX} == linked


@pytest.mark.parametrize("name", sorted(NOTES))
def test_note_links_and_values_resolve(name):
    text = NOTES[name]
    assert text.strip()
    assert set(notas.linked_notes(text)) <= set(NOTES)
    assert notas.placeholders(text) <= set(ayuda.values())
    # Convención: "—" no se usa como separador en textos
    assert "—" not in text


def test_rendered_links_point_to_sections():
    anchors = {notas.anchor(n) for n in NOTES} | {"indice"}
    for text in NOTES.values():
        links = set(re.findall(r"\]\(#([\w-]+)\)", notas.render(text, ayuda.values())))
        assert links <= anchors


# --- tipos de máquina -----------------------------------------------------------
@pytest.mark.parametrize("cat, name", [(c, n) for c, ns in machinery.EXAMPLES.items() for n in ns])
def test_machinery_examples_classify_to_their_category(cat, name):
    assert machinery.classify_machinery(f"{name} · Pérez") == cat


def test_machinery_examples_cover_every_category():
    assert set(machinery.EXAMPLES) == set(machinery.CATEGORIES) - {machinery.OTHER}
