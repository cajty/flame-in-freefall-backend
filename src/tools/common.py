from __future__ import annotations

from typing import Any

from core.data.registry import (
    ADAPTERS,
    ATM_PER_BAR,
    ATM_PER_KPA,
    METRIC_NAMES,
)
from core.data.summary import js_round
from core.errors import ToolFault
from models import InvestigationRecord, MetricName, ProvenanceItem
from tools.context import AppContext


def validate_metric(metric: str) -> str:
    if metric not in METRIC_NAMES:
        raise ToolFault(
            "UNKNOWN_METRIC",
            f"Unsupported metric: {metric}. Use get_schema for supported metrics.",
        )
    return metric


def metric_value(record: InvestigationRecord, metric: str, normalize_units: bool = True) -> Any:
    validate_metric(metric)
    summary = record.data
    if summary is None:
        return None

    if metric == MetricName.o2_pct:
        if summary.o2 is None:
            return None
        return summary.o2.model_dump()

    if metric == MetricName.pressure_atm:
        if summary.pressure is None:
            return None
        value = summary.pressure
        if normalize_units:
            factor = {"atm": 1.0, "bar": ATM_PER_BAR, "kPa": ATM_PER_KPA}.get(
                value.unit, 1.0
            )
            return {
                "min": js_round(value.min * factor, 2),
                "max": js_round(value.max * factor, 2),
                "unit": "atm",
            }
        return value.model_dump()

    if metric == MetricName.airflow_cm_s:
        if summary.airflow is None:
            return None
        return summary.airflow.model_dump()

    if metric == MetricName.test_count:
        return summary.tests

    if metric == MetricName.test_date:
        if summary.date is None:
            return None
        return summary.date.model_dump()

    if metric == MetricName.fuel:
        return list(summary.fuels)

    return None


def metric_fields(record: InvestigationRecord, metrics: list[str]) -> list[ProvenanceItem]:
    adapter = ADAPTERS[record.id]
    items: list[ProvenanceItem] = []
    for spec in adapter.files:
        fields: list[str] = []
        for metric in metrics:
            if metric == MetricName.o2_pct:
                fields.extend(column for column, _ in spec.pick.o2)
            elif metric == MetricName.pressure_atm:
                fields.extend(spec.pick.pressure)
            elif metric == MetricName.airflow_cm_s:
                fields.extend(spec.pick.airflow)
            elif metric == MetricName.test_date:
                if spec.pick.date is not None:
                    fields.append(spec.pick.date)
            elif metric == MetricName.fuel:
                if spec.pick.fuel is not None:
                    fields.append(spec.pick.fuel)
            elif metric == MetricName.test_count and adapter.count_rule is not None:
                fields.append(adapter.count_rule.column)
        deduped: list[str] = []
        for field in fields:
            if field not in deduped:
                deduped.append(field)
        items.append(
            ProvenanceItem(
                investigation_id=record.id,
                source_file=spec.path,
                fields=deduped,
            )
        )
    return items


def provenance(
    records: list[InvestigationRecord], metrics: list[str]
) -> list[ProvenanceItem]:
    items: list[ProvenanceItem] = []
    for record in records:
        items.extend(metric_fields(record, metrics))
    return items


def record_warnings(record: InvestigationRecord, metrics: list[str]) -> list[str]:
    summary = record.data
    assert summary is not None
    warnings: list[str] = []

    if MetricName.o2_pct in metrics:
        if summary.o2 is None:
            warnings.append(f"{record.name} has no O2 column in the cleaned table.")
        elif summary.o2.partial:
            warnings.append(
                f"{record.name} O2 range is partial: only Saffire-I is in the cleaned table."
            )
        elif record.o2src == "air":
            warnings.append(
                f"{record.name} O2 is assumed to be air (21%) because the cleaned table has no O2 column."
            )

    if MetricName.pressure_atm in metrics and summary.pressure is None:
        warnings.append(f"{record.name} pressure is not recorded in the cleaned table.")

    if MetricName.airflow_cm_s in metrics and summary.airflow is None:
        warnings.append(f"{record.name} airflow is not recorded in the cleaned table.")

    if MetricName.test_date in metrics and summary.date is None:
        warnings.append(f"{record.name} has no ISO test dates in the cleaned table.")

    if record.planned_only:
        warnings.append(
            f"{record.name} is a planned test matrix, not measured results."
        )

    return _dedupe(warnings)


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def combined_warnings(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        merged.extend(group)
    return _dedupe(merged)


def citation_context(record: InvestigationRecord) -> dict[str, list[str]]:
    return {
        "sourceFiles": list(record.source_files),
        "psiIds": list(record.psi.ids),
        "psiUrls": list(record.psi.urls),
    }


def require_investigations(ctx: AppContext, ids: list[str]) -> list[InvestigationRecord]:
    return [ctx.catalog.get(investigation_id) for investigation_id in ids]
