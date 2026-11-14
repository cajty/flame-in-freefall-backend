from __future__ import annotations

import base64
import binascii
import math
from typing import Any

from core.data.registry import ADAPTERS, METRIC_NAMES, InvestigationAdapter
from core.errors import ToolFault
from models import (
    AggregateData,
    AggregateGroup,
    AggregateStat,
    AggregateTestsInput,
    Envelope,
    QueryTestsInput,
    TestRowsData,
)
from tools.common import combined_warnings, provenance
from tools.context import AppContext

CANONICAL_ROW_METRICS = {"o2_pct", "pressure_atm", "airflow_cm_s"}
MAX_GROUPS = 1_000


def _selected_frames(ctx: AppContext, adapter: InvestigationAdapter):
    frames = []
    for spec, source in zip(adapter.files, ctx.repo.frames(adapter), strict=True):
        frame = source.frame
        if adapter.count_rule is not None:
            frame = frame[frame[adapter.count_rule.column] == adapter.count_rule.value]
        frames.append((spec, frame))
    return frames


def _available_columns(frames) -> set[str]:
    columns: set[str] = {"rowIndex", "sourceFile"}
    for _, frame in frames:
        columns.update(str(column) for column in frame.columns)
    return columns


def _canonical_available(adapter: InvestigationAdapter) -> set[str]:
    result: set[str] = set()
    for spec in adapter.files:
        result.update(spec.canonical)
    return result


def _raw_numeric(value: str) -> float | None:
    if value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _metric_value_for_row(spec, frame_columns: set[str], row, metric: str) -> float | str | None:
    if metric in spec.canonical:
        column, scale = spec.canonical[metric]
        number = _raw_numeric(row[column])
        return number * scale if number is not None else None
    if metric in frame_columns:
        return row[metric] if row[metric] != "" else None
    return None


def _is_canonical(metric: str) -> bool:
    return metric in CANONICAL_ROW_METRICS


def _validate_metric(adapter: InvestigationAdapter, frames, metric: str) -> None:
    available = _available_columns(frames) | _canonical_available(adapter)
    if metric not in available:
        raise ToolFault("UNKNOWN_COLUMN", f"Unknown row metric: {metric}")


def _fuel_match(spec, row, fuel: str) -> bool:
    if spec.pick.fuel is None:
        return False
    return fuel.lower() in str(row[spec.pick.fuel]).lower()


def _date_in_range(spec, row, date_start: str | None, date_end: str | None) -> bool:
    if spec.pick.date is None:
        return False
    value = str(row[spec.pick.date])
    if not value:
        return False
    if date_start is not None and value < date_start:
        return False
    return not (date_end is not None and value > date_end)


def _has_dates(adapter: InvestigationAdapter) -> bool:
    return any(spec.pick.date is not None for spec in adapter.files)


def _prepare_rows(
    ctx: AppContext,
    adapter: InvestigationAdapter,
    metric: str | None,
    min_value: float | None,
    max_value: float | None,
    fuel: str | None,
    date_start: str | None,
    date_end: str | None,
):
    frames = _selected_frames(ctx, adapter)
    if min_value is not None and max_value is not None and min_value > max_value:
        raise ToolFault("INVALID_QUERY", "min must be less than or equal to max.")
    if (date_start is not None or date_end is not None) and not _has_dates(adapter):
        raise ToolFault(
            "DATE_FILTER_UNSUPPORTED",
            f"{adapter.id} has no ISO date column for row filtering.",
        )
    if metric is not None:
        _validate_metric(adapter, frames, metric)

    selected: list[tuple[Any, Any, dict[str, str]]] = []
    for spec, frame in frames:
        columns = {str(column) for column in frame.columns}
        for _, row in frame.iterrows():
            if fuel is not None and not _fuel_match(spec, row, fuel):
                continue
            if (date_start is not None or date_end is not None) and not _date_in_range(
                spec, row, date_start, date_end
            ):
                continue
            if metric is not None and (min_value is not None or max_value is not None):
                value = _metric_value_for_row(spec, columns, row, metric)
                numeric = _raw_numeric(value) if isinstance(value, str) else value
                if not isinstance(numeric, (int, float)):
                    continue
                numeric = float(numeric)
                if min_value is not None and numeric < min_value:
                    continue
                if max_value is not None and numeric > max_value:
                    continue
            selected.append((spec, frame, row))
    return frames, selected


def _encode_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(str(offset).encode("ascii")).decode("ascii")


def _decode_cursor(cursor: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii")
        value = int(raw)
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise ToolFault("INVALID_QUERY", "Invalid cursor.") from error
    if value < 0:
        raise ToolFault("INVALID_QUERY", "Invalid cursor.")
    return value


def query_tests(ctx: AppContext, request: QueryTestsInput) -> Envelope[TestRowsData]:
    adapter = ADAPTERS.get(request.investigation_id)
    if adapter is None:
        raise ToolFault(
            "INVESTIGATION_NOT_FOUND",
            f"Unknown investigation: {request.investigation_id}",
            status_code=404,
        )

    _, selected = _prepare_rows(
        ctx,
        adapter,
        request.metric,
        request.min,
        request.max,
        request.fuel,
        request.date_start,
        request.date_end,
    )

    frames = _selected_frames(ctx, adapter)
    available = _available_columns(frames) | _canonical_available(adapter)
    columns = request.columns or [
        column
        for column in ("rowIndex", "sourceFile", *adapter.variables)
        if column in available
    ]
    if request.metric is not None and request.metric not in columns:
        columns = [*columns, request.metric]
    for column in columns:
        if column not in available:
            raise ToolFault("INVALID_EXPORT_COLUMNS", f"Unknown column: {column}")

    offset = request.offset
    if request.cursor is not None:
        if request.offset != 0:
            raise ToolFault("INVALID_QUERY", "Use either offset or cursor, not both.")
        offset = _decode_cursor(request.cursor)

    page = selected[offset : offset + request.limit]
    rows: list[dict[str, Any]] = []
    for spec, frame, row in page:
        frame_columns = {str(column) for column in frame.columns}
        output: dict[str, Any] = {}
        for column in columns:
            if column == "rowIndex":
                output[column] = int(row["row_index"])
            elif column == "sourceFile":
                output[column] = spec.path
            elif column in spec.canonical and column not in frame_columns:
                output[column] = _metric_value_for_row(spec, frame_columns, row, column)
            else:
                value = row.get(column, "")
                output[column] = value if value != "" else None
        rows.append(output)

    next_cursor = (
        _encode_cursor(offset + request.limit)
        if offset + request.limit < len(selected)
        else None
    )
    warnings = (
        [f"{adapter.id} rows are planned values, not measured results."]
        if adapter.planned_only
        else []
    )
    record = ctx.catalog.get(adapter.id)
    return Envelope(
        data=TestRowsData(
            investigation_id=adapter.id,
            rows=rows,
            row_count=len(rows),
            limit=request.limit,
            offset=offset,
            next_cursor=next_cursor,
            source_files=list(record.source_files),
            psi_ids=list(record.psi.ids),
            psi_urls=list(record.psi.urls),
        ),
        provenance=provenance([record], list(METRIC_NAMES)),
        warnings=combined_warnings(warnings),
    )


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = fraction * (len(ordered) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def aggregate_tests(
    ctx: AppContext, request: AggregateTestsInput
) -> Envelope[AggregateData]:
    adapter = ADAPTERS.get(request.investigation_id)
    if adapter is None:
        raise ToolFault(
            "INVESTIGATION_NOT_FOUND",
            f"Unknown investigation: {request.investigation_id}",
            status_code=404,
        )
    if request.stat not in {stat.value for stat in AggregateStat}:
        raise ToolFault("INVALID_QUERY", f"Unsupported stat: {request.stat}")
    if len(request.group_by) > 2:
        raise ToolFault("INVALID_QUERY", "At most two groupBy columns are supported.")
    if len(set(request.group_by)) != len(request.group_by):
        raise ToolFault("INVALID_QUERY", "groupBy must be unique.")

    frames, selected = _prepare_rows(
        ctx,
        adapter,
        request.metric,
        request.min,
        request.max,
        request.fuel,
        None,
        None,
    )
    available = _available_columns(frames) | _canonical_available(adapter)
    for column in request.group_by:
        if column not in available:
            raise ToolFault("UNKNOWN_COLUMN", f"Unknown groupBy column: {column}")

    grouped: dict[tuple[Any, ...], list[tuple[Any, dict[str, str]]]] = {}
    for spec, frame, row in selected:
        key = tuple(
            (row[column] if row.get(column, "") != "" else None)
            for column in request.group_by
        )
        grouped.setdefault(key, []).append((spec, row))
    if len(grouped) > MAX_GROUPS:
        raise ToolFault("INVALID_QUERY", "Too many groups; narrow the filters.")

    groups: list[AggregateGroup] = []
    for key in sorted(grouped, key=lambda item: tuple("" if v is None else str(v) for v in item)):
        numeric_values: list[float] = []
        for spec, row in grouped[key]:
            if request.metric in spec.canonical:
                column, scale = spec.canonical[request.metric]
                number = _raw_numeric(row[column])
                if number is not None:
                    numeric_values.append(number * scale)
            else:
                number = _raw_numeric(row[request.metric])
                if number is not None:
                    numeric_values.append(number)
        if not numeric_values:
            raise ToolFault(
                "INVALID_QUERY",
                f"Metric {request.metric} has no numeric values.",
            )
        if request.stat == "count":
            value = float(len(numeric_values))
        elif request.stat == "min":
            value = min(numeric_values)
        elif request.stat == "max":
            value = max(numeric_values)
        elif request.stat == "mean":
            value = sum(numeric_values) / len(numeric_values)
        elif request.stat == "median":
            value = _percentile(numeric_values, 0.5)
        else:
            value = _percentile(numeric_values, 0.9)
        groups.append(
            AggregateGroup(
                group=dict(zip(request.group_by, key, strict=True)),
                count=len(numeric_values),
                value=value,
            )
        )

    warnings = (
        [f"{adapter.id} rows are planned values, not measured results."]
        if adapter.planned_only
        else []
    )
    record = ctx.catalog.get(adapter.id)
    return Envelope(
        data=AggregateData(
            investigation_id=adapter.id,
            metric=request.metric,
            stat=request.stat,
            groups=groups,
            row_count=len(selected),
            source_files=list(record.source_files),
            psi_ids=list(record.psi.ids),
            psi_urls=list(record.psi.urls),
        ),
        provenance=provenance([record], list(METRIC_NAMES)),
        warnings=combined_warnings(warnings),
    )
