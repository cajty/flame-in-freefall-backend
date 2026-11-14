#!/usr/bin/env python
"""Real, non-mocked test of POST /api/agent.

The server must already be running with a real GEMINI_API_KEY in .env:
    uv run uvicorn api.main:app --host 127.0.0.1 --port 8000

Then run:
    uv run python scripts/agent_real_test.py

Every scenario makes one real model request and spends tokens. Raw responses
and exported CSV files are written under artifacts/agent-real-test-<timestamp>/.

Options:
    --base-url URL       default http://127.0.0.1:8000
    --scenario NAME      run only selected scenario(s); repeatable
    --output-dir PATH    override artifact directory
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "schema",
        "question": "Use get_schema and tell me which metrics and investigation IDs I can query.",
        "expect_tool": "get_schema",
        "require_citations": False,
    },
    {
        "name": "compare",
        "question": (
            "Use compare_investigations for ids bass2 and flex2 with metrics "
            "o2_pct, pressure_atm and test_count. Explain the comparison."
        ),
        "expect_tool": "compare_investigations",
        "require_citations": True,
    },
    {
        "name": "gaps",
        "question": (
            "Use find_data_gaps for ids bass2 and flex2. Tell me what is missing "
            "and what is planned-only."
        ),
        "expect_tool": "find_data_gaps",
        "require_citations": False,
    },
    {
        "name": "score",
        "question": (
            "Use score_investigations for environmentId moon with theme prevention. "
            "Rank the investigations."
        ),
        "expect_tool": "score_investigations",
        "require_citations": False,
    },
    {
        "name": "rows",
        "question": (
            "Use query_tests for investigation flex with metric o2_percent, "
            "min 20, max 30 and limit 5. Show me the rows."
        ),
        "expect_tool": "query_tests",
        "require_citations": True,
    },
    {
        "name": "aggregate",
        "question": (
            "Use aggregate_tests for investigation flex with metric o2_percent, "
            "groupBy fuel and stat mean."
        ),
        "expect_tool": "aggregate_tests",
        "require_citations": True,
    },
    {
        "name": "psi",
        "question": "Use get_psi_record for PSI-25. Tell me which investigation it belongs to.",
        "expect_tool": "get_psi_record",
        "require_citations": False,
    },
    {
        "name": "export",
        "question": (
            "Use export_csv with kind comparison, ids bass2 and flex2, and metrics "
            "o2_pct and test_count. Then give me the download link."
        ),
        "expect_tool": "export_csv",
        "require_citations": False,
        "require_download": True,
    },
    {
        "name": "scope",
        "question": (
            "Compare BASS-II and FLEX-2 oxygen ranges and test counts. "
            "Only use the supplied PSI scope."
        ),
        "psi_ids": ["PSI-25"],
        "expected_investigation_ids": ["bass2"],
        "expect_tool": "get_schema",
        "require_citations": False,
    },
    {
        "name": "scope-empty",
        "question": "Use get_schema and list the investigation IDs you can query.",
        "psi_ids": [],
        "expected_investigation_ids": None,
        "expect_tool": "get_schema",
        "require_citations": False,
    },
    {
        "name": "scope-multi",
        "question": (
            "Compare BASS-II and FLEX-2 oxygen ranges and test counts using "
            "only PSI-25 and PSI-68."
        ),
        "psi_ids": ["PSI-25", "PSI-68"],
        "expected_investigation_ids": ["bass2", "flex2"],
        "expect_tool": "compare_investigations",
        "require_citations": True,
    },
]


class Results:
    def __init__(self) -> None:
        self.failures = 0
        self.passes = 0

    def check(self, name: str, condition: bool, detail: str = "") -> None:
        if condition:
            self.passes += 1
            print(f"  PASS  {name}")
        else:
            self.failures += 1
            print(f"  FAIL  {name}")
            if detail:
                print(f"        {detail}")


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _error_text(response: httpx.Response) -> str:
    payload = _json(response)
    error = payload.get("error")
    if isinstance(error, dict):
        return f"{error.get('code')}: {error.get('message')}"
    return response.text[:500]


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "file"


def _validate_citations(
    client: httpx.Client,
    checker: Results,
    citations: list[dict[str, Any]],
) -> None:
    cache: dict[str, dict[str, Any]] = {}
    for citation in citations:
        investigation_id = citation.get("investigationId")
        if not investigation_id:
            checker.check("citation has investigationId", False, str(citation))
            continue
        if investigation_id not in cache:
            response = client.get(f"/api/investigations/{investigation_id}")
            cache[investigation_id] = _json(response).get("data", {})
        record = cache[investigation_id]
        checker.check(
            f"citation investigation exists: {investigation_id}",
            bool(record),
            str(citation),
        )
        psi_ids = record.get("psi", {}).get("ids", [])
        checker.check(
            f"citation PSI mapped to {investigation_id}",
            citation.get("psiId") in psi_ids,
            f"got {citation.get('psiId')}, expected one of {psi_ids}",
        )
        source_files = record.get("sourceFiles", [])
        checker.check(
            f"citation source file mapped to {investigation_id}",
            citation.get("sourceFile") in [*source_files, "generated.json"],
            f"got {citation.get('sourceFile')}, expected one of {source_files}",
        )
        expected_url = (
            f"https://psi.nasa.gov/physci/repo/data/investigations/{citation.get('psiId')}"
        )
        checker.check(
            "citation URL matches PSI ID",
            citation.get("url") == expected_url,
            f"got {citation.get('url')}",
        )


def run_scenario(
    client: httpx.Client,
    scenario: dict[str, Any],
    output_dir: Path,
    checker: Results,
) -> None:
    name = scenario["name"]
    print(f"\n[{name}]")
    print(f"  question: {scenario['question']}")
    started = datetime.now(UTC)
    payload: dict[str, Any] = {
        "question": scenario["question"],
        "conversationId": f"real-test-{name}",
    }
    has_scope = "psi_ids" in scenario
    if has_scope:
        payload["psiIds"] = scenario["psi_ids"]
    response = client.post("/api/agent", json=payload)
    elapsed = (datetime.now(UTC) - started).total_seconds()
    body = _json(response)
    (output_dir / f"{name}.json").write_text(
        json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    if response.status_code != 200:
        checker.check(
            f"{name}: POST /api/agent returns 200",
            False,
            f"{response.status_code} {_error_text(response)}",
        )
        return
    checker.check(f"{name}: HTTP 200", True)
    print(f"  latency: {elapsed:.1f}s")

    data = body.get("data", {})
    answer = str(data.get("answer", ""))
    tools = data.get("plan", {}).get("tools", [])
    citations = data.get("citations", [])
    warnings = data.get("warnings", [])
    download = data.get("download")

    checker.check(f"{name}: envelope ok", body.get("ok") is True)
    checker.check(f"{name}: answer non-empty", bool(answer.strip()), answer[:300])
    checker.check(f"{name}: at least one tool used", bool(tools), str(tools))
    if scenario.get("expect_tool"):
        checker.check(
            f"{name}: expected tool {scenario['expect_tool']} used",
            scenario["expect_tool"] in tools,
            str(tools),
        )
    if has_scope and scenario["psi_ids"]:
        expected_ids = scenario["expected_investigation_ids"]
        checker.check(
            f"{name}: request scope returned",
            data.get("scope")
            == {
                "psiIds": scenario["psi_ids"],
                "investigationIds": expected_ids,
            },
            str(data.get("scope")),
        )
        checker.check(
            f"{name}: citations stay inside scope",
            all(
                citation.get("investigationId") in expected_ids
                for citation in citations
            ),
            str(citations),
        )
    elif has_scope:
        checker.check(
            f"{name}: empty psiIds leaves scope unrestricted",
            data.get("scope") is None,
            str(data.get("scope")),
        )
        checker.check(
            f"{name}: no scope warning",
            not any("scoped to PSI IDs" in warning for warning in warnings),
            str(warnings),
        )
    if scenario.get("require_citations"):
        checker.check(f"{name}: citations present", bool(citations), str(citations))
    checker.check(f"{name}: citations is list", isinstance(citations, list))
    checker.check(f"{name}: warnings is list", isinstance(warnings, list))

    print(f"  tools: {tools}")
    print(f"  answer: {answer[:700]}")
    if warnings:
        print(f"  warnings: {warnings}")
    if citations:
        print(f"  citations: {citations}")

    _validate_citations(client, checker, citations)

    if scenario.get("require_download"):
        checker.check(f"{name}: download present", isinstance(download, dict), str(download))
    if isinstance(download, dict) and download.get("downloadUrl"):
        csv_response = client.get(download["downloadUrl"])
        checker.check(
            f"{name}: CSV download returns 200",
            csv_response.status_code == 200,
            f"{csv_response.status_code} {csv_response.text[:200]}",
        )
        checker.check(
            f"{name}: CSV content type",
            csv_response.headers.get("content-type", "").startswith("text/csv"),
            csv_response.headers.get("content-type", ""),
        )
        checker.check(f"{name}: CSV has rows", bool(csv_response.text.strip()))
        csv_path = output_dir / f"{name}-{_safe_filename(download.get('exportId', 'export'))}.csv"
        csv_path.write_bytes(csv_response.content)
        print(f"  csv: {csv_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Real non-mocked test of /api/agent")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    selected = [
        scenario
        for scenario in SCENARIOS
        if not args.scenario or scenario["name"] in args.scenario
    ]
    unknown = set(args.scenario) - {scenario["name"] for scenario in SCENARIOS}
    if unknown:
        print(f"Unknown scenario(s): {', '.join(sorted(unknown))}")
        print(f"Available: {', '.join(scenario['name'] for scenario in SCENARIOS)}")
        return 2

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (
        Path(args.output_dir)
        if args.output_dir
        else Path("artifacts") / f"agent-real-test-{stamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    checker = Results()
    try:
        with httpx.Client(
            base_url=args.base_url,
            timeout=httpx.Timeout(120.0, connect=5.0),
        ) as client:
            health = client.get("/api/health")
            if health.status_code != 200:
                print(f"Server not healthy at {args.base_url}: {health.status_code}")
                return 1
            print(f"Server OK: {args.base_url}")
            print(f"Artifacts: {output_dir}")
            for scenario in selected:
                run_scenario(client, scenario, output_dir, checker)
    except httpx.HTTPError as error:
        print(f"\nREQUEST ERROR: {type(error).__name__}: {error}")
        print("Is the server running at the base URL?")
        return 1

    summary = {
        "base_url": args.base_url,
        "scenarios": [scenario["name"] for scenario in selected],
        "passes": checker.passes,
        "failures": checker.failures,
        "created_at": stamp,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(f"\n{checker.passes} pass, {checker.failures} fail")
    return 1 if checker.failures else 0


if __name__ == "__main__":
    sys.exit(main())
