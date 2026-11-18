"""Análisis geográfico: conteo de zonas (provincias y localidades), mapa
coroplético de provincias y mapa de burbujas por localidad."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from .charts import pct_label
from .phone_ar import ZONE_FOREIGN, ZONE_UNKNOWN, ZONE_UNVERIFIED, load_localities

OTHERS = "Otros"
NON_PROVINCE_ZONES = {ZONE_FOREIGN, ZONE_UNKNOWN, ZONE_UNVERIFIED, OTHERS}


def zone_counts(zones: pd.Series, threshold: float = 0.10) -> pd.DataFrame:
    """Tabla [Zona, Cantidad, %] ordenada de mayor a menor.

    Las zonas más chicas se agrupan en 'Otros' mientras la suma de las
    agrupadas quede por debajo de `threshold` (10 % por defecto). Sólo se
    agrupa si son al menos dos zonas; una zona sola conserva su nombre.
    """
    s = zones.fillna("").astype(str).str.strip().replace("", ZONE_UNKNOWN)
    counts = s.value_counts()
    if counts.empty:
        return pd.DataFrame(columns=["Zona", "Cantidad", "%"])
    total = int(counts.sum())

    grouped: list[str] = []
    acc = 0
    for zone, n in counts.sort_values(kind="stable").items():  # de menor a mayor
        if (acc + n) / total < threshold:
            grouped.append(zone)
            acc += n
        else:
            break

    if len(grouped) >= 2:
        counts = counts.drop(grouped)
        counts[OTHERS] = acc

    out = counts.sort_values(ascending=False, kind="stable").reset_index()
    out.columns = ["Zona", "Cantidad"]
    # 'Otros' siempre al final
    out = pd.concat([out[out["Zona"] != OTHERS], out[out["Zona"] == OTHERS]], ignore_index=True)
    out["%"] = (out["Cantidad"] / total * 100).round(1)
    return out


def top_province(zones: pd.Series) -> tuple[str, int]:
    """Provincia con más registros, sin contar Extranjero / Sin identificar."""
    s = zones.fillna("").astype(str).str.strip()
    s = s[(s != "") & ~s.isin(NON_PROVINCE_ZONES)]
    if s.empty:
        return "—", 0
    vc = s.value_counts()
    return str(vc.index[0]), int(vc.iloc[0])


# ---------------------------------------------------------------------------
# Mapa coroplético por provincia
# ---------------------------------------------------------------------------
_GEOJSON_PATH = Path(__file__).resolve().parent.parent / "data" / "provincias_argentina.geojson"

MAP_GRAY = "#C9CED2"
MAP_BLUE = "#01498E"
MAP_COLORSCALE = [[0.0, MAP_GRAY], [1.0, MAP_BLUE]]


@lru_cache(maxsize=1)
def load_provinces() -> dict:
    """GeoJSON de provincias (id = nombre de provincia; CABA incluida en
    Buenos Aires, igual que en las zonas de la app)."""
    with _GEOJSON_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _label_point(feature: dict) -> tuple[float, float]:
    p = feature["properties"]
    return float(p["lon"]), float(p["lat"])


def province_map(
    counts: pd.DataFrame, total: int, unit: str = "consultas", height: int = 520
) -> go.Figure:
    """Mapa coroplético de las provincias con datos.

    ``counts`` = [Zona, Cantidad] (sin agrupar en Otros). Sólo se dibujan las
    provincias con al menos un registro y el encuadre se ajusta a ellas.
    El % de cada etiqueta es sobre ``total`` (incluye Extranjero y Sin
    identificar, igual que la tabla).
    """
    geo = load_provinces()
    features = {f["id"]: f for f in geo["features"]}
    data = counts[counts["Zona"].isin(features) & (counts["Cantidad"] > 0)].copy()
    fig = go.Figure()
    if data.empty or total <= 0:
        return fig

    data["pct"] = data["Cantidad"] / total * 100
    vmax = float(data["Cantidad"].max())
    vmin = 0.0

    fig.add_trace(
        go.Choropleth(
            geojson=geo,
            locations=data["Zona"],
            z=data["Cantidad"],
            zmin=vmin,
            zmax=vmax,
            colorscale=MAP_COLORSCALE,
            marker_line_color="white",
            marker_line_width=1,
            # [provincia, %]: el nombre identifica la provincia al hacer clic
            customdata=[[z, pct_label(v)] for z, v in zip(data["Zona"], data["pct"])],
            hovertemplate=(
                f"<b>%{{location}}</b><br>%{{z}} {unit}<br>%{{customdata[1]}} del total"
                "<extra></extra>"
            ),
            # El clic no atenúa las demás provincias
            selected=dict(marker=dict(opacity=1)),
            unselected=dict(marker=dict(opacity=1)),
            colorbar=dict(
                title=dict(text=unit.capitalize()),
                thickness=12,
                len=0.6,
                tickformat="d",
                nticks=min(int(vmax) + 1, 6),
            ),
        )
    )

    # Etiquetas de % en el punto interior de cada provincia. El color del texto
    # se adapta al fondo: blanco sobre azul, gris oscuro sobre gris.
    pts = [_label_point(features[z]) for z in data["Zona"]]
    shade = (data["Cantidad"] - vmin) / (vmax - vmin) if vmax > vmin else data["Cantidad"] * 0 + 1
    text_colors = ["white" if s >= 0.45 else "#2B2F33" for s in shade]
    fig.add_trace(
        go.Scattergeo(
            lon=[p[0] for p in pts],
            lat=[p[1] for p in pts],
            text=[pct_label(v) for v in data["pct"]],
            mode="text",
            textfont=dict(size=12, color=text_colors, family="sans-serif"),
            hoverinfo="skip",
            showlegend=False,
        )
    )

    fig.update_geos(
        visible=False,
        fitbounds="locations",
        projection_type="mercator",
        bgcolor="rgba(0,0,0,0)",
    )
    fig.update_layout(
        height=height,
        margin=dict(t=10, b=10, l=10, r=10),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def outside_map_note(counts: pd.DataFrame, total: int, unit: str = "consultas") -> str:
    """Texto con lo que no se puede ubicar en el mapa (Extranjero, Sin verificar,
    Sin identificar)."""
    parts = []
    for zone in (ZONE_FOREIGN, ZONE_UNVERIFIED, ZONE_UNKNOWN):
        n = int(counts.loc[counts["Zona"] == zone, "Cantidad"].sum())
        if n and total:
            label = unit if n != 1 else unit.rstrip("s")
            parts.append(f"{zone}: {n} {label} ({pct_label(n / total * 100)})")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# Detalle por localidad (al hacer clic en una provincia)
# ---------------------------------------------------------------------------
_DEPTS_PATH = Path(__file__).resolve().parent.parent / "data" / "departamentos_ar.geojson"

MAP_BASE = "#EEF0F2"  # provincia elegida (departamentos con límites blancos)
MAP_NEIGHBOR = "#F7F8F9"  # provincias vecinas, atenuadas
NEIGHBOR_LINE = "#DDE1E5"
NEIGHBOR_TEXT = "#9AA3A9"
PROVINCE_LINE = "#AEB5BB"  # contorno de la provincia elegida
CALLOUT_LINE = "#7B868C"  # gris Cotear
TEXT_DARK = "#2B2F33"
TRANSPARENT = "rgba(0,0,0,0)"
BUBBLE_MIN_PX = 8  # diámetro de la burbuja más chica
BUBBLE_MAX_PX = 34  # diámetro de la más grande (área proporcional a la cantidad)
ARROW_PX = 8
LABEL_MIN_PCT = 3.0  # localidades más chicas: sólo tooltip (evita etiquetas encimadas)
LABEL_TOP = 8
# Callouts: los textos y las flechas se ubican en grados antes de dibujar, así
# que hace falta la escala del mapa. Con el encuadre a lo sumo
# FRAME_ASPECT_MAX veces más ancho que alto (en Mercator), el alto es el que
# limita en cualquier tarjeta y la escala es (alto en px) / (alto en grados),
# sin depender del ancho de la pantalla. Ancho por carácter, alto de renglón
# y separación entre la provincia y la columna de etiquetas, en px.
FRAME_ASPECT_MAX = 1.25
MARGIN_PX = 10  # márgenes de arriba y abajo de la figura
CHAR_PX = 7.0
LINE_PX = 19.0
GAP_PX = 14.0


@lru_cache(maxsize=1)
def locality_points() -> dict[tuple[str, str], tuple[float, float]]:
    """{(provincia, localidad): (lon, lat)} de las localidades con centroide.
    La clave lleva la provincia: hay nombres repetidos (Colón, La Paz)."""
    out: dict[tuple[str, str], tuple[float, float]] = {}
    for e in load_localities().values():
        if "lat" in e and "lon" in e:
            out[(str(e["provincia"]), str(e["localidad"]))] = (float(e["lon"]), float(e["lat"]))
    return out


@lru_cache(maxsize=1)
def load_departments() -> dict[str, dict]:
    """{provincia: FeatureCollection} de departamentos / partidos / comunas
    (IGN vía Georef; `scripts/build_departamentos.py`). Vacío si falta el
    archivo: el mapa cae a la provincia lisa."""
    if not _DEPTS_PATH.exists():
        return {}
    with _DEPTS_PATH.open("r", encoding="utf-8") as fh:
        src = json.load(fh)
    out: dict[str, dict] = {}
    for f in src.get("features", []):
        prov = f.get("properties", {}).get("provincia", "")
        out.setdefault(prov, {"type": "FeatureCollection", "features": []})["features"].append(f)
    return out


def locality_counts(zones: pd.Series, localities: pd.Series, province: str) -> pd.DataFrame:
    """Tabla [Localidad, Cantidad, %] de una provincia, de mayor a menor.

    El % es sobre el total de la provincia (distribución interna). Los números
    cuyo código no figura en el ENACOM quedan como 'Sin verificar', al final.
    """
    z = zones.fillna("").astype(str).str.strip()
    loc = localities.reindex(zones.index).fillna("").astype(str).str.strip()
    loc = loc.replace("", ZONE_UNVERIFIED)[z == province]
    counts = loc.value_counts()
    if counts.empty:
        return pd.DataFrame(columns=["Localidad", "Cantidad", "%"])
    total = int(counts.sum())
    out = counts.sort_values(ascending=False, kind="stable").reset_index()
    out.columns = ["Localidad", "Cantidad"]
    out = pd.concat(
        [out[out["Localidad"] != ZONE_UNVERIFIED], out[out["Localidad"] == ZONE_UNVERIFIED]],
        ignore_index=True,
    )
    out["%"] = (out["Cantidad"] / total * 100).round(1)
    return out


# --- Proyección y callouts ----------------------------------------------------
def _merc_y(lat: float) -> float:
    """Latitud → y de Mercator (en grados), para que las distancias verticales
    se midan como se ven en pantalla."""
    return math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def _merc_lat(y: float) -> float:
    return math.degrees(2 * math.atan(math.exp(math.radians(y))) - math.pi / 2)


def _rings(feature: dict) -> list[list[list[float]]]:
    g = feature["geometry"]
    polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    return [p[0] for p in polys]


def _bbox(feature: dict) -> tuple[float, float, float, float]:
    """(lon mín, y mín, lon máx, y máx) con y en Mercator."""
    pts = [pt for ring in _rings(feature) for pt in ring]
    xs, ys = [p[0] for p in pts], [_merc_y(p[1]) for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _spread(wanted: list[float], step: float, low: float, high: float) -> list[float]:
    """Posiciones verticales (de arriba hacia abajo) lo más cerca posible de
    ``wanted`` con al menos ``step`` entre sí, dentro de [low, high]."""
    ys: list[float] = []
    for w in wanted:  # de arriba hacia abajo, empujando hacia abajo
        ys.append(min(w, high, ys[-1] - step) if ys else min(w, high))
    floor = low
    for i in range(len(ys) - 1, -1, -1):  # de abajo hacia arriba, empujando hacia arriba
        ys[i] = max(ys[i], floor)
        floor = ys[i] + step
    return ys


def _callout_layout(
    bubbles: list[tuple[float, float, int]],
    box: tuple[float, float, float, float],
    height: int,
) -> tuple[list[tuple[float, float, str]], tuple[float, float, float, float], float]:
    """Ubica las etiquetas en columnas a los costados de la provincia.

    ``bubbles`` = [(lon, y Mercator, largo del texto)]. Cada burbuja va a la
    columna del lado más cercano; dentro de la columna las etiquetas se
    ordenan por altura y se separan un renglón. Devuelve
    ([(lon, y, lado)] de cada etiqueta, encuadre (x0, y0, x1, y1) y escala en
    px por grado)."""
    x0, y0, x1, y1 = box
    w, h = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    sides = ["left" if lon < x0 + w / 2 else "right" for lon, _, _ in bubbles]
    need = {
        s: max((n for (_, _, n), side in zip(bubbles, sides) if side == s), default=0) * CHAR_PX
        for s in ("left", "right")
    }
    map_h = max(height - 2 * MARGIN_PX, 100)
    margin_y = h * 0.06
    pad = {s: (w * 0.25 if need[s] else w * 0.04) for s in need}
    span_y = h + 2 * margin_y
    for _ in range(8):  # el ancho de las columnas depende de la escala y viceversa
        span_x = w + pad["left"] + pad["right"]
        # Un encuadre muy ancho se completa con aire arriba y abajo
        span_y = max(h + 2 * margin_y, span_x / FRAME_ASPECT_MAX)
        scale = map_h / span_y  # px por grado
        pad = {s: ((need[s] + 2 * GAP_PX) / scale if need[s] else w * 0.04) for s in need}
    margin_y = (span_y - h) / 2
    step = LINE_PX / scale
    gap = GAP_PX / scale

    labels: list[tuple[float, float, str] | None] = [None] * len(bubbles)
    for side in ("left", "right"):
        idx = [i for i, s in enumerate(sides) if s == side]
        idx.sort(key=lambda i: -bubbles[i][1])
        ys = _spread([bubbles[i][1] for i in idx], step, y0 - margin_y / 2, y1 + margin_y / 2)
        lon = x0 - gap if side == "left" else x1 + gap
        for i, y in zip(idx, ys):
            labels[i] = (lon, y, side)
    frame = (x0 - pad["left"], y0 - margin_y, x1 + pad["right"], y1 + margin_y)
    return [lab for lab in labels if lab], frame, scale


def _arrow(
    lx: float, ly: float, bx: float, by: float, radius_px: float, scale: float
) -> tuple[float, float, float]:
    """Punta de flecha de la etiqueta (lx, ly) a la burbuja (bx, by), en lon e
    y Mercator: (lon, y, ángulo en grados horario desde arriba). El centro del
    marcador queda a radio + media flecha del centro de la burbuja, así la
    punta toca su borde."""
    dx, dy = bx - lx, by - ly
    dist = math.hypot(dx, dy) or 1e-9
    back = (radius_px + ARROW_PX / 2) / scale
    return bx - dx / dist * back, by - dy / dist * back, math.degrees(math.atan2(dx, dy))


def locality_map(
    counts: pd.DataFrame, province: str, unit: str = "consultas", height: int = 520
) -> go.Figure:
    """Mapa político de la provincia con una burbuja por localidad.

    ``counts`` = [Localidad, Cantidad] de ``locality_counts``. Debajo, los
    departamentos de la provincia (gris único, límites blancos, nombre en el
    tooltip) y las provincias vecinas atenuadas con su nombre. Cada burbuja
    tiene tamaño (área) y color (gris → azul Cotear) según la cantidad; las
    principales llevan un callout "**Rosario** 40,0 %" en columnas a los
    costados, con una flecha que toca el borde de la burbuja. Las localidades
    sin centroide (o 'Sin verificar') no se dibujan: quedan en el ranking y en
    la tabla.
    """
    geo = load_provinces()
    features = {f["id"]: f for f in geo["features"]}
    fig = go.Figure()
    if province not in features or counts.empty:
        return fig
    pts = locality_points()
    total = int(counts["Cantidad"].sum())
    data = counts[
        counts["Localidad"].map(lambda name: (province, name) in pts) & (counts["Cantidad"] > 0)
    ].copy()
    if data.empty or total <= 0:
        return fig

    data["pct"] = data["Cantidad"] / total * 100
    vmax = float(data["Cantidad"].max())
    data["lon"] = [pts[(province, n)][0] for n in data["Localidad"]]
    data["lat"] = [pts[(province, n)][1] for n in data["Localidad"]]
    data["d"] = [max(BUBBLE_MIN_PX, BUBBLE_MAX_PX * math.sqrt(v / vmax)) for v in data["Cantidad"]]
    top = data[data["pct"] >= LABEL_MIN_PCT].head(LABEL_TOP)
    texts = [f"<b>{n}</b> {pct_label(p)}" for n, p in zip(top["Localidad"], top["pct"])]
    plain_len = [len(f"{n} {pct_label(p)}") for n, p in zip(top["Localidad"], top["pct"])]
    labels, (fx0, fy0, fx1, fy1), scale = _callout_layout(
        [(lon, _merc_y(lat), n) for lon, lat, n in zip(top["lon"], top["lat"], plain_len)],
        _bbox(features[province]),
        height,
    )
    step = LINE_PX / scale

    # 1. Provincias vecinas, atenuadas (el encuadre recorta lo que sobra)
    others = [p for p in features if p != province]
    fig.add_trace(
        go.Choropleth(
            geojson=geo,
            locations=others,
            z=[0] * len(others),
            colorscale=[[0.0, MAP_NEIGHBOR], [1.0, MAP_NEIGHBOR]],
            showscale=False,
            marker_line_color=NEIGHBOR_LINE,
            marker_line_width=1,
            hoverinfo="skip",
        )
    )
    # 2. Departamentos de la provincia (o la provincia lisa si faltan)
    depts = load_departments().get(province)
    if depts and depts["features"]:
        fig.add_trace(
            go.Choropleth(
                geojson=depts,
                locations=[f["id"] for f in depts["features"]],
                z=[0] * len(depts["features"]),
                colorscale=[[0.0, MAP_BASE], [1.0, MAP_BASE]],
                showscale=False,
                marker_line_color="white",
                marker_line_width=0.8,
                customdata=[f["properties"]["nombre"] for f in depts["features"]],
                hovertemplate="%{customdata}<extra></extra>",
            )
        )
    else:
        fig.add_trace(
            go.Choropleth(
                geojson=geo,
                locations=[province],
                z=[0],
                colorscale=[[0.0, MAP_BASE], [1.0, MAP_BASE]],
                showscale=False,
                marker_line_width=0,
                hoverinfo="skip",
            )
        )
    # 3. Contorno de la provincia, encima de los departamentos
    fig.add_trace(
        go.Choropleth(
            geojson=geo,
            locations=[province],
            z=[0],
            colorscale=[[0.0, TRANSPARENT], [1.0, TRANSPARENT]],
            showscale=False,
            marker_line_color=PROVINCE_LINE,
            marker_line_width=1.2,
            hoverinfo="skip",
        )
    )
    # 4. Líneas de los callouts (debajo de las burbujas: llegan hasta su borde)
    line_lon: list[float | None] = []
    line_lat: list[float | None] = []
    for (lx, ly, _), bx, by in zip(labels, top["lon"], top["lat"]):
        line_lon += [lx, bx, None]
        line_lat += [_merc_lat(ly), by, None]
    if labels:
        fig.add_trace(
            go.Scattergeo(
                lon=line_lon,
                lat=line_lat,
                mode="lines",
                line=dict(color=CALLOUT_LINE, width=1),
                hoverinfo="skip",
                showlegend=False,
            )
        )
    # 5. Burbujas, de mayor a menor (las chicas quedan encima y se pueden señalar)
    fig.add_trace(
        go.Scattergeo(
            lon=data["lon"],
            lat=data["lat"],
            mode="markers",
            marker=dict(
                size=data["d"],
                color=data["Cantidad"],
                cmin=0,
                cmax=vmax,
                colorscale=MAP_COLORSCALE,
                line=dict(color="white", width=1),
                opacity=1,
                # Sin barra de color: los callouts y el tooltip dan los valores,
                # y la barra le quitaría ancho al encuadre (ver FRAME_ASPECT_MAX)
                showscale=False,
            ),
            customdata=[
                [name, int(n), pct_label(p)]
                for name, n, p in zip(data["Localidad"], data["Cantidad"], data["pct"])
            ],
            hovertemplate=(
                f"<b>%{{customdata[0]}}</b><br>%{{customdata[1]}} {unit}"
                f"<br>%{{customdata[2]}} de {province}<extra></extra>"
            ),
            showlegend=False,
        )
    )
    if labels:
        # 6. Puntas de flecha, apoyadas en el borde de cada burbuja. Ángulo y
        # posición se calculan acá: en mapas geo Plotly ignora angleref y
        # aplica el standoff hacia adelante
        arrows = [
            _arrow(lx, ly, bx, _merc_y(by), d / 2, scale)
            for (lx, ly, _), bx, by, d in zip(labels, top["lon"], top["lat"], top["d"])
        ]
        fig.add_trace(
            go.Scattergeo(
                lon=[a[0] for a in arrows],
                lat=[_merc_lat(a[1]) for a in arrows],
                mode="markers",
                marker=dict(
                    symbol="arrow",
                    angle=[a[2] for a in arrows],
                    size=ARROW_PX,
                    color=CALLOUT_LINE,
                    line=dict(width=0),
                ),
                hoverinfo="skip",
                showlegend=False,
            )
        )
        # 7. Textos de los callouts, hacia afuera de la provincia
        for side, position in (("left", "middle left"), ("right", "middle right")):
            sel = [i for i, lab in enumerate(labels) if lab[2] == side]
            if not sel:
                continue
            fig.add_trace(
                go.Scattergeo(
                    lon=[labels[i][0] for i in sel],
                    lat=[_merc_lat(labels[i][1]) for i in sel],
                    mode="text",
                    text=[texts[i] for i in sel],
                    textposition=position,
                    textfont=dict(size=12, color=TEXT_DARK, family="sans-serif"),
                    hoverinfo="skip",
                    showlegend=False,
                )
            )
    # 8. Nombres de las vecinas visibles, lejos de las columnas de etiquetas
    names = []
    for p in others:
        lon, lat = _label_point(features[p])
        y = _merc_y(lat)
        # El nombre entero dentro del encuadre (si no, se corta en el borde)
        half_w = len(p) * CHAR_PX * 0.5 / scale
        inside = fx0 + half_w <= lon <= fx1 - half_w and fy0 + step <= y <= fy1 - step
        crowded = any(
            abs(y - ly) < 1.5 * step and abs(lon - lx) < (fx1 - fx0) * 0.3 for lx, ly, _ in labels
        )
        if inside and not crowded:
            names.append((p, lon, lat))
    if names:
        fig.add_trace(
            go.Scattergeo(
                lon=[n[1] for n in names],
                lat=[n[2] for n in names],
                mode="text",
                text=[n[0] for n in names],
                textfont=dict(size=11, color=NEIGHBOR_TEXT, family="sans-serif"),
                hoverinfo="skip",
                showlegend=False,
            )
        )

    fig.update_geos(
        visible=False,
        fitbounds=False,
        projection_type="mercator",
        lonaxis_range=[fx0, fx1],
        lataxis_range=[_merc_lat(fy0), _merc_lat(fy1)],
        bgcolor="rgba(0,0,0,0)",
    )
    fig.update_layout(
        height=height,
        margin=dict(t=10, b=10, l=10, r=10),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def outside_locality_note(counts: pd.DataFrame, province: str, unit: str = "consultas") -> str:
    """Texto con lo de la provincia que no se puede ubicar en el mapa de
    localidades ('Sin verificar' o sin centroide)."""
    pts = locality_points()
    off = counts[~counts["Localidad"].map(lambda name: (province, name) in pts)]
    n = int(off["Cantidad"].sum())
    if not n:
        return ""
    label = unit if n != 1 else unit.rstrip("s")
    names = ", ".join(off["Localidad"].tolist())
    return f"{n} {label} sin ubicar ({names})"
