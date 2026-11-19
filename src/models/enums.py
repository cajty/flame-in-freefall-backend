from __future__ import annotations

from enum import StrEnum


class Gravity(StrEnum):
    microgravity = "microgravity"
    partial = "partial"
    ground = "ground"
    mixed = "mixed"


class Scale(StrEnum):
    bench = "bench"
    glovebox = "glovebox"
    rack = "rack"
    spacecraft = "spacecraft"


class DataQuality(StrEnum):
    measured = "measured"
    assumed_air = "assumed-air"
    partial = "partial"
    planned = "planned"


class MetricName(StrEnum):
    o2_pct = "o2_pct"
    pressure_atm = "pressure_atm"
    airflow_cm_s = "airflow_cm_s"
    test_count = "test_count"
    test_date = "test_date"
    fuel = "fuel"


class QueryOp(StrEnum):
    eq = "eq"
    neq = "neq"
    lt = "lt"
    lte = "lte"
    gt = "gt"
    gte = "gte"
    between = "between"
    in_ = "in"


class AggregateStat(StrEnum):
    count = "count"
    min = "min"
    max = "max"
    mean = "mean"
    median = "median"
    p90 = "p90"


class ExportKind(StrEnum):
    query = "query"
    comparison = "comparison"
    score = "score"
    gaps = "gaps"
