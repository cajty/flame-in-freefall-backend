from __future__ import annotations

import secrets
from typing import TypeVar

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from agents.runner import run_analysis
from core.context import AppContext
from core.data.registry import CANONICAL_ORDER
from core.errors import ErrorCode, ToolFault
from core.services.investigations import (
    find_data_gaps,
    get_environments,
    get_investigation,
    get_schema,
    search_investigations,
)
from models import (
    AnalyzeData,
    AnalyzeInput,
    Envelope,
    EnvironmentsData,
    GapsData,
    GapsInput,
    GetInvestigationInput,
    HealthData,
    InvestigationRecord,
    SchemaData,
    SearchData,
    SearchInput,
)
from tools.runner import run_tool

router = APIRouter(prefix="/api")
ModelT = TypeVar("ModelT", bound=BaseModel)


def context(request: Request) -> AppContext:
    return request.app.state.ctx


async def require_auth(request: Request) -> None:
    settings = context(request).settings
    if not settings.auth_enabled:
        return
    configured = (
        settings.api_token.get_secret_value() if settings.api_token is not None else ""
    )
    header = request.headers.get("Authorization", "")
    if not configured or not secrets.compare_digest(header, f"Bearer {configured}"):
        raise ToolFault(ErrorCode.UNAUTHORIZED, "A valid bearer token is required.", 401)


def _payload(envelope) -> dict:
    return envelope.model_dump(by_alias=True)


def _model(model: type[ModelT], **values) -> ModelT:
    try:
        return model(**values)
    except ValidationError as error:
        details = [
            f"{'.'.join(str(part) for part in item.get('loc', ()))}: {item.get('msg', 'invalid value')}"
            for item in error.errors()
        ]
        raise ToolFault(
            ErrorCode.INVALID_REQUEST,
            "Request validation failed.",
            details=details,
        ) from error


@router.get("/health", response_model=Envelope[HealthData])
async def health(request: Request) -> Envelope[HealthData]:
    ctx = context(request)
    return Envelope(
        data=HealthData(
            status="ok",
            generated_at=ctx.catalog.generated_at,
            investigations=len(CANONICAL_ORDER),
            tables=ctx.table_count,
        )
    )


@router.get("/schema", response_model=Envelope[SchemaData])
async def schema(request: Request) -> JSONResponse:
    ctx = context(request)
    envelope = await run_tool(get_schema, ctx, None)
    return JSONResponse(
        content=_payload(envelope),
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/investigations", response_model=Envelope[SearchData])
async def list_investigations(
    request: Request,
    q: str | None = None,
    theme: str | None = None,
    phase: str | None = None,
    o2Min: float | None = Query(default=None),
    o2Max: float | None = Query(default=None),
    fuel: str | None = None,
    hasData: bool | None = Query(default=None),
    limit: int = Query(default=50),
    offset: int = Query(default=0),
) -> Envelope[SearchData]:
    ctx = context(request)
    request_model = _model(
        SearchInput,
        q=q,
        theme=theme,
        phase=phase,
        o2_min=o2Min,
        o2_max=o2Max,
        fuel=fuel,
        has_data=hasData,
        limit=limit,
        offset=offset,
    )
    return await run_tool(search_investigations, ctx, request_model)


@router.get(
    "/investigations/{investigation_id}",
    response_model=Envelope[InvestigationRecord],
)
async def investigation(
    request: Request, investigation_id: str
) -> Envelope[InvestigationRecord]:
    ctx = context(request)
    return await run_tool(
        get_investigation, ctx, GetInvestigationInput(id=investigation_id)
    )


@router.get("/environments", response_model=Envelope[EnvironmentsData])
async def environments(request: Request) -> Envelope[EnvironmentsData]:
    ctx = context(request)
    return await run_tool(get_environments, ctx, None)


@router.get("/gaps", response_model=Envelope[GapsData])
async def gaps(request: Request, ids: str | None = None) -> Envelope[GapsData]:
    ctx = context(request)
    parsed = [item.strip() for item in ids.split(",") if item.strip()] if ids else None
    return await run_tool(find_data_gaps, ctx, GapsInput(ids=parsed))


@router.get("/exports/{export_id}")
async def download_export(request: Request, export_id: str) -> Response:
    ctx = context(request)
    artifact = ctx.exports.get(export_id)
    return Response(
        content=artifact.content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/agent",
    dependencies=[Depends(require_auth)],
    response_model=Envelope[AnalyzeData],
)
async def analyze(request: Request, payload: AnalyzeInput) -> Envelope[AnalyzeData]:
    ctx = context(request)
    if ctx.settings.rate_limit_enabled:
        client = request.client.host if request.client else "unknown"
        if not request.app.state.rate_limiter.allow(client):
            raise ToolFault(ErrorCode.RATE_LIMITED, "Rate limit exceeded.", 429)

    result = await run_analysis(
        ctx,
        payload,
        model_override=request.app.state.agent_model,
        request_id=getattr(request.state, "request_id", None),
    )
    return result
