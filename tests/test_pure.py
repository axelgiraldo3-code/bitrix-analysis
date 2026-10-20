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
    assert sorted(labels.text) == ["30.0%", "50.0%"]
    assert "Extranjero: 2" in geo.outside_map_note(counts, len(zones))


def test_geojson_has_all_provinces():
    names = {f["id"] for f in geo.load_provinces()["features"]}
    assert len(names) == 23 and {"Buenos Aires", "Tierra del Fuego", "Córdoba"} <= names
