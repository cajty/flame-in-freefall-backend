from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from models.base import BaseSchema


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


T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    model_config = ConfigDict(populate_by_name=True)

    ok: Literal[True] = True
    data: T
    provenance: list[ProvenanceItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
