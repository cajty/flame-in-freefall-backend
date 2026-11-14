from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from models import SummaryRecord


def iso_from_mtime(path: Path) -> str:
    stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return f"{stamp:%Y-%m-%dT%H:%M:%S}.{stamp.microsecond // 1000:03d}Z"


def load_generated(path: Path, expected_ids: set[str] | tuple[str, ...]) -> tuple[dict[str, SummaryRecord], str]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("generated.json must contain an object keyed by investigation ID")

    expected = set(expected_ids)
    actual = set(raw)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ValueError(f"generated.json ID mismatch: missing={missing} extra={extra}")

    summaries: dict[str, SummaryRecord] = {}
    for investigation_id, item in raw.items():
        summary = SummaryRecord.model_validate(item)
        if summary.tests < 0:
            raise ValueError(f"{investigation_id}: negative test count")
        if not summary.files:
            raise ValueError(f"{investigation_id}: no source files")
        if summary.o2 is not None and summary.o2.unit != "%":
            raise ValueError(f"{investigation_id}: unexpected O2 unit {summary.o2.unit}")
        if summary.airflow is not None and summary.airflow.unit != "cm/s":
            raise ValueError(f"{investigation_id}: unexpected airflow unit {summary.airflow.unit}")
        if summary.pressure is not None and summary.pressure.unit not in {"atm", "bar", "kPa"}:
            raise ValueError(f"{investigation_id}: unexpected pressure unit {summary.pressure.unit}")
        summaries[investigation_id] = summary

    return summaries, iso_from_mtime(path)
