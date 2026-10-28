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


def semester_bounds(year: int, semester: int) -> tuple[date, date]:
    """Primer y último día del semestre (1: ene–jun, 2: jul–dic)."""
    assert semester in (1, 2), semester
    return (
        (date(year, 1, 1), date(year, 6, 30))
        if semester == 1
        else (date(year, 7, 1), date(year, 12, 31))
    )


def current_semester(today: date) -> int:
    return 1 if today.month <= 6 else 2


def year_bounds(year: int) -> tuple[date, date]:
    """Primer y último día de un año calendario."""
    return date(year, 1, 1), date(year, 12, 31)


def current_quarter(today: date) -> int:
    """Trimestre (1-4) al que pertenece una fecha dada."""
    return (today.month - 1) // 3 + 1


def shift_months(year_month: str, delta: int) -> str:
    """'YYYY-MM' desplazado ``delta`` meses (negativo = hacia atrás)."""
    y, m = (int(x) for x in year_month.split("-"))
    idx = y * 12 + (m - 1) + delta
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def previous_period(start: date, end: date, kind: str) -> tuple[date, date]:
    """Período inmediatamente anterior y de igual duración.

    ``kind``: "Mes" → mes anterior, "Trimestre" → trimestre anterior,
    "Semestre" → semestre anterior,
    "Año" → año anterior; cualquier otro (rango) → los mismos días
    corridos justo antes de ``start``.
    """
    from datetime import timedelta

    if kind == "Mes":
        return month_bounds(shift_months(f"{start.year:04d}-{start.month:02d}", -1))
    if kind == "Trimestre":
        q = current_quarter(start)
        return quarter_bounds(start.year - 1, 4) if q == 1 else quarter_bounds(start.year, q - 1)
    if kind == "Semestre":
        return (
            semester_bounds(start.year - 1, 2)
            if current_semester(start) == 1
            else semester_bounds(start.year, 1)
        )
    if kind == "Año":
        return year_bounds(start.year - 1)
    days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    return prev_end - timedelta(days=days - 1), prev_end


def range_label(start: date, end: date) -> str:
    """Rango para nombres de archivo: '01-10-26_a_31-10-26'."""
    return f"{start.strftime('%d-%m-%y')}_a_{end.strftime('%d-%m-%y')}"


MONTHS_ES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
MONTHS_ES_FULL = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]


def month_label(year_month: str, full: bool = False) -> str:
    """'2026-10' → 'oct-26' (o 'Octubre 2026' con ``full``)."""
    y, m = (int(x) for x in year_month.split("-"))
    if full:
        return f"{MONTHS_ES_FULL[m - 1].capitalize()} {y}"
    return f"{MONTHS_ES[m - 1]}-{y % 100:02d}"


def period_label(start: date, end: date, kind: str, short: bool = False) -> str:
    """Texto del período para títulos (``short`` para KPIs: 'sep-26')."""
    if kind == "Mes":
        return month_label(f"{start.year:04d}-{start.month:02d}", full=not short)
    if kind == "Trimestre":
        return f"T{current_quarter(start)} {start.year}"
    if kind == "Semestre":
        return f"S{current_semester(start)} {start.year}"
    if kind == "Año":
        return str(start.year)
    return f"{start.strftime('%d-%m-%y')} a {end.strftime('%d-%m-%y')}"
