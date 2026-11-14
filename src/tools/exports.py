from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from core.errors import ToolFault
from core.services.exports import iso_z, write_csv
from models import (
    CompareInput,
    Envelope,
    ExportData,
    ExportInput,
    ExportKind,
    GapsInput,
    RunQueryInput,
    ScoreInput,
)
from tools.common import provenance
from tools.compare import compare_investigations
from tools.context import AppContext
from tools.query import run_query, score_investigations
from tools.summary_tools import find_data_gaps

REQUIRED_COLUMNS = ("source_file", "psi_id")


def _cell(value: Any) -> Any:
    if isinstance(value, list):
        return ";".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _primary_source(ctx: AppContext, investigation_id: str) -> tuple[str, str]:
    record = ctx.catalog.get(investigation_id)
    return (
        record.source_files[0] if record.source_files else "",
        record.psi.ids[0] if record.psi.ids else "",
    )


COMPARISON_METADATA = {
    "investigationId",
    "name",
    "testLabel",
    "sourceFiles",
    "psiIds",
    "psiUrls",
}


def _comparison_rows(ctx: AppContext, envelope) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    metrics = [
        metric
        for metric in envelope.data.items[0]
        if metric not in COMPARISON_METADATA
    ]
    for item in envelope.data.items:
        source_file, psi_id = _primary_source(ctx, item["investigationId"])
        for metric in metrics:
            value = item.get(metric)
            row: dict[str, Any] = {
                "investigation_id": item["investigationId"],
                "name": item["name"],
                "metric": metric,
                "testLabel": item.get("testLabel"),
                "source_file": source_file,
                "psi_id": psi_id,
            }
            if isinstance(value, dict) and "start" in value:
                row["min"] = value.get("start")
                row["max"] = value.get("end")
                row["unit"] = "ISO-8601 date"
            elif isinstance(value, dict) and "min" in value:
                row["min"] = value.get("min")
                row["max"] = value.get("max")
                row["unit"] = value.get("unit", "")
            elif isinstance(value, list):
                row["min"] = ";".join(str(entry) for entry in value)
                row["max"] = ""
                row["unit"] = "text"
            elif value is None:
                row["min"] = None
                row["max"] = None
                row["unit"] = ""
            else:
                row["min"] = value
                row["max"] = value
                row["unit"] = "count" if metric == "test_count" else ""
            rows.append(row)
    return rows


def _query_rows(ctx: AppContext, envelope) -> list[dict[str, Any]]:
    provenance_items = envelope.provenance
    grouped_files = sorted({item.source_file for item in provenance_items})
    grouped_investigations = sorted({item.investigation_id for item in provenance_items})
    grouped_psi = sorted(
        {
            psi_id
            for investigation_id in grouped_investigations
            for psi_id in ctx.catalog.get(investigation_id).psi.ids
        }
    )
    rows: list[dict[str, Any]] = []
    for row in envelope.data.rows:
        output = dict(row)
        investigation_id = output.get("investigation_id")
        if isinstance(investigation_id, str):
            _, psi_id = _primary_source(ctx, investigation_id)
            output["source_file"] = ";".join(
                ctx.catalog.get(investigation_id).source_files
            )
            output["psi_id"] = psi_id
        else:
            output["source_file"] = ";".join(grouped_files)
            output["psi_id"] = ";".join(grouped_psi)
        rows.append(output)
    return rows


def _score_rows(ctx: AppContext, envelope) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in envelope.data.items:
        source_file, psi_id = _primary_source(ctx, item.investigation_id)
        rows.append(
            {
                "investigation_id": item.investigation_id,
                "name": item.name,
                "score": item.score,
                "o2Overlap": item.o2_overlap,
                "gravityMatch": item.gravity_match,
                "scaleMatch": item.scale_match,
                "dataQualityFactor": item.data_quality_factor,
                "themeFraction": item.theme_fraction,
                "themeWeight": item.theme_weight,
                "gravity": item.gravity,
                "scale": item.scale,
                "dataQuality": item.data_quality,
                "o2_min": item.o2[0],
                "o2_max": item.o2[1],
                "theme": item.theme,
                "phase": item.phase,
                "source_file": source_file,
                "psi_id": psi_id,
            }
        )
    return rows


def _gap_rows(ctx: AppContext, envelope) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in envelope.data.items:
        source_file, psi_id = _primary_source(ctx, item.investigation_id)
        rows.append(
            {
                "investigation_id": item.investigation_id,
                "missing": ";".join(item.missing),
                "partial": ";".join(item.partial),
                "plannedOnly": item.planned_only,
                "source_file": source_file,
                "psi_id": psi_id,
            }
        )
    return rows


def _model_input(model, query: dict[str, Any] | None):
    try:
        return model.model_validate(query or {})
    except ValidationError as error:
        details = [
            f"{'.'.join(str(part) for part in item.get('loc', ()))}: {item.get('msg', 'invalid value')}"
            for item in error.errors()
        ]
        raise ToolFault(
            "INVALID_QUERY",
            f"Invalid export query for {model.__name__}.",
            details=details,
        ) from error


def export_csv(ctx: AppContext, request: ExportInput) -> Envelope[ExportData]:
    try:
        kind = ExportKind(request.kind)
    except ValueError as error:
        raise ToolFault(
            "INVALID_QUERY",
            f"Unsupported export kind: {request.kind}",
        ) from error

    if kind == ExportKind.comparison:
        envelope = compare_investigations(ctx, _model_input(CompareInput, request.query))
        rows = _comparison_rows(ctx, envelope)
        provenance_items = envelope.provenance
    elif kind == ExportKind.query:
        envelope = run_query(ctx, _model_input(RunQueryInput, request.query))
        rows = _query_rows(ctx, envelope)
        provenance_items = envelope.provenance
    elif kind == ExportKind.score:
        envelope = score_investigations(ctx, _model_input(ScoreInput, request.query))
        rows = _score_rows(ctx, envelope)
        provenance_items = envelope.provenance
    else:
        envelope = find_data_gaps(ctx, _model_input(GapsInput, request.query))
        rows = _gap_rows(ctx, envelope)
        provenance_items = provenance(
            [ctx.catalog.get(item.investigation_id) for item in envelope.data.items],
            ["o2_pct", "pressure_atm", "airflow_cm_s"],
        )

    if len(rows) > ctx.settings.export_max_rows:
        raise ToolFault(
            "EXPORT_TOO_LARGE",
            f"Export exceeds {ctx.settings.export_max_rows} rows.",
            status_code=413,
        )

    allowed: list[str] = []
    for row in rows:
        for key in row:
            if key not in allowed:
                allowed.append(key)
    for column in REQUIRED_COLUMNS:
        if column not in allowed:
            allowed.append(column)

    requested = list(request.columns) if request.columns else allowed
    unknown = [column for column in requested if column not in allowed]
    if unknown:
        raise ToolFault(
            "INVALID_EXPORT_COLUMNS",
            f"Unknown export columns: {', '.join(unknown)}",
        )
    columns = list(requested)
    for column in REQUIRED_COLUMNS:
        if column not in columns:
            columns.append(column)

    flat_rows = [{key: _cell(value) for key, value in row.items()} for row in rows]
    content = write_csv(columns, flat_rows)
    artifact = ctx.exports.create(content, columns, len(flat_rows))

    return Envelope(
        data=ExportData(
            export_id=artifact.id,
            download_url=f"/api/exports/{artifact.id}",
            row_count=artifact.row_count,
            columns=columns,
            expires_at=iso_z(artifact.expires_at),
            expires_in_seconds=ctx.settings.export_ttl_seconds,
        ),
        provenance=provenance_items,
        warnings=envelope.warnings,
    )
