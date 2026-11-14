from __future__ import annotations

from core.data.registry import CANONICAL_ORDER, METRIC_DEFS, METRIC_NAMES
from core.errors import ToolFault
from models import (
    Envelope,
    EnvironmentsData,
    GapItem,
    GapsData,
    GapsInput,
    GetInvestigationInput,
    InvestigationRecord,
    MetricDef,
    SchemaData,
    SearchData,
    SearchInput,
)
from tools.common import combined_warnings, provenance, record_warnings
from tools.context import AppContext

OPERATORS = ["eq", "neq", "lt", "lte", "gt", "gte", "between", "in"]


def get_schema(ctx: AppContext, _request: None = None) -> Envelope[SchemaData]:
    settings = ctx.settings
    data = SchemaData(
        metrics=[MetricDef.model_validate(metric) for metric in METRIC_DEFS],
        themes=list(ctx.reference.pillar_order),
        phases=list(ctx.reference.phases),
        investigation_ids=list(CANONICAL_ORDER),
        coverage=ctx.catalog.coverage(),
        operators=OPERATORS,
        limits={
            "investigations": settings.investigations_limit_max,
            "query": settings.query_limit_max,
            "compare": settings.compare_max_ids,
            "export": settings.export_max_rows,
            "question": settings.question_max_chars,
            "toolTimeoutSeconds": int(settings.tool_timeout_seconds),
        },
        generated_at=ctx.catalog.generated_at,
    )
    return Envelope(data=data)


def _validate_theme_phase(ctx: AppContext, theme: str | None, phase: str | None) -> None:
    if theme is not None and theme not in ctx.reference.pillar_order:
        raise ToolFault(
            "INVALID_QUERY",
            f"Unsupported theme: {theme}. Use get_schema for supported themes.",
        )
    if phase is not None and phase not in ctx.reference.phases:
        raise ToolFault(
            "INVALID_QUERY",
            f"Unsupported phase: {phase}. Use get_schema for supported phases.",
        )


def _matches_text(record: InvestigationRecord, tokens: list[str]) -> bool:
    haystack = (
        f"{record.name} {record.full} {record.obj} {record.fuel} {record.cond} {record.meas}"
    ).lower()
    return all(token in haystack for token in tokens)


def search_investigations(
    ctx: AppContext, request: SearchInput
) -> Envelope[SearchData]:
    _validate_theme_phase(ctx, request.theme, request.phase)
    if (
        request.o2_min is not None
        and request.o2_max is not None
        and request.o2_min > request.o2_max
    ):
        raise ToolFault("INVALID_QUERY", "o2Min must be less than or equal to o2Max.")
    if (request.o2_min is not None and not 0 <= request.o2_min <= 100) or (
        request.o2_max is not None and not 0 <= request.o2_max <= 100
    ):
        raise ToolFault("INVALID_QUERY", "O2 bounds must be between 0 and 100.")

    tokens = [token for token in (request.q or "").lower().split() if token]
    matches: list[InvestigationRecord] = []
    for record in ctx.catalog.all():
        if tokens and not _matches_text(record, tokens):
            continue
        if request.theme is not None and record.theme != request.theme:
            continue
        if request.phase is not None and record.phase != request.phase:
            continue
        if request.o2_min is not None and record.o2[1] < request.o2_min:
            continue
        if request.o2_max is not None and record.o2[0] > request.o2_max:
            continue
        if request.fuel is not None:
            fuel_text = " ".join(record.data.fuels if record.data else []).lower()
            if request.fuel.lower() not in f"{record.fuel} {fuel_text}".lower():
                continue
        if request.has_data is not None:
            has_data = (
                record.data is not None
                and record.data.tests > 0
                and not record.planned_only
            )
            if has_data != request.has_data:
                continue
        matches.append(record)

    total = len(matches)
    page = matches[request.offset : request.offset + request.limit]
    return Envelope(
        data=SearchData(
            items=page,
            total=total,
            limit=request.limit,
            offset=request.offset,
        ),
        provenance=provenance(page, list(METRIC_NAMES)),
    )


def get_investigation(
    ctx: AppContext, request: GetInvestigationInput
) -> Envelope[InvestigationRecord]:
    record = ctx.catalog.get(request.id)
    warnings = combined_warnings(
        record_warnings(record, list(METRIC_NAMES)),
        (
            [f"{record.name} has no ISO test dates in the cleaned table."]
            if record.data is not None and record.data.date is None
            else []
        ),
    )
    return Envelope(
        data=record,
        provenance=provenance([record], list(METRIC_NAMES)),
        warnings=warnings,
    )


def get_environments(
    ctx: AppContext, _request: None = None
) -> Envelope[EnvironmentsData]:
    return Envelope(data=EnvironmentsData(items=list(ctx.reference.environments)))


def find_data_gaps(ctx: AppContext, request: GapsInput) -> Envelope[GapsData]:
    requested = request.ids
    if requested is not None:
        seen: set[str] = set()
        for investigation_id in requested:
            if investigation_id in seen:
                raise ToolFault(
                    "INVALID_QUERY", f"Duplicate investigation ID: {investigation_id}"
                )
            seen.add(investigation_id)
    records = (
        list(ctx.catalog.all())
        if requested is None
        else [ctx.catalog.get(investigation_id) for investigation_id in requested]
    )
    items: list[GapItem] = ctx.catalog.gaps(requested)
    return Envelope(
        data=GapsData(items=items),
        provenance=provenance(records, list(METRIC_NAMES)),
    )
