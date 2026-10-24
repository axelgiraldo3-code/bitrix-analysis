"""Opciones de Apache ECharts para ``st.echarts_chart`` (funciones puras).

Todos los gráficos comparten: tooltip al pasar el mouse, sin controles de
zoom, y un único ícono para descargar la imagen en PNG.
"""
from __future__ import annotations

import html
from typing import Sequence

from .branding import COTEAR_BLUE, COTEAR_GRAY

TEXT = "#2B2F33"
MUTED = "#6B7785"
GRID = "#EEF1F4"
DARK_LABEL = "#1A1D21"

# Suavizado de las líneas (0 = recta, 1 = máximo). Con valores chicos y
# enteros un suavizado alto dibuja curvas por debajo de los datos.
SMOOTH = 0.35

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


def pct_label(p: float) -> str:
    """Porcentaje con 1 decimal y coma decimal no: '14.3%'."""
    return f"{p:.1f}%"


def _num(v) -> str:
    v = float(v)
    return str(int(v)) if v.is_integer() else f"{v:.1f}"


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
    # El % se calcula acá con 1 decimal: valores iguales muestran el mismo %
    # (ECharts reparte el redondeo para sumar 100 y da 14.28 % / 14.29 %).
    total = float(sum(values)) or 1.0
    data = []
    for n, v, c in zip(names, values, colors):
        pct = pct_label(float(v) / total * 100)
        data.append({
            "name": str(n), "value": float(v),
            "itemStyle": {"color": c},
            "label": {"color": label_color(c), "formatter": pct},
            "tooltip": {"formatter": f"{html.escape(str(n))}<br/>{_num(v)} ({pct})"},
        })
    rows = legend_rows(names, width - 16, label_width)
    legend_h = rows * 22 + 6
    free_h = height - legend_h - 24
    radius = max(60, min(width - 40, free_h) // 2)
    return {
        **_base(filename),
        "tooltip": {"trigger": "item", "confine": True},
        "legend": _legend(type="plain", bottom=0, left="center",
                          textStyle={"color": TEXT, "fontSize": 12, "width": label_width,
                                     "overflow": "truncate"},
                          tooltip={"show": True}),
        "series": [{
            "type": "pie", "radius": [int(radius * 0.58), radius],
            "center": ["50%", 18 + free_h // 2],
            "avoidLabelOverlap": True,
            "itemStyle": {"borderColor": "#FFFFFF", "borderWidth": 1},
            "label": {"show": True, "position": "inside",
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
                 rotate: int = 0, width: int = 720, label_width: int = 110) -> dict:
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
                                "width": label_width, "overflow": "truncate"},
                  "tooltip": {"show": True}},
        "yAxis": _value_axis(y_name, percent),
        "series": out_series,
    }


def timeseries(categories: Sequence[str], series: Sequence[tuple[str, Sequence[float], str]],
               filename: str, *, kind: str = "line", y_name: str = "",
               width: int = 900) -> dict:
    """Evolución en el tiempo: líneas o columnas agrupadas (no apiladas).
    ``series`` = [(nombre, valores, color), ...]; un cuarto elemento
    ``"dashed"`` dibuja esa línea punteada (y la columna con trama)."""
    out = []
    for name, values, color, *opts in series:
        dashed = "dashed" in opts
        item: dict = {"name": name, "type": "bar" if kind == "bar" else "line",
                      "itemStyle": {"color": color},
                      "emphasis": {"focus": "series"},
                      "data": [float(v) for v in values]}
        if kind == "bar":
            style = {"color": color, "borderRadius": [4, 4, 0, 0]}
            if dashed:
                style.update(decal={"symbol": "rect", "dashArrayX": [1, 0],
                                    "dashArrayY": [3, 3], "rotation": 0.8,
                                    "color": "rgba(255,255,255,0.45)"})
            item.update(barMaxWidth=28, itemStyle=style,
                        label={"show": True, "position": "top", "color": TEXT, "fontSize": 11,
                               "formatter": "{c}"})
        else:
            item.update(smooth=SMOOTH, smoothMonotone="x", symbol="circle", symbolSize=7,
                        lineStyle={"width": 2.5, "color": color,
                                   "type": "dashed" if dashed else "solid"},
                        label={"show": len(categories) <= 14, "position": "top",
                               "color": TEXT, "fontSize": 11})
        out.append(item)
    return {
        **_base(filename),
        "tooltip": {"trigger": "axis", "confine": True,
                    "axisPointer": {"type": "shadow" if kind == "bar" else "line"}},
        "legend": _legend(type="plain", bottom=0, left="center"),
        "grid": {"left": 8, "right": 16, "top": 36, "containLabel": True,
                 "bottom": legend_rows([s[0] for s in series], width - 16) * 22 + 12},
        "xAxis": {"type": "category", "data": [str(c) for c in categories],
                  "boundaryGap": kind == "bar", "axisTick": {"show": False},
                  "axisLine": {"lineStyle": {"color": "#D5DBE1"}},
                  "axisLabel": {"color": TEXT}},
        "yAxis": {**_value_axis(y_name), "minInterval": 1},
        "series": out,
    }


def heatmap(x_labels: Sequence[str], y_labels: Sequence[str],
            cells: Sequence[tuple[int, int, float]], filename: str, *,
            unit: str = "consultas", tooltips: Sequence[str] | None = None) -> dict:
    """Mapa de calor. ``cells`` = [(x, y, valor), ...] con índices de
    ``x_labels`` / ``y_labels``. Escala gris claro → azul Cotear; las celdas
    en 0 quedan en blanco."""
    vmax = max((v for _, _, v in cells), default=0) or 1
    data: list = [[x, y, float(v) if v else "-"] for x, y, v in cells]
    if tooltips is not None:
        data = [{"value": d, "tooltip": {"formatter": t}} for d, t in zip(data, tooltips)]
    return {
        **_base(filename),
        "tooltip": {"trigger": "item", "confine": True},
        "grid": {"left": 8, "right": 12, "top": 28, "bottom": 52, "containLabel": True},
        "xAxis": {"type": "category", "data": list(x_labels), "splitArea": {"show": False},
                  "axisTick": {"show": False}, "axisLine": {"show": False},
                  "axisLabel": {"color": MUTED, "fontSize": 10, "interval": 1}},
        "yAxis": {"type": "category", "data": list(y_labels), "inverse": True,
                  "axisTick": {"show": False}, "axisLine": {"show": False},
                  "axisLabel": {"color": TEXT}},
        "visualMap": {"min": 0, "max": vmax, "calculable": False, "orient": "horizontal",
                      "left": "center", "bottom": 0, "itemWidth": 12, "itemHeight": 160,
                      "text": [f"Más {unit}", "Menos"], "textStyle": {"color": MUTED},
                      "inRange": {"color": ["#E8EEF5", "#7FA6CC", COTEAR_BLUE]}},
        "series": [{
            "type": "heatmap", "data": data,
            "itemStyle": {"borderColor": "#FFFFFF", "borderWidth": 2, "borderRadius": 3},
            "label": {"show": False},
            "emphasis": {"itemStyle": {"borderColor": TEXT, "borderWidth": 1}},
        }],
    }


def funnel(names: Sequence[str], values: Sequence[float], colors: Sequence[str],
           filename: str) -> dict:
    """Embudo con el orden dado (no se reordena). La etiqueta muestra la
    cantidad y el % sobre la primera etapa; el tooltip, además, el % sobre la
    etapa anterior."""
    first = float(values[0]) if values and values[0] else 0.0
    data = []
    for i, (n, v, c) in enumerate(zip(names, values, colors)):
        v = float(v)
        of_first = pct_label(v / first * 100) if first else "—"
        prev = float(values[i - 1]) if i else 0.0
        step = f"<br/>{pct_label(v / prev * 100)} de la etapa anterior" if i and prev else ""
        data.append({
            "name": str(n), "value": v,
            "itemStyle": {"color": c},
            "label": {"color": label_color(c),
                      "formatter": f"{n}\n{_num(v)} · {of_first}"},
            "tooltip": {"formatter": f"{html.escape(str(n))}: {_num(v)}<br/>"
                                     f"{of_first} de las consultas{step}"},
        })
    return {
        **_base(filename),
        "tooltip": {"trigger": "item", "confine": True},
        "series": [{
            "type": "funnel", "sort": "none", "gap": 3,
            "left": "6%", "right": "6%", "top": 30, "bottom": 10,
            "minSize": "18%", "maxSize": "100%",
            "label": {"show": True, "position": "inside", "fontSize": 12,
                      "fontWeight": "bold", "lineHeight": 16, "textBorderWidth": 0},
            "labelLine": {"show": False},
            "itemStyle": {"borderColor": "#FFFFFF", "borderWidth": 1},
            "emphasis": {"label": {"fontSize": 13}},
            "data": data,
        }],
    }


SPARK_UP, SPARK_DOWN, SPARK_FLAT = "#21C354", "#FF4B4B", "#A3A8B4"


def sparkline(labels: Sequence[str], values: Sequence, color: str, *, unit: str = "") -> dict:
    """Mini línea suavizada para un KPI, sin ejes ni descarga. Al pasar el
    mouse: "Jun - 72". Los meses sin datos (None) quedan como hueco."""
    data = ["-" if v is None else v for v in values]
    return {
        "animation": False,
        "grid": {"left": 4, "right": 4, "top": 6, "bottom": 4},
        "xAxis": {"type": "category", "show": False, "boundaryGap": False,
                  "data": [str(x) for x in labels]},
        "yAxis": {"type": "value", "show": False, "scale": True},
        "tooltip": {"trigger": "axis", "confine": False, "appendToBody": True,
                    "formatter": "{b} - {c}" + unit, "padding": [3, 8],
                    "textStyle": {"fontSize": 12, "color": TEXT},
                    "axisPointer": {"type": "line",
                                    "lineStyle": {"color": "#C9D1D9", "width": 1}}},
        "series": [{
            "type": "line", "smooth": SMOOTH, "smoothMonotone": "x",
            "data": data, "connectNulls": False,
            "showSymbol": False, "symbol": "circle", "symbolSize": 6,
            "lineStyle": {"width": 2, "color": color},
            "itemStyle": {"color": color},
            "areaStyle": {"color": color, "opacity": 0.10},
            "emphasis": {"focus": "none", "scale": 1.4},
        }],
    }
