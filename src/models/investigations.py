from __future__ import annotations

from pydantic import Field

from models.base import BaseSchema
from models.common import MetricDef, SummaryRecord
from models.enums import DataQuality, Gravity, Scale


class InvestigationBase(BaseSchema):
    id: str
    name: str
    full_name: str = Field(alias="full")
    theme: str
    phase: str
    gravity: Gravity
    scale: Scale
    data_quality: DataQuality
    o2: list[float]
    o2_known: bool | None = Field(default=None, alias="o2known")
    o2_source: str | None = Field(default=None, alias="o2src")
    hardware: str = Field(alias="hw")
    objective: str = Field(alias="obj")
    fuel: str
    conditions: str = Field(alias="cond")
    measurements: str = Field(alias="meas")


class InvestigationMeta(InvestigationBase):
    pass


class PsiLinks(BaseSchema):
    ids: list[str]
    urls: list[str]


class InvestigationRecord(InvestigationBase):
    data: SummaryRecord | None
    psi: PsiLinks
    source_files: list[str]
    planned_only: bool


class EnvironmentRecord(BaseSchema):
    id: str
    name: str
    short_name: str = Field(alias="short")
    gravity: Gravity
    o2: list[float]
    pressure_label: str = Field(alias="psi")
    pressure_window: list[float] = Field(alias="p")
    source_note: str = Field(alias="src")
    accent_color: str = Field(alias="color")
    glow_color: str = Field(alias="glow")
    description: str = Field(alias="blurb")
    theme_weights: dict[str, int]


class HealthData(BaseSchema):
    status: str
    generated_at: str
    investigations: int
    tables: int


class SchemaData(BaseSchema):
    metrics: list[MetricDef]
    themes: list[str]
    phases: list[str]
    investigation_ids: list[str]
    coverage: dict[str, dict[str, bool]]
    operators: list[str]
    limits: dict[str, int]
    generated_at: str


class SearchInput(BaseSchema):
    q: str | None = None
    theme: str | None = None
    phase: str | None = None
    o2_min: float | None = None
    o2_max: float | None = None
    fuel: str | None = None
    has_data: bool | None = None
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)


class SearchData(BaseSchema):
    items: list[InvestigationRecord]
    total: int
    limit: int
    offset: int


class GetInvestigationInput(BaseSchema):
    id: str


class EnvironmentsData(BaseSchema):
    items: list[EnvironmentRecord]


class GapsInput(BaseSchema):
    ids: list[str] | None = None


class GapItem(BaseSchema):
    investigation_id: str
    missing: list[str]
    partial: list[str]
    planned_only: bool
    source_files: list[str]
    psi_ids: list[str]
    psi_urls: list[str]


class GapsData(BaseSchema):
    items: list[GapItem]
