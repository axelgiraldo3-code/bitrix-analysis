"""Análisis geográfico: conteo de zonas (provincias) y mapa coroplético."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from .charts import pct_label
from .phone_ar import ZONE_FOREIGN, ZONE_UNKNOWN

OTHERS = "Otros"
NON_PROVINCE_ZONES = {ZONE_FOREIGN, ZONE_UNKNOWN, OTHERS}


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
            customdata=[pct_label(v) for v in data["pct"]],
            hovertemplate=(
                f"<b>%{{location}}</b><br>%{{z}} {unit}<br>%{{customdata}} del total<extra></extra>"
            ),
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
    """Texto con lo que no se puede ubicar en el mapa (Extranjero, Sin identificar)."""
    parts = []
    for zone in (ZONE_FOREIGN, ZONE_UNKNOWN):
        n = int(counts.loc[counts["Zona"] == zone, "Cantidad"].sum())
        if n and total:
            label = unit if n != 1 else unit.rstrip("s")
            parts.append(f"{zone}: {n} {label} ({pct_label(n / total * 100)})")
    return " · ".join(parts)
