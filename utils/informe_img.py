"""Gráficos del informe descargable en PNG (matplotlib).

ECharts dibuja en el navegador, así que el informe arma sus imágenes acá,
con el mismo criterio visual de la app: fondo blanco, colores fijos, coma
decimal y etiquetas en blanco u oscuro según contraste. Se usa la API
orientada a objetos (sin ``pyplot``): la descarga corre en otro hilo.
"""
from __future__ import annotations

import io
import math
from typing import Sequence

from matplotlib.colors import to_hex, to_rgb
from matplotlib.figure import Figure
from matplotlib.patches import Polygon

from . import geo
from .charts import GRID, MUTED, TEXT, label_color, pct_label

DPI = 160
WIDTH = 8.0          # pulgadas (≈ 1280 px a 160 dpi)
LOST_RED = "#B10202"


def _png(fig: Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, facecolor="white", bbox_inches="tight",
                pad_inches=0.15)
    return buf.getvalue()


def _num(v: float) -> str:
    v = float(v)
    return str(int(v)) if v.is_integer() else f"{v:.1f}".replace(".", ",")


def _clean_axes(ax) -> None:
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#D5DBE1")
    ax.tick_params(colors=MUTED, length=0, labelsize=9)


def hbar(names: Sequence[str], values: Sequence[float], colors: Sequence[str] | str,
         *, title: str = "") -> bytes:
    """Barras horizontales en el orden dado (el primero arriba), con el valor
    y el % sobre el total al final de cada barra."""
    if isinstance(colors, str):
        colors = [colors] * len(names)
    total = float(sum(values)) or 1.0
    fig = Figure(figsize=(WIDTH, max(1.6, 0.42 * len(names) + 0.8)))
    ax = fig.add_subplot()
    y = list(range(len(names)))[::-1]
    ax.barh(y, values, color=list(colors), height=0.62)
    vmax = max(values, default=0) or 1
    for yi, v in zip(y, values):
        ax.text(v + vmax * 0.01, yi, f"{_num(v)} · {pct_label(v / total * 100)}",
                va="center", ha="left", fontsize=9, color=TEXT)
    _clean_axes(ax)
    ax.set_yticks(y, [str(n) for n in names], fontsize=9.5, color=TEXT)
    ax.set_xlim(0, vmax * 1.22)
    ax.xaxis.set_visible(False)
    ax.spines["bottom"].set_visible(False)
    if title:
        ax.set_title(title, loc="left", fontsize=11, color=TEXT, pad=10)
    return _png(fig)


def donut(names: Sequence[str], values: Sequence[float], colors: Sequence[str],
          *, title: str = "") -> bytes:
    """Torta con agujero: % con 1 decimal dentro de cada porción y leyenda
    al costado. Las porciones muy finas no llevan etiqueta (está en la tabla)."""
    total = float(sum(values)) or 1.0
    fig = Figure(figsize=(WIDTH, 4.2))
    ax = fig.add_subplot()
    wedges, _ = ax.pie(values, colors=list(colors), startangle=90, counterclock=False,
                       wedgeprops={"width": 0.45, "edgecolor": "white", "linewidth": 1})
    for w, v, c in zip(wedges, values, colors):
        if v / total < 0.04:
            continue
        ang = math.radians((w.theta1 + w.theta2) / 2)
        ax.text(0.775 * math.cos(ang), 0.775 * math.sin(ang), pct_label(v / total * 100),
                ha="center", va="center", fontsize=8.5, fontweight="bold",
                color=label_color(to_hex(c)))
    ax.legend(wedges, [f"{n} ({_num(v)})" for n, v in zip(names, values)],
              loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=9.5,
              labelcolor=TEXT)
    ax.set_aspect("equal")
    if title:
        ax.set_title(title, loc="left", fontsize=11, color=TEXT)
    return _png(fig)


def stacked_columns(categories: Sequence[str],
                    series: Sequence[tuple[str, Sequence[float], str]],
                    *, y_name: str = "", title: str = "") -> bytes:
    """Columnas apiladas con el valor de cada segmento (los segmentos en 0
    o muy finos no llevan etiqueta) y el total arriba."""
    fig = Figure(figsize=(WIDTH, 4.0))
    ax = fig.add_subplot()
    x = list(range(len(categories)))
    bottoms = [0.0] * len(categories)
    totals = [sum(float(vals[i]) for _, vals, _ in series) for i in x]
    vmax = max(totals, default=0) or 1
    for name, vals, color in series:
        vals = [float(v) for v in vals]
        ax.bar(x, vals, bottom=bottoms, color=color, width=0.6, label=name)
        for i, v in enumerate(vals):
            if v and v >= vmax * 0.05:
                ax.text(i, bottoms[i] + v / 2, _num(v), ha="center", va="center",
                        fontsize=9, color=label_color(color))
        bottoms = [b + v for b, v in zip(bottoms, vals)]
    for i, t in enumerate(totals):
        if t:
            ax.text(i, t + vmax * 0.015, _num(t), ha="center", va="bottom", fontsize=9,
                    color=TEXT, fontweight="bold")
    _clean_axes(ax)
    ax.set_xticks(x, [str(c) for c in categories], fontsize=9, color=TEXT,
                  rotation=30 if len(categories) > 5 else 0,
                  ha="right" if len(categories) > 5 else "center")
    ax.set_ylim(0, vmax * 1.12)
    ax.set_ylabel(y_name, color=MUTED, fontsize=9)
    ax.yaxis.grid(True, color=GRID)
    ax.set_axisbelow(True)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.22 if len(categories) > 5 else -0.1),
              ncol=len(series), frameon=False, fontsize=9.5)
    if title:
        ax.set_title(title, loc="left", fontsize=11, color=TEXT)
    return _png(fig)


def _mix(a: str, b: str, t: float) -> str:
    ra, rb = to_rgb(a), to_rgb(b)
    return to_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def province_map(counts: dict[str, int], *, unit: str = "negocios") -> bytes | None:
    """Mapa de las provincias con datos (gris → azul Cotear según la
    cantidad), con nombre y cantidad en cada una. None si ninguna se puede
    ubicar en el mapa."""
    features = {f["id"]: f for f in geo.load_provinces()["features"]}
    data = {z: n for z, n in counts.items() if z in features and n > 0}
    if not data:
        return None
    vmax = max(data.values())
    fig = Figure(figsize=(6.0, 7.0))
    ax = fig.add_subplot()
    lons, lats = [], []
    for zone, n in data.items():
        f = features[zone]
        color = _mix(geo.MAP_GRAY, geo.MAP_BLUE, n / vmax if vmax else 1)
        for poly in f["geometry"]["coordinates"]:
            ring = poly[0]
            ax.add_patch(Polygon(ring, closed=True, facecolor=color, edgecolor="white",
                                 linewidth=0.8))
            lons += [p[0] for p in ring]
            lats += [p[1] for p in ring]
        lon, lat = float(f["properties"]["lon"]), float(f["properties"]["lat"])
        ax.text(lon, lat, f"{zone}\n{n}", ha="center", va="center", fontsize=8,
                color=label_color(color), linespacing=1.15)
    pad = 0.6
    ax.set_xlim(min(lons) - pad, max(lons) + pad)
    ax.set_ylim(min(lats) - pad, max(lats) + pad)
    # Equirectangular corregida por la latitud media (aprox. a Mercator)
    ax.set_aspect(1 / math.cos(math.radians((min(lats) + max(lats)) / 2)))
    ax.axis("off")
    ax.set_title(f"Cantidad de {unit} por provincia", loc="left", fontsize=10, color=MUTED)
    return _png(fig)

