from __future__ import annotations

from typing import Any

from core.observability import configure_observability


def test_configure_observability_keeps_traces_local_and_instruments_pydantic_ai(
    monkeypatch,
):
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
        lambda *, endpoint: ("exporter", endpoint),
    )
    monkeypatch.setattr(
        "core.observability.BatchSpanProcessor",
        lambda exporter: ("processor", exporter),
    )

    configure_observability()

    assert [name for name, _ in calls] == ["configure", "instrument_pydantic_ai"]
    assert calls[0][1]["send_to_logfire"] is False
    assert calls[0][1]["additional_span_processors"] == [
        ("processor", ("exporter", "http://127.0.0.1:4318/v1/traces"))
    ]
