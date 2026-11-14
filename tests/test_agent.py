from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import (
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel

from agents.deps import ToolDeps
from agents.runner import run_analysis
from agents.tools import build_agent
from api.app import create_app
from core.errors import ToolFault
from core.services.scoring import rank
from models import AnalyzeInput


def _tool_returned(messages) -> bool:
    return any(
        isinstance(part, ToolReturnPart)
        for message in messages
        for part in getattr(message, "parts", [])
    )


def test_scripted_agent_calls_tool_and_returns_grounded_answer(context):
    def model_function(messages, info):
        if not _tool_returned(messages):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "get_investigation",
                        {"investigation_id": "bass2"},
                        tool_call_id="call-1",
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "final_result",
                    {
                        "answer": "BASS-II tested 13.6-22.2% O2 over 129 tests.",
                        "citations": [
                            {
                                "investigation_id": "bass2",
                                "source_file": "bass2/BASS-II_clean.csv",
                                "psi_id": "PSI-25",
                                "url": "https://psi.nasa.gov/physci/repo/data/investigations/PSI-25",
                            }
                        ],
                        "warnings": [],
                    },
                    tool_call_id="call-2",
                )
            ]
        )

    envelope = asyncio.run(
        run_analysis(
            context,
            AnalyzeInput(question="Compare BASS-II oxygen."),
            model_override=FunctionModel(model_function),
        )
    )
    assert envelope.data.plan["tools"] == ["get_investigation"]
    assert envelope.data.citations[0].psi_id == "PSI-25"
    assert envelope.data.download is None


def test_agent_without_tool_call_is_ungrounded(context):
    def model_function(messages, info):
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "final_result",
                    {"answer": "BASS-II has 129 tests.", "citations": [], "warnings": []},
                    tool_call_id="call-1",
                )
            ]
        )

    with pytest.raises(ToolFault) as error:
        asyncio.run(
            run_analysis(
                context,
                AnalyzeInput(question="How many tests?"),
                model_override=FunctionModel(model_function),
            )
        )
    assert error.value.code == "UNGROUNDED_ANSWER"
    assert error.value.status_code == 422


def test_agent_rejects_hallucinated_citation(context):
    def model_function(messages, info):
        if not _tool_returned(messages):
            return ModelResponse(
                parts=[ToolCallPart("get_schema", {}, tool_call_id="call-1")]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "final_result",
                    {
                        "answer": "BASS-II used PSI-999.",
                        "citations": [
                            {
                                "investigation_id": "bass2",
                                "source_file": "bass2/BASS-II_clean.csv",
                                "psi_id": "PSI-999",
                                "url": "https://example.com",
                            }
                        ],
                        "warnings": [],
                    },
                    tool_call_id="call-2",
                )
            ]
        )

    with pytest.raises(ToolFault) as error:
        asyncio.run(
            run_analysis(
                context,
                AnalyzeInput(question="Cite BASS-II."),
                model_override=FunctionModel(model_function),
            )
        )
    assert error.value.code == "INVALID_CITATION"


def test_agent_rejects_citation_that_no_tool_returned(context):
    def model_function(messages, info):
        if not _tool_returned(messages):
            return ModelResponse(
                parts=[ToolCallPart("get_schema", {}, tool_call_id="call-1")]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "final_result",
                    {
                        "answer": "BASS-II tested 13.6-22.2% O2 over 129 tests.",
                        "citations": [
                            {
                                "investigation_id": "bass2",
                                "source_file": "bass2/BASS-II_clean.csv",
                                "psi_id": "PSI-25",
                                "url": "https://psi.nasa.gov/physci/repo/data/investigations/PSI-25",
                            }
                        ],
                        "warnings": [],
                    },
                    tool_call_id="call-2",
                )
            ]
        )

    with pytest.raises(ToolFault) as error:
        asyncio.run(
            run_analysis(
                context,
                AnalyzeInput(question="How many BASS-II tests?"),
                model_override=FunctionModel(model_function),
            )
        )
    assert error.value.code == "UNGROUNDED_CITATION"
    assert error.value.status_code == 422


def test_agent_reuses_conversation_history_and_prior_provenance(context):
    seen: list[list] = []

    def model_function(messages, info):
        seen.append(list(messages))
        if not _tool_returned(messages):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "get_investigation",
                        {"investigation_id": "bass2"},
                        tool_call_id=f"tool-{len(seen)}",
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "final_result",
                    {
                        "answer": "BASS-II tested 13.6-22.2% O2 over 129 tests.",
                        "citations": [
                            {
                                "investigation_id": "bass2",
                                "source_file": "bass2/BASS-II_clean.csv",
                                "psi_id": "PSI-25",
                                "url": "https://psi.nasa.gov/physci/repo/data/investigations/PSI-25",
                            }
                        ],
                        "warnings": [],
                    },
                    tool_call_id=f"final-{len(seen)}",
                )
            ]
        )

    first = asyncio.run(
        run_analysis(
            context,
            AnalyzeInput(
                question="How many BASS-II tests?",
                conversation_id="conversation-1",
            ),
            model_override=FunctionModel(model_function),
        )
    )
    assert first.data.plan["tools"] == ["get_investigation"]

    second = asyncio.run(
        run_analysis(
            context,
            AnalyzeInput(
                question="Repeat that answer.",
                conversation_id="conversation-1",
            ),
            model_override=FunctionModel(model_function),
        )
    )
    assert second.data.plan["tools"] == []

    prompts = [
        part.content
        for message in seen[-1]
        for part in getattr(message, "parts", [])
        if isinstance(part, UserPromptPart)
    ]
    assert prompts == ["How many BASS-II tests?", "Repeat that answer."]


def test_agent_tool_errors_are_returned_to_model_and_cannot_ground(context):
    def model_function(messages, info):
        if not _tool_returned(messages):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        "get_investigation",
                        {"investigation_id": "nope"},
                        tool_call_id="call-1",
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "final_result",
                    {"answer": "Unknown.", "citations": [], "warnings": []},
                    tool_call_id="call-2",
                )
            ]
        )

    with pytest.raises(ToolFault) as error:
        asyncio.run(
            run_analysis(
                context,
                AnalyzeInput(question="What is nope?"),
                model_override=FunctionModel(model_function),
            )
        )
    assert error.value.code == "UNGROUNDED_ANSWER"


def test_test_model_registers_all_twelve_tools(context):
    deps = ToolDeps(ctx=context, timeout_seconds=5)
    agent = build_agent(TestModel(call_tools="all"))
    result = asyncio.run(agent.run("Compare.", deps=deps))
    assert result.output.answer is not None
    assert {call.name for call in deps.calls} == {
        "get_schema",
        "search_investigations",
        "get_investigation",
        "get_environments",
        "find_data_gaps",
        "compare_investigations",
        "run_query",
        "score_investigations",
        "export_csv",
        "query_tests",
        "aggregate_tests",
        "get_psi_record",
    }
    assert len(deps.calls) == 12
    assert all(call.duration_ms is not None for call in deps.calls)


def test_agent_request_scope_is_returned(context):
    def model_function(messages, info):
        if not _tool_returned(messages):
            return ModelResponse(
                parts=[ToolCallPart("get_schema", {}, tool_call_id="call-1")]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "final_result",
                    {
                        "answer": "Only BASS-II is in the supplied PSI scope.",
                        "citations": [],
                        "warnings": [],
                    },
                    tool_call_id="call-2",
                )
            ]
        )

    envelope = asyncio.run(
        run_analysis(
            context,
            AnalyzeInput(question="What is in scope?", psi_ids=["PSI-25"]),
            model_override=FunctionModel(model_function),
        )
    )
    assert envelope.data.scope == {
        "psiIds": ["PSI-25"],
        "investigationIds": ["bass2"],
    }
    assert set(envelope.data.generated) == {"bass2"}
    assert any("scoped to PSI IDs" in warning for warning in envelope.warnings)


def test_agent_prompt_includes_selected_environment(context):
    seen: list[str] = []

    def model_function(messages, info):
        if not seen:
            seen.append(messages[0].parts[0].content)
        if not _tool_returned(messages):
            return ModelResponse(
                parts=[ToolCallPart("get_schema", {}, tool_call_id="call-1")]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "final_result",
                    {"answer": "Ranked.", "citations": [], "warnings": []},
                    tool_call_id="call-2",
                )
            ]
        )

    asyncio.run(
        run_analysis(
            context,
            AnalyzeInput(
                question="Rank investigations for this habitat.",
                environment_id="moon",
                o2=30,
            ),
            model_override=FunctionModel(model_function),
        )
    )

    prompt = seen[0]
    assert "id: moon" in prompt
    assert "Lunar base" in prompt
    assert "30-40%" in prompt
    assert "Requested O2 probe: 30%." in prompt
    assert prompt.endswith("Rank investigations for this habitat.")


def test_agent_repeated_identical_tool_call_is_rejected(context):
    calls = {"count": 0}

    def model_function(messages, info):
        calls["count"] += 1
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "get_environments",
                    {},
                    tool_call_id=f"call-{calls['count']}",
                )
            ]
        )

    with pytest.raises(ToolFault) as error:
        asyncio.run(
            run_analysis(
                context,
                AnalyzeInput(question="Rank investigations for this habitat."),
                model_override=FunctionModel(model_function),
            )
        )

    assert error.value.code == "REPEATED_TOOL_CALL"
    assert error.value.status_code == 422
    assert calls["count"] == 2


def test_analysis_timeout(context):
    def slow_model(messages, info):
        time.sleep(0.2)
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "final_result",
                    {"answer": "late", "citations": [], "warnings": []},
                    tool_call_id="call-1",
                )
            ]
        )

    context.settings.analyze_timeout_seconds = 0.01
    with pytest.raises(ToolFault) as error:
        asyncio.run(
            run_analysis(
                context,
                AnalyzeInput(question="Slow?"),
                model_override=FunctionModel(slow_model),
            )
        )
    assert error.value.code == "ANALYZE_TIMEOUT"


def test_analysis_usage_limit_is_reported(context, monkeypatch):
    class LimitedAgent:
        async def run(self, *args, **kwargs):
            raise UsageLimitExceeded("request limit")

    monkeypatch.setattr("agents.runner.build_agent", lambda model: LimitedAgent())
    with pytest.raises(ToolFault) as error:
        asyncio.run(
            run_analysis(
                context,
                AnalyzeInput(question="Too many steps?"),
                model_override=object(),
            )
        )
    assert error.value.code == "ANALYZE_LIMIT_EXCEEDED"
    assert error.value.status_code == 500


def test_analyze_without_model_key_returns_503(context):
    with pytest.raises(ToolFault) as error:
        asyncio.run(
            run_analysis(context, AnalyzeInput(question="Compare."), model_override=None)
        )
    assert error.value.code == "MODEL_NOT_CONFIGURED"
    assert error.value.status_code == 503


def test_analyze_question_limit_via_api(client):
    response = client.post("/api/agent", json={"question": "x" * 2_001})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_analyze_rejects_malformed_conversation_id_via_api(client):
    response = client.post(
        "/api/agent",
        json={"question": "Compare.", "conversationId": "bad id"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_analyze_endpoint_with_injected_model(context):
    def model_function(messages, info):
        if not _tool_returned(messages):
            return ModelResponse(
                parts=[ToolCallPart("get_schema", {}, tool_call_id="call-1")]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    "final_result",
                    {
                        "answer": "There are 15 investigations.",
                        "citations": [],
                        "warnings": [],
                    },
                    tool_call_id="call-2",
                )
            ]
        )

    app = create_app(context=context, agent_model=FunctionModel(model_function))
    with TestClient(app) as client:
        response = client.post(
            "/api/agent",
            json={
                "question": "Rank investigations for the ISS at 30% O2.",
                "environmentId": "iss",
                "o2": 30,
            },
        )
        assert response.status_code == 200
        payload = response.json()["data"]
        assert payload["plan"]["tools"] == ["get_schema"]
        assert len(payload["generated"]) == 15
        assert payload["generated"]["bass2"]["tests"] == 129

        expected = rank(
            list(context.catalog.all()),
            context.catalog.environment("iss"),
            context.reference.theme_weights["iss"],
        )
        assert [item["investigationId"] for item in payload["ranking"]] == [
            record.id for record, _ in expected
        ]
        assert payload["ranking"][0]["score"] == expected[0][1].total

        expected_covers = [
            record.id
            for record in context.catalog.all()
            if record.o2[0] <= 30 <= record.o2[1]
        ]
        assert payload["covers"] == expected_covers
        assert payload["reach"] == len(expected_covers)


def test_analyze_unknown_environment_is_rejected(context):
    with pytest.raises(ToolFault) as error:
        asyncio.run(
            run_analysis(
                context,
                AnalyzeInput(question="Rank?", environment_id="nope"),
                model_override=object(),
            )
        )
    assert error.value.code == "ENVIRONMENT_NOT_FOUND"
    assert error.value.status_code == 404
