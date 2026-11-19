from __future__ import annotations

from typing import Any

from core.errors import ToolFault
from core.query_filters import matches_filter
from core.services.metrics import (
    combined_warnings,
    metric_value,
    provenance,
    record_warnings,
    validate_metric,
)
from core.services.scoring import rank, to_score_items
from core.services.validation import validate_theme_phase
from models import (
    Envelope,
    MetricName,
    QueryData,
    RunQueryInput,
    ScoreData,
    ScoreInput,
)
from core.context import AppContext

GROUP_KEYS = {"investigation_id", "theme", "phase"}


def _group_key(record, key: str) -> str:
    if key == "investigation_id":
        return record.id
    if key == "theme":
        return record.theme
    if key == "phase":
        return record.phase
    raise ToolFault("INVALID_QUERY", f"Unsupported groupBy: {key}")


def _aggregate(records: list[Any], metric: str) -> Any:
    values = [metric_value(record, metric, normalize_units=True) for record in records]
    values = [value for value in values if value is not None]
    if not values:
        return None

    if metric == MetricName.test_count:
        labels = {record.data.test_label for record in records if record.data is not None}
        if len(labels) != 1:
            return None
        return sum(int(value) for value in values)

    if metric == MetricName.test_date:
        starts = [value["start"] for value in values]
        ends = [value["end"] for value in values]
        return {"start": min(starts), "end": max(ends)}

    if metric == MetricName.fuel:
        fuels = sorted({fuel for value in values for fuel in value})
        return fuels

    mins = [float(value["min"]) for value in values]
    maxes = [float(value["max"]) for value in values]
    result: dict[str, Any] = {"min": min(mins), "max": max(maxes)}
    if metric == MetricName.o2_pct:
        result["unit"] = "%"
        result["partial"] = any(bool(value.get("partial")) for value in values)
    elif metric == MetricName.pressure_atm:
        result["unit"] = "atm"
    else:
        result["unit"] = "cm/s"
    return result


def _sort_key(row: dict[str, Any], metric: str) -> tuple[bool, Any]:
    value = row.get(metric)
    if value is None:
        return True, 0
    if isinstance(value, dict):
        if "start" in value:
            return False, value["start"]
        return False, value.get("min", 0)
    if isinstance(value, list):
        return False, " ".join(str(item) for item in value)
    return False, value


def run_query(ctx: AppContext, request: RunQueryInput) -> Envelope[QueryData]:
    if request.investigation_ids is not None:
        if len(set(request.investigation_ids)) != len(request.investigation_ids):
            raise ToolFault("INVALID_QUERY", "investigationIds must be unique.")
        records = [ctx.catalog.get(investigation_id) for investigation_id in request.investigation_ids]
    else:
        records = list(ctx.catalog.all())

    for metric in request.metrics:
        validate_metric(metric)
    if len(set(request.metrics)) != len(request.metrics):
        raise ToolFault("INVALID_QUERY", "metrics must be unique.")

    group_by = list(request.group_by) or ["investigation_id"]
    if len(set(group_by)) != len(group_by):
        raise ToolFault("INVALID_QUERY", "groupBy must be unique.")
    for key in group_by:
        if key not in GROUP_KEYS:
            raise ToolFault("INVALID_QUERY", f"Unsupported groupBy: {key}")

    for filter_ in request.filters:
        validate_metric(filter_.metric)

    filtered = [
        record
        for record in records
        if all(matches_filter(record, filter_) for filter_ in request.filters)
    ]

    groups: dict[tuple[str, ...], list[Any]] = {}
    for record in filtered:
        key = tuple(_group_key(record, group) for group in group_by)
        groups.setdefault(key, []).append(record)

    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for key, group_records in groups.items():
        row: dict[str, Any] = dict(zip(group_by, key, strict=True))
        for metric in request.metrics:
            row[metric] = _aggregate(group_records, metric)
        row["testLabels"] = sorted(
            {record.data.test_label for record in group_records if record.data is not None}
        )
        row["sourceFiles"] = sorted(
            {source for record in group_records for source in record.source_files}
        )
        row["psiIds"] = sorted(
            {
                psi_id
                for record in group_records
                for psi_id in record.psi.ids
            }
        )
        row["psiUrls"] = [
            ctx.reference.psi_url_template.format(id=psi_id)
            for psi_id in row["psiIds"]
        ]
        if MetricName.test_count in request.metrics:
            labels = row["testLabels"]
            if len(labels) > 1:
                warnings.append(
                    "Test counts use different units in one group: "
                    + ", ".join(labels)
                    + "."
                )
        rows.append(row)

    for sort_spec in request.sort:
        validate_metric(sort_spec.metric)
    for sort_spec in reversed(request.sort):
        rows.sort(
            key=lambda row, metric=sort_spec.metric: _sort_key(row, metric),
            reverse=sort_spec.dir == "desc",
        )

    rows = rows[: request.limit]

    for record in filtered:
        warnings.extend(record_warnings(record, request.metrics))
        summary = record.data
        if (
            summary is not None
            and summary.pressure is not None
            and summary.pressure.unit != "atm"
            and MetricName.pressure_atm in request.metrics
        ):
            warnings.append(
                f"{record.name} pressure converted from {summary.pressure.unit} to atm."
            )

    return Envelope(
        data=QueryData(scope="summary", rows=rows, row_count=len(rows)),
        provenance=provenance(filtered, request.metrics),
        warnings=combined_warnings(warnings),
    )


def score_investigations(ctx: AppContext, request: ScoreInput) -> Envelope[ScoreData]:
    environment = ctx.catalog.environment(request.environment_id)
    validate_theme_phase(ctx, request.filters.theme, request.filters.phase)
    weights = ctx.reference.theme_weights[environment.id]

    records = [
        record
        for record in ctx.catalog.all()
        if (request.filters.theme is None or record.theme == request.filters.theme)
        and (request.filters.phase is None or record.phase == request.filters.phase)
    ]
    items = to_score_items(rank(records, environment, weights))

    warnings: list[str] = []
    for record in records:
        warnings.extend(record_warnings(record, ["o2_pct", "test_count"]))

    return Envelope(
        data=ScoreData(
            environment_id=environment.id,
            weights=dict(weights),
            items=items,
        ),
        provenance=provenance(records, ["o2_pct"]),
        warnings=combined_warnings(warnings),
    )
