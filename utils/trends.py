"""Tendencias mensuales y agrupaciones para los gráficos (funciones puras).

* ``leader_trend``: cuántos casos tuvo, mes a mes, la categoría líder del
  último mes (para la mini línea de los KPI de categoría).
* ``top_with_others``: las N filas más grandes de una tabla y el resto
  sumado en "Otros" (sólo para el gráfico; la tabla de datos va completa).
* ``by_month`` / ``weekday_hour_cells`` / ``daily_counts``: conteos por
  mes, por día de semana × hora y por día del mes.
"""
from __future__ import annotations

import calendar
from datetime import date, datetime
from typing import Optional, Sequence

import pandas as pd

from .kpis import top_category

OTHERS = "Otros"
WEEKDAYS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
WEEKDAYS_SHORT = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def leader_trend(series_by_month: Sequence[Optional[pd.Series]],
                 exclude: set[str] | None = None) -> list[Optional[int]]:
    """Para la categoría líder del último mes, su cantidad en cada mes.
    Un mes sin datos (``None``) queda como ``None``."""
    if not series_by_month or series_by_month[-1] is None:
        return []
    top, _ = top_category(series_by_month[-1], exclude)
    if top == "—":
        return []
    out: list[Optional[int]] = []
    for s in series_by_month:
        if s is None:
            out.append(None)
        else:
            out.append(int((s.fillna("").astype(str).str.strip() == top).sum()))
    return out


def top_with_others(pivot: pd.DataFrame, n: int = 6) -> pd.DataFrame:
    """Las ``n`` filas con mayor total y el resto sumado en una fila "Otros"
    (al final). Si sobra una sola fila, se muestra con su nombre."""
    if len(pivot) <= n + 1:
        return pivot
    order = pivot.sum(axis=1).sort_values(ascending=False, kind="stable").index
    top = pivot.loc[order[:n]]
    rest = pivot.loc[order[n:]].sum(axis=0).to_frame().T
    rest.index = [OTHERS]
    return pd.concat([top, rest])


def month_key(d) -> Optional[str]:
    if d is None or pd.isna(d):
        return None
    return f"{d.year:04d}-{d.month:02d}"


def by_month(dates: pd.Series, months: Sequence[str]) -> list[int]:
    """Cantidad de fechas que caen en cada 'YYYY-MM' de ``months``."""
    keys = dates.map(month_key)
    vc = keys.value_counts()
    return [int(vc.get(m, 0)) for m in months]


def _as_datetime(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce")


def weekday_hour_cells(dts: pd.Series) -> list[tuple[int, int, int]]:
    """[(hora 0-23, día 0=lunes, cantidad), ...] para las 7 × 24 celdas."""
    d = _as_datetime(dts).dropna()
    counts = pd.Series(list(zip(d.dt.hour, d.dt.weekday))).value_counts() if not d.empty \
        else pd.Series(dtype=int)
    return [(h, wd, int(counts.get((h, wd), 0))) for wd in range(7) for h in range(24)]


def daily_counts(dts: pd.Series, year_month: str,
                 today: Optional[date] = None) -> tuple[list[date], list[int]]:
    """(días, cantidad por día) del mes. En el mes en curso llega hasta hoy."""
    y, m = (int(x) for x in year_month.split("-"))
    last = calendar.monthrange(y, m)[1]
    today = today or datetime.now().date()
    if (y, m) == (today.year, today.month):
        last = today.day
    days = [date(y, m, i) for i in range(1, last + 1)]
    d = _as_datetime(dts).dropna().dt.date
    vc = d.value_counts()
    return days, [int(vc.get(day, 0)) for day in days]


def weekday_counts(dts: pd.Series, year_month: str,
                   today: Optional[date] = None) -> tuple[list[int], list[int]]:
    """(consultas, cantidad de días) por día de la semana (0=lunes) en el mes.

    La cantidad de días sirve para el promedio: un mes tiene 4 o 5 de cada
    día, y en el mes en curso sólo se cuentan los días hasta hoy."""
    days, counts = daily_counts(dts, year_month, today)
    totals, n_days = [0] * 7, [0] * 7
    for day, c in zip(days, counts):
        totals[day.weekday()] += c
        n_days[day.weekday()] += 1
    return totals, n_days
