from __future__ import annotations

from enum import StrEnum
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class BaseSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


class Theme(StrEnum):
    prevention = "prevention"
    detection = "detection"
    suppression = "suppression"
    fundamentals = "fundamentals"


class Phase(StrEnum):
    solid = "solid"
    liquid = "liquid"
    gas = "gas"


class Gravity(StrEnum):
    microgravity = "microgravity"
    partial = "partial"
    ground = "ground"
    mixed = "mixed"


class Scale(StrEnum):
    bench = "bench"
    glovebox = "glovebox"
    rack = "rack"
    spacecraft = "spacecraft"


class DataQuality(StrEnum):
    measured = "measured"
    assumed_air = "assumed-air"
    partial = "partial"
    planned = "planned"


class MetricName(StrEnum):
    o2_pct = "o2_pct"
    pressure_atm = "pressure_atm"
    airflow_cm_s = "airflow_cm_s"
    test_count = "test_count"
    test_date = "test_date"
    fuel = "fuel"


class QueryOp(StrEnum):
    eq = "eq"
    neq = "neq"
    lt = "lt"
    lte = "lte"
    gt = "gt"
    gte = "gte"
    between = "between"
    in_ = "in"


class AggregateStat(StrEnum):
    count = "count"
    min = "min"
    max = "max"
    mean = "mean"
    median = "median"
    p90 = "p90"


class ExportKind(StrEnum):
    query = "query"
    comparison = "comparison"
    score = "score"
    gaps = "gaps"


class NumericRange(BaseSchema):
    min: float
    max: float


class O2Range(BaseSchema):
    min: float
    max: float
    unit: Literal["%"] = "%"
    partial: bool = False


class UnitRange(BaseSchema):
    min: float
    max: float
    unit: str


class DateRange(BaseSchema):
    start: str
    end: str


class SummaryRecord(BaseSchema):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )

    files: list[str]
    tests: int
    test_label: str
    date: DateRange | None
    o2: O2Range | None
    airflow: UnitRange | None
    pressure: UnitRange | None
    fuels: list[str]
    variables: list[str]


class InvestigationMeta(BaseSchema):
    id: str
    name: str
    full: str
    theme: str
    phase: str
    gravity: Gravity
    scale: Scale
    data_quality: DataQuality
    o2: list[float]
    o2known: bool | None = None
    o2src: str | None = None
    hw: str
    obj: str
    fuel: str
    cond: str
    meas: str


class PsiLinks(BaseSchema):
    ids: list[str]
    urls: list[str]


class InvestigationRecord(BaseSchema):
    id: str
    name: str
    full: str
    theme: str
    phase: str
    gravity: Gravity
    scale: Scale
    data_quality: DataQuality
    o2: list[float]
    o2known: bool | None = None
    o2src: str | None = None
    hw: str
    obj: str
    fuel: str
    cond: str
    meas: str
    data: SummaryRecord | None
    psi: PsiLinks
    source_files: list[str]
    planned_only: bool


class EnvironmentRecord(BaseSchema):
    id: str
    name: str
    short: str
    gravity: Gravity
    o2: list[float]
    psi: str
    src: str
    color: str
    glow: str
    blurb: str
    theme_weights: dict[str, int]


class MetricDef(BaseSchema):
    name: str
    unit: str
    kind: Literal["range", "scalar", "date", "text"]
    min: float | None = None
    max: float | None = None


class ProvenanceItem(BaseSchema):
    investigation_id: str
    source_file: str
    fields: list[str] = Field(default_factory=list)


class ErrorInfo(BaseSchema):
    code: str
    message: str
    details: list[str] = Field(default_factory=list)


T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    model_config = ConfigDict(populate_by_name=True)

    ok: Literal[True] = True
    data: T
    provenance: list[ProvenanceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ok: Literal[False] = False
    error: ErrorInfo


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


class PsiRecordInput(BaseSchema):
    id: str


class PsiRecordData(BaseSchema):
    psi_id: str
    ids: list[str]
    urls: list[str]
    investigations: list[dict[str, Any]]
    source_files: list[str]
    metadata_source: Literal["local-reference"] = "local-reference"


class PsiCatalogRecord(BaseSchema):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )

    psi_id: str
    title: str = ""
    acronym: str = ""
    research_area: str = ""
    sub_research_area: str = ""
    project_type: str = ""
    flight_program: str = ""
    experiment_hardware: str = ""
    objective: str = ""
    approach: str = ""
    hypothesis: str = ""
    research_impacts: str = ""
    modified_date: str = ""
    restricted: bool = False
    source_hash: str = ""


class PsiCatalogSearchInput(BaseSchema):
    q: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=50)


class PsiCatalogHit(BaseSchema):
    psi_id: str
    title: str
    acronym: str
    research_area: str
    sub_research_area: str
    snippet: str
    url: str
    curated: bool
    investigation_ids: list[str]
    restricted: bool
    score: float
    matched_terms: list[str]
    modified_date: str


class PsiCatalogSearchData(BaseSchema):
    query: str
    items: list[PsiCatalogHit]
    total: int
    catalog_size: int
    generated_at: str


class AnalyzeInput(BaseSchema):
    question: str = Field(min_length=1, max_length=2_000)
    conversation_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9._:-]+$",
    )
    psi_ids: list[str] | None = None
    environment_id: str | None = None
    o2: float | None = Field(default=None, ge=0, le=100)


class Citation(BaseSchema):
    investigation_id: str
    source_file: str
    psi_id: str
    url: str


class AnalysisAnswer(BaseSchema):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AnalyzeData(BaseSchema):
    answer: str
    plan: dict[str, list[str]]
    citations: list[Citation]
    warnings: list[str]
    generated: dict[str, SummaryRecord]
    ranking: list[ScoreItem] | None = None
    covers: list[str] | None = None
    reach: int | None = None
    download: dict[str, Any] | None = None
    scope: dict[str, list[str]] | None = None
