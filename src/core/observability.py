"""Local-only tracing for the analysis agent.

Logfire runs without a token or the Logfire cloud: spans are printed to the
server's terminal by the SDK's console exporter and sent to a local Jaeger
instance started from `compose.yaml`.
"""

from __future__ import annotations

import logfire
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor

JAEGER_OTLP_ENDPOINT = "http://127.0.0.1:4318/v1/traces"


def configure_observability() -> None:
    """Trace Pydantic AI runs locally.

    `send_to_logfire=False` keeps every span inside this process, so the
    Gemini key and the investigation data never leave the machine.
    """
    logfire.configure(
        send_to_logfire=False,
        service_name="flame-atlas-backend",
        additional_span_processors=[
            BatchSpanProcessor(OTLPSpanExporter(endpoint=JAEGER_OTLP_ENDPOINT))
        ],
    )
    logfire.instrument_pydantic_ai()
