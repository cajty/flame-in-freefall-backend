from __future__ import annotations

from typing import Any

from models.base import BaseSchema
from models.enums import ExportKind


class ExportInput(BaseSchema):
    kind: ExportKind
    query: dict[str, Any] | None = None
    columns: list[str] | None = None


class ExportData(BaseSchema):
    export_id: str
    download_url: str
    row_count: int
    columns: list[str]
    expires_at: str
    expires_in_seconds: int
