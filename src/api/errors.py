from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.errors import ToolFault

logger = logging.getLogger("flame_atlas.api")


def error_payload(code: str, message: str, details: list[str] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"ok": False, "error": error}


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
