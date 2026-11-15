"""Local search index over the NASA PSI investigation catalog.

`scripts/fetch_psi_catalog.py` writes `data/reference/psi_catalog.json` offline.
This module only reads that file, so the API never depends on psi.nasa.gov at
request time. The catalog is small (133 records at the time of writing), so
BM25 over weighted metadata stays the baseline. An optional cross-encoder
reranker can reorder the top BM25 hits; it never adds or removes records.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from core.data.reranker import Reranker
from models import PsiCatalogRecord

TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "with",
    }
)
FIELD_BOOSTS: tuple[tuple[str, int], ...] = (
    ("psi_id", 3),
    ("title", 3),
    ("acronym", 3),
    ("research_area", 2),
    ("sub_research_area", 2),
    ("experiment_hardware", 1),
    ("objective", 1),
    ("approach", 1),
    ("hypothesis", 1),
    ("research_impacts", 1),
    ("flight_program", 1),
    ("project_type", 1),
)
RERANK_TEXT_FIELDS: tuple[str, ...] = (
    "title",
    "acronym",
    "research_area",
    "sub_research_area",
    "experiment_hardware",
    "objective",
    "approach",
    "hypothesis",
    "research_impacts",
    "flight_program",
)
BM25_K1 = 1.5
BM25_B = 0.75
SNIPPET_CHARS = 400
PSI_ID_RE = re.compile(r"^PSI-\d+$")


def tokenize(text: str) -> list[str]:
    tokens = [token for token in TOKEN_RE.findall(text.lower()) if len(token) > 1]
    return [token for token in tokens if token not in STOPWORDS]


@dataclass(frozen=True)
class PsiCatalogMatch:
    record: PsiCatalogRecord
    score: float
    matched_terms: list[str]
    rerank_score: float | None = None


@dataclass(frozen=True)
class _IndexedDocument:
    record: PsiCatalogRecord
    term_frequencies: dict[str, int]
    length: int


@dataclass(frozen=True)
class PsiCatalogIndex:
    generated_at: str
    documents: tuple[_IndexedDocument, ...]
    document_frequency: dict[str, int]
    average_length: float

    @property
    def size(self) -> int:
        return len(self.documents)

    def search(self, query: str) -> list[PsiCatalogMatch]:
        query_terms = tokenize(query)
        if not query_terms:
            return []
        ordered_terms = list(dict.fromkeys(query_terms))
        matches: list[PsiCatalogMatch] = []
        total = self.size
        for document in self.documents:
            score = 0.0
            matched: list[str] = []
            for term in ordered_terms:
                frequency = document.term_frequencies.get(term, 0)
                if frequency == 0:
                    continue
                matched.append(term)
                document_frequency = self.document_frequency[term]
                inverse_frequency = math.log(
                    1 + (total - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                denominator = frequency + BM25_K1 * (
                    1 - BM25_B + BM25_B * document.length / self.average_length
                )
                score += inverse_frequency * frequency * (BM25_K1 + 1) / denominator
            if score > 0:
                matches.append(
                    PsiCatalogMatch(
                        record=document.record,
                        score=round(score, 6),
                        matched_terms=matched,
                    )
                )
        matches.sort(
            key=lambda item: (-item.score, _accession_number(item.record.psi_id))
        )
        return matches


def _accession_number(psi_id: str) -> int:
    try:
        return int(psi_id.removeprefix("PSI-"))
    except ValueError:
        return 2**31 - 1


def rerank_text(record: PsiCatalogRecord) -> str:
    """Flatten the metadata a cross-encoder reads for one catalog record."""
    parts = []
    for field in RERANK_TEXT_FIELDS:
        value = getattr(record, field)
        if value:
            parts.append(" ".join(value.split()))
    return " ".join(parts)


def rerank_matches(
    query: str,
    matches: list[PsiCatalogMatch],
    reranker: Reranker,
    pool_size: int,
) -> list[PsiCatalogMatch]:
    """Reorder the top BM25 hits with a cross-encoder.

    The BM25 score stays on every match; the cross-encoder score is added as
    `rerank_score`. Records outside the pool keep their BM25 order and appear
    after the reranked pool, so no record is dropped and no search result is
    invented.
    """
    if not matches:
        return []
    pool = matches[: min(pool_size, len(matches))]
    tail = matches[len(pool) :]
    scores = reranker.score(query, [rerank_text(match.record) for match in pool])
    if len(scores) != len(pool):
        raise ValueError(
            f"reranker returned {len(scores)} scores for {len(pool)} documents"
        )
    ranked = [
        PsiCatalogMatch(
            record=match.record,
            score=match.score,
            matched_terms=match.matched_terms,
            rerank_score=round(float(score), 6),
        )
        for match, score in zip(pool, scores)
    ]
    ranked.sort(
        key=lambda item: (
            -(item.rerank_score if item.rerank_score is not None else 0.0),
            _accession_number(item.record.psi_id),
        )
    )
    return ranked + list(tail)


def _document(record: PsiCatalogRecord) -> _IndexedDocument:
    tokens: list[str] = []
    for field, boost in FIELD_BOOSTS:
        if field == "psi_id":
            # Index the accession number only. The shared "PSI-" prefix would
            # match every record and drown out real query terms.
            tokens.extend([record.psi_id.removeprefix("PSI-").lower()] * boost)
            continue
        value = getattr(record, field)
        if value:
            tokens.extend(tokenize(value) * boost)
    frequencies: dict[str, int] = {}
    for token in tokens:
        frequencies[token] = frequencies.get(token, 0) + 1
    return _IndexedDocument(
        record=record,
        term_frequencies=frequencies,
        length=len(tokens),
    )


@lru_cache(maxsize=4)
def load_psi_catalog(path: Path) -> PsiCatalogIndex:
    """Load and index the local catalog. Raises when the file is unusable."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("psi_catalog.json must contain an object")
    items = raw.get("items")
    if not isinstance(items, list):
        raise TypeError("psi_catalog.json must contain an items list")
    records = [PsiCatalogRecord.model_validate(item) for item in items]
    if not records:
        raise ValueError("catalog contains no records")
    seen: set[str] = set()
    for record in records:
        if not PSI_ID_RE.match(record.psi_id):
            raise ValueError(f"invalid catalog PSI ID: {record.psi_id!r}")
        if record.psi_id in seen:
            raise ValueError(f"duplicate catalog record: {record.psi_id}")
        seen.add(record.psi_id)
    declared = raw.get("count")
    if isinstance(declared, int) and declared != len(records):
        raise ValueError(
            f"catalog count {declared} does not match {len(records)} records"
        )
    documents = tuple(_document(record) for record in records)
    document_frequency: dict[str, int] = {}
    for document in documents:
        for term in document.term_frequencies:
            document_frequency[term] = document_frequency.get(term, 0) + 1
    average_length = (
        sum(document.length for document in documents) / len(documents)
        if documents
        else 0.0
    )
    return PsiCatalogIndex(
        generated_at=str(raw.get("generatedAt", "")),
        documents=documents,
        document_frequency=document_frequency,
        average_length=average_length or 1.0,
    )


def snippet(record: PsiCatalogRecord, limit: int = SNIPPET_CHARS) -> str:
    for value in (
        record.objective,
        record.approach,
        record.hypothesis,
        record.research_impacts,
        record.title,
    ):
        text = " ".join(value.split())
        if not text:
            continue
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."
    return ""
