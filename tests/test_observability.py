from __future__ import annotations

import base64
from typing import Any

from config import Settings
from core.observability import _langfuse_endpoint, configure_observability


def _settings(**values: Any) -> Settings:
    return Settings(_env_file=None, gemini_api_key=None, **values)


def _patch_tracing(monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "core.observability.logfire.configure",
        lambda **kwargs: calls.append(("configure", kwargs)),
    )
    monkeypatch.setattr(
        "core.observability.logfire.instrument_pydantic_ai",
        lambda: calls.append(("instrument_pydantic_ai", {})),
    )
    monkeypatch.setattr(
        "core.observability.OTLPSpanExporter",
        lambda **kwargs: ("exporter", kwargs),
    )
    monkeypatch.setattr(
        "core.observability.BatchSpanProcessor",
        lambda exporter: ("processor", exporter),
    )
    return calls


def test_configure_observability_is_local_by_default(monkeypatch):
    calls = _patch_tracing(monkeypatch)

    configure_observability(_settings())

    assert [name for name, _ in calls] == ["configure", "instrument_pydantic_ai"]
    assert calls[0][1]["send_to_logfire"] is False
    assert calls[0][1]["additional_span_processors"] == []


def test_configure_observability_adds_langfuse_exporter_when_configured(monkeypatch):
    calls = _patch_tracing(monkeypatch)
    settings = _settings(
        langfuse_enabled=True,
        langfuse_public_key="pk-lf-test",
        langfuse_secret_key="sk-lf-test",
        langfuse_otlp_endpoint="https://cloud.langfuse.com/api/public/otel",
    )

    configure_observability(settings)

    processors = calls[0][1]["additional_span_processors"]
    assert len(processors) == 1
    _, exporter = processors[0]
    assert exporter[1]["endpoint"] == (
        "https://cloud.langfuse.com/api/public/otel/v1/traces"
    )
    token = exporter[1]["headers"]["Authorization"].removeprefix("Basic ")
    assert base64.b64decode(token).decode("utf-8") == "pk-lf-test:sk-lf-test"


def test_langfuse_enabled_without_keys_keeps_local_tracing(monkeypatch, caplog):
    calls = _patch_tracing(monkeypatch)

    configure_observability(_settings(langfuse_enabled=True))

    assert calls[0][1]["additional_span_processors"] == []
    assert "Langfuse tracing is enabled" in caplog.text


def test_langfuse_endpoint_does_not_duplicate_trace_path():
    assert _langfuse_endpoint("https://langfuse.local/api/public/otel") == (
        "https://langfuse.local/api/public/otel/v1/traces"
    )
    assert _langfuse_endpoint(
        "https://langfuse.local/api/public/otel/v1/traces"
    ) == "https://langfuse.local/api/public/otel/v1/traces"
