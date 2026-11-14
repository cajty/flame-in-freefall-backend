from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, Literal

from pydantic import ValidationError
from pydantic_ai import Agent, RunContext
from pydantic_ai.settings import ModelSettings

from agents.deps import ToolDeps
from core.errors import ToolFault
from models import (
    AggregateTestsInput,
    AnalysisAnswer,
    CompareInput,
    ExportInput,
    GapsInput,
    GetInvestigationInput,
    PsiCatalogSearchInput,
    PsiRecordInput,
    QueryFilter,
    QueryTestsInput,
    RunQueryInput,
    ScoreFilters,
    ScoreInput,
    SearchInput,
    SortSpec,
)
from prompts import SYSTEM_PROMPT
from tools.compare import compare_investigations as compare_tool
from tools.exports import export_csv as export_tool
from tools.psi import get_psi_record as psi_tool
from tools.psi import search_psi_catalog as catalog_tool
from tools.query import run_query as query_tool
from tools.query import score_investigations as score_tool
from tools.rows import aggregate_tests as aggregate_tool
from tools.rows import query_tests as rows_tool
from tools.runner import run_tool
from tools.summary_tools import (
    find_data_gaps as gaps_tool,
)
from tools.summary_tools import (
    get_environments as environments_tool,
)
from tools.summary_tools import (
    get_investigation as investigation_tool,
)
from tools.summary_tools import (
    get_schema as schema_tool,
)
from tools.summary_tools import (
    search_investigations as search_tool,
)

logger = logging.getLogger("flame_atlas.agent")


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


async def _invoke(
    run_context: RunContext[ToolDeps],
    name: str,
    function: Callable[[Any, Any], Any],
    request_factory: Callable[[], Any],
) -> dict[str, Any]:
    deps = run_context.deps
    started = time.perf_counter()
    try:
        request = request_factory()
    except ValidationError as error:
        details = [
            f"{'.'.join(str(part) for part in item.get('loc', ()))}: {item.get('msg', 'invalid value')}"
            for item in error.errors()
        ]
        fault = ToolFault("INVALID_REQUEST", "Tool arguments failed validation.", details=details)
        deps.record(
            name,
            error=fault.as_error(),
            duration_ms=_elapsed_ms(started),
        )
        logger.warning(
            "tool call name=%s ok=false code=%s duration_ms=%s args=invalid details=%s",
            name,
            fault.code,
            _elapsed_ms(started),
            fault.details,
        )
        return {"ok": False, "error": fault.as_error()}

    arguments = request.model_dump(by_alias=True) if request is not None else None

    if deps.repeated(name, arguments):
        duration_ms = _elapsed_ms(started)
        fault = ToolFault(
            "REPEATED_TOOL_CALL",
            (
                f"{name} was already called with the same arguments. "
                "Use the earlier result, or ask one clarifying question."
            ),
            status_code=422,
        )
        deps.record(
            name,
            error=fault.as_error(),
            arguments=arguments,
            duration_ms=duration_ms,
        )
        logger.error(
            "tool call name=%s ok=false code=%s duration_ms=%s args=%s",
            name,
            fault.code,
            duration_ms,
            arguments,
        )
        raise fault

    try:
        envelope = await run_tool(function, deps.ctx, request, deps.timeout_seconds)
    except ToolFault as fault:
        duration_ms = _elapsed_ms(started)
        deps.record(
            name,
            error=fault.as_error(),
            arguments=arguments,
            duration_ms=duration_ms,
        )
        logger.warning(
            "tool call name=%s ok=false code=%s duration_ms=%s args=%s details=%s",
            name,
            fault.code,
            duration_ms,
            arguments,
            fault.details,
        )
        return {"ok": False, "error": fault.as_error()}
    except Exception:
        duration_ms = _elapsed_ms(started)
        logger.exception("tool call name=%s ok=false args=%s", name, arguments)
        fault = ToolFault("INTERNAL_ERROR", "Tool failed.", status_code=500)
        deps.record(
            name,
            error=fault.as_error(),
            arguments=arguments,
            duration_ms=duration_ms,
        )
        return {"ok": False, "error": fault.as_error()}

    duration_ms = _elapsed_ms(started)
    deps.record(
        name,
        envelope=envelope,
        arguments=arguments,
        duration_ms=duration_ms,
    )
    logger.info(
        "tool call name=%s ok=true duration_ms=%s args=%s",
        name,
        duration_ms,
        arguments,
    )
    return envelope.model_dump(by_alias=True)


def build_agent(model: Any) -> Agent[ToolDeps, AnalysisAnswer]:
    agent = Agent(
        model,
        output_type=AnalysisAnswer,
        deps_type=ToolDeps,
        instructions=SYSTEM_PROMPT,
        model_settings=ModelSettings(temperature=0.2, top_p=0.95, max_tokens=4000),
        retries=2,
    )

    @agent.tool(strict=True)
    async def get_schema(run_context: RunContext[ToolDeps]) -> dict[str, Any]:
        """Return canonical metrics, units, themes, phases, investigation IDs, coverage and limits. Call this first."""
        return await _invoke(run_context, "get_schema", schema_tool, lambda: None)

    @agent.tool(strict=True)
    async def search_investigations(
        run_context: RunContext[ToolDeps],
        q: str | None = None,
        theme: str | None = None,
        phase: str | None = None,
        o2_min: float | None = None,
        o2_max: float | None = None,
        fuel: str | None = None,
        has_data: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Search investigations by text, theme, phase, O2 window, fuel, or data availability."""
        return await _invoke(
            run_context,
            "search_investigations",
            search_tool,
            lambda: SearchInput(
                q=q,
                theme=theme,
                phase=phase,
                o2_min=o2_min,
                o2_max=o2_max,
                fuel=fuel,
                has_data=has_data,
                limit=limit,
                offset=offset,
            ),
        )

    @agent.tool(strict=True)
    async def get_investigation(
        run_context: RunContext[ToolDeps], investigation_id: str
    ) -> dict[str, Any]:
        """Return one merged investigation record, its summary, PSI IDs, URLs, and source files."""
        return await _invoke(
            run_context,
            "get_investigation",
            investigation_tool,
            lambda: GetInvestigationInput(id=investigation_id),
        )

    @agent.tool(strict=True)
    async def get_environments(
        run_context: RunContext[ToolDeps],
    ) -> dict[str, Any]:
        """Return the four mission environments, their O2 windows, pressure strings, and theme weights."""
        return await _invoke(
            run_context, "get_environments", environments_tool, lambda: None
        )

    @agent.tool(strict=True)
    async def find_data_gaps(
        run_context: RunContext[ToolDeps], ids: list[str] | None = None
    ) -> dict[str, Any]:
        """Report missing, partial, and planned-only data for one or more investigations."""
        return await _invoke(
            run_context,
            "find_data_gaps",
            gaps_tool,
            lambda: GapsInput(ids=ids),
        )

    @agent.tool(strict=True)
    async def compare_investigations(
        run_context: RunContext[ToolDeps],
        ids: list[str],
        metrics: list[str],
        normalize_units: bool = True,
    ) -> dict[str, Any]:
        """Compare two to five investigations on canonical metrics with provenance and warnings."""
        return await _invoke(
            run_context,
            "compare_investigations",
            compare_tool,
            lambda: CompareInput(
                ids=ids, metrics=metrics, normalize_units=normalize_units
            ),
        )

    @agent.tool(strict=True)
    async def run_query(
        run_context: RunContext[ToolDeps],
        investigation_ids: list[str] | None = None,
        filters: list[QueryFilter] | None = None,
        metrics: list[str] | None = None,
        group_by: list[str] | None = None,
        sort: list[SortSpec] | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        """Filter, group, and aggregate dashboard summary rows across investigations. One row per investigation by default. Use this for cross-investigation ranges and counts. Does not return individual test rows; use query_tests or aggregate_tests for those."""
        return await _invoke(
            run_context,
            "run_query",
            query_tool,
            lambda: RunQueryInput(
                investigation_ids=investigation_ids,
                filters=filters or [],
                metrics=metrics
                or ["o2_pct", "pressure_atm", "airflow_cm_s", "test_count"],
                group_by=group_by or [],
                sort=sort or [],
                limit=limit,
            ),
        )

    @agent.tool(strict=True)
    async def score_investigations(
        run_context: RunContext[ToolDeps],
        environment_id: str,
        theme: str | None = None,
        phase: str | None = None,
    ) -> dict[str, Any]:
        """Rank investigations by weighted O2 coverage, gravity, scale, data quality and theme. Planned-only data scores 0."""
        return await _invoke(
            run_context,
            "score_investigations",
            score_tool,
            lambda: ScoreInput(
                environment_id=environment_id,
                filters=ScoreFilters(theme=theme, phase=phase),
            ),
        )

    @agent.tool(strict=True)
    async def export_csv(
        run_context: RunContext[ToolDeps],
        kind: Literal["query", "comparison", "score", "gaps"],
        ids: list[str] | None = None,
        metrics: list[str] | None = None,
        investigation_ids: list[str] | None = None,
        filters: list[QueryFilter] | None = None,
        group_by: list[str] | None = None,
        sort: list[SortSpec] | None = None,
        limit: int | None = None,
        environment_id: str | None = None,
        theme: str | None = None,
        phase: str | None = None,
        columns: list[str] | None = None,
    ) -> dict[str, Any]:
        """Export a query, comparison, score, or gap result as CSV with provenance. Returns a download URL."""
        if kind == "comparison":
            query: dict[str, Any] = {"ids": ids or [], "metrics": metrics or []}
        elif kind == "query":
            query = {
                key: value
                for key, value in {
                    "investigationIds": investigation_ids,
                    "filters": filters,
                    "metrics": metrics,
                    "groupBy": group_by,
                    "sort": sort,
                    "limit": limit,
                }.items()
                if value is not None
            }
        elif kind == "score":
            query = {
                "environmentId": environment_id or "",
                "filters": {
                    key: value
                    for key, value in {"theme": theme, "phase": phase}.items()
                    if value is not None
                },
            }
        else:
            query = {"ids": ids} if ids is not None else {}
        return await _invoke(
            run_context,
            "export_csv",
            export_tool,
            lambda: ExportInput(kind=kind, query=query, columns=columns),
        )

    @agent.tool(strict=True)
    async def query_tests(
        run_context: RunContext[ToolDeps],
        investigation_id: str,
        metric: str | None = None,
        min: float | None = None,
        max: float | None = None,
        fuel: str | None = None,
        date_start: str | None = None,
        date_end: str | None = None,
        columns: list[str] | None = None,
        limit: int = 50,
        offset: int = 0,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Query individual measured test rows for one investigation, with numeric, fuel, and date filters plus pagination. Use this for per-test values and dates. For cross-investigation summary metrics use run_query; for statistics over test rows use aggregate_tests."""
        return await _invoke(
            run_context,
            "query_tests",
            rows_tool,
            lambda: QueryTestsInput(
                investigation_id=investigation_id,
                metric=metric,
                min=min,
                max=max,
                fuel=fuel,
                date_start=date_start,
                date_end=date_end,
                columns=columns,
                limit=limit,
                offset=offset,
                cursor=cursor,
            ),
        )

    @agent.tool(strict=True)
    async def aggregate_tests(
        run_context: RunContext[ToolDeps],
        investigation_id: str,
        metric: str,
        group_by: list[str] | None = None,
        stat: str = "mean",
        min: float | None = None,
        max: float | None = None,
        fuel: str | None = None,
    ) -> dict[str, Any]:
        """Aggregate individual test rows: count, min, max, mean, median, or p90, optionally grouped."""
        return await _invoke(
            run_context,
            "aggregate_tests",
            aggregate_tool,
            lambda: AggregateTestsInput(
                investigation_id=investigation_id,
                metric=metric,
                group_by=group_by or [],
                stat=stat,
                min=min,
                max=max,
                fuel=fuel,
            ),
        )

    @agent.tool(strict=True)
    async def get_psi_record(
        run_context: RunContext[ToolDeps], psi_id: str
    ) -> dict[str, Any]:
        """Look up a NASA PSI accession number and the investigation it belongs to."""
        return await _invoke(
            run_context,
            "get_psi_record",
            psi_tool,
            lambda: PsiRecordInput(id=psi_id),
        )

    @agent.tool(strict=True)
    async def search_psi_catalog(
        run_context: RunContext[ToolDeps], q: str, limit: int = 10
    ) -> dict[str, Any]:
        """Search the full NASA PSI investigation metadata catalog by free text. Use only to discover related PSI records outside the 15 curated investigations. Results are metadata-only leads, not measured evidence."""
        return await _invoke(
            run_context,
            "search_psi_catalog",
            catalog_tool,
            lambda: PsiCatalogSearchInput(q=q, limit=limit),
        )

    return agent
