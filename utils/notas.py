"""Notas Markdown al estilo Obsidian para la página "Ayuda" (funciones puras).

Las notas viven en ``docs/ayuda/`` y se pueden editar desde un vault de
Obsidian. Al mostrarlas en la app:

- ``[[Nota]]``, ``[[Nota#Título]]`` y ``[[Nota|texto]]`` pasan a enlaces a la
  sección de esa nota dentro de la página (``#nota-<slug>``).
- ``{{nombre}}`` se reemplaza por un valor tomado del código (plazos, meses de
  tendencia, etc.); si el nombre no existe, queda tal cual.
- Los títulos bajan dos niveles (``##`` → ``####``) para no competir con los
  títulos de grupo de la app.
- Los callouts (``> [!info] Título``) quedan como cita con el título en negrita.
- El frontmatter YAML se descarta.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#([^\]|]*))?(?:\|([^\]]+))?\]\]")
PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
FRONTMATTER = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.S)
HEADING = re.compile(r"^(#{1,6}) ", re.M)
CALLOUT = re.compile(r"^> ?\[!\w+\][+-]? ?(.*)$", re.M)
ANCHOR_PREFIX = "nota-"


def slug(name: str) -> str:
    """'Navegación y filtros' → 'navegacion-y-filtros'."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def anchor(name: str) -> str:
    return ANCHOR_PREFIX + slug(name)


def load_notes(folder: Path) -> dict[str, str]:
    """{nombre de la nota (archivo sin .md): texto sin frontmatter}."""
    return {p.stem: FRONTMATTER.sub("", p.read_text(encoding="utf-8"))
            for p in sorted(Path(folder).glob("*.md"))}


def linked_notes(text: str) -> list[str]:
    """Notas enlazadas con [[...]], en orden de aparición y sin repetir."""
    seen: list[str] = []
    for m in WIKILINK.finditer(text):
        name = m[1].strip()
        if name not in seen:
            seen.append(name)
    return seen


def order(notes: dict[str, str], index: str) -> list[str]:
    """Notas a mostrar debajo del índice: primero las que enlaza el índice,
    en ese orden; después las que no enlaza, alfabéticamente."""
    linked = [n for n in linked_notes(notes.get(index, "")) if n in notes and n != index]
    rest = sorted(n for n in notes if n != index and n not in linked)
    return linked + rest


def placeholders(text: str) -> set[str]:
    return {m[1] for m in PLACEHOLDER.finditer(text)}


def render(text: str, values: dict[str, object], demote: int = 2) -> str:
    """Texto de la nota listo para ``st.markdown``."""
    text = PLACEHOLDER.sub(lambda m: str(values.get(m[1], m[0])), text)
    text = WIKILINK.sub(lambda m: f"[{(m[3] or m[1]).strip()}](#{anchor(m[1].strip())})", text)
    text = HEADING.sub(lambda m: "#" * min(6, len(m[1]) + demote) + " ", text)
    text = CALLOUT.sub(lambda m: f"> **{m[1].strip()}**" if m[1].strip() else ">", text)
    return text.strip()
