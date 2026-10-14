"""Análisis geográfico: conteo de zonas (provincias) con agrupación en 'Otros'."""
from __future__ import annotations

import pandas as pd

from .phone_ar import ZONE_FOREIGN, ZONE_UNKNOWN

OTHERS = "Otros"
NON_PROVINCE_ZONES = {ZONE_FOREIGN, ZONE_UNKNOWN, OTHERS}


def zone_counts(zones: pd.Series, threshold: float = 0.10) -> pd.DataFrame:
    """Tabla [Zona, Cantidad, %] ordenada de mayor a menor.

    Las zonas más chicas se agrupan en 'Otros' mientras la suma de las
    agrupadas quede por debajo de `threshold` (10 % por defecto). Sólo se
    agrupa si son al menos dos zonas; una zona sola conserva su nombre.
    """
    s = zones.fillna("").astype(str).str.strip().replace("", ZONE_UNKNOWN)
    counts = s.value_counts()
    if counts.empty:
        return pd.DataFrame(columns=["Zona", "Cantidad", "%"])
    total = int(counts.sum())

    grouped: list[str] = []
    acc = 0
    for zone, n in counts.sort_values(kind="stable").items():  # de menor a mayor
        if (acc + n) / total < threshold:
            grouped.append(zone)
            acc += n
        else:
            break

    if len(grouped) >= 2:
        counts = counts.drop(grouped)
        counts[OTHERS] = acc

    out = counts.sort_values(ascending=False, kind="stable").reset_index()
    out.columns = ["Zona", "Cantidad"]
    # 'Otros' siempre al final
    out = pd.concat([out[out["Zona"] != OTHERS], out[out["Zona"] == OTHERS]],
                    ignore_index=True)
    out["%"] = (out["Cantidad"] / total * 100).round(1)
    return out


def top_province(zones: pd.Series) -> tuple[str, int]:
    """Provincia con más registros, sin contar Extranjero / Sin identificar."""
    s = zones.fillna("").astype(str).str.strip()
    s = s[(s != "") & ~s.isin(NON_PROVINCE_ZONES)]
    if s.empty:
        return "—", 0
    vc = s.value_counts()
    return str(vc.index[0]), int(vc.iloc[0])
