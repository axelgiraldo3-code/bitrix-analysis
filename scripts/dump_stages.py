"""Lista los STAGE_ID de todos los pipelines (categorías) de deals.

Uso:
    python -m scripts.dump_stages

Salida: data/stages_map.json con {STAGE_ID: NAME} por pipeline.
"""
from __future__ import annotations

import json
from pathlib import Path

import requests
import streamlit as st


def _call(base: str, method: str, params: dict) -> dict:
    r = requests.post(base + method + ".json", json=params, timeout=30)
    r.raise_for_status()
    return r.json()


def main() -> None:
    base = st.secrets["bitrix24"]["webhook_url"].rstrip("/") + "/"

    # Categorías (pipelines)
    cats = _call(base, "crm.dealcategory.list", {"select": ["ID", "NAME"]}).get("result", [])
    print("Pipelines:")
    for c in cats:
        print(f"  ID={c['ID']:<3} NAME={c['NAME']}")
    # La categoría 0 (default) tiene stages tipo NEW, PREPARATION, WON, LOSE
    all_cats = [{"ID": "0", "NAME": "General (default)"}] + [
        {"ID": str(c["ID"]), "NAME": c["NAME"]} for c in cats
    ]

    result: dict[str, dict[str, str]] = {}
    for cat in all_cats:
        cat_id = cat["ID"]
        data = _call(base, "crm.dealcategory.stage.list", {"id": cat_id})
        stages = data.get("result", [])
        result[f"{cat_id} - {cat['NAME']}"] = {s["STATUS_ID"]: s["NAME"] for s in stages}

    out = Path("data") / "stages_map.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nEscrito: {out.resolve()}")
    for pipe, mp in result.items():
        print(f"\n[{pipe}]")
        for sid, name in mp.items():
            print(f"  {sid:40s} → {name}")


if __name__ == "__main__":
    main()
