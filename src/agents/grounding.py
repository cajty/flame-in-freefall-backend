from __future__ import annotations

from typing import Any

from agents.deps import ToolDeps
from core.errors import DomainError, ToolFault
from core.services.scoring import rank, to_score_items
from models import AnalysisAnswer, AnalyzeData, Envelope, ProvenanceItem
from core.services.metrics import combined_warnings
from core.context import AppContext


def _validate_citations(ctx: AppContext, answer: AnalysisAnswer) -> None:
    for citation in answer.citations:
        try:
            record = ctx.catalog.get(citation.investigation_id)
        except DomainError as error:
            raise ToolFault(
                "INVALID_CITATION",
                f"Citation names an unknown investigation: {citation.investigation_id}",
                status_code=422,
            ) from error

        if citation.source_file not in {*record.source_files, "generated.json"}:
            raise ToolFault(
                "INVALID_CITATION",
                f"Citation source file is not attached to {citation.investigation_id}.",
                status_code=422,
            )
        if citation.psi_id not in record.psi.ids:
            raise ToolFault(
                "INVALID_CITATION",
                f"Citation PSI ID is not mapped to {citation.investigation_id}.",
                status_code=422,
            )
        expected_url = ctx.reference.psi_url_template.format(id=citation.psi_id)
        if citation.url != expected_url:
            raise ToolFault(
                "INVALID_CITATION",
                "Citation URL does not match the local PSI reference.",
                status_code=422,
            )


def _validate_citation_grounding(deps: ToolDeps, answer: AnalysisAnswer) -> None:
    pairs = deps.grounded_provenance
    grounded_investigations = {investigation_id for investigation_id, _ in pairs}
    for citation in answer.citations:
        if citation.source_file == "generated.json":
            grounded = citation.investigation_id in grounded_investigations
        else:
            grounded = (citation.investigation_id, citation.source_file) in pairs
        if not grounded:
            raise ToolFault(
                "UNGROUNDED_CITATION",
                (
                    f"Citation for {citation.investigation_id} is not backed by "
                    "a tool result in this conversation."
                ),
                status_code=422,
            )


def _dedupe_provenance(items: list[ProvenanceItem]) -> list[ProvenanceItem]:
    seen: set[tuple[str, str, tuple[str, ...]]] = set()
    result: list[ProvenanceItem] = []
    for item in items:
        key = (item.investigation_id, item.source_file, tuple(item.fields))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _ranking(ctx: AppContext, environment_id: str) -> list:
    environment = ctx.catalog.environment(environment_id)
    weights = ctx.reference.theme_weights[environment.id]
    ranked = rank(list(ctx.catalog.all()), environment, weights)
    return to_score_items(ranked)


def _covers(ctx: AppContext, probe: float) -> list[str]:
    return [
        record.id
        for record in ctx.catalog.all()
        if record.o2[0] <= probe <= record.o2[1]
    ]


def assemble(
    ctx: AppContext,
    deps: ToolDeps,
    answer: AnalysisAnswer,
    environment_id: str | None = None,
    probe: float | None = None,
) -> Envelope[AnalyzeData]:
    successful = [call for call in deps.calls if call.ok]
    if not successful and not deps.history_provenance:
        raise ToolFault(
            "UNGROUNDED_ANSWER",
            "The agent returned no grounded tool result.",
            status_code=422,
        )

    _validate_citations(ctx, answer)
    _validate_citation_grounding(deps, answer)

    warnings: list[str] = []
    provenance: list[ProvenanceItem] = []
    download: dict[str, Any] | None = None
    for call in successful:
        envelope = call.envelope
        warnings.extend(envelope.warnings)
        provenance.extend(envelope.provenance)
        data = getattr(envelope, "data", None)
        if data is not None and hasattr(data, "download_url"):
            download = data.model_dump(by_alias=True)

    warnings.extend(answer.warnings)
    plan = {
        "tools": list(dict.fromkeys(call.name for call in deps.calls))
    }
    scope = None
    if deps.scope_psi_ids:
        scope = {
            "psiIds": list(deps.scope_psi_ids),
            "investigationIds": list(deps.scope_investigation_ids),
        }
        warnings.insert(
            0,
            "Request scoped to PSI IDs: " + ", ".join(deps.scope_psi_ids) + ".",
        )

    ranking = _ranking(ctx, environment_id) if environment_id is not None else None
    covers = _covers(ctx, probe) if probe is not None else None

    return Envelope(
        data=AnalyzeData(
            answer=answer.answer,
            plan=plan,
            citations=answer.citations,
            warnings=combined_warnings(warnings),
            generated=dict(ctx.catalog.summaries),
            ranking=ranking,
            covers=covers,
            reach=len(covers) if covers is not None else None,
            download=download,
            scope=scope,
        ),
        provenance=_dedupe_provenance(provenance),
        warnings=combined_warnings(warnings),
    )
