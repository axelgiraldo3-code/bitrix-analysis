"""Opciones de Apache ECharts para ``st.echarts_chart`` (funciones puras).

Todos los gráficos comparten: tooltip al pasar el mouse, sin controles de
zoom, y un único ícono para descargar la imagen en PNG.
"""
from __future__ import annotations

from typing import Sequence

from .branding import COTEAR_BLUE, COTEAR_GRAY

TEXT = "#2B2F33"
MUTED = "#6B7785"
GRID = "#EEF1F4"
DARK_LABEL = "#1A1D21"

# Paleta para series sin color propio (ej. motivos de baja)
SERIES_COLORS = [COTEAR_BLUE, "#E67E22", "#11734B", "#39A8EF", "#B10202",
                 "#5A3286", "#C9A400", "#2BB3A3", "#D35FB7", COTEAR_GRAY]


# ---------------------------------------------------------------------------
# Contraste de etiquetas
# ---------------------------------------------------------------------------
def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    def ch(c: int) -> float:
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(int(h[i:i + 2], 16)) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def label_color(fill: str) -> str:
    """Blanco u oscuro, el que más se lea sobre ``fill`` (WCAG)."""
    return "#FFFFFF" if contrast_ratio(fill, "#FFFFFF") >= contrast_ratio(fill, DARK_LABEL) \
        else DARK_LABEL


def series_color(i: int) -> str:
    return SERIES_COLORS[i % len(SERIES_COLORS)]


# ---------------------------------------------------------------------------
# Piezas comunes
# ---------------------------------------------------------------------------
def _toolbox(filename: str) -> dict:
    return {
        "right": 0, "top": 0, "itemSize": 14,
        "iconStyle": {"borderColor": "#9AA4AD"},
        "emphasis": {"iconStyle": {"borderColor": COTEAR_BLUE}},
        "feature": {"saveAsImage": {
            "title": "Descargar PNG", "name": filename, "pixelRatio": 2,
            "backgroundColor": "#FFFFFF",
        }},
    }


def _base(filename: str) -> dict:
    return {
        "animationDuration": 500,
        "textStyle": {"color": TEXT},
        "toolbox": _toolbox(filename),
        "tooltip": {"confine": True},
    }


def _legend(**kw) -> dict:
    return {"type": "scroll", "icon": "roundRect", "itemWidth": 12, "itemHeight": 12,
            "textStyle": {"color": TEXT, "fontSize": 12}, **kw}


def legend_rows(names: Sequence[str], width: int, max_label: int = 0) -> int:
    """Filas que ocupa una leyenda horizontal en ``width`` px (estimado:
    ~6.6 px por carácter a 12 px + ícono y separación)."""
    rows, used = 1, 0
    for n in names:
        chars = min(len(str(n)), max_label // 7) if max_label else len(str(n))
        item = 12 + 5 + 6.6 * chars + 12
        if used and used + item > width:
            rows, used = rows + 1, 0
        used += item
    return rows


def _value_axis(name: str = "", percent: bool = False) -> dict:
    axis = {"type": "value", "name": name, "nameTextStyle": {"color": MUTED},
            "axisLabel": {"color": MUTED}, "splitLine": {"lineStyle": {"color": GRID}}}
    if percent:
        axis.update(max=100, axisLabel={"color": MUTED, "formatter": "{value}%"})
    return axis


# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------
def donut(names: Sequence[str], values: Sequence[float], colors: Sequence[str],
          filename: str, *, width: int = 520, height: int = 380,
          label_width: int = 150) -> dict:
    """Torta con agujero: porcentaje dentro de cada porción y leyenda abajo
    (las etiquetas largas se cortan; el texto completo aparece en el
    tooltip). ``width``/``height`` aproximan el tamaño en px para ubicar la
    leyenda sin que tape la torta."""
    data = [{"name": str(n), "value": float(v),
             "itemStyle": {"color": c},
             "label": {"color": label_color(c)}}
            for n, v, c in zip(names, values, colors)]
    rows = legend_rows(names, width - 16, label_width)
    legend_h = rows * 22 + 6
    free_h = height - legend_h - 24
    radius = max(60, min(width - 40, free_h) // 2)
    return {
        **_base(filename),
        "tooltip": {"trigger": "item", "confine": True, "formatter": "{b}<br/>{c} ({d}%)"},
        "legend": _legend(type="plain", bottom=0, left="center",
                          textStyle={"color": TEXT, "fontSize": 12, "width": label_width,
                                     "overflow": "truncate"},
                          tooltip={"show": True}),
        "series": [{
            "type": "pie", "radius": [int(radius * 0.58), radius],
            "center": ["50%", 18 + free_h // 2],
            "avoidLabelOverlap": True,
            "itemStyle": {"borderColor": "#FFFFFF", "borderWidth": 1},
            "label": {"show": True, "position": "inside", "formatter": "{d}%",
                      "fontSize": 11, "fontWeight": "bold"},
            "labelLayout": {"hideOverlap": True},
            "emphasis": {"scaleSize": 6},
            "data": data,
        }],
    }


def hbar(names: Sequence[str], values: Sequence[float], colors: Sequence[str] | str,
         filename: str, *, unit: str = "", label_width: int = 150) -> dict:
    """Barras horizontales ordenadas de mayor (arriba) a menor."""
    if isinstance(colors, str):
        colors = [colors] * len(names)
    rows = list(zip(names, values, colors))[::-1]   # ECharts dibuja de abajo hacia arriba
    return {
        **_base(filename),
        "tooltip": {"trigger": "item", "confine": True, "formatter": "{b}<br/>{c}" + unit},
        "grid": {"left": 8, "right": 48, "top": 28, "bottom": 8, "containLabel": True},
        "xAxis": {**_value_axis(), "show": False},
        "yAxis": {"type": "category", "data": [str(n) for n, _, _ in rows],
                  "axisTick": {"show": False}, "axisLine": {"show": False},
                  "axisLabel": {"color": TEXT, "width": label_width, "overflow": "truncate"},
                  "tooltip": {"show": True}},
        "series": [{
            "type": "bar", "barMaxWidth": 22,
            "itemStyle": {"borderRadius": [0, 4, 4, 0]},
            "label": {"show": True, "position": "right", "color": TEXT,
                      "formatter": "{c}"},
            "data": [{"value": float(v), "itemStyle": {"color": c}} for _, v, c in rows],
        }],
    }


def stacked_bars(categories: Sequence[str], series: Sequence[tuple[str, Sequence[float], str]],
                 filename: str, *, y_name: str = "", percent: bool = False,
                 rotate: int = 0, width: int = 720) -> dict:
    """Columnas apiladas. ``series`` = [(nombre, valores, color), ...].
    Los segmentos en 0 no muestran etiqueta."""
    # Altura de la columna más alta: los segmentos muy finos (< 4 % de esa
    # altura) no muestran etiqueta porque no entra; el valor sigue en el tooltip.
    stack_max = max((sum(float(vals[i]) for _, vals, _ in series)
                     for i in range(len(categories))), default=0) or 1
    min_label = stack_max * 0.04
    out_series = []
    for name, values, color in series:
        txt = label_color(color)
        data = []
        for v in values:
            v = round(float(v), 1)
            item: dict = {"value": v}
            if v == 0 or v < min_label:
                item["label"] = {"show": False}
            data.append(item)
        out_series.append({
            "name": name, "type": "bar", "stack": "total", "barMaxWidth": 56,
            "itemStyle": {"color": color},
            "label": {"show": True, "color": txt, "fontSize": 11,
                      "formatter": "{c}%" if percent else "{c}"},
            "emphasis": {"focus": "series"},
            "data": data,
        })
    return {
        **_base(filename),
        "tooltip": {"trigger": "axis", "confine": True, "axisPointer": {"type": "shadow"}},
        "legend": _legend(type="plain", bottom=0, left="center"),
        "grid": {"left": 8, "right": 16, "top": 36, "containLabel": True,
                 "bottom": legend_rows([n for n, _, _ in series], width - 16) * 22 + 12},
        "xAxis": {"type": "category", "data": [str(c) for c in categories],
                  "axisTick": {"show": False},
                  "axisLine": {"lineStyle": {"color": "#D5DBE1"}},
                  "axisLabel": {"color": TEXT, "rotate": rotate, "interval": 0,
                                "width": 110, "overflow": "truncate"}},
        "yAxis": _value_axis(y_name, percent),
        "series": out_series,
    }
