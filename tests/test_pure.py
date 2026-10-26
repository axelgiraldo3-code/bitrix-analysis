"""Pruebas de las funciones puras (sin Sheets ni Bitrix)."""
from datetime import datetime

import pandas as pd
import pytest

from utils import cache, geo
from utils.machinery import classify_machinery
from utils.phone_ar import format_ar, is_foreign, province_of, significant_ar


# --- phone_ar ----------------------------------------------------------------
@pytest.mark.parametrize("raw, expected", [
    ("5493416868753", "+54 9 341 686-8753"),           # ejemplo del requisito
    ("https://wa.me/5491155891098", "+54 9 11 5589-1098"),
    ("3516868753", "+54 9 351 686-8753"),
    ("158995511824620", "158995511824620"),            # extranjero: sin formato
])
def test_format_ar(raw, expected):
    assert format_ar(raw) == expected


def test_significant_ar_compares_last_10_digits():
    assert significant_ar("5493416868753") == significant_ar("+54 341 686-8753") == "3416868753"
    assert significant_ar("5934987654321") == ""


@pytest.mark.parametrize("raw, prov", [
    ("5493516868753", "Córdoba"),
    ("5491155891098", "Buenos Aires"),
    ("5493416868753", "Santa Fe"),
    ("5492974170867", "Chubut"),
    ("5934987654321", "Extranjero"),
    ("", "Sin identificar"),
])
def test_province_of(raw, prov):
    assert province_of(raw) == prov


def test_is_foreign():
    assert is_foreign("5934987654321")
    assert not is_foreign("5493516868753")
    assert not is_foreign("")


# --- machinery ---------------------------------------------------------------
@pytest.mark.parametrize("title, cat", [
    ("Torno CNC Travis", "Torno CNC"),
    ("Torno paralelo", "Torno convencional"),
    ("Láser tubo y chapa 3kW", "Cortadora láser dual"),
    ("Laser de tubo", "Cortadora de tubo láser"),
    ("Laser fibra 3015", "Cortadora de chapa láser"),
    ("Plegadora hidráulica", "Plegadora"),
    ("Sierra sin fin", "Otro / Sin clasificar"),
])
def test_classify_machinery(title, cat):
    assert classify_machinery(title) == cat


# --- cache -------------------------------------------------------------------
def _bot_df(rows):
    df = pd.DataFrame(rows)
    df["_dt"] = df["_dt"].map(lambda s: datetime.fromisoformat(s))
    for c, v in {"Nombre": "", "Area de interes": "", "Clasificacion interna": "",
                 "Tipo de contacto": "SI_RESUMEN", "Fecha": ""}.items():
        df[c] = df[c].fillna(v) if c in df.columns else v
    df["_phone_sig"] = df["Numero"].map(significant_ar)
    return df


def test_unify_recent_collapses_same_number_same_month():
    df = _bot_df([
        {"Numero": "+54 9 351 686-8753", "_dt": "2026-10-01 10:00:00", "Resumen general": "A", "Nombre": "Juan"},
        {"Numero": "+54 9 351 686-8753", "_dt": "2026-10-20 10:00:00", "Resumen general": "B"},
        {"Numero": "+54 9 351 686-8753", "_dt": "2026-11-02 10:00:00", "Resumen general": "C"},
    ])
    out = cache.unify_recent(df)
    assert len(out) == 2
    octubre = out[out["_dt"].map(lambda d: d.month) == 10].iloc[0]
    assert octubre["Resumen general"].startswith("B")
    assert "A" in octubre["Resumen general"]
    assert octubre["Nombre"] == "Juan"


def test_apply_auto_rules_order():
    df = _bot_df([
        {"Numero": "+593987654321", "_dt": "2026-10-01 10:00:00", "Resumen general": ""},
        {"Numero": "+54 9 351 686-8753", "_dt": "2026-10-01 10:00:00", "Resumen general": ""},
        {"Numero": "+54 9 341 111-2222", "_dt": "2026-10-01 10:00:00", "Resumen general": "",
         "Tipo de contacto": "SI_RESUMEN_G2"},
        {"Numero": "+54 9 11 5589-1098", "_dt": "2026-10-01 10:00:00", "Resumen general": ""},
    ])
    out = cache.apply_auto_rules(df, {"3516868753", "3411112222"})
    assert out["Clasificacion interna"].tolist() == [
        cache.SIN_INTERES, cache.DERIVADO_BITRIX, cache.DERIVADO_TECNICA, cache.SIN_CLASIFICAR,
    ]


@pytest.mark.parametrize("area, bucket", [
    ("Repuestos", cache.AREA_REPUESTOS),
    ("Venta de máquinas", cache.AREA_MAQUINAS),
    ("Asistencia técnica", cache.AREA_TECNICA),
    ("", cache.AREA_NO_IDENTIFICADA),
])
def test_area_bucket(area, bucket):
    assert cache.area_bucket(area) == bucket


# --- geo ---------------------------------------------------------------------
def test_zone_counts_groups_small_zones_under_10_percent():
    zones = pd.Series(["Córdoba"] * 60 + ["Santa Fe"] * 30 + ["Salta"] * 4
                      + ["Jujuy"] * 3 + ["Chaco"] * 2 + ["Extranjero"] * 1)
    out = geo.zone_counts(zones)
    # Extranjero 1 + Chaco 2 + Jujuy 3 = 6 % < 10 %; sumar Salta llegaría a 10 %
    assert out["Zona"].tolist() == ["Córdoba", "Santa Fe", "Salta", "Otros"]
    assert out.set_index("Zona").loc["Otros", "Cantidad"] == 6
    assert out["Cantidad"].sum() == 100


def test_zone_counts_keeps_single_small_zone():
    zones = pd.Series(["Córdoba"] * 95 + ["Salta"] * 5)
    assert geo.zone_counts(zones)["Zona"].tolist() == ["Córdoba", "Salta"]


def test_top_province_ignores_foreign_and_unknown():
    zones = pd.Series(["Extranjero"] * 5 + ["Sin identificar"] * 4 + ["Córdoba"] * 2)
    assert geo.top_province(zones) == ("Córdoba", 2)


# --- mejoras oct-19 ------------------------------------------------------------
@pytest.mark.parametrize("title, cat", [
    ("Centro de torneado DMTG", "Torno CNC"),
    ("Torno C.N.C. 500", "Torno CNC"),
    ("VMC 850", "Centro de mecanizado"),
    ("Fresa CNC", "Fresadora CNC"),
    ("Cizalla hidráulica", "Cortadora guillotina"),
    ("Dobladora de caños", "Curvadora de tubos"),
    ("Tronzadora de caños", "Cortadora de caños a disco"),
    ("Taladro radial", "Centro de perforado"),
    ("Mandrinadora", "Alesadora"),
    ("Cortadora laser de caños", "Cortadora de tubo láser"),
])
def test_classify_machinery_synonyms(title, cat):
    assert classify_machinery(title) == cat


# Sinónimos tomados de los aliases del vault de Obsidian (Maquinas/)
@pytest.mark.parametrize("title, cat", [
    ("Torno slant bed 8\"", "Torno CNC"),
    ("Torno tipo suizo 32 mm", "Torno CNC"),
    ("Torno petrolero 9\" pasaje", "Torno CNC"),
    ("Torno petrolero convencional", "Torno convencional"),
    ("Torno pesado 630", "Torno convencional"),
    ("VTL 1600", "Torno CNC"),
    ("Centro de maquinado 5 ejes", "Centro de mecanizado"),
    ("Drill tap 600", "Centro de perforado"),
    ("Fresadora a control numérico", "Fresadora CNC"),
    ("Fresadora tipo Bridgeport", "Fresadora convencional"),
    ("Mandriladora horizontal", "Alesadora"),
    ("Boring mill 110", "Alesadora"),
    ("Brochadora hidráulica", "Brochadora"),
    ("Surface grinder 618", "Rectificadora CNC"),
    ("Tube bender CNC", "Curvadora de tubos"),
])
def test_classify_machinery_vault_aliases(title, cat):
    assert classify_machinery(title) == cat


def test_short_labels_trim_and_keep_unique():
    from utils.styling import short_labels
    out = short_labels([
        "Sin respuesta inicial (el interesado no responde ante el primer intento de contacto)",
        "Proyecto suspendido.",
        "Extraccion de informacion para comparar con competencia",
        "Extraccion de informacion para comprar China directo",
    ])
    assert out[0] == "Sin respuesta inicia…"
    assert out[1] == "Proyecto suspendido"
    assert all(len(x) <= 25 for x in out)  # 20 + "…" + sufijo " (2)"
    assert len(set(out)) == len(out)


def test_attach_deal_names():
    df = pd.DataFrame({"_phone_sig": ["3516868753", "1155891098", ""]})
    lookup = pd.DataFrame({"_phone_sig": ["3516868753"], "Negocio": ["Torno CNC Travis"]})
    assert cache.attach_deal_names(df, lookup)["Negocio"].tolist() == ["Torno CNC Travis", "", ""]


def test_province_map_only_active_provinces():
    zones = pd.Series(["Córdoba"] * 3 + ["Buenos Aires"] * 5 + ["Extranjero"] * 2)
    counts = geo.zone_counts(zones, threshold=0)
    fig = geo.province_map(counts, len(zones))
    choro, labels = fig.data
    assert sorted(choro.locations) == ["Buenos Aires", "Córdoba"]
    assert sorted(labels.text) == ["30,0 %", "50,0 %"]
    assert "Extranjero: 2 consultas (20,0 %)" in geo.outside_map_note(counts, len(zones))


def test_geojson_has_all_provinces():
    names = {f["id"] for f in geo.load_provinces()["features"]}
    assert len(names) == 23 and {"Buenos Aires", "Tierra del Fuego", "Córdoba"} <= names


# --- fuentes ------------------------------------------------------------------
@pytest.mark.parametrize("raw, canon", [
    ("Email", "Correo"), ("correo electrónico", "Correo"), ("WhatsApp", "WhatsApp"),
    ("Recomendación", "Por Recomendación"), ("Sitio web", "Sitio Web"),
    ("Redes sociales", "RRSS"), ("Derivación de otra área", "Derivación de otra area"),
    ("CLIENTE EXISTENTE", "Cliente existente"), ("", "Sin fuente"), (None, "Sin fuente"),
    ("Feria", "Feria"), ("OTROS", "Otro"), ("Casa Matriz", "Casa matriz"),
    ("impulso de ventas", "Impulso de venta"),
])
def test_canonical_source(raw, canon):
    from utils.branding import canonical_source
    assert canonical_source(raw) == canon


def test_source_colors_static():
    from utils.branding import SOURCE_ORDER, SOURCE_COLORS, source_color, COTEAR_GRAY
    assert set(SOURCE_ORDER) == set(SOURCE_COLORS)
    assert len(set(SOURCE_COLORS.values())) == len(SOURCE_COLORS)
    assert source_color("Otra cosa") == COTEAR_GRAY
    assert source_color("Sin fuente") == COTEAR_GRAY
    assert COTEAR_GRAY not in SOURCE_COLORS.values()


# --- motivos de baja ----------------------------------------------------------
def test_canonical_motivo_strips_explanation():
    from utils.branding import canonical_motivo
    assert canonical_motivo("Sin respuesta inicial (el interesado no responde ante el "
                            "primer intento de contacto)") == "Sin respuesta inicial"
    assert canonical_motivo("  precio alto ") == "Precio alto"
    assert canonical_motivo(None) == "" and canonical_motivo("") == ""


def test_motivo_colors_fixed_and_stable():
    from utils.branding import motivo_color
    assert motivo_color("Sin respuesta inicial") == motivo_color("SIN RESPUESTA INICIAL")
    assert motivo_color("Necesidad de producto no comercializado") == motivo_color(
        "Necesidad de producto")
    assert motivo_color("Motivo nuevo") == motivo_color("Motivo nuevo")


# --- gráficos nuevos ----------------------------------------------------------
def test_donut_equal_values_same_percent():
    import json
    from utils import charts
    opt = charts.donut(["a", "b", "c", "d", "e", "f", "g"], [3, 1, 1, 1, 1, 0, 0],
                       ["#01498E"] * 7, "x")
    labels = [d["label"]["formatter"] for d in opt["series"][0]["data"]]
    assert labels[1] == labels[2] == labels[3] == labels[4] == "14,3 %"
    json.dumps(opt)


def test_funnel_keeps_order_and_percent_of_first():
    from utils import charts
    opt = charts.funnel(["A", "B"], [10, 4], ["#01498E", "#11734B"], "x")
    s = opt["series"][0]
    assert s["sort"] == "none"
    assert "40,0 %" in s["data"][1]["label"]["formatter"]


def test_fmt_dec_uses_decimal_comma():
    from utils import charts
    assert charts.fmt_dec(14.26) == "14,3"
    assert charts.fmt_dec(3) == "3,0"
    assert charts.pct_label(52.5) == "52,5 %"


def test_stacked_bars_percent_labels_with_comma():
    from utils import charts
    opt = charts.stacked_bars(["Torno"], [("A", [33.33], "#01498E"), ("B", [66.67], "#11734B")],
                              "x", percent=True)
    item = opt["series"][0]["data"][0]
    assert item["label"]["formatter"] == "33,3 %"
    assert item["tooltip"]["formatter"] == "Torno<br/>A: 33,3 %"
    assert opt["tooltip"]["trigger"] == "item"

def test_heatmap_zero_cells_blank_and_tooltips():
    from utils import charts
    opt = charts.heatmap(["0h", "1h"], ["Lun"], [(0, 0, 0), (1, 0, 3)], "x",
                         tooltips=["t0", "t1"])
    data = opt["series"][0]["data"]
    assert data[0]["value"][2] == "-" and data[1]["value"][2] == 3.0
    assert data[1]["tooltip"]["formatter"] == "t1"


# --- tendencias ---------------------------------------------------------------
def test_leader_trend_follows_current_leader():
    import pandas as pd
    from utils.trends import leader_trend
    months = [pd.Series(["A", "B", "B"]), None, pd.Series(["A", "A", "B"])]
    assert leader_trend(months) == [1, None, 2]


def test_top_with_others_groups_rest():
    import pandas as pd
    from utils.trends import top_with_others, OTHERS
    p = pd.DataFrame({"x": [9, 8, 7, 6, 5, 4, 3, 2]}, index=list("abcdefgh"))
    out = top_with_others(p, 6)
    assert list(out.index) == list("abcdef") + [OTHERS]
    assert out.loc[OTHERS, "x"] == 5
    small = top_with_others(p.iloc[:7], 6)   # sobra una sola: se muestra con su nombre
    assert OTHERS not in small.index


def test_daily_counts_and_weekday_hour():
    from datetime import date, datetime
    import pandas as pd
    from utils.trends import daily_counts, weekday_hour_cells
    dts = pd.Series([datetime(2026, 9, 7, 10, 5), datetime(2026, 9, 7, 10, 50),
                     datetime(2026, 9, 8, 23, 0), None])
    days, counts = daily_counts(dts, "2026-09", today=date(2026, 10, 1))
    assert len(days) == 30 and counts[6] == 2 and counts[7] == 1
    cells = {(h, wd): v for h, wd, v in weekday_hour_cells(dts)}
    assert len(cells) == 7 * 24
    assert cells[(10, 0)] == 2 and cells[(23, 1)] == 1      # 7-sep-26 es lunes
    days, _ = daily_counts(dts, "2026-10", today=date(2026, 10, 23))
    assert len(days) == 23                                   # mes en curso: hasta hoy


# --- embudo -------------------------------------------------------------------
def test_stage_rank_lost_after_quote():
    from utils.funnel import stage_rank
    assert stage_rank("Pendiente de cotizar") == 1
    assert stage_rank("Cotizado aguardando devolución") == 2
    assert stage_rank("En negociación") == 3
    assert stage_rank("Cerrado Ganado") == 5
    assert stage_rank("Cerrado Perdido", "En negociacion") == 3
    assert stage_rank("Cerrado Perdido, motivo?", "Pendiente de cotizar") == 1


def test_funnel_counts_uses_most_advanced_deal():
    import pandas as pd
    from utils.funnel import match_deals, funnel_counts
    consultas = pd.DataFrame({
        "Clasificacion interna": ["DERIVADO A BITRIX", "DERIVADO A BITRIX", "SIN INTERES",
                                  "DERIVADO A BITRIX"],
        "_phone_sig": ["111", "222", "333", "444"],
    })
    deals = pd.DataFrame({
        "_phone_sig": ["111", "111", "222"],
        "Nombre negocio": ["Torno", "Torno 2", "Plegadora"],
        "Etapa": ["Pendiente de cotizar", "Cerrado Ganado", "Cerrado Perdido"],
        "Etapa anterior": ["", "", "Cotizado aguardando devolución"],
    })
    matched = match_deals(consultas, deals)
    assert funnel_counts(consultas, matched) == [4, 3, 2, 1]
    assert matched.set_index("_phone_sig").loc["111", "Negocio Bitrix"] == "Torno 2"


# --- semestre y mini línea -----------------------------------------------------
def test_semester_bounds_and_previous():
    from datetime import date
    from utils.periods import semester_bounds, previous_period, period_label
    assert semester_bounds(2026, 1) == (date(2026, 1, 1), date(2026, 6, 30))
    assert semester_bounds(2026, 2) == (date(2026, 7, 1), date(2026, 12, 31))
    assert previous_period(date(2026, 7, 1), date(2026, 12, 31), "Semestre") == \
        (date(2026, 1, 1), date(2026, 6, 30))
    assert previous_period(date(2026, 1, 1), date(2026, 6, 30), "Semestre") == \
        (date(2025, 7, 1), date(2025, 12, 31))
    assert period_label(date(2026, 7, 1), date(2026, 12, 31), "Semestre") == "S2 2026"


def test_sparkline_smooth_tooltip_and_gaps():
    import json
    from utils import charts
    opt = charts.sparkline(["May", "Jun", "Jul"], [None, 72, 52.5], "#21C354", unit=" %")
    s = opt["series"][0]
    assert s["smooth"] and s["data"] == ["-", 72, 52.5]
    assert opt["tooltip"]["formatter"] == "{b}"
    assert opt["xAxis"]["data"] == ["May - sin datos", "Jun - 72 %", "Jul - 52,5 %"]
    assert "toolbox" not in opt
    json.dumps(opt)


def test_timeseries_lines_are_smooth():
    from utils import charts
    opt = charts.timeseries(["a", "b"], [("x", [1, 2], "#000000")], "f")
    assert opt["series"][0]["smooth"]


def test_weekday_counts():
    from datetime import date, datetime
    import pandas as pd
    from utils.trends import weekday_counts
    dts = pd.Series([datetime(2026, 9, 7, 10, 5), datetime(2026, 9, 14, 9, 0),
                     datetime(2026, 9, 8, 23, 0), None])
    totals, n_days = weekday_counts(dts, "2026-09", today=date(2026, 10, 1))
    assert totals == [2, 1, 0, 0, 0, 0, 0]                   # 7 y 14-sep-26 son lunes
    assert sum(n_days) == 30 and n_days[0] == 4 and n_days[1] == 5
    _, n_days = weekday_counts(dts, "2026-10", today=date(2026, 10, 3))
    assert sum(n_days) == 3                                  # mes en curso: hasta hoy
