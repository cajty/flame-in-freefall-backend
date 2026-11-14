#!/usr/bin/env python
"""Smoke test for the Flame Atlas public API.

Run the server first:
    uv run uvicorn api.main:app --host 127.0.0.1 --port 8000

Then:
    uv run python scripts/api_smoke_test.py

Options:
    --base-url URL   default http://127.0.0.1:8000
    --skip-agent     skip POST /api/agent (no model key needed)

Exit code 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx

AGENT_QUESTION = "Compare BASS-II and FLEX-2 oxygen ranges and test counts."

REMOVED_ENDPOINTS = [
    ("POST", "/api/query"),
    ("POST", "/api/compare"),
    ("POST", "/api/score"),
    ("POST", "/api/tests/aggregate"),
    ("POST", "/api/exports"),
    ("GET", "/api/investigations/saffire/tests"),
    ("GET", "/api/psi/PSI-25"),
    ("POST", "/api/analyze"),
]


class Checker:
    def __init__(self) -> None:
        self.failures = 0

    def check(self, name: str, condition: bool, detail: str = "") -> None:
        if condition:
            print(f"PASS  {name}")
            return
        self.failures += 1
        print(f"FAIL  {name}")
        if detail:
            print(f"      {detail}")

    def section(self, title: str) -> None:
        print(f"\n{title}")


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _error_code(response: httpx.Response) -> str:
    payload = _json(response)
    error = payload.get("error")
    return error.get("code", "") if isinstance(error, dict) else ""


def test_read_endpoints(client: httpx.Client, checker: Checker) -> None:
    checker.section("Read-only endpoints")

    health = client.get("/api/health")
    body = _json(health)
    data = body.get("data", {})
    checker.check("GET /api/health returns 200", health.status_code == 200, health.text[:300])
    checker.check("health investigations == 15", data.get("investigations") == 15)
    checker.check("health tables == 18", data.get("tables") == 18)

    schema = client.get("/api/schema")
    body = _json(schema)
    data = body.get("data", {})
    metric_names = [metric.get("name") for metric in data.get("metrics", [])]
    checker.check("GET /api/schema returns 200", schema.status_code == 200, schema.text[:300])
    checker.check(
        "schema has six canonical metrics",
        metric_names
        == ["o2_pct", "pressure_atm", "airflow_cm_s", "test_count", "test_date", "fuel"],
        str(metric_names),
    )

    listing = client.get(
        "/api/investigations", params={"q": "solid", "limit": 2}
    )
    body = _json(listing)
    data = body.get("data", {})
    checker.check(
        "GET /api/investigations returns 200", listing.status_code == 200, listing.text[:300]
    )
    checker.check("investigations total >= 2", data.get("total", 0) >= 2)
    checker.check("investigations limit works", len(data.get("items", [])) == 2)

    detail = client.get("/api/investigations/bass2")
    body = _json(detail)
    data = body.get("data", {})
    checker.check(
        "GET /api/investigations/bass2 returns 200",
        detail.status_code == 200,
        detail.text[:300],
    )
    checker.check(
        "BASS-II PSI ID is PSI-25",
        data.get("psi", {}).get("ids") == ["PSI-25"],
        str(data.get("psi")),
    )

    environments = client.get("/api/environments")
    body = _json(environments)
    items = body.get("data", {}).get("items", [])
    checker.check(
        "GET /api/environments returns 200",
        environments.status_code == 200,
        environments.text[:300],
    )
    checker.check(
        "four environments",
        [item.get("id") for item in items] == ["iss", "moon", "mars", "rover"],
        str([item.get("id") for item in items]),
    )

    gaps = client.get("/api/gaps", params={"ids": "bass2,flex2"})
    body = _json(gaps)
    items = body.get("data", {}).get("items", [])
    by_id = {item.get("investigationId"): item for item in items}
    checker.check("GET /api/gaps returns 200", gaps.status_code == 200, gaps.text[:300])
    checker.check(
        "BASS-II missing pressure",
        "pressure" in by_id.get("bass2", {}).get("missing", []),
        str(by_id.get("bass2")),
    )
    checker.check(
        "FLEX-2 marked planned-only",
        by_id.get("flex2", {}).get("plannedOnly") is True,
        str(by_id.get("flex2")),
    )


def test_removed_endpoints(client: httpx.Client, checker: Checker) -> None:
    checker.section("Removed endpoints")
    for method, path in REMOVED_ENDPOINTS:
        if method == "POST":
            response = client.post(path, json={})
        else:
            response = client.get(path)
        checker.check(
            f"{method} {path} returns 404",
            response.status_code == 404 and _error_code(response) == "NOT_FOUND",
            f"{response.status_code} {response.text[:200]}",
        )


def test_agent(client: httpx.Client, checker: Checker) -> None:
    checker.section("Agent endpoint")
    response = client.post(
        "/api/agent",
        json={"question": AGENT_QUESTION, "conversationId": "smoke-test-001"},
    )
    body = _json(response)
    if response.status_code == 503 and _error_code(response) == "MODEL_NOT_CONFIGURED":
        checker.check(
            "POST /api/agent configured",
            False,
            "Model key missing. Set GEMINI_API_KEY in .env and restart the server, "
            "or rerun with --skip-agent.",
        )
        return
    if response.status_code != 200:
        checker.check(
            "POST /api/agent returns 200",
            False,
            f"{response.status_code} {response.text[:500]}",
        )
        return

    data = body.get("data", {})
    answer = str(data.get("answer", ""))
    plan = data.get("plan", {}).get("tools", [])
    citations = data.get("citations", [])
    warnings = data.get("warnings", [])
    download = data.get("download")

    checker.check("POST /api/agent returns 200", True)
    checker.check("agent answer is not empty", bool(answer.strip()), answer[:200])
    checker.check("agent used at least one tool", bool(plan), str(plan))
    checker.check("agent response is JSON envelope", body.get("ok") is True)
    checker.check("citations is a list", isinstance(citations, list))
    checker.check("warnings is a list", isinstance(warnings, list))

    print(f"\nanswer: {answer[:500]}")
    print(f"tools: {plan}")
    if warnings:
        print(f"warnings: {warnings}")

    for citation in citations:
        checker.check(
            "citation has investigationId, sourceFile, psiId, url",
            all(key in citation for key in ("investigationId", "sourceFile", "psiId", "url")),
            str(citation),
        )

    if download:
        url = download.get("downloadUrl") if isinstance(download, dict) else None
        checker.check("agent download has downloadUrl", bool(url), str(download))
        if url:
            csv_response = client.get(url)
            checker.check(
                "export download returns CSV",
                csv_response.status_code == 200
                and csv_response.headers.get("content-type", "").startswith("text/csv")
                and bool(csv_response.text),
                f"{csv_response.status_code} {csv_response.headers.get('content-type')}",
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test the Flame Atlas API")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--skip-agent", action="store_true")
    args = parser.parse_args()

    checker = Checker()
    try:
        with httpx.Client(
            base_url=args.base_url,
            timeout=httpx.Timeout(90.0, connect=5.0),
        ) as client:
            test_read_endpoints(client, checker)
            test_removed_endpoints(client, checker)
            if args.skip_agent:
                print("\nSKIP  POST /api/agent (--skip-agent)")
            else:
                test_agent(client, checker)
    except httpx.HTTPError as error:
        print(f"\nREQUEST ERROR: {type(error).__name__}: {error}")
        print("Is the server running at the base URL?")
        return 1

    print(f"\n{checker.failures} failure(s)")
    return 1 if checker.failures else 0


if __name__ == "__main__":
    sys.exit(main())
