"""Pruebas del informe mensual descargable (tablas y Markdown)."""

import re

import pandas as pd
import pytest

from utils import informe


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


def test_month_deals_keeps_only_created_in_month(deals):
    d = informe.month_deals(deals, "2026-09")
    assert len(d) == 4  # el de agosto queda afuera
    assert d["_perdido"].sum() == 3
    assert d["Fuente"].tolist() == ["RRSS", "RRSS", "Sitio Web", "Correo"]
    assert d["Zona"].iloc[0] == "Buenos Aires"
    assert informe.month_deals(deals, "2026-07").empty


def test_source_table(deals):
    t = informe.source_table(informe.month_deals(deals, "2026-09"))
    assert t.columns.tolist() == ["Fuente", "Cantidad", "%"]
    assert t.iloc[0].tolist() == ["RRSS", 2, 50.0]
    assert t["Cantidad"].sum() == 4


def test_motivos_and_no_response(deals):
    t = informe.motivos_table(informe.month_deals(deals, "2026-09"))
    assert t["Cantidad"].sum() == 3
    assert t["Motivo de baja"].map(informe.is_no_response).sum() == 2


def test_efficiency_and_stage_order(deals):
    d = informe.month_deals(deals, "2026-09")
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
    md = informe.build(bot, deals, "2026-09", [10, 3, 2, 1])
    assert md.startswith("# REPORTE DE ACTIVIDAD COMERCIAL - SEPTIEMBRE 2026")
    links = re.findall(r"!\[[^\]]*\]\(img/([^)]+)\)", md)
    assert links == [
        "clasificaciones_2026-09.png",
        "embudo_2026-09.png",
        "negocios_por_fuente_01-09-26_a_30-09-26.png",
        "provincias_negocios_01-09-26_a_30-09-26.png",
        "motivos_baja_01-09-26_a_30-09-26.png",
        "fuentes_etapa_01-09-26_a_30-09-26.png",
        "demanda_productos_01-09-26_a_30-09-26.png",
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
    md = informe.build(bot, pd.DataFrame(), "2026-09")
    assert "Sin negocios de Bitrix" in md
    assert re.findall(r"\(img/([^)]+)\)", md) == ["clasificaciones_2026-09.png"]


def test_funnel_table():
    t = informe.funnel_table([10, 4, 2, 1])
    assert t["% de las consultas"].tolist() == [100.0, 40.0, 20.0, 10.0]
    assert t["% de la etapa anterior"].tolist()[1:] == [40.0, 50.0, 50.0]
    md = informe.md_table(t, pct_cols=("% de las consultas", "% de la etapa anterior"))
    assert "| Consultas del mes | 10 | 100,0 % | — |" in md and "|---|---:|---:|---:|" in md


def test_build_without_funnel_skips_section(bot, deals):
    md = informe.build(bot, deals, "2026-09")
    assert "1.2 De la consulta a la venta" not in md and "embudo_" not in md


def test_stacked_bars_horizontal():
    from utils import charts

    opt = charts.stacked_bars(
        ["RRSS", "Web"], [("Perdido", [3, 1], "#f11716")], "f", horizontal=True
    )
    assert opt["yAxis"]["type"] == "category" and opt["yAxis"]["inverse"] is True
    assert opt["xAxis"]["type"] == "value"
    assert opt["yAxis"]["data"] == ["RRSS", "Web"]
