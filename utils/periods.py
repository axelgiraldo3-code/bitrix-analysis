"""Utilidades de períodos de tiempo para los filtros del Tab de Bitrix
(mes, trimestre, año, rango personalizado).
"""
from __future__ import annotations

import calendar
from datetime import date


def year_months_spanning(start: date, end: date) -> list[str]:
    """Lista de 'YYYY-MM' que cubren [start, end] (ambos inclusive)."""
    months: list[str] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def month_bounds(year_month: str) -> tuple[date, date]:
    """Primer y último día del mes 'YYYY-MM'."""
    y, m = (int(x) for x in year_month.split("-"))
    last_day = calendar.monthrange(y, m)[1]
    return date(y, m, 1), date(y, m, last_day)


def quarter_bounds(year: int, quarter: int) -> tuple[date, date]:
    """Primer y último día del trimestre (1-4) de un año."""
    assert 1 <= quarter <= 4, quarter
    start_month = (quarter - 1) * 3 + 1
    end_month = start_month + 2
    end_day = calendar.monthrange(year, end_month)[1]
    return date(year, start_month, 1), date(year, end_month, end_day)


def year_bounds(year: int) -> tuple[date, date]:
    """Primer y último día de un año calendario."""
    return date(year, 1, 1), date(year, 12, 31)


def current_quarter(today: date) -> int:
    """Trimestre (1-4) al que pertenece una fecha dada."""
    return (today.month - 1) // 3 + 1
