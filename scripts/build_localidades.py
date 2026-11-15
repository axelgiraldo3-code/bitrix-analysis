"""Genera `data/localidades_ar.json` desde la numeración geográfica del ENACOM.

Uso local (una vez, o cuando el ENACOM publique un archivo nuevo):
    python -m scripts.build_localidades ["data/Numeración Geográfica.xlsx"]

1. Lee el xlsx con la librería estándar (zip + XML, sin openpyxl) y saca los
   pares únicos (INDICATIVO, LOCALIDAD). En el ENACOM cada indicativo tiene
   una sola localidad: la cabecera del área local. El BLOQUE no se usa.
2. Limpia el nombre ("JUNIN (PROV.  BUENOS AIRES)" → "Junin") y toma la
   provincia de `data/codigos_area_argentina.json` (11 → Buenos Aires).
3. Busca el nombre con tildes y el centroide en la API pública Georef
   (apis.datos.gob.ar). Sólo se envían nombres de localidades. Lo que Georef
   no encuentra o ubica mal se corrige en ``OVERRIDES``.

Salida: {"341": {"localidad": "Rosario", "provincia": "Santa Fe",
"lat": -32.95, "lon": -60.65}, ...}
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent.parent / "data"
XLSX = DATA / "Numeración Geográfica.xlsx"
CODES = DATA / "codigos_area_argentina.json"
OUT = DATA / "localidades_ar.json"
GEOREF = "https://apis.datos.gob.ar/georef/api/localidades"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# Nombres de provincia de la app → nombre en Georef
GEOREF_PROVINCE = {
    "Tierra del Fuego": "Tierra del Fuego, Antártida e Islas del Atlántico Sur",
}
LOWER_WORDS = {"de", "del", "la", "las", "los", "y", "el"}
ACRONYMS = {"AMBA"}

# indicativo → (nombre, lat, lon) cuando Georef no encuentra la localidad o
# la confunde con otra (revisar los "~" y "!" que imprime el script)
OVERRIDES: dict[str, tuple[str, float, float]] = {
    # AMBA: centro de la Ciudad de Buenos Aires
    "11": ("AMBA", -34.6037, -58.3816),
    "2242": ("Lezama", -35.8711, -57.8958),
    "2264": ("La Dulce", -38.3167, -59.2000),  # Georef: Arroyo Dulce (Salto)
    "2271": ("Monte", -35.4397, -58.8078),  # San Miguel del Monte; Georef: Monte Grande
    "2344": ("Saladillo", -35.6383, -59.7786),
    "2646": ("San Agustín del Valle Fértil", -30.6339, -67.4681),
    "2933": ("Huanguelén", -37.0333, -61.9333),
    "3327": ("López Camelo", -34.4056, -58.6919),
    "3489": ("Campana", -34.1633, -58.9592),
    "3522": ("Villa de María de Río Seco", -29.9047, -63.7258),
    "3543": ("Argüello", -31.3467, -64.2600),
}
# indicativo → nombre con tildes, cuando Georef ubica bien pero con otro nombre
# ("San Carlos de Bolívar") y se prefiere el del ENACOM
NAMES = {
    "2267": "General Madariaga",
    "2286": "General Lamadrid",
    "2314": "Bolívar",
    "2647": "Jáchal",
    "2657": "Villa Mercedes",
    "2902": "Río Turbio",
    "2962": "San Julián",
    "3387": "Bouchard",
    "3781": "Caá Catí",
    "383": "Catamarca",
    "3845": "Loreto",
    "3856": "Ojo de Agua",
    "3862": "Trancas",
    "3876": "Metán",
    "3878": "Orán",
    "3894": "Burruyacú",
}


def _cell_col(ref: str) -> str:
    return "".join(ch for ch in ref if ch.isalpha())


def read_pairs(path: Path) -> dict[str, str]:
    """{indicativo: LOCALIDAD} desde la primera hoja del xlsx."""
    z = zipfile.ZipFile(path)
    strings = [
        "".join(t.text or "" for t in si.iter(NS + "t"))
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(NS + "si")
    ]
    pairs: dict[str, str] = {}
    rows = ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter(NS + "row")
    header: dict[str, str] | None = None
    for row in rows:
        vals: dict[str, str] = {}
        for c in row.findall(NS + "c"):
            v = c.find(NS + "v")
            val = v.text if v is not None and v.text else ""
            if c.get("t") == "s" and val:
                val = strings[int(val)]
            vals[_cell_col(c.get("r", ""))] = val.strip()
        if header is None:
            header = {name: col for col, name in vals.items()}
            continue
        ind = vals.get(header["INDICATIVO"], "")
        loc = vals.get(header["LOCALIDAD"], "")
        if ind.isdigit() and loc:
            pairs.setdefault(ind, loc)
    return pairs


def clean_name(raw: str) -> str:
    """'JUNIN (PROV.  BUENOS AIRES)' → 'Junin'; 'AMBA' queda igual."""
    name = re.sub(r"\s*\(.*?\)\s*", " ", raw).strip()
    name = re.sub(r"\s+", " ", name)
    words = []
    for i, w in enumerate(name.split(" ")):
        if w.upper() in ACRONYMS:
            words.append(w.upper())
        elif i > 0 and w.lower() in LOWER_WORDS:
            words.append(w.lower())
        else:
            words.append(w.capitalize())
    return " ".join(words)


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower().strip()


def georef(items: list[tuple[str, str, str]]) -> dict[str, tuple[str, float, float]]:
    """Consulta masiva a Georef: [(indicativo, nombre, provincia)] →
    {indicativo: (nombre con tildes, lat, lon)} de los encontrados."""
    body = {
        "localidades": [
            {
                "nombre": name,
                "provincia": GEOREF_PROVINCE.get(prov, prov),
                "max": 5,
                "campos": "nombre,centroide",
            }
            for _, name, prov in items
        ]
    }
    r = requests.post(GEOREF, json=body, timeout=60)
    r.raise_for_status()
    out: dict[str, tuple[str, float, float]] = {}
    for (ind, name, _), res in zip(items, r.json()["resultados"]):
        found = res.get("localidades") or []
        if not found:
            continue
        # Preferir coincidencia exacta del nombre (sin tildes); si no, la primera
        exact = [f for f in found if _fold(f["nombre"]) == _fold(name)]
        best = (exact or found)[0]
        if not exact and ind not in NAMES:
            print(f"~ {ind} {name}: sin coincidencia exacta, se usa {best['nombre']!r}")
        c = best["centroide"]
        out[ind] = (best["nombre"] if exact else name, float(c["lat"]), float(c["lon"]))
    return out


def _province_shapes() -> dict[str, list[list[list[float]]]]:
    """{provincia: [anillo exterior, ...]} del geojson de la app."""
    geo = json.loads((DATA / "provincias_argentina.geojson").read_text(encoding="utf-8"))
    out: dict[str, list] = {}
    for f in geo["features"]:
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        out[f["id"]] = [p[0] for p in polys]
    return out


def _inside(lon: float, lat: float, rings: list[list[list[float]]]) -> bool:
    """Punto en alguno de los polígonos (ray casting; alcanza como control)."""
    for ring in rings:
        hit = False
        for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
            if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                hit = not hit
        if hit:
            return True
    return False


def main() -> None:
    xlsx = Path(sys.argv[1]) if len(sys.argv) > 1 else XLSX
    pairs = read_pairs(xlsx)
    codes = json.loads(CODES.read_text(encoding="utf-8"))
    codes = codes.get("codes", codes)

    items = []
    for ind, raw in sorted(pairs.items()):
        prov = codes.get(ind, "")
        if not prov:
            print(f"! {ind} {raw}: sin provincia en codigos_area_argentina.json")
            continue
        items.append((ind, clean_name(raw), prov))

    pending = [it for it in items if it[0] not in OVERRIDES]
    found: dict[str, tuple[str, float, float]] = {}
    for i in range(0, len(pending), 100):  # Georef admite lotes; vamos de a 100
        found.update(georef(pending[i : i + 100]))
    found.update(OVERRIDES)

    shapes = _province_shapes()
    result: dict[str, dict] = {}
    missing = []
    for ind, name, prov in items:
        hit = found.get(ind)
        entry: dict = {"localidad": NAMES.get(ind, hit[0] if hit else name), "provincia": prov}
        if hit:
            entry["lat"], entry["lon"] = round(hit[1], 4), round(hit[2], 4)
            if prov in shapes and not _inside(hit[2], hit[1], shapes[prov]):
                print(f"! {ind} {entry['localidad']}: el punto cae fuera de {prov}")
        else:
            missing.append(f"{ind} {name} ({prov})")
        result[ind] = entry

    OUT.write_text(
        json.dumps(
            {
                "descripcion": "Indicativo (código de área) → localidad cabecera, provincia "
                "y centroide. Generado con scripts/build_localidades.py.",
                "fuente": "ENACOM, Numeración Geográfica; coordenadas: Georef (datos.gob.ar)",
                "codes": result,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"{len(result)} indicativos escritos en {OUT.name}; sin coordenadas: {len(missing)}")
    for m in missing:
        print("  -", m)


if __name__ == "__main__":
    main()
