from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from core.data.registry import CANONICAL_ORDER
from core.errors import ToolFault
from models import AnalyzeInput, GapsInput, GetInvestigationInput, SearchInput
from tools.context import AppContext
from tools.runner import run_tool
from tools.summary_tools import (
    find_data_gaps,
    get_environments,
    get_investigation,
    get_schema,
    search_investigations,
)

router = APIRouter(prefix="/api")


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
        raise ToolFault("UNAUTHORIZED", "A valid bearer token is required.", 401)


def _payload(envelope) -> dict:
    return envelope.model_dump(by_alias=True)


def _model(model, **values):
    try:
        return model(**values)
    except ValidationError as error:
        details = [
            f"{'.'.join(str(part) for part in item.get('loc', ()))}: {item.get('msg', 'invalid value')}"
            for item in error.errors()
        ]
        raise ToolFault("INVALID_REQUEST", "Request validation failed.", details=details) from error


@router.get("/health")
async def health(request: Request) -> dict:
    ctx = context(request)
    return {
        "ok": True,
        "data": {
            "status": "ok",
            "generatedAt": ctx.catalog.generated_at,
            "investigations": len(CANONICAL_ORDER),
            "tables": ctx.table_count,
        },
        "warnings": [],
    }


@router.get("/schema")
async def schema(request: Request) -> JSONResponse:
    ctx = context(request)
    envelope = await run_tool(get_schema, ctx, None)
    return JSONResponse(
        content=_payload(envelope),
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/investigations")
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
):
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
    return _payload(await run_tool(search_investigations, ctx, request_model))


@router.get("/investigations/{investigation_id}")
async def investigation(request: Request, investigation_id: str):
    ctx = context(request)
    return _payload(
        await run_tool(
            get_investigation, ctx, GetInvestigationInput(id=investigation_id)
        )
    )


@router.get("/environments")
async def environments(request: Request):
    ctx = context(request)
    return _payload(await run_tool(get_environments, ctx, None))


@router.get("/gaps")
async def gaps(request: Request, ids: str | None = None):
    ctx = context(request)
    parsed = [item.strip() for item in ids.split(",") if item.strip()] if ids else None
    return _payload(await run_tool(find_data_gaps, ctx, GapsInput(ids=parsed)))


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


@router.post("/agent", dependencies=[Depends(require_auth)])
async def analyze(request: Request, payload: AnalyzeInput):
    ctx = context(request)
    if ctx.settings.rate_limit_enabled:
        client = request.client.host if request.client else "unknown"
        if not request.app.state.rate_limiter.allow(client):
            raise ToolFault("RATE_LIMITED", "Rate limit exceeded.", 429)
    from agents.runner import run_analysis

    result = await run_analysis(
        ctx,
        payload,
        model_override=request.app.state.agent_model,
        request_id=getattr(request.state, "request_id", None),
    )
    return _payload(result)
