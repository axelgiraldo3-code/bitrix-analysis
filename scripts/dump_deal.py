"""Vuelca un deal específico por ID y lista sus campos UF con valor.

Uso:
    python -m scripts.dump_deal 1799
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests
import streamlit as st


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: python -m scripts.dump_deal <ID>")
        sys.exit(1)
    deal_id = sys.argv[1]

    base = st.secrets["bitrix24"]["webhook_url"].rstrip("/") + "/"
    r = requests.post(base + "crm.deal.get.json", json={"id": deal_id}, timeout=30)
    r.raise_for_status()
    deal = r.json().get("result", {}) or {}

    out = Path("data") / f"deal_{deal_id}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(deal, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Escrito: {out.resolve()}\n")

    print("Campos UF (custom) con valor no vacío:")
    for k, v in deal.items():
        if k.startswith("UF_") and v not in (None, "", False, [], {}):
            print(f"  {k:35s} = {v!r}")

    print(f"\nSTAGE_ID={deal.get('STAGE_ID')!r}  "
          f"STAGE_SEMANTIC_ID={deal.get('STAGE_SEMANTIC_ID')!r}  "
          f"CATEGORY_ID={deal.get('CATEGORY_ID')!r}")


if __name__ == "__main__":
    main()
