from __future__ import annotations

from typing import Any

from core.data.summary import ISO_DATE_RE
from core.errors import ToolFault
from models import QueryFilter, QueryOp
from tools.common import metric_value, validate_metric


def _range(value: dict[str, Any]) -> tuple[float, float]:
    return float(value["min"]), float(value["max"])


def _numbers_for(filter_: QueryFilter) -> list[float]:
    try:
        if filter_.op == QueryOp.between:
            if filter_.min is None or filter_.max is None:
                raise ToolFault("INVALID_QUERY", "between needs min and max.")
            low, high = float(filter_.min), float(filter_.max)
            if low > high:
                raise ToolFault("INVALID_QUERY", "Filter min must be <= max.")
            return [low, high]
        if filter_.op == QueryOp.in_:
            if not filter_.values:
                raise ToolFault("INVALID_QUERY", "in needs at least one value.")
            return [float(value) for value in filter_.values]
        single = filter_.min if filter_.min is not None else filter_.max
        if single is None:
            raise ToolFault("INVALID_QUERY", f"{filter_.op} needs a value in min or max.")
        return [float(single)]
    except (TypeError, ValueError) as error:
        raise ToolFault("INVALID_QUERY", "Filter values must be numeric.") from error


def matches_filter(record, filter_: QueryFilter) -> bool:
    validate_metric(filter_.metric)
    if filter_.metric == "fuel":
        values = metric_value(record, "fuel", normalize_units=False) or []
        lowered = {str(value).lower() for value in values}
        if filter_.op == QueryOp.in_:
            if not filter_.values:
                raise ToolFault("INVALID_QUERY", "in needs at least one value.")
            return any(str(value).lower() in lowered for value in filter_.values)
        if filter_.op not in {QueryOp.eq, QueryOp.neq}:
            raise ToolFault("INVALID_QUERY", "fuel supports only eq, neq and in.")
        if not filter_.values:
            raise ToolFault("INVALID_QUERY", "fuel eq/neq needs values.")
        targets = [str(value).lower() for value in filter_.values]
        found = any(target in lowered for target in targets)
        return found if filter_.op == QueryOp.eq else not found

    value = metric_value(record, filter_.metric, normalize_units=True)
    if value is None:
        return False

    if filter_.metric == "test_date":
        start, end = value["start"], value["end"]
        if filter_.op == QueryOp.between:
            if filter_.min is None or filter_.max is None:
                raise ToolFault("INVALID_QUERY", "between needs min and max dates.")
            low, high = str(filter_.min), str(filter_.max)
            if not ISO_DATE_RE.match(low) or not ISO_DATE_RE.match(high):
                raise ToolFault("INVALID_QUERY", "Date filters must be YYYY-MM-DD.")
            return start <= high and end >= low
        target = filter_.min if filter_.min is not None else filter_.max
        if target is None:
            raise ToolFault("INVALID_QUERY", "Date filter needs a value.")
        target_text = str(target)
        if not ISO_DATE_RE.match(target_text):
            raise ToolFault("INVALID_QUERY", "Date filters must be YYYY-MM-DD.")
        if filter_.op == QueryOp.eq:
            return start <= target_text <= end
        if filter_.op == QueryOp.lt:
            return start < target_text
        if filter_.op == QueryOp.lte:
            return start <= target_text
        if filter_.op == QueryOp.gt:
            return end > target_text
        if filter_.op == QueryOp.gte:
            return end >= target_text
        if filter_.op == QueryOp.neq:
            return not (start <= target_text <= end)
        raise ToolFault("INVALID_QUERY", f"Date does not support {filter_.op}.")

    if isinstance(value, (int, float)):
        target = _numbers_for(filter_)[0] if filter_.op != QueryOp.in_ else None
        if filter_.op == QueryOp.eq:
            return value == target
        if filter_.op == QueryOp.neq:
            return value != target
        if filter_.op == QueryOp.lt:
            return value < target
        if filter_.op == QueryOp.lte:
            return value <= target
        if filter_.op == QueryOp.gt:
            return value > target
        if filter_.op == QueryOp.gte:
            return value >= target
        if filter_.op == QueryOp.between:
            low, high = _numbers_for(filter_)
            return low <= value <= high
        if filter_.op == QueryOp.in_:
            return value in _numbers_for(filter_)
        raise ToolFault("INVALID_QUERY", f"Unsupported operator: {filter_.op}")

    if isinstance(value, dict):
        low, high = _range(value)
        if filter_.op == QueryOp.between:
            request_low, request_high = _numbers_for(filter_)
            return low <= request_high and high >= request_low
        if filter_.op == QueryOp.in_:
            return any(low <= item <= high for item in _numbers_for(filter_))
        target = _numbers_for(filter_)[0]
        if filter_.op == QueryOp.eq:
            return low <= target <= high
        if filter_.op == QueryOp.neq:
            return not (low <= target <= high)
        if filter_.op == QueryOp.lt:
            return low < target
        if filter_.op == QueryOp.lte:
            return low <= target
        if filter_.op == QueryOp.gt:
            return high > target
        if filter_.op == QueryOp.gte:
            return high >= target
        raise ToolFault("INVALID_QUERY", f"Unsupported operator: {filter_.op}")

    raise ToolFault("INVALID_QUERY", f"Unsupported metric value for {filter_.metric}.")
