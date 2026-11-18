"""Genera `data/departamentos_ar.geojson` (departamentos, partidos y comunas)
para el mapa político de la provincia elegida.

Uso local (una vez, o para actualizar los límites):
    python -m scripts.build_departamentos

Descarga `departamentos.geojson` de Georef (datos.gob.ar, fuente IGN) y:
1. Pasa la provincia al nombre de la app: las comunas de CABA van a
   "Buenos Aires" (como en las zonas) y "Tierra del Fuego, Antártida e Islas
   del Atlántico Sur" a "Tierra del Fuego".
2. Descarta los departamentos cuyo centroide cae fuera del recuadro de su
   provincia en `provincias_argentina.geojson` (Antártida e islas del
   Atlántico Sur, que el mapa de la app no dibuja).
3. Redondea las coordenadas a 3 decimales (~100 m), quita puntos repetidos y
   orienta los anillos como el geojson de la app (exterior en sentido
   horario, huecos al revés): con la orientación invertida Plotly rellena
   todo el globo.

Salida: FeatureCollection con id = id de Georef y properties
{nombre, provincia}.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent.parent / "data"
URL = "https://infra.datos.gob.ar/georef/departamentos.geojson"
OUT = DATA / "departamentos_ar.geojson"
PROVINCE_NAMES = {
    "Ciudad Autónoma de Buenos Aires": "Buenos Aires",
    "Tierra del Fuego, Antártida e Islas del Atlántico Sur": "Tierra del Fuego",
}
DECIMALS = 3


def _signed_area(ring: list[list[float]]) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1])) / 2


def _clean_ring(ring: list[list[float]], clockwise: bool) -> list[list[float]] | None:
    pts: list[list[float]] = []
    for x, y in ring:
        p = [round(x, DECIMALS), round(y, DECIMALS)]
        if not pts or p != pts[-1]:
            pts.append(p)
    if pts and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) < 3:
        return None
    if (_signed_area(pts) < 0) != clockwise:
        pts.reverse()
    return pts + [pts[0]]


def _clean_polygon(poly: list) -> list | None:
    exterior = _clean_ring(poly[0], clockwise=True)
    if exterior is None:
        return None
    holes = [h for h in (_clean_ring(r, clockwise=False) for r in poly[1:]) if h]
    return [exterior, *holes]


def _bboxes() -> dict[str, tuple[float, float, float, float]]:
    geo = json.loads((DATA / "provincias_argentina.geojson").read_text(encoding="utf-8"))
    out = {}
    for f in geo["features"]:
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        xs = [x for p in polys for x, _ in p[0]]
        ys = [y for p in polys for _, y in p[0]]
        out[f["id"]] = (min(xs), min(ys), max(xs), max(ys))
    return out


def main() -> None:
    r = requests.get(URL, timeout=120)
    r.raise_for_status()
    src = r.json()
    boxes = _bboxes()
    features, dropped = [], []
    for f in src["features"]:
        p = f["properties"]
        prov = PROVINCE_NAMES.get(p["provincia"]["nombre"], p["provincia"]["nombre"])
        c = p.get("centroide") or {}
        box = boxes.get(prov)
        if box is None:
            dropped.append(f"{p['nombre']} ({prov}: provincia desconocida)")
            continue
        x0, y0, x1, y1 = box
        if not (
            x0 - 0.5 <= c.get("lon", 0) <= x1 + 0.5 and y0 - 0.5 <= c.get("lat", 0) <= y1 + 0.5
        ):
            dropped.append(f"{p['nombre']} ({prov}: fuera del mapa)")
            continue
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        polys = [q for q in (_clean_polygon(poly) for poly in polys) if q]
        if not polys:
            dropped.append(f"{p['nombre']} ({prov}: sin geometría)")
            continue
        geometry = (
            {"type": "Polygon", "coordinates": polys[0]}
            if len(polys) == 1
            else {"type": "MultiPolygon", "coordinates": polys}
        )
        features.append(
            {
                "type": "Feature",
                "id": str(p["id"]),
                "properties": {"nombre": p["nombre"], "provincia": prov},
                "geometry": geometry,
            }
        )
    OUT.write_text(
        json.dumps(
            {"type": "FeatureCollection", "features": features},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"{len(features)} departamentos en {OUT.name} ({OUT.stat().st_size // 1024} KB)")
    for d in dropped:
        print("  - descartado:", d)


if __name__ == "__main__":
    main()
