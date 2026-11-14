from __future__ import annotations

import pytest

from core.errors import ToolFault
from core.services.exports import ExportStore, escape_cell, write_csv
from models import ExportInput
from tools.context import build_context
from tools.exports import export_csv


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def test_export_store_ttl_and_unknown_id():
    clock = Clock()
    store = ExportStore(ttl_seconds=900, clock=clock)
    artifact = store.create(b"a,b\n1,2\n", ["a", "b"], 1)

    assert store.get(artifact.id) is artifact
    clock.now += 901
    with pytest.raises(ToolFault) as error:
        store.get(artifact.id)
    assert error.value.code == "EXPORT_EXPIRED"
    assert error.value.status_code == 410

    with pytest.raises(ToolFault) as error:
        store.get("missing")
    assert error.value.code == "EXPORT_NOT_FOUND"


def test_export_ids_are_server_generated_and_unique():
    store = ExportStore(ttl_seconds=900)
    first = store.create(b"x\n", ["x"], 0)
    second = store.create(b"x\n", ["x"], 0)
    assert first.id != second.id
    assert len(first.id) == 16
    assert first.filename == f"flame-atlas-export-{first.id}.csv"


def test_csv_formula_escaping_and_quoting():
    payload = write_csv(
        ["value", "note"],
        [
            {"value": "=1+1", "note": "a,b"},
            {"value": "+cmd", "note": 'say "hi"'},
            {"value": "-1", "note": "@user"},
            {"value": None, "note": "normal"},
        ],
    ).decode("utf-8")
    assert "'=1+1" in payload
    assert "'+cmd" in payload
    assert "'-1" in payload
    assert "'@user" in payload
    assert '"a,b"' in payload
    assert 'say ""hi"""' in payload
    assert payload.splitlines()[-1] == ",normal"
    assert escape_cell("plain") == "plain"


def test_export_comparison_has_rows_and_provenance(context):
    result = export_csv(
        context,
        ExportInput(
            kind="comparison",
            query={
                "ids": ["bass2", "flex2"],
                "metrics": ["o2_pct", "pressure_atm", "airflow_cm_s", "test_count"],
            },
        ),
    )
    assert result.data.row_count == 8
    assert "source_file" in result.data.columns
    assert "psi_id" in result.data.columns
    assert result.data.export_id
    artifact = context.exports.get(result.data.export_id)
    text = artifact.content.decode("utf-8")
    assert "bass2" in text and "flex2" in text
    assert "PSI-25" in text and "PSI-68" in text


def test_export_accepts_requested_columns_and_appends_provenance(context):
    result = export_csv(
        context,
        ExportInput(
            kind="comparison",
            query={"ids": ["bass2", "flex2"], "metrics": ["o2_pct", "test_count"]},
            columns=["investigation_id", "metric", "min"],
        ),
    )
    assert result.data.columns == [
        "investigation_id",
        "metric",
        "min",
        "source_file",
        "psi_id",
    ]
    assert result.data.row_count == 4


def test_export_rejects_unknown_column(context):
    with pytest.raises(ToolFault) as error:
        export_csv(
            context,
            ExportInput(
                kind="comparison",
                query={"ids": ["bass2", "flex2"], "metrics": ["o2_pct"]},
                columns=["nope"],
            ),
        )
    assert error.value.code == "INVALID_EXPORT_COLUMNS"


def test_export_flattens_date_and_fuel_metrics(context):
    result = export_csv(
        context,
        ExportInput(
            kind="comparison",
            query={"ids": ["bass2", "bre"], "metrics": ["test_date", "fuel"]},
        ),
    )
    artifact = context.exports.get(result.data.export_id)
    text = artifact.content.decode("utf-8")
    assert "2014-02-14" in text and "2016-02-26" in text
    assert "ISO-8601 date" in text
    assert "PMMA" in text
    assert result.data.row_count == 4


def test_export_query_score_and_gaps_kinds(context):
    query_result = export_csv(
        context,
        ExportInput(
            kind="query",
            query={"investigationIds": ["bass2", "flex2"], "groupBy": ["investigation_id"]},
        ),
    )
    assert query_result.data.row_count == 2

    score_result = export_csv(
        context, ExportInput(kind="score", query={"environmentId": "moon"})
    )
    assert score_result.data.row_count == 15

    gap_result = export_csv(
        context, ExportInput(kind="gaps", query={"ids": ["bass2", "flex2"]})
    )
    assert gap_result.data.row_count == 2


def test_export_row_limit(settings):
    context = build_context(settings)
    context.settings.export_max_rows = 1
    with pytest.raises(ToolFault) as error:
        export_csv(
            context,
            ExportInput(
                kind="comparison",
                query={"ids": ["bass2", "flex2"], "metrics": ["o2_pct", "test_count"]},
            ),
        )
    assert error.value.code == "EXPORT_TOO_LARGE"
    assert error.value.status_code == 413
