from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.errors import (
    http_handler,
    tool_fault_handler,
    unhandled_handler,
    validation_handler,
)
from api.middleware import (
    BodyLimitMiddleware,
    FixedWindowRateLimiter,
    RequestContextMiddleware,
)
from api.routes import router
from config import Settings, get_settings
from core.errors import ToolFault
from tools.context import AppContext, build_context


def create_app(
    settings: Settings | None = None,
    context: AppContext | None = None,
    agent_model: Any = None,
    clock: Callable[[], float] = time.time,
) -> FastAPI:
    if settings is None:
        settings = context.settings if context is not None else get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        active_context = context or build_context(settings, clock=clock)
        app.state.ctx = active_context
        app.state.rate_limiter = FixedWindowRateLimiter(
            settings.analyze_rate_limit_per_minute,
            clock=clock,
        )
        app.state.agent_model = agent_model
        yield
        close = getattr(app.state, "close_agent_client", None)
        if close is not None:
            await close()

    app = FastAPI(
        title="Flame Atlas backend",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        BodyLimitMiddleware, max_bytes=settings.max_request_body_bytes
    )
    app.add_middleware(RequestContextMiddleware, clock=clock)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
        expose_headers=["Content-Disposition", "X-Request-ID"],
    )

    app.add_exception_handler(ToolFault, tool_fault_handler)
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_handler)
    app.add_exception_handler(Exception, unhandled_handler)
    app.include_router(router)
    return app
