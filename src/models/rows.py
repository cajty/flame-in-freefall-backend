from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from models.base import BaseSchema


class QueryTestsInput(BaseSchema):
    investigation_id: str
    metric: str | None = None
    min: float | None = None
    max: float | None = None
    fuel: str | None = None
    date_start: str | None = None
    date_end: str | None = None
    columns: list[str] | None = None
    limit: int = Field(default=50, ge=1, le=1_000)
    offset: int = Field(default=0, ge=0)
    cursor: str | None = None


class TestRowsData(BaseSchema):
    investigation_id: str
    scope: Literal["tests"] = "tests"
    rows: list[dict[str, Any]]
    row_count: int
    limit: int
    offset: int
    next_cursor: str | None = None
    source_files: list[str]
    psi_ids: list[str]
    psi_urls: list[str]


class AggregateTestsInput(BaseSchema):
    investigation_id: str
    metric: str
    group_by: list[str] = Field(default_factory=list)
    stat: str = "mean"
    min: float | None = None
    max: float | None = None
    fuel: str | None = None


class AggregateGroup(BaseSchema):
    group: dict[str, Any]
    count: int
    value: float | None = None


class AggregateData(BaseSchema):
    investigation_id: str
    metric: str
    stat: str
    groups: list[AggregateGroup]
    row_count: int
    source_files: list[str]
    psi_ids: list[str]
    psi_urls: list[str]
