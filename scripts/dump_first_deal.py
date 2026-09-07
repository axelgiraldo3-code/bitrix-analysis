"""Vuelca el primer deal crudo de Bitrix a data/first_deal.json para inspección.

Uso:
    python -m scripts.dump_first_deal
"""
from __future__ import annotations

import json
from pathlib import Path

import requests
import streamlit as st


def main() -> None:
    base = st.secrets["bitrix24"]["webhook_url"].rstrip("/") + "/"
    r = requests.post(
        base + "crm.deal.list.json",
        json={"start": 0, "select": ["*", "UF_*"]},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    result = data.get("result", [])
    print(f"Total en esta página: {len(result)}  next: {data.get('next')}  total: {data.get('total')}")
    if not result:
        print("No hay deals.")
        return
    out = Path("data") / "first_deal.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(
        json.dumps(result[0], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Escrito: {out.resolve()}")
    print("\nClaves disponibles en el primer deal:")
    for k in sorted(result[0].keys()):
        print(f"  - {k}")


if __name__ == "__main__":
    main()
