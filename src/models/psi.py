from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel

from models.base import BaseSchema


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
    rerank_score: float | None = None


class PsiCatalogSearchData(BaseSchema):
    query: str
    items: list[PsiCatalogHit]
    total: int
    catalog_size: int
    generated_at: str
