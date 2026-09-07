"""Lista los userfields custom (UF_CRM_*) de deals con su LABEL y opciones de lista.

Uso:
    python -m scripts.dump_userfields
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests
import streamlit as st


def _call(base: str, method: str, params: dict) -> dict:
    r = requests.post(base + method + ".json", json=params, timeout=30)
    r.raise_for_status()
    return r.json()


def main() -> None:
    base = st.secrets["bitrix24"]["webhook_url"].rstrip("/") + "/"

    # Trae metadata de todos los userfields de la entidad DEAL
    data = _call(base, "crm.deal.userfield.list", {})
    fields = data.get("result", [])

    print(f"Userfields custom encontrados: {len(fields)}\n")

    out: dict[str, dict] = {}
    for f in fields:
        fid = f.get("FIELD_NAME", "")
        label = ""
        edit = f.get("EDIT_FORM_LABEL")
        list_label = f.get("LIST_COLUMN_LABEL")
        if isinstance(edit, dict):
            label = edit.get("es") or edit.get("en") or next(iter(edit.values()), "")
        elif edit:
            label = str(edit)
        if not label and isinstance(list_label, dict):
            label = list_label.get("es") or next(iter(list_label.values()), "")

        entry = {
            "label": label,
            "type": f.get("USER_TYPE_ID"),
            "list_options": {},
        }

        # Si es una lista enumerada, traer sus items
        if f.get("USER_TYPE_ID") == "enumeration":
            items = f.get("LIST") or []
            entry["list_options"] = {str(it["ID"]): it.get("VALUE", "") for it in items}

        out[fid] = entry
        print(f"{fid:35s}  [{entry['type']:12s}]  {label}")
        if entry["list_options"]:
            for k, v in entry["list_options"].items():
                marker = "  ← Sin repuestas" if "sin re" in v.lower() else ""
                print(f"      {k:5s} → {v}{marker}")
        print()

    dst = Path("data") / "userfields.json"
    dst.parent.mkdir(exist_ok=True)
    dst.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nEscrito: {dst.resolve()}")


if __name__ == "__main__":
    main()
