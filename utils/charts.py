"""Opciones de Apache ECharts para ``st.echarts_chart`` (funciones puras).

Todos los gráficos comparten: tooltip al pasar el mouse (con la cantidad),
etiquetas en porcentaje, sin controles de zoom, y un único ícono para
descargar la imagen en SVG.
"""

from __future__ import annotations

import html
from collections.abc import Sequence

from .branding import COTEAR_BLUE, COTEAR_GRAY

TEXT = "#2B2F33"
MUTED = "#6B7785"
GRID = "#EEF1F4"
DARK_LABEL = "#1A1D21"
# Misma fuente que el tema de Streamlit, sin comillas: el tema usa
# '"Source Sans", sans-serif' y ECharts la copia sin escapar dentro de
# style="…" al exportar, lo que deja el SVG mal formado.
FONT = "Source Sans, sans-serif"

# Tamaño fijo de la imagen descargada (px, 4:3), igual en cualquier pantalla
EXPORT_SIZE = (800, 600)

# Ancho aproximado de un carácter a 12 px y medidas de las leyendas
CHAR_W = 6.6
LEGEND_GAP = 16
LEGEND_TEXT_MAX = 200

# Suavizado de las líneas (0 = recta, 1 = máximo). Con valores chicos y
# enteros un suavizado alto dibuja curvas por debajo de los datos.
SMOOTH = 0.35

# Paleta para series sin color propio (ej. motivos de baja)
SERIES_COLORS = [
    COTEAR_BLUE,
    "#E67E22",
    "#11734B",
    "#39A8EF",
    "#B10202",
    "#5A3286",
    "#C9A400",
    "#2BB3A3",
    "#D35FB7",
    COTEAR_GRAY,
]


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

    r, g, b = (ch(int(h[i : i + 2], 16)) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def label_color(fill: str) -> str:
    """Blanco u oscuro, el que más se lea sobre ``fill`` (WCAG)."""
    return (
        "#FFFFFF"
        if contrast_ratio(fill, "#FFFFFF") >= contrast_ratio(fill, DARK_LABEL)
        else DARK_LABEL
    )


def fmt_dec(v: float, decimals: int = 1) -> str:
    """Número con coma decimal: 14.25 → '14,3'."""
    return f"{float(v):.{decimals}f}".replace(".", ",")


def pct_label(p: float) -> str:
    """Porcentaje con 1 decimal, coma decimal y espacio: '14,3 %'."""
    return f"{fmt_dec(p)} %"


def _num(v) -> str:
    v = float(v)
    return str(int(v)) if v.is_integer() else fmt_dec(v)


def series_color(i: int) -> str:
    return SERIES_COLORS[i % len(SERIES_COLORS)]


# ---------------------------------------------------------------------------
# Piezas comunes
# ---------------------------------------------------------------------------
def _toolbox(filename: str) -> dict:
    """Toolbox oculto: sólo lleva el nombre del archivo. La descarga la hace
    ``ui.echart`` con su propio ícono, redibujando el gráfico a
    ``EXPORT_SIZE`` (el ``saveAsImage`` de ECharts exporta el tamaño de
    pantalla)."""
    return {"show": False, "feature": {"saveAsImage": {"type": "svg", "name": filename}}}


def export_name(option: dict) -> str | None:
    """Nombre de descarga de un gráfico (``None`` si no se descarga, como
    las mini líneas)."""
    try:
        return option["toolbox"]["feature"]["saveAsImage"]["name"]
    except (KeyError, TypeError):
        return None


def svg_safe_fonts(option: dict) -> dict:
    """Copia de ``option`` con ``FONT`` en cada texto al que el tema de
    Streamlit le pone su fuente entre comillas (general, leyenda, ejes,
    escala del mapa de calor y etiquetas del embudo). El tooltip no hace
    falta: es HTML y no se exporta."""

    def with_font(style: dict | None) -> dict:
        return {**(style or {}), "fontFamily": FONT}

    out = dict(option)
    out["textStyle"] = with_font(out.get("textStyle"))
    for key in ("legend", "visualMap"):
        if isinstance(out.get(key), dict):
            out[key] = {**out[key], "textStyle": with_font(out[key].get("textStyle"))}
    for key in ("xAxis", "yAxis"):
        axes = out.get(key)
        if axes is None:
            continue
        fixed = [
            {
                **ax,
                "axisLabel": with_font(ax.get("axisLabel")),
                "nameTextStyle": with_font(ax.get("nameTextStyle")),
            }
            for ax in (axes if isinstance(axes, list) else [axes])
        ]
        out[key] = fixed if isinstance(axes, list) else fixed[0]
    if "series" in out:
        out["series"] = [
            {**s, "label": with_font(s.get("label"))} if s.get("type") == "funnel" else s
            for s in out["series"]
        ]
    return out


def _base(filename: str) -> dict:
    return {
        "animationDuration": 300,
        "textStyle": {"color": TEXT},
        "toolbox": _toolbox(filename),
        "tooltip": {"confine": True},
    }


def _legend(**kw) -> dict:
    return {
        "type": "scroll",
        "icon": "roundRect",
        "itemWidth": 12,
        "itemHeight": 12,
        "textStyle": {"color": TEXT, "fontSize": 12},
        **kw,
    }


def _text_width(names: Sequence[str], max_width: int) -> int:
    """Ancho del nombre más largo a 12 px (~6.6 px por carácter), con tope."""
    longest = max((len(str(n)) for n in names), default=0)
    return int(min(max_width, CHAR_W * longest + 2))


def _bottom_legend(names: Sequence[str]) -> dict:
    """Leyenda abajo en columnas parejas: todos los ítems miden lo mismo
    (el nombre más largo, con tope), así quedan alineados y al bajar de fila
    no se pisan. Los nombres que no entran se cortan con "…" (tooltip)."""
    return _legend(
        type="plain",
        bottom=0,
        left="center",
        itemGap=LEGEND_GAP,
        textStyle={
            "color": TEXT,
            "fontSize": 12,
            "width": _text_width(names, LEGEND_TEXT_MAX),
            "overflow": "truncate",
        },
        tooltip={"show": True},
    )


def legend_rows(names: Sequence[str], width: int) -> int:
    """Filas que ocupa ``_bottom_legend`` en ``width`` px."""
    if not names:
        return 1
    item = 12 + 5 + _text_width(names, LEGEND_TEXT_MAX) + LEGEND_GAP
    per_row = max(1, int((width + LEGEND_GAP) // item))
    return -(-len(names) // per_row)


def wrap_label(text, max_chars: int) -> str:
    """Etiqueta de eje en hasta 2 renglones: corta en el último espacio que
    entra en ``max_chars`` (o a la fuerza si es una sola palabra) y, si el
    segundo renglón tampoco entra, lo termina con "…"."""
    s = str(text)
    if max_chars <= 0 or len(s) <= max_chars:
        return s
    cut = s.rfind(" ", 0, max_chars + 1)
    first, rest = (s[:cut], s[cut + 1 :]) if cut > 0 else (s[:max_chars], s[max_chars:])
    rest = rest.strip()
    if len(rest) > max_chars:
        rest = rest[: max_chars - 1].rstrip() + "…"
    return f"{first}\n{rest}"


def _wrap_chars(label_width: int) -> int:
    return max(4, int(label_width / CHAR_W))


def _value_axis(name: str = "") -> dict:
    return {
        "type": "value",
        "name": name,
        "nameTextStyle": {"color": MUTED},
        "axisLabel": {"color": MUTED},
        "splitLine": {"lineStyle": {"color": GRID}},
    }


# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------
def donut(
    names: Sequence[str],
    values: Sequence[float],
    colors: Sequence[str],
    filename: str,
    *,
    width: int = 520,
    height: int = 380,
    label_width: int = 150,
) -> dict:
    """Torta con agujero: porcentaje dentro de cada porción y leyenda vertical
    a la derecha (los nombres largos bajan de renglón). ``width``/``height``
    aproximan el tamaño en px de la tarjeta: con eso se calculan el centro y
    el radio en %, así la torta escala igual en pantalla y en la descarga."""
    # El % se calcula acá con 1 decimal: valores iguales muestran el mismo %
    # (ECharts reparte el redondeo para sumar 100 y da 14.28 % / 14.29 %).
    total = float(sum(values)) or 1.0
    data = []
    for n, v, c in zip(names, values, colors):
        pct = pct_label(float(v) / total * 100)
        data.append(
            {
                "name": str(n),
                "value": float(v),
                "itemStyle": {"color": c},
                "label": {"color": label_color(c), "formatter": pct},
                "tooltip": {"formatter": f"{html.escape(str(n))}<br/>{_num(v)} ({pct})"},
            }
        )
    # Espacio libre a la izquierda de la leyenda: ahí va la torta, centrada
    text_w = _text_width(names, label_width)
    legend_w = 12 + 5 + text_w + 8
    free_w = max(120, width - legend_w - 8)
    outer = max(50, min(free_w / 2, height / 2) - 14)  # px en la tarjeta
    outer_pct = round(outer / (min(width, height) / 2) * 100)
    return {
        **_base(filename),
        "tooltip": {"trigger": "item", "confine": True},
        "legend": _legend(
            type="scroll",
            orient="vertical",
            right=8,
            top="middle",
            itemGap=10,
            textStyle={
                "color": TEXT,
                "fontSize": 12,
                "width": text_w,
                "overflow": "break",
                "lineHeight": 15,
            },
            tooltip={"show": True},
        ),
        "series": [
            {
                "type": "pie",
                "radius": [f"{round(outer_pct * 0.39)}%", f"{outer_pct}%"],
                "center": [f"{round(free_w / 2 / width * 100)}%", "50%"],
                "avoidLabelOverlap": True,
                "itemStyle": {"borderColor": "#FFFFFF", "borderWidth": 1},
                "label": {"show": True, "position": "inside", "fontSize": 11, "fontWeight": "bold"},
                "labelLayout": {"hideOverlap": True},
                "emphasis": {"scaleSize": 6},
                "data": data,
            }
        ],
    }


def hbar(
    names: Sequence[str],
    values: Sequence[float],
    colors: Sequence[str] | str,
    filename: str,
    *,
    unit: str = "",
    label_width: int = 150,
) -> dict:
    """Barras horizontales ordenadas de mayor (arriba) a menor. Etiqueta: %
    sobre el total; tooltip: cantidad y %."""
    if isinstance(colors, str):
        colors = [colors] * len(names)
    rows = list(zip(names, values, colors))[::-1]  # ECharts dibuja de abajo hacia arriba
    total = float(sum(values)) or 1.0
    data = []
    for n, v, c in rows:
        pct = pct_label(float(v) / total * 100)
        data.append(
            {
                "value": float(v),
                "itemStyle": {"color": c},
                "label": {"formatter": pct},
                "tooltip": {"formatter": f"{html.escape(str(n))}<br/>{_num(v)}{unit} ({pct})"},
            }
        )
    return {
        **_base(filename),
        "tooltip": {"trigger": "item", "confine": True},
        "grid": {"left": 8, "right": 48, "top": 28, "bottom": 8, "containLabel": True},
        "xAxis": {**_value_axis(), "show": False},
        "yAxis": {
            "type": "category",
            "data": [wrap_label(n, _wrap_chars(label_width)) for n, _, _ in rows],
            "axisTick": {"show": False},
            "axisLine": {"show": False},
            "axisLabel": {"color": TEXT, "lineHeight": 14},
            "tooltip": {"show": True},
        },
        "series": [
            {
                "type": "bar",
                "barMaxWidth": 22,
                "itemStyle": {"borderRadius": [0, 4, 4, 0]},
                "label": {"show": True, "position": "right", "color": TEXT},
                "data": data,
            }
        ],
    }


def stacked_bars(
    categories: Sequence[str],
    series: Sequence[tuple[str, Sequence[float], str]],
    filename: str,
    *,
    y_name: str = "",
    rotate: int = 0,
    width: int = 720,
    label_width: int = 110,
    horizontal: bool = False,
) -> dict:
    """Columnas apiladas. ``series`` = [(nombre, valores, color), ...].
    ``horizontal``: barras horizontales con la primera categoría arriba.
    La altura es la cantidad y la etiqueta, el %: con una sola serie, sobre
    el total del gráfico; con varias, sobre el total de su columna (cada
    columna suma 100 %). Los segmentos en 0 no muestran etiqueta. Etiquetas
    y tooltip van armados por segmento ("33,3 %"): las plantillas de ECharts
    no admiten coma decimal."""
    col_totals = [sum(float(vals[i]) for _, vals, _ in series) for i in range(len(categories))]
    grand_total = sum(col_totals)
    # Altura de la columna más alta: los segmentos muy finos (< 4 % de esa
    # altura) no muestran etiqueta porque no entra; el valor sigue en el tooltip.
    min_label = (max(col_totals, default=0) or 1) * 0.04
    out_series = []
    for name, values, color in series:
        txt = label_color(color)
        data = []
        for cat, v, col_total in zip(categories, values, col_totals):
            v = round(float(v), 1)
            base = grand_total if len(series) == 1 else col_total
            pct = pct_label(v / base * 100) if base else "—"
            item: dict = {
                "value": v,
                "label": {"formatter": pct},
                "tooltip": {
                    "formatter": f"{html.escape(str(cat))}<br/>"
                    f"{html.escape(str(name))}: {_num(v)} ({pct})"
                },
            }
            if v == 0 or v < min_label:
                item["label"] = {"show": False}
            data.append(item)
        out_series.append(
            {
                "name": name,
                "type": "bar",
                "stack": "total",
                "barMaxWidth": 56,
                "itemStyle": {"color": color},
                "label": {"show": True, "color": txt, "fontSize": 11},
                "emphasis": {"focus": "series"},
                "data": data,
            }
        )
    cat_axis = {
        "type": "category",
        "data": [wrap_label(c, _wrap_chars(label_width)) for c in categories],
        "axisTick": {"show": False},
        "axisLine": {"lineStyle": {"color": "#D5DBE1"}},
        "axisLabel": {"color": TEXT, "rotate": rotate, "interval": 0, "lineHeight": 14},
        "tooltip": {"show": True},
    }
    value_axis = _value_axis(y_name)
    if horizontal:
        cat_axis.update(inverse=True, axisLine={"show": False})
        for serie in out_series:
            serie["barMaxWidth"] = 22
    return {
        **_base(filename),
        "tooltip": {"trigger": "item", "confine": True},
        "legend": _bottom_legend([n for n, _, _ in series]),
        "grid": {
            "left": 8,
            "right": 16,
            "top": 36,
            "containLabel": True,
            "bottom": legend_rows([n for n, _, _ in series], width - 16) * 22 + 12,
        },
        "xAxis": value_axis if horizontal else cat_axis,
        "yAxis": cat_axis if horizontal else value_axis,
        "series": out_series,
    }


def timeseries(
    categories: Sequence[str],
    series: Sequence[tuple[str, Sequence[float], str]],
    filename: str,
    *,
    kind: str = "line",
    y_name: str = "",
    width: int = 900,
) -> dict:
    """Evolución en el tiempo: líneas o columnas agrupadas (no apiladas).
    ``series`` = [(nombre, valores, color), ...]."""
    out = []
    for name, values, color in series:
        item: dict = {
            "name": name,
            "type": "bar" if kind == "bar" else "line",
            "itemStyle": {"color": color},
            "emphasis": {"focus": "series"},
            "data": [float(v) for v in values],
        }
        if kind == "bar":
            item.update(
                barMaxWidth=28,
                itemStyle={"color": color, "borderRadius": [4, 4, 0, 0]},
                label={
                    "show": True,
                    "position": "top",
                    "color": TEXT,
                    "fontSize": 11,
                    "formatter": "{c}",
                },
            )
        else:
            item.update(
                smooth=SMOOTH,
                smoothMonotone="x",
                symbol="circle",
                symbolSize=7,
                lineStyle={"width": 2.5, "color": color},
                label={
                    "show": len(categories) <= 14,
                    "position": "top",
                    "color": TEXT,
                    "fontSize": 11,
                },
            )
        out.append(item)
    return {
        **_base(filename),
        "tooltip": {
            "trigger": "axis",
            "confine": True,
            "axisPointer": {"type": "shadow" if kind == "bar" else "line"},
        },
        "legend": _bottom_legend([s[0] for s in series]),
        "grid": {
            "left": 8,
            "right": 16,
            "top": 36,
            "containLabel": True,
            "bottom": legend_rows([s[0] for s in series], width - 16) * 22 + 12,
        },
        "xAxis": {
            "type": "category",
            "data": [str(c) for c in categories],
            "boundaryGap": kind == "bar",
            "axisTick": {"show": False},
            "axisLine": {"lineStyle": {"color": "#D5DBE1"}},
            "axisLabel": {"color": TEXT},
        },
        "yAxis": {**_value_axis(y_name), "minInterval": 1},
        "series": out,
    }


def leader_bars(
    categories: Sequence[str],
    leaders: Sequence[tuple[str, int, int]],
    colors: dict[str, str],
    filename: str,
    *,
    y_name: str = "",
    width: int = 600,
) -> dict:
    """Una columna por período con la categoría líder de ese período, en su
    color. ``leaders`` = [(líder, casos, total del período), ...]; un período
    sin casos queda vacío. Cada líder es una serie (para la leyenda) apilada
    con las demás, así la columna queda centrada aunque las otras estén
    vacías. Tooltip: "Sep-26 · WhatsApp<br/>12 de 30 (40,0 %)"."""
    names = list(dict.fromkeys(n for n, v, _ in leaders if v))
    out_series = []
    for name in names:
        data: list = []
        for cat, (lead, v, total) in zip(categories, leaders):
            if lead != name or not v:
                data.append("-")
                continue
            pct = pct_label(v / total * 100) if total else "—"
            data.append(
                {
                    "value": float(v),
                    "label": {"formatter": pct},
                    "tooltip": {
                        "formatter": (
                            f"{html.escape(str(cat))} · {html.escape(name)}<br/>"
                            f"{_num(v)} de {_num(total)} ({pct})"
                        )
                    },
                }
            )
        out_series.append(
            {
                "name": name,
                "type": "bar",
                "stack": "lider",
                "barMaxWidth": 40,
                "itemStyle": {"color": colors.get(name, COTEAR_GRAY), "borderRadius": [4, 4, 0, 0]},
                "label": {"show": True, "position": "top", "color": TEXT, "fontSize": 11},
                "data": data,
            }
        )
    return {
        **_base(filename),
        "tooltip": {"trigger": "item", "confine": True},
        "legend": _bottom_legend(names),
        "grid": {
            "left": 8,
            "right": 16,
            "top": 36,
            "containLabel": True,
            "bottom": legend_rows(names, width - 16) * 22 + 12,
        },
        "xAxis": {
            "type": "category",
            "data": [str(c) for c in categories],
            "axisTick": {"show": False},
            "axisLine": {"lineStyle": {"color": "#D5DBE1"}},
            "axisLabel": {"color": TEXT},
        },
        "yAxis": {**_value_axis(y_name), "minInterval": 1},
        "series": out_series,
    }


def heatmap(
    x_labels: Sequence[str],
    y_labels: Sequence[str],
    cells: Sequence[tuple[int, int, float]],
    filename: str,
    *,
    unit: str = "consultas",
    tooltips: Sequence[str] | None = None,
) -> dict:
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
        "xAxis": {
            "type": "category",
            "data": list(x_labels),
            "splitArea": {"show": False},
            "axisTick": {"show": False},
            "axisLine": {"show": False},
            "axisLabel": {"color": MUTED, "fontSize": 10, "interval": 1},
        },
        "yAxis": {
            "type": "category",
            "data": list(y_labels),
            "inverse": True,
            "axisTick": {"show": False},
            "axisLine": {"show": False},
            "axisLabel": {"color": TEXT},
        },
        "visualMap": {
            "min": 0,
            "max": vmax,
            "calculable": False,
            "orient": "horizontal",
            "left": "center",
            "bottom": 0,
            "itemWidth": 12,
            "itemHeight": 160,
            "text": [f"Más {unit}", "Menos"],
            "textStyle": {"color": MUTED},
            "inRange": {"color": ["#E8EEF5", "#7FA6CC", COTEAR_BLUE]},
        },
        "series": [
            {
                "type": "heatmap",
                "data": data,
                "itemStyle": {"borderColor": "#FFFFFF", "borderWidth": 2, "borderRadius": 3},
                "label": {"show": False},
                "emphasis": {"itemStyle": {"borderColor": TEXT, "borderWidth": 1}},
            }
        ],
    }


def funnel(
    names: Sequence[str], values: Sequence[float], colors: Sequence[str], filename: str
) -> dict:
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
        data.append(
            {
                "name": str(n),
                "value": v,
                "itemStyle": {"color": c},
                "label": {"color": label_color(c), "formatter": f"{n}\n{_num(v)} · {of_first}"},
                "tooltip": {
                    "formatter": f"{html.escape(str(n))}: {_num(v)}<br/>"
                    f"{of_first} de las consultas{step}"
                },
            }
        )
    return {
        **_base(filename),
        "tooltip": {"trigger": "item", "confine": True},
        "series": [
            {
                "type": "funnel",
                "sort": "none",
                "gap": 3,
                "left": "6%",
                "right": "6%",
                "top": 30,
                "bottom": 10,
                "minSize": "18%",
                "maxSize": "100%",
                "label": {
                    "show": True,
                    "position": "inside",
                    "fontSize": 12,
                    "fontWeight": "bold",
                    "lineHeight": 16,
                    "textBorderWidth": 0,
                },
                "labelLine": {"show": False},
                "itemStyle": {"borderColor": "#FFFFFF", "borderWidth": 1},
                "emphasis": {"label": {"fontSize": 13}},
                "data": data,
            }
        ],
    }


SPARK_UP, SPARK_DOWN, SPARK_FLAT = "#21C354", "#FF4B4B", "#A3A8B4"


def sparkline(labels: Sequence[str], values: Sequence, color: str, *, unit: str = "") -> dict:
    """Mini línea suavizada para un KPI, sin ejes ni descarga. Al pasar el
    mouse: "Jun - 72" / "Jun - 52,5 %". Los meses sin datos (None) quedan
    como hueco. El texto del tooltip va en la categoría del eje (que no se
    ve), porque la plantilla "{c}" mostraría el punto decimal."""
    data = ["-" if v is None else v for v in values]
    tips = [
        f"{x} - sin datos" if v is None else f"{x} - {_num(v)}{unit}"
        for x, v in zip(labels, values)
    ]
    return {
        "animation": False,
        "grid": {"left": 4, "right": 4, "top": 6, "bottom": 4},
        "xAxis": {"type": "category", "show": False, "boundaryGap": False, "data": tips},
        "yAxis": {"type": "value", "show": False, "scale": True},
        "tooltip": {
            "trigger": "axis",
            "confine": False,
            "appendToBody": True,
            "formatter": "{b}",
            "padding": [3, 8],
            "textStyle": {"fontSize": 12, "color": TEXT},
            "axisPointer": {"type": "line", "lineStyle": {"color": "#C9D1D9", "width": 1}},
        },
        "series": [
            {
                "type": "line",
                "smooth": SMOOTH,
                "smoothMonotone": "x",
                "data": data,
                "connectNulls": False,
                "showSymbol": False,
                "symbol": "circle",
                "symbolSize": 6,
                "lineStyle": {"width": 2, "color": color},
                "itemStyle": {"color": color},
                "areaStyle": {"color": color, "opacity": 0.10},
                "emphasis": {"focus": "none", "scale": 1.4},
            }
        ],
    }
