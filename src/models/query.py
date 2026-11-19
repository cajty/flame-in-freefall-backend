from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from models.base import BaseSchema
from models.enums import DataQuality, Gravity, Scale


class CompareInput(BaseSchema):
    ids: list[str]
    metrics: list[str]
    normalize_units: bool = True


class CompareData(BaseSchema):
    items: list[dict[str, Any]]


class QueryFilter(BaseSchema):
    metric: str
    op: str
    min: float | str | None = None
    max: float | str | None = None
    values: list[Any] | None = None


class SortSpec(BaseSchema):
    metric: str
    dir: Literal["asc", "desc"] = "asc"


class RunQueryInput(BaseSchema):
    investigation_ids: list[str] | None = None
    filters: list[QueryFilter] = Field(default_factory=list)
    metrics: list[str] = Field(
        default_factory=lambda: [
            "o2_pct",
            "pressure_atm",
            "airflow_cm_s",
            "test_count",
        ]
    )
    group_by: list[str] = Field(default_factory=list)
    sort: list[SortSpec] = Field(default_factory=list)
    limit: int = Field(default=500, ge=1, le=5_000)


class QueryData(BaseSchema):
    scope: Literal["summary"] = "summary"
    rows: list[dict[str, Any]]
    row_count: int


class ScoreFilters(BaseSchema):
    theme: str | None = None
    phase: str | None = None


class ScoreInput(BaseSchema):
    environment_id: str
    filters: ScoreFilters = Field(default_factory=ScoreFilters)


class ScoreItem(BaseSchema):
    investigation_id: str
    name: str
    score: int
    o2_overlap: float
    gravity_match: float
    scale_match: float
    data_quality_factor: float
    theme_fraction: float
    theme_weight: int
    gravity: Gravity
    scale: Scale
    data_quality: DataQuality
    o2: list[float]
    theme: str
    phase: str
    source_files: list[str]
    psi_ids: list[str]
    psi_urls: list[str]


class ScoreData(BaseSchema):
    environment_id: str
    weights: dict[str, int]
    items: list[ScoreItem]
