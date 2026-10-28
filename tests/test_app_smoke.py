"""Prueba de humo: cada página abre sin excepciones con datos sintéticos.

Las lecturas y escrituras de Google Sheets y Bitrix se reemplazan por datos
falsos en memoria (sin red ni datos reales). No revisa el aspecto visual:
sólo detecta errores de ejecución antes de abrir la app.
"""

from datetime import datetime, timedelta

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from streamlit.util import calc_hash

from utils import bitrix, pending, sheets

_NOW = datetime.now()
_YM = _NOW.strftime("%Y-%m")

_BOT_ROWS = [
    # fecha_hora, wa_link, tipo, tipo_dup, área, nombre, resúmenes
    (
        _NOW.replace(day=2, hour=10),
        "5493416868753",
        "SI_RESUMEN",
        "Máquinas",
        "Ana Pérez",
        "Busca torno CNC",
    ),
    (
        _NOW.replace(day=3, hour=15),
        "5491145678901",
        "SI_RESUMEN",
        "Repuestos",
        "-",
        "Turcite para guías",
    ),
    (
        _NOW.replace(day=4, hour=22),
        "5493514567890",
        "SI_RESUMEN_G2",
        "Servicio Técnico",
        "Luis",
        "Falla en husillo",
    ),
    (_NOW.replace(day=5, hour=8), "34612345678", "SI_RESUMEN", "", "John", "Ofrece servicios"),
    (
        _NOW.replace(day=1, hour=9) - timedelta(days=3),
        "5492614567890",
        "SI_RESUMEN",
        "Máquinas",
        "Carla",
        "Plegadora",
    ),
]

_DEALS = pd.DataFrame(
    [
        (
            "1",
            "Torno CNC Travis",
            "Pendiente de cotizar",
            "",
            "Ana Pérez",
            "+54 9 341 686-8753",
            "WhatsApp",
            "",
        ),
        (
            "2",
            "Centro de mecanizado VMC",
            "Cotizado aguardando devolución",
            "Pendiente de cotizar",
            "Pedro",
            "+54 9 11 4567-8902",
            "Sitio Web",
            "",
        ),
        (
            "3",
            "Plegadora hidráulica",
            "Cerrado Perdido",
            "Cotizado aguardando devolución",
            "Carla",
            "+54 9 261 456-7890",
            "RRSS",
            "Precio alto",
        ),
        (
            "4",
            "Cortadora láser de chapa",
            "Cerrado Ganado",
            "En negociación",
            "Marta",
            "+54 9 351 111-2222",
            "Correo",
            "",
        ),
    ],
    columns=[
        "ID negocio",
        "Nombre negocio",
        "Etapa",
        "Etapa anterior",
        "Cliente",
        "Telefono",
        "Fuente",
        "Motivo de baja",
    ],
)


def _bot_raw() -> pd.DataFrame:
    rows = [
        [
            dt.strftime("%Y-%m-%d %H:%M:%S"),
            f"https://wa.me/{num}",
            tipo,
            tipo,
            area,
            nombre,
            resumen,
            "",
            "",
            "",
        ]
        for dt, num, tipo, area, nombre, resumen in _BOT_ROWS
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "fecha_hora",
            "wa_link",
            "tipo_contacto",
            "tipo_contacto_dup",
            "area_interes",
            "nombre",
            "resumen_1",
            "resumen_2",
            "resumen_3",
            "resumen_4",
        ],
    )


def _bitrix_month(ym: str) -> pd.DataFrame:
    df = _DEALS.copy()
    created = datetime.strptime(f"{ym}-02", "%Y-%m-%d").strftime("%d-%m-%y")
    moved = datetime.strptime(f"{ym}-10", "%Y-%m-%d").strftime("%d-%m-%y")
    df["ID negocio"] = ym + "-" + df["ID negocio"]
    df["Fecha creacion"], df["Fecha movimiento"] = created, moved
    df["Nuevo"], df["Tipo maquinaria"], df["Compania"] = "", "", ""
    return df[sheets.BITRIX_HEADERS]


def _month_tab(ym: str, kind: str) -> pd.DataFrame:
    if kind == "Bitrix":
        return _bitrix_month(ym)
    return pd.DataFrame(columns=sheets.BOT_HEADERS)


def _no_api(*_a, **_k):
    raise AssertionError("la prueba de humo no debe llamar a la API de Bitrix")


@pytest.fixture
def fake_io(monkeypatch, tmp_path):
    monkeypatch.setattr(pending, "PENDING_FILE", tmp_path / "pending_changes.json")
    monkeypatch.setattr(sheets, "read_source_bot_reports", _bot_raw)
    monkeypatch.setattr(sheets, "read_month_dataframe", _month_tab)
    monkeypatch.setattr(
        sheets, "read_months_batch", lambda yms, kind: {ym: _month_tab(ym, kind) for ym in yms}
    )
    monkeypatch.setattr(sheets, "get_last_bitrix_sync", lambda ym: datetime.now())
    index = _bitrix_month(_YM)
    index["_phone_sig"] = index["Telefono"].str.replace(r"\D", "", regex=True).str[-10:]
    index["Negocio"] = index["Nombre negocio"]
    monkeypatch.setattr(
        sheets, "read_phone_index", lambda: (index[sheets.PHONE_INDEX_HEADERS], datetime.now())
    )
    monkeypatch.setattr(sheets, "load_ignored_phones", lambda: set())
    for name in (
        "sync_month_bot",
        "write_month_dataframe",
        "set_last_bitrix_sync",
        "write_phone_index",
        "batch_upsert_bot_rows",
    ):
        monkeypatch.setattr(sheets, name, lambda *a, **k: None)
    for name in ("fetch_activity_for_month", "fetch_phone_index"):
        monkeypatch.setattr(bitrix, name, _no_api)


@pytest.mark.parametrize("url_path", ["reporte", "negocios", "clasificacion", "analisis", "ayuda"])
def test_page_runs(fake_io, url_path):
    at = AppTest.from_file("../app.py", default_timeout=30)
    at.run()
    at._page_hash = calc_hash(url_path)  # páginas de st.navigation con función, no archivo
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert not [w.value for w in at.warning if "prueba de humo" in w.value]
