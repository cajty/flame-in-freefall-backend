from __future__ import annotations

import csv
import io
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from core.errors import ExportExpired, ExportNotFound

FORMULA_PREFIXES = ("=", "+", "-", "@")


@dataclass(frozen=True)
class ExportArtifact:
    id: str
    filename: str
    content: bytes
    columns: list[str]
    row_count: int
    created_at: float
    expires_at: float


def iso_z(timestamp: float) -> str:
    stamp = datetime.fromtimestamp(timestamp, tz=UTC)
    return f"{stamp:%Y-%m-%dT%H:%M:%S}.{stamp.microsecond // 1000:03d}Z"


def escape_cell(value: object) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def write_csv(columns: list[str], rows: list[dict[str, object]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([escape_cell(row.get(column)) for column in columns])
    return buffer.getvalue().encode("utf-8")


class ExportStore:
    """In-memory TTL store. Single-process only; exports are lost on restart."""

    def __init__(
        self, ttl_seconds: int, clock: Callable[[], float] = time.time, max_entries: int = 100
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._max_entries = max_entries
        self._items: dict[str, ExportArtifact] = {}
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        expired = [key for key, item in self._items.items() if item.expires_at <= now]
        for key in expired:
            self._items.pop(key, None)

    def create(
        self,
        content: bytes,
        columns: list[str],
        row_count: int,
    ) -> ExportArtifact:
        now = self._clock()
        export_id = secrets.token_hex(8)
        artifact = ExportArtifact(
            id=export_id,
            filename=f"flame-atlas-export-{export_id}.csv",
            content=content,
            columns=list(columns),
            row_count=row_count,
            created_at=now,
            expires_at=now + self._ttl,
        )
        with self._lock:
            self._purge(now)
            while len(self._items) >= self._max_entries:
                oldest = min(self._items, key=lambda key: self._items[key].created_at)
                self._items.pop(oldest, None)
            self._items[export_id] = artifact
        return artifact

    def get(self, export_id: str) -> ExportArtifact:
        now = self._clock()
        with self._lock:
            artifact = self._items.get(export_id)
            if artifact is None:
                raise ExportNotFound(f"Unknown export: {export_id}")
            if artifact.expires_at <= now:
                self._items.pop(export_id, None)
                raise ExportExpired("This export has expired.")
            return artifact

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
