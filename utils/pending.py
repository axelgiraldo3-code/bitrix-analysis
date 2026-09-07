"""Cola de cambios de clasificación pendientes de sincronizar a Sheets.

- Fuente de verdad en la sesión: st.session_state["pending_changes"]
  (dict {Numero: {"Fecha", "Nombre", "Clasificacion interna", "ts"}}).
- Red de seguridad en disco: data/pending_changes.json. Se escribe en cada
  add/remove/clear para poder recuperar la cola si el proceso muere antes
  de que el usuario haga "Sincronizar".

En Streamlit Cloud el disco es efímero pero dura mientras el container vive
(horas típicamente). En local sobrevive reinicios de la app.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st


PENDING_FILE = Path("data") / "pending_changes.json"
_STATE_KEY = "pending_changes"
_LOADED_KEY = "_pending_loaded_from_disk"


# ---------------------------------------------------------------------------
# Persistencia en disco
# ---------------------------------------------------------------------------
def _read_disk() -> dict[str, dict]:
    if not PENDING_FILE.exists():
        return {}
    try:
        with PENDING_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        # Filtrar entradas malformadas
        return {
            str(k): v for k, v in data.items()
            if isinstance(v, dict) and "Clasificacion interna" in v
        }
    except (json.JSONDecodeError, OSError):
        return {}


def _write_disk(pending: dict[str, dict]) -> None:
    try:
        PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PENDING_FILE.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)
        os.replace(tmp, PENDING_FILE)
    except OSError:
        # Si no se puede escribir a disco, seguimos con session_state solamente.
        pass


# ---------------------------------------------------------------------------
# API pública (opera sobre session_state y espeja a disco)
# ---------------------------------------------------------------------------
def get() -> dict[str, dict]:
    """Devuelve el dict de cambios pendientes (referencia viva)."""
    if _STATE_KEY not in st.session_state:
        st.session_state[_STATE_KEY] = {}
    return st.session_state[_STATE_KEY]


def load_from_disk_once() -> dict[str, dict]:
    """Levanta la cola del disco a session_state una sola vez por sesión.

    Devuelve los ítems que estaban en disco (para poder mostrarlos al usuario
    en un diálogo de confirmación). En corridas subsiguientes devuelve {}.
    """
    if st.session_state.get(_LOADED_KEY):
        return {}
    st.session_state[_LOADED_KEY] = True
    disk = _read_disk()
    if disk:
        # Fusionar con lo que ya haya en session_state (normalmente vacío)
        current = get()
        for k, v in disk.items():
            current.setdefault(k, v)
    return disk


def add(numero: str, payload: dict) -> None:
    """Agrega o reemplaza un cambio pendiente por número."""
    p = get()
    p[str(numero)] = {
        **payload,
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    _write_disk(p)


def remove(numeros: list[str]) -> None:
    """Quita entradas por número (post-flush exitoso, o descarte parcial)."""
    p = get()
    for n in numeros:
        p.pop(str(n), None)
    _write_disk(p)


def clear() -> None:
    """Vacía toda la cola."""
    st.session_state[_STATE_KEY] = {}
    _write_disk({})


def count() -> int:
    return len(get())


def apply_to_df(df: pd.DataFrame) -> pd.DataFrame:
    """Overlay: superpone las clasificaciones pendientes sobre un DataFrame
    con columnas 'Numero' y 'Clasificacion interna'. Útil para que la UI
    refleje los cambios en cola aunque todavía no estén en Sheets."""
    p = get()
    if not p or df.empty or "Numero" not in df.columns:
        return df
    out = df.copy()
    for i in out.index:
        num = str(out.at[i, "Numero"])
        if num in p:
            out.at[i, "Clasificacion interna"] = p[num]["Clasificacion interna"]
    return out


def as_dataframe() -> pd.DataFrame:
    """Vista tabular de la cola para mostrar 'ver pendientes'."""
    p = get()
    if not p:
        return pd.DataFrame(columns=["Numero", "Nombre", "Fecha",
                                     "Clasificacion interna", "ts"])
    rows = []
    for num, v in p.items():
        rows.append({
            "Numero": num,
            "Nombre": v.get("Nombre", ""),
            "Fecha": v.get("Fecha", ""),
            "Clasificacion interna": v.get("Clasificacion interna", ""),
            "ts": v.get("ts", ""),
        })
    return pd.DataFrame(rows).sort_values("ts", ascending=False)
