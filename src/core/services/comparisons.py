from __future__ import annotations

from typing import Any

from core.errors import ToolFault
from core.services.metrics import (
    citation_context,
    combined_warnings,
    metric_value,
    provenance,
    record_warnings,
    validate_metric,
)
from models import CompareData, CompareInput, Envelope, MetricName
from core.context import AppContext


def compare_investigations(
    ctx: AppContext, request: CompareInput
) -> Envelope[CompareData]:
    ids = request.ids
    if len(ids) < 2:
        raise ToolFault("INVALID_QUERY", "Compare needs at least two investigation IDs.")
    if len(ids) > ctx.settings.compare_max_ids:
        raise ToolFault(
            "INVALID_QUERY",
            f"Compare accepts at most {ctx.settings.compare_max_ids} investigation IDs.",
        )
    if len(set(ids)) != len(ids):
        raise ToolFault("INVALID_QUERY", "Compare IDs must be unique.")
    if not request.metrics:
        raise ToolFault("INVALID_QUERY", "Compare needs at least one metric.")
    if len(set(request.metrics)) != len(request.metrics):
        raise ToolFault("INVALID_QUERY", "Compare metrics must be unique.")
    for metric in request.metrics:
        validate_metric(metric)

    records = [ctx.catalog.get(investigation_id) for investigation_id in ids]

    items: list[dict[str, Any]] = []
    warnings: list[str] = []
    for record in records:
        summary = record.data
        assert summary is not None
        item: dict[str, Any] = {
            "investigationId": record.id,
            "name": record.name,
            "testLabel": summary.test_label,
            **citation_context(record),
        }
        for metric in request.metrics:
            item[metric] = metric_value(record, metric, request.normalize_units)
        items.append(item)

        warnings.extend(record_warnings(record, request.metrics))
        if (
            request.normalize_units
            and MetricName.pressure_atm in request.metrics
            and summary.pressure is not None
            and summary.pressure.unit != "atm"
        ):
            warnings.append(
                f"{record.name} pressure converted from {summary.pressure.unit} to atm."
            )

    if MetricName.test_count in request.metrics:
        labels = {record.data.test_label for record in records if record.data is not None}
        if len(labels) > 1:
            warnings.append(
                "Test counts use different units: " + ", ".join(sorted(labels)) + "."
            )

    return Envelope(
        data=CompareData(items=items),
        provenance=provenance(records, request.metrics),
        warnings=combined_warnings(warnings),
    )
