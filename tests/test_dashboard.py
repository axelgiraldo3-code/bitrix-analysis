"""Pruebas de las funciones puras del dashboard: períodos, KPIs y gráficos."""
import json
from datetime import date

import pandas as pd
import pytest

from utils import charts, kpis, periods


# --- períodos -----------------------------------------------------------------
@pytest.mark.parametrize("ym, delta, expected", [
    ("2026-10", -1, "2026-09"), ("2026-01", -1, "2025-12"), ("2026-12", 1, "2027-01"),
])
def test_shift_months(ym, delta, expected):
    assert periods.shift_months(ym, delta) == expected


@pytest.mark.parametrize("start, end, kind, expected", [
    (date(2026, 10, 1), date(2026, 10, 31), "Mes", (date(2026, 9, 1), date(2026, 9, 30))),
    (date(2026, 1, 1), date(2026, 3, 31), "Trimestre", (date(2025, 10, 1), date(2025, 12, 31))),
    (date(2026, 7, 1), date(2026, 9, 30), "Trimestre", (date(2026, 4, 1), date(2026, 6, 30))),
    (date(2026, 1, 1), date(2026, 12, 31), "Año", (date(2025, 1, 1), date(2025, 12, 31))),
    (date(2026, 10, 5), date(2026, 10, 14), "Rango personalizado",
     (date(2026, 9, 25), date(2026, 10, 4))),
])
def test_previous_period(start, end, kind, expected):
    assert periods.previous_period(start, end, kind) == expected


def test_month_labels():
    assert periods.month_label("2026-10") == "oct-26"
    assert periods.month_label("2026-09", full=True) == "Septiembre 2026"


# --- KPIs ---------------------------------------------------------------------
def test_delta_positive_indicator():
    kw = kpis.delta_kwargs(10, 7, kpis.UP_GOOD, vs="vs. sep-26")
    assert kw == {"delta": "+3", "delta_color": "normal", "delta_description": "vs. sep-26"}


def test_delta_negative_indicator_is_inverse():
    kw = kpis.delta_kwargs(27.5, 30.1, kpis.DOWN_GOOD, unit=" p.p.", decimals=1)
    assert kw["delta"] == "-2.6 p.p." and kw["delta_color"] == "inverse"


def test_delta_zero_and_missing_previous():
    assert kpis.delta_kwargs(5, 5, kpis.UP_GOOD)["delta"] == 0
    kw = kpis.delta_kwargs(5, None, kpis.UP_GOOD)
    assert kw["delta"] is None and kw["delta_description"] == kpis.NO_PREVIOUS


def test_category_kpi_reports_previous_leader():
    top, kw = kpis.category_kwargs(pd.Series(["Córdoba"] * 3 + ["Salta"]),
                                   pd.Series(["Salta"] * 2 + ["Córdoba"]),
                                   kpis.UP_GOOD, "consultas")
    assert top == "Córdoba"
    assert kw["delta"] == "+2"
    assert kw["delta_description"] == "3 consultas · antes Salta"


def test_category_kpi_excludes_non_provinces():
    top, _ = kpis.category_kwargs(pd.Series(["Extranjero"] * 5 + ["Salta"]), None,
                                  kpis.UP_GOOD, "consultas", exclude={"Extranjero"})
    assert top == "Salta"


# --- gráficos -------------------------------------------------------------------
def test_charts_are_json_and_have_png_export():
    opts = [
        charts.donut(["A", "B"], [1, 2], ["#01498E", "#ffe5a0"], "f"),
        charts.hbar(["A", "B"], [3, 1], "#01498E", "f"),
        charts.stacked_bars(["x", "y"], [("A", [1, 0], "#01498E")], "f"),
    ]
    for opt in opts:
        json.dumps(opt)   # st.echarts_chart sólo acepta opciones JSON
        assert opt["toolbox"]["feature"]["saveAsImage"]["name"] == "f"
        assert "dataZoom" not in opt


def test_labels_readable_on_their_color():
    for color in ["#01498E", "#ffe5a0", "#ee00ff", "#E67E22", "#BDC3C7", "#11734b"]:
        assert charts.contrast_ratio(charts.label_color(color), color) >= 4.5


def test_stacked_bars_hide_zero_labels():
    opt = charts.stacked_bars(["x", "y"], [("A", [2, 0], "#01498E")], "f")
    data = opt["series"][0]["data"]
    assert "label" not in data[0] and data[1]["label"] == {"show": False}


def test_stacked_bars_no_white_border_and_hide_thin_labels():
    opt = charts.stacked_bars(["x"], [("A", [60], "#01498E"), ("B", [1], "#B10202")], "f")
    assert all("borderColor" not in s["itemStyle"] for s in opt["series"])
    assert opt["series"][1]["data"][0]["label"] == {"show": False}   # 1 de 61: muy fino
    assert "label" not in opt["series"][0]["data"][0]


def test_hbar_orders_largest_on_top():
    opt = charts.hbar(["Grande", "Chico"], [9, 1], "#01498E", "f")
    assert opt["yAxis"]["data"] == ["Chico", "Grande"]   # ECharts dibuja de abajo hacia arriba
