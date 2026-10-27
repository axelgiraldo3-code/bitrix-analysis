"""Pruebas del informe mensual descargable (tablas, Markdown y ZIP)."""
import io
import re
import zipfile

import pandas as pd
import pytest

from utils import informe


@pytest.fixture
def bot():
    return pd.DataFrame({"Clasificacion interna":
                         ["DERIVADO A BITRIX"] * 3 + ["SIN RESPUESTAS"] * 5 + ["SIN INTERES"] * 2})


@pytest.fixture
def deals():
    return pd.DataFrame({
        "Fuente": ["Redes sociales", "RRSS", "Sitio Web", "", "Email"],
        "Telefono": ["5491155891098", "5493416868753", "5491155891098", "", "5493516868753"],
        "Nombre negocio": ["Torno paralelo", "Torno CNC", "Torno", "Láser", "Fresadora"],
        "Tipo maquinaria": ["Torno convencional", "Torno CNC", "Torno convencional",
                            "Cortadora de chapa láser", "Fresadora convencional"],
        "Etapa": ["Cerrado Perdido", "Cerrado Perdido", "Cotizado aguardando devolución",
                  "Pendiente de cotizar", "Cerrado Perdido"],
        "Motivo de baja": ["Sin repuestas (no contesta)", "Sin respuesta inicial", "", "",
                           "Precio alto"],
        "Fecha creacion": ["05-09-26", "20-09-26", "01-09-26", "30-08-26", "12-09-26"],
    })


def test_month_deals_keeps_only_created_in_month(deals):
    d = informe.month_deals(deals, "2026-09")
    assert len(d) == 4                                # el de agosto queda afuera
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
    zones = ["Buenos Aires"] * 18 + ["Santa Fe"] * 12 + ["La Pampa", "Salta"] + \
        ["Sin identificar"] * 2
    t, others = informe.zone_table(pd.DataFrame({"Zona": zones}))
    assert t["Provincia"].tolist() == ["Buenos Aires", "Santa Fe", "Otros", "Sin identificar"]
    assert sorted(others) == ["La Pampa", "Salta"]
    assert t["%"].iloc[-1] == pytest.approx(5.9)


def test_md_table_formats_percent_and_total():
    df = pd.DataFrame({"Fuente": ["RRSS"], "Cantidad": [3], "%": [13.2]})
    md = informe.md_table(df, pct_cols=("%",), total_row={"Fuente": "TOTAL", "Cantidad": 3})
    assert md.splitlines() == ["| Fuente | Cantidad | % |", "|---|---:|---:|",
                               "| RRSS | 3 | 13,2 % |", "| **TOTAL** | **3** |  |"]


def test_zip_has_markdown_and_every_linked_image(bot, deals):
    z = zipfile.ZipFile(io.BytesIO(informe.build_zip(bot, deals, "2026-09")))
    names = set(z.namelist())
    md = z.read("informe_2026-09/Reporte de actividad 2026-09.md").decode("utf-8")
    assert md.startswith("# REPORTE DE ACTIVIDAD COMERCIAL - SEPTIEMBRE 2026")
    links = re.findall(r"!\[[^\]]*\]\((img/[^)]+)\)", md)
    assert "img/07_pipeline.png" in links and len(links) == 7
    for link in links:
        assert f"informe_2026-09/{link}" in names
        assert z.read(f"informe_2026-09/{link}").startswith(b"\x89PNG")
    assert "A la fecha de corte, hay **3 negocios" in md
    assert "creados en el mes" not in md and "(3 de 10)" not in md
    assert "| Clasificación | Cantidad | Porcentaje | Descripción |" in md


def test_build_without_deals(bot):
    md, images = informe.build(bot, pd.DataFrame(), "2026-09")
    assert "Sin negocios de Bitrix" in md
    assert list(images) == ["01_calidad_consultas.png"]
