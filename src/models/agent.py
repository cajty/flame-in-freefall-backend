from __future__ import annotations

from typing import Any

from pydantic import Field

from models.base import BaseSchema
from models.common import SummaryRecord
from models.query import ScoreItem


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
