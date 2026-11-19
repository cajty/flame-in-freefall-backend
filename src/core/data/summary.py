from __future__ import annotations

import math
import re

import pandas as pd

from core.data.loader import CsvRepository
from core.data.registry import InvestigationAdapter
from models import (
    DateRange,
    NumericRange,
    O2Range,
    SummaryRecord,
    UnitRange,
)

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def js_round(value: float, digits: int = 0) -> float:
    factor = 10**digits
    return math.floor(value * factor + 0.5) / factor


def _values(frame: pd.DataFrame, column: str) -> list[str]:
    return [value for value in frame[column].tolist() if value != ""]


def _numbers(frame: pd.DataFrame, columns: tuple[tuple[str, float], ...]) -> list[float]:
    values: list[float] = []
    for column, scale in columns:
        for raw in frame[column].tolist():
            if raw == "":
                continue
            try:
                number = float(raw)
            except (TypeError, ValueError):
                continue
            if math.isfinite(number):
                values.append(number * scale)
    return values


def _unique_sorted(values: list[str]) -> list[str]:
    return sorted({value.strip() for value in values if value.strip()})


def _date_range(values: list[str]) -> DateRange | None:
    dates = _unique_sorted([value for value in values if ISO_DATE_RE.match(value)])
    if not dates:
        return None
    return DateRange(start=dates[0], end=dates[-1])


def _numeric_range(values: list[float], digits: int) -> NumericRange | None:
    if not values:
        return None
    return NumericRange(min=js_round(min(values), digits), max=js_round(max(values), digits))


def _count_rows(repo: CsvRepository, adapter: InvestigationAdapter) -> int:
    frames = repo.frames(adapter)
    if adapter.count_rule is None:
        return sum(len(source.frame) for source in frames)
    rule = adapter.count_rule
    return sum(
        int((source.frame[rule.column] == rule.value).sum()) for source in frames
    )


def summarize_investigation(
    repo: CsvRepository, adapter: InvestigationAdapter
) -> SummaryRecord:
    frames = repo.frames(adapter)

    o2_values: list[float] = []
    airflow_values: list[float] = []
    pressure_values: list[float] = []
    dates: list[str] = []
    fuels: list[str] = []

    for source, spec in zip(frames, adapter.files, strict=True):
        frame = source.frame
        o2_values.extend(_numbers(frame, spec.pick.o2))
        airflow_values.extend(_numbers(frame, spec.pick.airflow))
        pressure_values.extend(_numbers(frame, spec.pick.pressure))
        if spec.pick.date is not None:
            dates.extend(_values(frame, spec.pick.date))
        if spec.pick.fuel is not None:
            fuels.extend(_values(frame, spec.pick.fuel))

    o2 = _numeric_range(o2_values, 1)
    airflow = _numeric_range(airflow_values, 1)
    pressure = _numeric_range(pressure_values, 2)

    return SummaryRecord(
        files=[spec.path for spec in adapter.files],
        tests=_count_rows(repo, adapter),
        test_label=adapter.test_label,
        date=_date_range(dates),
        o2=(
            O2Range(min=o2.min, max=o2.max, unit="%", partial=adapter.o2_partial)
            if o2 is not None
            else None
        ),
        airflow=(
            UnitRange(min=airflow.min, max=airflow.max, unit="cm/s")
            if airflow is not None
            else None
        ),
        pressure=(
            UnitRange(min=pressure.min, max=pressure.max, unit=adapter.pressure_unit)
            if pressure is not None
            else None
        ),
        fuels=_unique_sorted(fuels),
        variables=list(adapter.variables),
    )
