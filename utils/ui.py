"""Componentes visuales del dashboard (estilo SaaS claro con marca Cotear).

* ``inject_css``: estilos globales (tarjetas, KPIs, transición gráfico ⇄ datos).
* ``kpi``: tarjeta de indicador con variación contra el período anterior.
* ``chart_card``: tarjeta con título, controles opcionales y el botón
  Gráfico | Datos. Al alternar, el gráfico se desliza al costado y aparece la
  tabla; es sólo CSS, no vuelve a ejecutar la app.
* ``raw_data``: tabla completa y botón de descarga dentro de un desplegable.
"""
from __future__ import annotations

import inspect
from typing import Callable, Optional

import pandas as pd
import streamlit as st

from .branding import COTEAR_BLUE

CSV_ENCODING = "utf-8-sig"  # BOM: Excel en español muestra bien las tildes

VIEW_CHART = ":material/insert_chart:"
VIEW_DATA = ":material/table_chart:"
_VIEW_HELP = "Alternar entre el gráfico y sus datos"


def _call(fn, *args, **kwargs):
    """Llama ``fn`` descartando los argumentos que la versión instalada de
    Streamlit todavía no acepta (así la app no se rompe con versiones algo
    más viejas; sólo se pierde ese detalle)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return fn(*args, **kwargs)
    if any(p.kind is p.VAR_KEYWORD for p in params.values()):
        return fn(*args, **kwargs)
    return fn(*args, **{k: v for k, v in kwargs.items() if k in params})


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode(CSV_ENCODING)


def plural(n: int, unit: str) -> str:
    """'1 consulta' / '3 consultas'."""
    return f"{n} {unit if n != 1 else unit[:-1]}"


# ---------------------------------------------------------------------------
# CSS global
# ---------------------------------------------------------------------------
def inject_css() -> None:
    st.markdown(f"""
    <style>
      :root {{
        --ct-blue: {COTEAR_BLUE};
        --ct-text: #1F2933;
        --ct-muted: #6B7785;
        --ct-line: #E3E8EE;
        --ct-card: #FFFFFF;
        --ct-shadow: 0 1px 2px rgba(16, 24, 40, .04), 0 2px 8px rgba(16, 24, 40, .06);
      }}

      /* Encabezado de página */
      .ct-eyebrow {{
        color: var(--ct-blue); font-size: 1.125rem; font-weight: 700;
        letter-spacing: .08em; text-transform: uppercase; margin-bottom: .1rem;
      }}
      body .stApp h1 {{ color: var(--ct-text); font-weight: 800; letter-spacing: -.01em; }}
      .ct-subtitle {{ color: var(--ct-muted); font-size: .95rem; margin-top: -.35rem; }}

      /* Tarjetas (st.container con key "card_*") */
      div[class*="st-key-card_"] {{
        background: var(--ct-card);
        border: 1px solid var(--ct-line) !important;
        border-radius: 14px !important;
        box-shadow: var(--ct-shadow);
        padding: 1rem 1.15rem .9rem 1.15rem;
      }}
      .ct-card-title {{ font-size: 1.02rem; font-weight: 700; color: var(--ct-text); line-height: 1.3; }}
      .ct-card-sub {{ font-size: .8rem; color: var(--ct-muted); }}
      /* Título de grupo de tarjetas */
      .ct-section {{
        font-size: 1.17rem; font-weight: 700; letter-spacing: .07em; text-transform: uppercase;
        color: var(--ct-blue); margin: .9rem 0 0 .1rem;
        display: flex; align-items: center; gap: .6rem;
      }}
      .ct-section::after {{ content: ""; flex: 1; height: 1px; background: var(--ct-line); }}
      .ct-section-sub {{ font-size: .8rem; color: var(--ct-muted); margin: .1rem 0 0 .1rem; }}
      div[class*="st-key-cardctl_"] {{ flex-shrink: 0; }}

      /* KPIs: tarjeta blanca con acento lateral azul */
      div[data-testid="stMetric"] {{
        background: var(--ct-card);
        border: 1px solid var(--ct-line) !important;
        border-left: 4px solid var(--ct-blue) !important;
        border-radius: 12px !important;
        box-shadow: var(--ct-shadow);
        padding: .85rem 1rem .8rem 1rem;
        min-height: 150px;
      }}
      [data-testid="stMetricLabel"] p {{
        color: var(--ct-muted); font-size: .74rem; font-weight: 700;
        letter-spacing: .06em; text-transform: uppercase;
      }}
      div[data-testid="stMetricValue"] {{ font-weight: 700; color: var(--ct-text); font-size: 1.85rem; }}
      /* Descripción de la variación: puede ocupar dos líneas */
      div[data-testid="stMetricDelta"] {{ flex-shrink: 0; }}
      div:has(> div[data-testid="stMetricDeltaDescription"]) {{ flex-wrap: wrap; row-gap: 2px; }}
      div[data-testid="stMetricDeltaDescription"],
      div[data-testid="stMetricDeltaDescription"] p {{
        white-space: normal !important; overflow: visible !important;
        text-overflow: clip !important; line-height: 1.3;
      }}

      /* Desplegables (datos crudos) como tarjeta */
      div[data-testid="stExpander"] details {{
        background: var(--ct-card); border: 1px solid var(--ct-line);
        border-radius: 14px; box-shadow: var(--ct-shadow);
      }}
      div[data-testid="stExpander"] summary p {{ font-weight: 700; }}

      /* Gráfico ⇄ Datos: ambos ocupan la misma celda; el gráfico se desliza
         a la izquierda y la tabla aparece detrás. */
      div[class*="st-key-flip_"] {{
        display: grid !important; grid-template-columns: minmax(0, 1fr);
        overflow: hidden; gap: 0 !important;
      }}
      div[class*="st-key-flip_"] > div {{ grid-area: 1 / 1; width: 100%; min-width: 0; }}
      div[class*="st-key-front_"], div[class*="st-key-back_"] {{
        transition: transform .55s cubic-bezier(.4, 0, .2, 1), opacity .45s ease,
                    visibility 0s linear 0s;
      }}
      div[class*="st-key-back_"] {{
        transform: scale(.97); opacity: 0; visibility: hidden; pointer-events: none;
        transition: transform .55s cubic-bezier(.4, 0, .2, 1), opacity .45s ease,
                    visibility 0s linear .55s;
      }}
      div[class*="st-key-card_"]:has([class*="st-key-view_"] button[role="radio"]:nth-of-type(2)[aria-checked="true"])
        div[class*="st-key-front_"] {{
        transform: translateX(-104%); opacity: 0; visibility: hidden; pointer-events: none;
        transition: transform .55s cubic-bezier(.4, 0, .2, 1), opacity .45s ease,
                    visibility 0s linear .55s;
      }}
      div[class*="st-key-card_"]:has([class*="st-key-view_"] button[role="radio"]:nth-of-type(2)[aria-checked="true"])
        div[class*="st-key-back_"] {{
        transform: none; opacity: 1; visibility: visible; pointer-events: auto;
        transition: transform .55s cubic-bezier(.4, 0, .2, 1) .1s, opacity .45s ease .1s,
                    visibility 0s linear 0s;
      }}

      /* Encabezado de tarjeta: el título puede ocupar dos líneas sin cortarse */
      div[class*="st-key-cardhead_"] {{ overflow: visible !important; flex-wrap: nowrap !important; }}
      div[class*="st-key-cardhead_"] div[data-testid="stMarkdownContainer"] {{
        margin-bottom: 0 !important;
      }}
      div[class*="st-key-cardhead_"] div[data-testid="stMarkdown"],
      div[class*="st-key-cardhead_"] div[data-testid="stMarkdown"] > div {{ height: auto !important; }}
      /* Controles compactos en el encabezado de las tarjetas */
      div[class*="st-key-cardhead_"] div[data-testid="stButtonGroup"] button {{
        min-height: 2rem; padding: .2rem .7rem;
      }}

      /* Resumen de solo lectura (Clasificación manual): texto con color normal */
      div[class*="st-key-card_"] textarea:disabled {{
        color: var(--ct-text) !important; -webkit-text-fill-color: var(--ct-text) !important;
        opacity: 1 !important; cursor: text;
      }}

      /* Barra lateral */
      section[data-testid="stSidebar"] h3 {{ font-size: .8rem; letter-spacing: .06em;
        text-transform: uppercase; color: var(--ct-muted); }}
    </style>
    """, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Encabezados y KPIs
# ---------------------------------------------------------------------------
def page_header(title: str, subtitle: str = "") -> None:
    st.markdown("<div class='ct-eyebrow'>COTEAR · Informe de Actividad Comercial</div>",
                unsafe_allow_html=True)
    st.title(title, anchor=False)
    if subtitle:
        st.markdown(f"<div class='ct-subtitle'>{subtitle}</div>", unsafe_allow_html=True)
    if hasattr(st, "space"):
        st.space("small")


def section(title: str, subtitle: str = "") -> None:
    """Título de un grupo de tarjetas relacionadas."""
    sub = f"<div class='ct-section-sub'>{subtitle}</div>" if subtitle else ""
    st.markdown(f"<div class='ct-section'>{title}</div>{sub}", unsafe_allow_html=True)


def kpi(col, label: str, value, delta: dict, help: Optional[str] = None) -> None:
    """``delta`` = kwargs de ``utils.kpis.delta_kwargs`` / ``category_kwargs``."""
    col.metric(label, value, help=help, **delta)


# ---------------------------------------------------------------------------
# Tarjetas
# ---------------------------------------------------------------------------
def _title_html(title: str, subtitle: str = "") -> str:
    sub = f"<div class='ct-card-sub'>{subtitle}</div>" if subtitle else ""
    return f"<div class='ct-card-title'>{title}</div>{sub}"


def card(key: str, title: str = "", subtitle: str = ""):
    """Tarjeta simple (sin alternar datos). Usar como ``with ui.card(...):``."""
    box = st.container(border=True, key=f"card_{key}")
    if title:
        box.markdown(_title_html(title, subtitle), unsafe_allow_html=True)
    return box


def chart_card(key: str, title: str, render_chart: Callable[[], None],
               render_data: Callable[[], None], *, subtitle: str = "",
               controls: Optional[Callable[[], None]] = None) -> None:
    """Tarjeta con gráfico y su tabla de datos detrás.

    ``controls`` dibuja controles extra en el encabezado (ej. torta ⇄
    barras). Para que esos controles re-ejecuten sólo esta tarjeta, llamar
    a ``chart_card`` desde una función decorada con ``@st.fragment``.
    """
    with st.container(border=True, key=f"card_{key}"):
        with _call(st.container, horizontal=True, vertical_alignment="top",
                   key=f"cardhead_{key}", gap="small"):
            _call(st.markdown, _title_html(title, subtitle), unsafe_allow_html=True,
                  width="stretch")
            # Controles apilados a la derecha: el título conserva el ancho y
            # todas las tarjetas tienen el mismo alto de encabezado.
            with _call(st.container, horizontal_alignment="right", gap="small",
                       width="content", key=f"cardctl_{key}"):
                if controls:
                    controls()
                # on_change="ignore": alternar no ejecuta la app, sólo cambia el CSS.
                _call(
                    st.segmented_control, "Vista", [VIEW_CHART, VIEW_DATA], default=VIEW_CHART,
                    required=True, key=f"view_{key}", on_change="ignore",
                    label_visibility="collapsed", help=_VIEW_HELP,
                )
        with st.container(key=f"flip_{key}"):
            with st.container(key=f"front_{key}"):
                render_chart()
            with st.container(key=f"back_{key}"):
                render_data()


def raw_data(key: str, title: str, data, csv_df: pd.DataFrame, file_name: str,
             **dataframe_kwargs) -> None:
    """Datos crudos en un desplegable cerrado, con su botón de descarga."""
    with st.expander(title, icon=":material/dataset:", key=f"raw_{key}"):
        st.dataframe(data, hide_index=True, width="stretch", **dataframe_kwargs)
        _call(
            st.download_button, "Descargar datos (CSV)", data=csv_bytes(csv_df), file_name=file_name,
            mime="text/csv", icon=":material/download:", on_click="ignore",
            key=f"dl_{key}",
        )


# ---------------------------------------------------------------------------
# Gráficos
# ---------------------------------------------------------------------------
def echart(option: dict, *, height: int = 360, key: Optional[str] = None,
           alt: Optional[str] = None) -> None:
    if not hasattr(st, "echarts_chart"):
        st.error("Esta versión de Streamlit no tiene gráficos ECharts. "
                 "Actualizá con `pip install -U streamlit` (mínimo 1.66).")
        return
    _call(st.echarts_chart, option, height=height, key=key, alt=alt)


PLOTLY_STATIC = {"displayModeBar": False, "scrollZoom": False, "displaylogo": False}


def plotly_map(fig, *, key: Optional[str] = None) -> None:
    """Mapa Plotly sin barra de herramientas ni zoom (sólo tooltip)."""
    fig.update_layout(dragmode=False)
    st.plotly_chart(fig, width="stretch", config=PLOTLY_STATIC, key=key)
