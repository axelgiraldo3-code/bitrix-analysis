"""Smoke test end-to-end del setup: secrets, Sheets fuente/destino, Bitrix.

Uso:
    python verify_setup.py

No modifica datos productivos: sólo crea/borra una pestaña efímera
'__test__' en el libro destino.
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime

import streamlit as st

from utils import bitrix, sheets, cache


OK = "✅"
FAIL = "❌"
WARN = "⚠️ "


def _print(status: str, label: str, detail: str = "") -> None:
    line = f"{status} {label}"
    if detail:
        line += f" — {detail}"
    print(line)


def check(label: str, fn):
    try:
        result = fn()
        _print(OK, label, result if isinstance(result, str) else "")
        return result
    except Exception as e:
        _print(FAIL, label, f"{type(e).__name__}: {e}")
        traceback.print_exc()
        return None


def main() -> int:
    failed = 0

    print("=" * 60)
    print("VERIFICACIÓN DE SETUP — COTEAR App")
    print("=" * 60)

    # 1) Secrets
    print("\n[1] Secrets")
    try:
        sa = st.secrets["gcp_service_account"]
        _print(OK, "gcp_service_account presente", sa.get("client_email", "?"))
        gs = st.secrets["google_sheets"]
        src_id = (gs.get("source") or gs).get("spreadsheet_id")
        dst_id = (gs.get("dest") or {}).get("spreadsheet_id") or gs.get("dest_spreadsheet_id")
        _print(OK if src_id else FAIL, "google_sheets.source.spreadsheet_id",
               src_id or "FALTA")
        _print(OK if dst_id else FAIL, "google_sheets.dest.spreadsheet_id",
               dst_id or "FALTA")
        wh = st.secrets["bitrix24"]["webhook_url"]
        _print(OK, "bitrix24.webhook_url",
               wh[:50] + "…" if len(wh) > 50 else wh)
    except Exception as e:
        _print(FAIL, "Lectura de secrets", str(e))
        return 1

    # 2) Sheets fuente
    print("\n[2] Libro fuente (reportes bot)")
    raw = check("Lectura hoja fuente", sheets.read_source_bot_reports)
    if raw is not None:
        _print(OK, f"Filas leídas: {len(raw)}",
               f"primeras fechas: {raw['fecha_hora'].head(3).tolist() if len(raw) else '—'}")
    else:
        failed += 1

    # 3) Procesamiento
    print("\n[3] Procesamiento (limpieza + unificación)")
    if raw is not None:
        clean = check("clean_source", lambda: cache.clean_source(raw))
        if clean is not None:
            unified = check("unify_recent (<2 días)",
                            lambda: cache.unify_recent(clean))
            months = cache.available_year_months(unified) if unified is not None else []
            _print(OK, f"Meses detectados: {months[:6]}")

    # 4) Sheets destino: crear/borrar pestaña de prueba
    print("\n[4] Libro destino (persistencia)")
    try:
        import pandas as pd
        test_month = "__test__"
        test_df = pd.DataFrame([{
            "Fecha": "01-01-99",
            "Numero": "+54 9 351 555-0000",
            "Nombre": "Test",
            "Area de interes": "Maquinaria",
            "Resumen general": "smoke test",
            "Clasificacion interna": "SIN CLASIFICAR",
            "Tipo de contacto": "SI_RESUMEN",
        }])
        sheets.write_month_dataframe(test_month, "Bot", test_df)
        _print(OK, "Escritura pestaña __test___Bot")
        read_back = sheets.read_month_dataframe(test_month, "Bot")
        assert len(read_back) == 1 and read_back.iloc[0]["Nombre"] == "Test"
        _print(OK, "Re-lectura correcta")
        # Borrar pestaña
        sh = sheets._open_dest()
        try:
            ws = sh.worksheet("__test___Bot")
            sh.del_worksheet(ws)
            _print(OK, "Pestaña de prueba eliminada")
        except Exception as e:
            _print(WARN, "No se pudo borrar __test___Bot", str(e))
    except Exception as e:
        _print(FAIL, "Ciclo escribir/leer/borrar en libro destino", str(e))
        traceback.print_exc()
        failed += 1

    # 5) Bitrix
    print("\n[5] Bitrix24")
    try:
        stages = bitrix.fetch_stage_map()
        _print(OK, f"Stage map ({len(stages)} etapas)",
               f"'LOSE' → {stages.get('LOSE', '(no)')}")
    except Exception as e:
        _print(FAIL, "fetch_stage_map", str(e))
        failed += 1
    try:
        opts = bitrix.fetch_userfield_options()
        motivo_uf = opts.get("UF_CRM_1774960743170", {})
        _print(OK if motivo_uf else WARN,
               f"Motivo de baja: {len(motivo_uf)} opciones",
               f"'251' → {motivo_uf.get('251', '(no)')}")
    except Exception as e:
        _print(FAIL, "fetch_userfield_options", str(e))
        failed += 1
    try:
        print("  → Descargando deals (puede tardar por rate limit)…")
        deals = bitrix.fetch_all_deals()
        _print(OK, f"Deals totales: {len(deals)}")
        df = bitrix.deals_to_dataframe(deals)
        _print(OK, f"Deals filtrados (TYPE_ID=SALE): {len(df)}")
        if len(df):
            from collections import Counter
            etapas = Counter(df["Etapa"]).most_common(6)
            print(f"  Etapas: {etapas}")
            motivos = Counter(m for m in df["Motivo de baja"] if m).most_common(5)
            print(f"  Motivos de baja (top 5): {motivos}")
            print(f"  Sin teléfono: {(df['_phone_sig'] == '').sum()}/{len(df)}")
    except Exception as e:
        _print(FAIL, "Descarga/normalización de deals", str(e))
        traceback.print_exc()
        failed += 1

    print("\n" + "=" * 60)
    if failed == 0:
        print(f"{OK} Todo OK — la app debería funcionar")
        return 0
    print(f"{FAIL} {failed} fallo(s) — revisar arriba")
    return 1


if __name__ == "__main__":
    sys.exit(main())
