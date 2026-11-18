"""Pruebas del informe mensual descargable (tablas y Markdown)."""

import re
from datetime import date

import pandas as pd
import pytest

from utils import informe, periods

SEP = periods.Period("Mes", date(2026, 9, 1), date(2026, 9, 30))


@pytest.fixture
def bot():
    return pd.DataFrame(
        {
            "Clasificacion interna": ["DERIVADO A BITRIX"] * 3
            + ["SIN RESPUESTAS"] * 5
            + ["SIN INTERES"] * 2
        }
    )


@pytest.fixture
def deals():
    return pd.DataFrame(
        {
            "Fuente": ["Redes sociales", "RRSS", "Sitio Web", "", "Email"],
            "Telefono": ["5491155891098", "5493416868753", "5491155891098", "", "5493516868753"],
            "Nombre negocio": ["Torno paralelo", "Torno CNC", "Torno", "Láser", "Fresadora"],
            "Tipo maquinaria": [
                "Torno convencional",
                "Torno CNC",
                "Torno convencional",
                "Cortadora de chapa láser",
                "Fresadora convencional",
            ],
            "Etapa": [
                "Cerrado Perdido",
                "Cerrado Perdido",
                "Cotizado aguardando devolución",
                "Pendiente de cotizar",
                "Cerrado Perdido",
            ],
            "Motivo de baja": [
                "Sin repuestas (no contesta)",
                "Sin respuesta inicial",
                "",
                "",
                "Precio alto",
            ],
            "Fecha creacion": ["05-09-26", "20-09-26", "01-09-26", "30-08-26", "12-09-26"],
        }
    )


def _sep(deals):
    return informe.period_deals(deals, SEP.start, SEP.end)


def test_period_deals_keeps_only_created_in_period(deals):
    d = _sep(deals)
    assert len(d) == 4  # el de agosto queda afuera
    assert d["_perdido"].sum() == 3
    assert d["Fuente"].tolist() == ["RRSS", "RRSS", "Sitio Web", "Correo"]
    assert d["Zona"].iloc[0] == "Buenos Aires"
    assert informe.period_deals(deals, date(2026, 7, 1), date(2026, 7, 31)).empty
    q3 = informe.period_deals(deals, date(2026, 7, 1), date(2026, 9, 30))
    assert len(q3) == 5


def test_source_table(deals):
    t = informe.source_table(_sep(deals))
    assert t.columns.tolist() == ["Fuente", "Cantidad", "%"]
    assert t.iloc[0].tolist() == ["RRSS", 2, 50.0]
    assert t["Cantidad"].sum() == 4


def test_motivos_and_no_response(deals):
    t = informe.motivos_table(_sep(deals))
    assert t["Cantidad"].sum() == 3
    assert t["Motivo de baja"].map(informe.is_no_response).sum() == 2


def test_efficiency_and_stage_order(deals):
    d = _sep(deals)
    eff = informe.efficiency_table(d).set_index("Fuente")
    assert eff.loc["RRSS", "Perdidos"] == 2 and eff.loc["RRSS", "Tasa de pérdida"] == 100.0
    stages = informe.stage_table(d)["Etapa"].tolist()
    assert stages == ["Cotizado aguardando devolución", "Cerrado Perdido"]


def test_zone_table_keeps_unknown_apart_from_others():
    zones = (
        ["Buenos Aires"] * 18 + ["Santa Fe"] * 12 + ["La Pampa", "Salta"] + ["Sin identificar"] * 2
    )
    t, others = informe.zone_table(pd.DataFrame({"Zona": zones}))
    assert t["Provincia"].tolist() == ["Buenos Aires", "Santa Fe", "Otros", "Sin identificar"]
    assert sorted(others) == ["La Pampa", "Salta"]
    assert t["%"].iloc[-1] == pytest.approx(5.9)


def test_md_table_formats_percent_and_total():
    df = pd.DataFrame({"Fuente": ["RRSS"], "Cantidad": [3], "%": [13.2]})
    md = informe.md_table(df, pct_cols=("%",), total_row={"Fuente": "TOTAL", "Cantidad": 3})
    assert md.splitlines() == [
        "| Fuente | Cantidad | % |",
        "|---|---:|---:|",
        "| RRSS | 3 | 13,2 % |",
        "| **TOTAL** | **3** |  |",
    ]


def test_markdown_links_app_chart_names(bot, deals):
    md = informe.build(bot, deals, SEP, [10, 3, 2, 1])
    assert md.startswith("# REPORTE DE ACTIVIDAD COMERCIAL - SEPTIEMBRE 2026")
    links = re.findall(r"!\[[^\]]*\]\(img/([^)]+)\)", md)
    assert links == [
        "clasificaciones_2026-09.svg",
        "embudo_2026-09.svg",
        "negocios_por_fuente_01-09-26_a_30-09-26.svg",
        "provincias_negocios_01-09-26_a_30-09-26.svg",
        "motivos_baja_01-09-26_a_30-09-26.svg",
        "fuentes_etapa_01-09-26_a_30-09-26.svg",
        "demanda_productos_01-09-26_a_30-09-26.svg",
    ]
    assert md.count("%% Descargar de:") == len(links)
    assert "A la fecha de corte, hay **3 negocios" in md
    assert "creados en el mes" not in md and "(3 de 10)" not in md
    assert "| Clasificación | Cantidad | Porcentaje | Descripción |" in md


def test_class_table_fixed_order():
    df = pd.DataFrame(
        {
            "Clasificacion interna": ["SIN RESPUESTAS"] * 5
            + ["SIN CLASIFICAR"]
            + ["DERIVADO A RRHH", "DERIVADO A BITRIX", "VENTA DE REPUESTOS"]
            + ["DERIVADO A TÉCNICA"] * 2
        }
    )
    assert informe.class_table(df)["Clasificación"].tolist() == [
        "DERIVADO A BITRIX",
        "DERIVADO A TÉCNICA",
        "VENTA DE REPUESTOS",
        "DERIVADO A RRHH",
        "SIN RESPUESTAS",
        "SIN CLASIFICAR",
    ]


def test_build_without_deals(bot):
    md = informe.build(bot, pd.DataFrame(), SEP)
    assert "Sin negocios de Bitrix" in md
    assert re.findall(r"\(img/([^)]+)\)", md) == ["clasificaciones_2026-09.svg"]


def test_funnel_table():
    t = informe.funnel_table([10, 4, 2, 1])
    assert t["% de las consultas"].tolist() == [100.0, 40.0, 20.0, 10.0]
    assert t["% de la etapa anterior"].tolist()[1:] == [40.0, 50.0, 50.0]
    md = informe.md_table(t, pct_cols=("% de las consultas", "% de la etapa anterior"))
    assert "| Consultas del mes | 10 | 100,0 % | — |" in md and "|---|---:|---:|---:|" in md


def test_build_without_funnel_skips_section(bot, deals):
    md = informe.build(bot, deals, SEP)
    assert "1.2 De la consulta a la venta" not in md and "embudo_" not in md


def test_build_month_has_period_callout(bot, deals):
    md = informe.build(bot, deals, SEP, today=date(2026, 11, 17))
    assert md.splitlines()[2:4] == [
        "> [!info] Período analizado",
        "> Septiembre 2026 · 01-09-26 a 30-09-26",
    ]
    assert "durante el mes de septiembre" in md
    assert informe.file_name(SEP) == "Reporte de actividad 2026-09.md"


@pytest.mark.parametrize(
    "period, title, detail, phrase, slug",
    [
        (
            periods.Period("Trimestre", date(2026, 7, 1), date(2026, 9, 30)),
            "T3 2026",
            "Tercer trimestre de 2026 (T3) · julio a septiembre · 01-07-26 a 30-09-26",
            "durante el tercer trimestre de 2026",
            "2026-T3",
        ),
        (
            periods.Period("Semestre", date(2026, 7, 1), date(2026, 12, 31)),
            "S2 2026",
            "Segundo semestre de 2026 (S2) · julio a diciembre · 01-07-26 a 31-12-26 "
            "(en curso, datos al 17-11-26)",
            "durante el segundo semestre de 2026",
            "2026-S2",
        ),
        (
            periods.Period("Año", date(2026, 1, 1), date(2026, 12, 31)),
            "AÑO 2026",
            "Año 2026 · enero a diciembre · 01-01-26 a 31-12-26 (en curso, datos al 17-11-26)",
            "durante el año 2026",
            "2026",
        ),
        (
            periods.Period("Rango personalizado", date(2026, 9, 5), date(2026, 9, 14)),
            "05-09-26 A 14-09-26",
            "Del 05-09-26 al 14-09-26 (10 días)",
            "durante el período del 05-09-26 al 14-09-26",
            "05-09-26_a_14-09-26",
        ),
    ],
)
def test_build_other_periods(bot, deals, period, title, detail, phrase, slug):
    md = informe.build(bot, deals, period, [10, 3, 2, 1], today=date(2026, 11, 17))
    lines = md.splitlines()
    assert lines[0] == f"# REPORTE DE ACTIVIDAD COMERCIAL - {title}"
    assert lines[2:4] == ["> [!info] Período analizado", f"> {detail}"]
    assert phrase in md
    assert f"datos del {period.noun}" in md and f"| Consultas del {period.noun} | 10 |" in md
    links = re.findall(r"\(img/([^)]+)\)", md)
    assert links[:2] == [f"clasificaciones_{slug}.svg", f"embudo_{slug}.svg"]
    assert informe.file_name(period) == f"Reporte de actividad {slug}.md"


def test_stacked_bars_horizontal():
    from utils import charts

    opt = charts.stacked_bars(
        ["RRSS", "Web"], [("Perdido", [3, 1], "#f11716")], "f", horizontal=True
    )
    assert opt["yAxis"]["type"] == "category" and opt["yAxis"]["inverse"] is True
    assert opt["xAxis"]["type"] == "value"
    assert opt["yAxis"]["data"] == ["RRSS", "Web"]
