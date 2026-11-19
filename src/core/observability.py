"""Tracing for the analysis agent.

Logfire runs without a token and prints spans to the server terminal. Langfuse
export is off by default. When enabled, spans are also sent to Langfuse over
OTLP, so model and tool metadata leaves the machine.
"""

from __future__ import annotations

import base64
import logging

import logfire
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from config import Settings, get_settings

logger = logging.getLogger("flame_atlas.observability")

LANGFUSE_TRACES_PATH = "/v1/traces"


def _langfuse_endpoint(base: str) -> str:
    endpoint = base.rstrip("/")
    if endpoint.endswith(LANGFUSE_TRACES_PATH):
        return endpoint
    return endpoint + LANGFUSE_TRACES_PATH


def _langfuse_processor(settings: Settings) -> BatchSpanProcessor | None:
    if not settings.langfuse_enabled:
        return None
    if not settings.langfuse_configured:
        logger.warning(
            "Langfuse tracing is enabled but LANGFUSE_PUBLIC_KEY or "
            "LANGFUSE_SECRET_KEY is missing; Langfuse export is disabled."
        )
        return None

    assert settings.langfuse_public_key is not None
    assert settings.langfuse_secret_key is not None
    credentials = (
        f"{settings.langfuse_public_key.get_secret_value()}:"
        f"{settings.langfuse_secret_key.get_secret_value()}"
    )
    token = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
    endpoint = _langfuse_endpoint(settings.langfuse_otlp_endpoint)
    logger.info("Langfuse trace export enabled: %s", endpoint)
    return BatchSpanProcessor(
        OTLPSpanExporter(
            endpoint=endpoint,
            headers={"Authorization": f"Basic {token}"},
        )
    )


def configure_observability(settings: Settings | None = None) -> None:
    """Configure terminal tracing and optional Langfuse export.

    `send_to_logfire=False` keeps Logfire from uploading spans. Langfuse export
    only runs when explicitly enabled and both API keys are present.
    """
    settings = settings or get_settings()
    processors = []
    langfuse = _langfuse_processor(settings)
    if langfuse is not None:
        processors.append(langfuse)

    logfire.configure(
        send_to_logfire=False,
        service_name="flame-atlas-backend",
        additional_span_processors=processors,
    )
    logfire.instrument_pydantic_ai()
