from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from core.errors import ToolFault
from tools.context import AppContext


async def run_tool(
    function: Callable[[AppContext, Any], Any],
    ctx: AppContext,
    request: Any,
    timeout: float | None = None,
) -> Any:
    limit = timeout if timeout is not None else ctx.settings.tool_timeout_seconds
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(function, ctx, request),
            timeout=limit,
        )
    except TimeoutError as error:
        raise ToolFault(
            "TOOL_TIMEOUT",
            "The tool did not finish within the allowed time.",
            status_code=500,
        ) from error
