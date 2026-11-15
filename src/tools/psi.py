from __future__ import annotations

import logging

from core.data.catalog import ScopedCatalog
from core.data.psi_catalog import (
    PsiCatalogMatch,
    load_psi_catalog,
    rerank_matches,
    snippet,
    tokenize,
)
from core.data.reference import PSI_ID_RE
from core.data.registry import METRIC_NAMES
from core.data.reranker import load_reranker
from core.errors import ToolFault
from models import (
    Envelope,
    PsiCatalogHit,
    PsiCatalogSearchData,
    PsiCatalogSearchInput,
    PsiRecordData,
    PsiRecordInput,
)
from tools.common import provenance
from tools.context import AppContext

logger = logging.getLogger("flame_atlas.psi_catalog")


def _apply_reranker(
    ctx: AppContext, query: str, matches: list[PsiCatalogMatch]
) -> tuple[list[PsiCatalogMatch], str | None]:
    if not ctx.settings.reranker_enabled or not matches:
        return matches, None
    reranker = load_reranker(ctx.settings.reranker_model_dir)
    if reranker is None:
        return matches, (
            "Reranker is enabled but its model is unavailable; results use BM25 order."
        )
    try:
        return (
            rerank_matches(
                query,
                matches,
                reranker,
                pool_size=ctx.settings.reranker_pool_size,
            ),
            None,
        )
    except (OSError, RuntimeError, ValueError) as error:
        logger.warning("Reranker failed; using BM25 order: %s", error)
        return matches, "Reranker failed; results use BM25 order."


def _curated_investigations(ctx: AppContext) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for investigation_id, psi_ids in ctx.reference.psi_ids.items():
        for psi_id in psi_ids:
            mapping.setdefault(psi_id, []).append(investigation_id)
    return mapping


def _clip(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def search_psi_catalog(
    ctx: AppContext, request: PsiCatalogSearchInput
) -> Envelope[PsiCatalogSearchData]:
    query = " ".join(request.q.split())
    if not tokenize(query):
        raise ToolFault(
            "INVALID_QUERY",
            "Search query needs at least one word with two or more characters.",
        )
    try:
        index = load_psi_catalog(ctx.settings.psi_catalog_path)
    except (OSError, TypeError, ValueError) as error:
        raise ToolFault(
            "PSI_CATALOG_UNAVAILABLE",
            "The NASA PSI metadata catalog is not available.",
            status_code=503,
        ) from error

    curated = _curated_investigations(ctx)
    allowed = (
        ctx.catalog.allowed_investigation_ids
        if isinstance(ctx.catalog, ScopedCatalog)
        else None
    )
    normalized = query.strip().upper()
    accession_query = PSI_ID_RE.match(normalized) is not None
    if accession_query:
        matches = [
            PsiCatalogMatch(
                record=document.record,
                score=1.0,
                matched_terms=[normalized],
            )
            for document in index.documents
            if document.record.psi_id == normalized
        ]
    else:
        matches = index.search(query)

    # Scope first, then rerank: a scoped query must reorder only the records
    # the caller is allowed to see, not spend the pool on records it drops.
    filtered: list[tuple[PsiCatalogMatch, list[str]]] = []
    for match in matches:
        investigation_ids = curated.get(match.record.psi_id, [])
        if allowed is not None:
            investigation_ids = [
                investigation_id
                for investigation_id in investigation_ids
                if investigation_id in allowed
            ]
            if not investigation_ids:
                continue
        filtered.append((match, investigation_ids))

    investigation_ids_by_psi = {
        match.record.psi_id: investigation_ids for match, investigation_ids in filtered
    }
    matches = [match for match, _ in filtered]
    rerank_warning: str | None = None
    if not accession_query:
        matches, rerank_warning = _apply_reranker(ctx, query, matches)

    total = len(matches)
    hits: list[PsiCatalogHit] = []
    for match in matches[: request.limit]:
        investigation_ids = investigation_ids_by_psi[match.record.psi_id]
        record = match.record
        hits.append(
            PsiCatalogHit(
                psi_id=record.psi_id,
                title=_clip(record.title, 300),
                acronym=_clip(record.acronym, 120),
                research_area=_clip(record.research_area, 160),
                sub_research_area=_clip(record.sub_research_area, 160),
                snippet=snippet(record),
                url=ctx.reference.psi_url_template.format(id=record.psi_id),
                curated=bool(investigation_ids),
                investigation_ids=investigation_ids,
                restricted=record.restricted,
                score=match.score,
                rerank_score=match.rerank_score,
                matched_terms=match.matched_terms,
                modified_date=record.modified_date,
            )
        )

    warnings = [
        "PSI catalog results are metadata only; they do not carry measured data in this project."
    ]
    if rerank_warning is not None:
        warnings.append(rerank_warning)
    uncurated = sum(1 for hit in hits if not hit.curated)
    if uncurated:
        warnings.append(
            f"{uncurated} of {len(hits)} returned records are outside the "
            f"{len(ctx.reference.investigations)} curated investigations; "
            "treat them as leads, not evidence."
        )
    if any(hit.restricted for hit in hits):
        warnings.append(
            "Some returned records are restricted; their files may not be downloadable from PSI."
        )
    if total == 0:
        warnings.append("No PSI catalog record matched the query.")
    if allowed is not None:
        warnings.append(
            "PSI catalog search was limited to the PSI scope supplied with the request."
        )

    return Envelope(
        data=PsiCatalogSearchData(
            query=query,
            items=hits,
            total=total,
            catalog_size=index.size,
            generated_at=index.generated_at,
        ),
        warnings=warnings,
    )


def get_psi_record(ctx: AppContext, request: PsiRecordInput) -> Envelope[PsiRecordData]:
    psi_id = request.id.strip()
    if not PSI_ID_RE.match(psi_id):
        raise ToolFault("INVALID_QUERY", "PSI ID must look like PSI-25.")

    investigations = []
    records = []
    source_files: list[str] = []
    for investigation_id, psi_ids in ctx.reference.psi_ids.items():
        if psi_id not in psi_ids:
            continue
        record = ctx.catalog.get(investigation_id)
        records.append(record)
        investigations.append(
            {
                "id": investigation_id,
                "name": record.name,
                "sourceFiles": list(record.source_files),
            }
        )
        source_files.extend(record.source_files)
    if not investigations:
        raise ToolFault("PSI_NOT_FOUND", f"Unknown PSI record: {psi_id}", status_code=404)

    url = ctx.reference.psi_url_template.format(id=psi_id)
    return Envelope(
        data=PsiRecordData(
            psi_id=psi_id,
            ids=[psi_id],
            urls=[url],
            investigations=investigations,
            source_files=source_files,
        ),
        provenance=provenance(records, list(METRIC_NAMES)),
        warnings=[
            "External NASA PSI metadata is not configured; this is the local reference URL only."
        ],
    )
