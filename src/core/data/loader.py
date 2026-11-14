from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from core.data.registry import InvestigationAdapter

READ_KWARGS = {
    "dtype": str,
    "keep_default_na": False,
    "na_values": [],
    "encoding": "utf-8-sig",
    "sep": ",",
    "quotechar": '"',
    "doublequote": True,
    "engine": "c",
}


@dataclass(frozen=True)
class SourceFrame:
    source_file: str
    frame: pd.DataFrame


class CsvRepository:
    """Read-only CSV cache. Frames are loaded once and keyed by path mtime."""

    def __init__(self, processed_dir: Path) -> None:
        self._root = processed_dir.resolve()
        self._frames: dict[str, tuple[int, int, SourceFrame]] = {}
        self._headers: dict[str, tuple[int, int, tuple[str, ...]]] = {}
        self._lock = threading.Lock()

    def _resolve(self, relative_path: str) -> Path:
        candidate = (self._root / relative_path).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise ValueError(f"path outside data directory: {relative_path}")
        return candidate

    @staticmethod
    def _stamp(path: Path) -> tuple[int, int]:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size

    def headers(self, relative_path: str) -> tuple[str, ...]:
        path = self._resolve(relative_path)
        stamp = self._stamp(path)
        with self._lock:
            cached = self._headers.get(relative_path)
            if cached is not None and cached[:2] == stamp:
                return cached[2]

        header_frame = pd.read_csv(path, nrows=0, **READ_KWARGS)
        headers = tuple(str(column).strip() for column in header_frame.columns)
        with self._lock:
            self._headers[relative_path] = (*stamp, headers)
        return headers

    def load(self, relative_path: str) -> SourceFrame:
        path = self._resolve(relative_path)
        stamp = self._stamp(path)
        with self._lock:
            cached = self._frames.get(relative_path)
            if cached is not None and cached[:2] == stamp:
                return cached[2]

        frame = pd.read_csv(path, **READ_KWARGS)
        frame.columns = [str(column).strip() for column in frame.columns]
        frame = frame.map(lambda value: value.strip() if isinstance(value, str) else value)
        frame.insert(0, "row_index", range(len(frame)))
        frame.insert(1, "source_file", relative_path)

        source_frame = SourceFrame(source_file=relative_path, frame=frame)
        with self._lock:
            self._frames[relative_path] = (*stamp, source_frame)
        return source_frame

    def frames(self, adapter: InvestigationAdapter) -> tuple[SourceFrame, ...]:
        return tuple(self.load(spec.path) for spec in adapter.files)

    def validate_adapter(self, adapter: InvestigationAdapter) -> None:
        for spec in adapter.files:
            headers = set(self.headers(spec.path))
            required: set[str] = set()
            if spec.pick.date is not None:
                required.add(spec.pick.date)
            if spec.pick.fuel is not None:
                required.add(spec.pick.fuel)
            required.update(column for column, _ in spec.pick.o2)
            required.update(spec.pick.airflow)
            required.update(spec.pick.pressure)
            required.update(column for column, _ in spec.canonical.values())
            missing = sorted(required - headers)
            if missing:
                raise ValueError(
                    f"{adapter.id} / {spec.path}: missing columns {missing}"
                )
