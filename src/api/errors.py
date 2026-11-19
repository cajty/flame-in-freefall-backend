from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.errors import DomainError, ErrorCode, ToolFault, error_body

logger = logging.getLogger("flame_atlas.api")

DOMAIN_STATUS = {
    ErrorCode.INVESTIGATION_NOT_FOUND: 404,
    ErrorCode.ENVIRONMENT_NOT_FOUND: 404,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.OUT_OF_SCOPE: 400,
    ErrorCode.INVALID_QUERY: 400,
    ErrorCode.EXPORT_NOT_FOUND: 404,
    ErrorCode.EXPORT_EXPIRED: 410,
    ErrorCode.PSI_CATALOG_UNAVAILABLE: 503,
    ErrorCode.UNAVAILABLE: 503,
    ErrorCode.PSI_NOT_FOUND: 404,
}


def error_payload(code: str, message: str, details: list[str] | None = None) -> dict[str, Any]:
    return {"ok": False, "error": error_body(code, message, details)}


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=DOMAIN_STATUS.get(exc.code, 400),
        content=error_payload(exc.code, exc.message, exc.details),
    )


async def tool_fault_handler(request: Request, exc: ToolFault) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(exc.code, exc.message, exc.details),
    )


async def validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()))
        details.append(f"{location}: {error.get('msg', 'invalid value')}")
    return JSONResponse(
        status_code=400,
        content=error_payload("INVALID_REQUEST", "Request validation failed.", details),
    )


async def http_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
    message = "Not found." if exc.status_code == 404 else "Request failed."
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(code, message),
    )


async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error: %s", type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content=error_payload("INTERNAL_ERROR", "Internal server error."),
    )
