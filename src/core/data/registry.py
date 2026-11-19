from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ATM_PER_BAR = 0.9869232667160128
ATM_PER_KPA = 1 / 101.325

ADAPTERS_PATH = Path(__file__).resolve().parents[3] / "data" / "reference" / "adapters.json"


@dataclass(frozen=True)
class Pick:
    date: str | None = None
    o2: tuple[tuple[str, float], ...] = ()
    airflow: tuple[tuple[str, float], ...] = ()
    pressure: tuple[tuple[str, float], ...] = ()
    fuel: str | None = None


@dataclass(frozen=True)
class FileSpec:
    path: str
    pick: Pick
    # Canonical row metric -> (source column, scale). Only used by row-level tools.
    canonical: dict[str, tuple[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class CountRule:
    column: str
    value: str


@dataclass(frozen=True)
class InvestigationAdapter:
    id: str
    files: tuple[FileSpec, ...]
    variables: tuple[str, ...]
    test_label: str = "tests"
    pressure_unit: str = "atm"
    o2_partial: bool = False
    planned_only: bool = False
    count_rule: CountRule | None = None


def _column_scales(raw: Any) -> tuple[tuple[str, float], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise TypeError("pick columns must be a list")
    columns: list[tuple[str, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise TypeError("pick column must be an object")
        column = item.get("column")
        if not isinstance(column, str) or not column:
            raise ValueError("pick column needs a non-empty column name")
        columns.append((column, float(item.get("scale", 1.0))))
    return tuple(columns)


def _pick(raw: Any) -> Pick:
    if raw is None:
        return Pick()
    if not isinstance(raw, dict):
        raise TypeError("file pick must be an object")
    date = raw.get("date")
    fuel = raw.get("fuel")
    if date is not None and not isinstance(date, str):
        raise TypeError("pick date must be a string")
    if fuel is not None and not isinstance(fuel, str):
        raise TypeError("pick fuel must be a string")
    return Pick(
        date=date,
        o2=_column_scales(raw.get("o2")),
        airflow=_column_scales(raw.get("airflow")),
        pressure=_column_scales(raw.get("pressure")),
        fuel=fuel,
    )


def _canonical(raw: Any) -> dict[str, tuple[str, float]]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise TypeError("file canonical map must be an object")
    result: dict[str, tuple[str, float]] = {}
    for metric, item in raw.items():
        if not isinstance(item, dict):
            raise TypeError(f"canonical {metric} must be an object")
        column = item.get("column")
        if not isinstance(column, str) or not column:
            raise ValueError(f"canonical {metric} needs a column")
        result[metric] = (column, float(item.get("scale", 1.0)))
    return result


def _file_spec(raw: Any) -> FileSpec:
    if not isinstance(raw, dict):
        raise TypeError("adapter file must be an object")
    path = raw.get("path")
    if not isinstance(path, str) or not path:
        raise ValueError("adapter file needs a path")
    return FileSpec(
        path=path,
        pick=_pick(raw.get("pick")),
        canonical=_canonical(raw.get("canonical")),
    )


def _count_rule(raw: Any) -> CountRule | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("countRule must be an object")
    column = raw.get("column")
    value = raw.get("value")
    if not isinstance(column, str) or not isinstance(value, str):
        raise TypeError("countRule needs string column and value")
    return CountRule(column=column, value=value)


def load_adapters(path: Path = ADAPTERS_PATH) -> dict[str, InvestigationAdapter]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("adapters.json must contain an object")
    entries = raw.get("adapters")
    if not isinstance(entries, dict) or not entries:
        raise ValueError("adapters.json needs a non-empty adapters object")

    adapters: dict[str, InvestigationAdapter] = {}
    for adapter_id, item in entries.items():
        if not isinstance(item, dict):
            raise TypeError(f"adapter {adapter_id} must be an object")
        files = item.get("files")
        variables = item.get("variables")
        if not isinstance(files, list) or not files:
            raise ValueError(f"adapter {adapter_id} needs files")
        if not isinstance(variables, list) or not all(
            isinstance(variable, str) for variable in variables
        ):
            raise TypeError(f"adapter {adapter_id} needs string variables")
        adapters[adapter_id] = InvestigationAdapter(
            id=adapter_id,
            files=tuple(_file_spec(file_spec) for file_spec in files),
            variables=tuple(variables),
            test_label=str(item.get("testLabel", "tests")),
            pressure_unit=str(item.get("pressureUnit", "atm")),
            o2_partial=bool(item.get("o2Partial", False)),
            planned_only=bool(item.get("plannedOnly", False)),
            count_rule=_count_rule(item.get("countRule")),
        )
    return adapters


ADAPTERS = load_adapters()
CANONICAL_ORDER = tuple(ADAPTERS)


METRIC_DEFS = (
    {
        "name": "o2_pct",
        "unit": "%",
        "kind": "range",
        "min": 0,
        "max": 100,
    },
    {
        "name": "pressure_atm",
        "unit": "atm",
        "kind": "range",
        "min": 0,
        "max": None,
    },
    {
        "name": "airflow_cm_s",
        "unit": "cm/s",
        "kind": "range",
        "min": 0,
        "max": None,
    },
    {
        "name": "test_count",
        "unit": "count",
        "kind": "scalar",
        "min": 0,
        "max": None,
    },
    {
        "name": "test_date",
        "unit": "ISO-8601 date",
        "kind": "date",
        "min": None,
        "max": None,
    },
    {
        "name": "fuel",
        "unit": "text",
        "kind": "text",
        "min": None,
        "max": None,
    },
)

METRIC_NAMES = tuple(metric["name"] for metric in METRIC_DEFS)
