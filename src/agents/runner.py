from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import UsageLimits
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider

from agents.deps import ToolDeps
from agents.grounding import assemble
from agents.tools import build_agent
from config import Settings
from core.data.reference import PSI_ID_RE
from core.errors import ToolFault
from models import AnalyzeInput, Envelope
from tools.context import AppContext, with_scope

logger = logging.getLogger("flame_atlas.agent")


def resolve_psi_scope(
    ctx: AppContext, psi_ids: list[str] | None
) -> tuple[list[str], list[str]] | None:
    if not psi_ids:
        return None

    ordered: list[str] = []
    for psi_id in psi_ids:
        if psi_id not in ordered:
            ordered.append(psi_id)

    investigation_ids: list[str] = []
    for psi_id in ordered:
        if not PSI_ID_RE.match(psi_id):
            raise ToolFault(
                "INVALID_REQUEST",
                f"Invalid PSI ID: {psi_id}. Use the form PSI-25.",
            )
        matches = [
            investigation_id
            for investigation_id, mapped in ctx.reference.psi_ids.items()
            if psi_id in mapped
        ]
        if not matches:
            raise ToolFault(
                "PSI_NOT_FOUND",
                f"Unknown PSI record: {psi_id}",
                status_code=404,
            )
        for investigation_id in matches:
            if investigation_id not in investigation_ids:
                investigation_ids.append(investigation_id)
    return ordered, investigation_ids


def build_model(settings: Settings) -> GoogleModel:
    if not settings.model_configured:
        raise ToolFault(
            "MODEL_NOT_CONFIGURED",
            "The analysis model is not configured.",
            status_code=503,
        )
    assert settings.gemini_api_key is not None
    return GoogleModel(
        settings.gemini_model,
        provider=GoogleProvider(api_key=settings.gemini_api_key.get_secret_value()),
    )


async def run_analysis(
    ctx: AppContext,
    request: AnalyzeInput,
    model_override: Any = None,
    request_id: str | None = None,
) -> Envelope:
    scope = resolve_psi_scope(ctx, request.psi_ids)
    active_ctx = with_scope(ctx, scope[1]) if scope is not None else ctx
    settings = ctx.settings
    environment = None
    if request.environment_id is not None:
        environment = ctx.catalog.environment(request.environment_id)
    if model_override is None and not settings.model_configured:
        raise ToolFault(
            "MODEL_NOT_CONFIGURED",
            "The analysis model is not configured.",
            status_code=503,
        )

    prompt_parts: list[str] = []
    if environment is not None:
        prompt_parts.append(
            f"Selected environment: {environment.name} (id: {environment.id}); "
            f"O2 window {environment.o2[0]:g}-{environment.o2[1]:g}%; "
            f"pressure {environment.psi}."
        )
        prompt_parts.append(
            'Treat phrases such as "this habitat" as this selected environment.'
        )
    if request.o2 is not None:
        prompt_parts.append(f"Requested O2 probe: {request.o2:g}%.")
    prompt = (
        "\n".join(prompt_parts) + "\n\n" + request.question
        if prompt_parts
        else request.question
    )

    model = model_override or build_model(settings)
    agent = build_agent(model)
    conversation_id = request.conversation_id
    conversation = (
        active_ctx.conversations.snapshot(conversation_id)
        if conversation_id is not None
        else None
    )
    deps = ToolDeps(
        ctx=active_ctx,
        timeout_seconds=settings.tool_timeout_seconds,
        scope_psi_ids=scope[0] if scope is not None else [],
        scope_investigation_ids=scope[1] if scope is not None else [],
        history_provenance=(
            set(conversation.provenance) if conversation is not None else set()
        ),
    )

    try:
        result = await agent.run(
            prompt,
            deps=deps,
            message_history=(
                list(conversation.messages)
                if conversation is not None and conversation.messages
                else None
            ),
            usage_limits=UsageLimits(
                tool_calls_limit=settings.tool_calls_limit,
                request_limit=settings.model_request_limit,
            ),
            timeout=settings.analyze_timeout_seconds,
        )
    except TimeoutError as error:
        raise ToolFault(
            "ANALYZE_TIMEOUT",
            "The analysis request timed out.",
            status_code=500,
        ) from error
    except UsageLimitExceeded as error:
        logger.error(
            "usage limit reached request_id=%s detail=%s tool_calls=%s tool_calls_limit=%s model_request_limit=%s tools=%s",
            request_id,
            error,
            len(deps.calls),
            settings.tool_calls_limit,
            settings.model_request_limit,
            [(call.name, call.error.get("code") if call.error else None) for call in deps.calls],
        )
        for index, call in enumerate(deps.calls, start=1):
            logger.error(
                "tool call #%s name=%s duration_ms=%s error=%s args=%s",
                index,
                call.name,
                call.duration_ms,
                call.error.get("code") if call.error else None,
                call.arguments,
            )
        raise ToolFault(
            "ANALYZE_LIMIT_EXCEEDED",
            (
                "The analysis request used too many model or tool steps "
                f"(tool calls: {settings.tool_calls_limit}, "
                f"model requests: {settings.model_request_limit})."
            ),
            status_code=500,
        ) from error
    except ToolFault:
        raise
    except Exception as error:
        logger.exception("analysis failed: %s", type(error).__name__)
        raise ToolFault(
            "MODEL_UNAVAILABLE",
            "The analysis model is unavailable.",
            status_code=503,
        ) from error

    usage = result.usage
    logger.info(
        "analysis request_id=%s requests=%s tool_calls=%s input_tokens=%s output_tokens=%s",
        request_id,
        getattr(usage, "requests", None),
        getattr(usage, "tool_calls", None),
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
    )
    envelope = assemble(
        active_ctx,
        deps,
        result.output,
        environment_id=request.environment_id,
        probe=request.o2,
    )
    if conversation_id is not None:
        active_ctx.conversations.append(
            conversation_id,
            tuple(result.new_messages()),
            deps.current_provenance,
        )
    return envelope
