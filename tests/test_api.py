from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from api.app import create_app
from models import ExportInput
from tools.context import build_context
from tools.exports import export_csv


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def test_health_schema_and_contract_keys(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["data"]["investigations"] == 15
    assert health.json()["data"]["tables"] == 18

    schema = client.get("/api/schema")
    assert schema.status_code == 200
    assert schema.headers["cache-control"] == "public, max-age=300"
    metrics = schema.json()["data"]["metrics"]
    assert [metric["name"] for metric in metrics] == [
        "o2_pct",
        "pressure_atm",
        "airflow_cm_s",
        "test_count",
        "test_date",
        "fuel",
    ]
    assert "o2_pct" in schema.json()["data"]["coverage"]["bass2"]


def test_investigation_endpoints_and_errors(client):
    listing = client.get("/api/investigations", params={"q": "solid", "limit": 2})
    assert listing.status_code == 200
    assert listing.json()["data"]["total"] >= 2
    assert len(listing.json()["data"]["items"]) == 2

    detail = client.get("/api/investigations/bass2")
    assert detail.status_code == 200
    assert detail.json()["data"]["psi"]["ids"] == ["PSI-25"]

    missing = client.get("/api/investigations/nope")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "INVESTIGATION_NOT_FOUND"

    bad_limit = client.get("/api/investigations", params={"limit": 201})
    assert bad_limit.status_code == 400
    assert bad_limit.json()["error"]["code"] == "INVALID_REQUEST"


def test_removed_tool_endpoints_are_not_exposed(client):
    removed = [
        ("post", "/api/query"),
        ("post", "/api/compare"),
        ("post", "/api/score"),
        ("post", "/api/tests/aggregate"),
        ("post", "/api/exports"),
        ("get", "/api/investigations/saffire/tests"),
        ("get", "/api/psi/PSI-25"),
        ("post", "/api/analyze"),
    ]
    for method, path in removed:
        response = client.post(path, json={}) if method == "post" else client.get(path)
        assert response.status_code == 404, (method, path)
        assert response.json()["error"]["code"] == "NOT_FOUND"


def test_export_download_and_expiry(settings):
    clock = Clock()
    context = build_context(settings, clock=clock)
    app = create_app(settings=settings, context=context, clock=clock)
    with TestClient(app) as client:
        created = export_csv(
            context,
            ExportInput(
                kind="comparison",
                query={
                    "ids": ["bass2", "flex2"],
                    "metrics": ["o2_pct", "test_count"],
                },
            ),
        )
        payload = created.data.model_dump(by_alias=True)
        assert payload["downloadUrl"] == f"/api/exports/{payload['exportId']}"

        download = client.get(payload["downloadUrl"])
        assert download.status_code == 200
        assert download.headers["content-type"].startswith("text/csv")
        assert "attachment; filename=" in download.headers["content-disposition"]
        assert download.headers["cache-control"] == "no-store"
        assert "bass2" in download.text

        clock.now += 901
        expired = client.get(payload["downloadUrl"])
        assert expired.status_code == 410
        assert expired.json()["error"]["code"] == "EXPORT_EXPIRED"


def test_request_id_and_cors(client):
    response = client.get("/api/health", headers={"X-Request-ID": "abc-123"})
    assert response.headers["x-request-id"] == "abc-123"

    allowed = client.get(
        "/api/health", headers={"Origin": "http://localhost:5173"}
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

    denied = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in denied.headers


def test_body_limit(settings):
    app = create_app(settings=settings, context=build_context(settings))
    with TestClient(app) as client:
        response = client.post(
            "/api/agent",
            content=b"x" * 65_537,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"


def test_optional_auth_when_enabled(settings):
    secured = settings.model_copy(
        update={"auth_enabled": True, "api_token": SecretStr("secret-token")}
    )
    app = create_app(settings=secured, context=build_context(secured))
    with TestClient(app) as client:
        denied = client.post("/api/agent", json={"question": "Compare?"})
        assert denied.status_code == 401
        assert denied.json()["error"]["code"] == "UNAUTHORIZED"

        allowed = client.post(
            "/api/agent",
            json={"question": "Compare?"},
            headers={"Authorization": "Bearer secret-token"},
        )
        assert allowed.status_code == 503
        assert allowed.json()["error"]["code"] == "MODEL_NOT_CONFIGURED"

        # Read-only endpoints stay open in this demo configuration.
        assert client.get("/api/health").status_code == 200


def test_agent_scope_validation(client):
    unknown = client.post(
        "/api/agent",
        json={"question": "Compare.", "psiIds": ["PSI-9999"]},
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "PSI_NOT_FOUND"

    malformed = client.post(
        "/api/agent",
        json={"question": "Compare.", "psiIds": ["bad-id"]},
    )
    assert malformed.status_code == 400
    assert malformed.json()["error"]["code"] == "INVALID_REQUEST"


def test_agent_probe_bounds(client):
    high = client.post("/api/agent", json={"question": "Probe.", "o2": 101})
    assert high.status_code == 400
    assert high.json()["error"]["code"] == "INVALID_REQUEST"

    low = client.post("/api/agent", json={"question": "Probe.", "o2": -2})
    assert low.status_code == 400
    assert low.json()["error"]["code"] == "INVALID_REQUEST"


def test_rate_limit_when_enabled(settings):
    limited = settings.model_copy(
        update={"rate_limit_enabled": True, "analyze_rate_limit_per_minute": 1}
    )
    app = create_app(settings=limited, context=build_context(limited))
    with TestClient(app) as client:
        first = client.post("/api/agent", json={"question": "Compare?"})
        assert first.status_code == 503
        second = client.post("/api/agent", json={"question": "Compare?"})
        assert second.status_code == 429
        assert second.json()["error"]["code"] == "RATE_LIMITED"


def test_unknown_route_envelope(client):
    response = client.get("/api/missing")
    assert response.status_code == 404
    assert response.json()["ok"] is False
    assert response.json()["error"]["code"] == "NOT_FOUND"
