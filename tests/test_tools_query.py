from __future__ import annotations

import pytest

from core.errors import ToolFault
from models import (
    CompareInput,
    QueryFilter,
    RunQueryInput,
    ScoreInput,
    SortSpec,
)
from tools.compare import compare_investigations
from tools.query import run_query, score_investigations


def test_compare_bass2_and_flex2(context):
    result = compare_investigations(
        context,
        CompareInput(
            ids=["bass2", "flex2"],
            metrics=["o2_pct", "pressure_atm", "airflow_cm_s", "test_count"],
        ),
    )
    bass2, flex2 = result.data.items
    assert bass2["o2_pct"] == {"min": 13.6, "max": 22.2, "unit": "%", "partial": False}
    assert bass2["pressure_atm"] is None
    assert bass2["airflow_cm_s"] == {"min": 0.0, "max": 38.5, "unit": "cm/s"}
    assert bass2["test_count"] == 129
    assert bass2["testLabel"] == "tests"
    assert bass2["psiIds"] == ["PSI-25"]
    assert bass2["psiUrls"] == [
        "https://psi.nasa.gov/physci/repo/data/investigations/PSI-25"
    ]
    assert bass2["sourceFiles"] == ["bass2/BASS-II_clean.csv"]

    assert flex2["o2_pct"]["min"] == 17.0
    assert flex2["pressure_atm"] == {"min": 0.5, "max": 3.0, "unit": "atm"}
    assert flex2["test_count"] == 8
    assert flex2["testLabel"] == "planned fuel cases"
    assert flex2["psiIds"] == ["PSI-68"]
    assert flex2["sourceFiles"] == ["flex2/FLEX2_clean.csv"]
    assert any("planned" in warning for warning in result.warnings)
    assert any("different units" in warning for warning in result.warnings)


def test_compare_normalizes_and_can_return_native_units(context):
    normalized = compare_investigations(
        context, CompareInput(ids=["cfig", "flex"], metrics=["pressure_atm"])
    )
    cfig, flex = normalized.data.items
    assert cfig["pressure_atm"]["unit"] == "atm"
    assert cfig["pressure_atm"]["min"] == pytest.approx(0.49, abs=0.01)
    assert flex["pressure_atm"]["min"] == pytest.approx(0.69, abs=0.01)
    assert any("converted" in warning for warning in normalized.warnings)

    native = compare_investigations(
        context,
        CompareInput(ids=["cfig", "flex"], metrics=["pressure_atm"], normalize_units=False),
    )
    assert native.data.items[0]["pressure_atm"]["unit"] == "bar"
    assert native.data.items[1]["pressure_atm"]["unit"] == "kPa"


def test_compare_validation(context):
    with pytest.raises(ToolFault):
        compare_investigations(context, CompareInput(ids=["bass2"], metrics=["o2_pct"]))
    with pytest.raises(ToolFault):
        compare_investigations(
            context, CompareInput(ids=["bass2", "bass2"], metrics=["o2_pct"])
        )
    with pytest.raises(ToolFault) as error:
        compare_investigations(
            context, CompareInput(ids=["bass2", "flex2"], metrics=["burn_rate"])
        )
    assert error.value.code == "UNKNOWN_METRIC"
    with pytest.raises(ToolFault):
        compare_investigations(context, CompareInput(ids=["nope", "bass2"], metrics=["o2_pct"]))


def test_run_query_filters_sorts_and_groups(context):
    result = run_query(
        context,
        RunQueryInput(
            investigation_ids=["bass2", "flex2", "bre"],
            filters=[QueryFilter(metric="o2_pct", op="between", min=17, max=22)],
            metrics=["o2_pct", "test_count"],
            group_by=["investigation_id"],
            sort=[SortSpec(metric="test_count", dir="desc")],
            limit=10,
        ),
    )
    ids = [row["investigation_id"] for row in result.data.rows]
    assert ids == ["bass2", "bre", "flex2"]
    assert result.data.scope == "summary"
    assert result.data.row_count == 3
    assert result.provenance


def test_run_query_grouping_by_theme_warns_on_mixed_test_labels(context):
    result = run_query(
        context,
        RunQueryInput(
            metrics=["test_count", "fuel"],
            group_by=["theme"],
            limit=10,
        ),
    )
    prevention = next(row for row in result.data.rows if row["theme"] == "prevention")
    assert prevention["test_count"] is None
    assert any("different units" in warning for warning in result.warnings)
    assert isinstance(prevention["fuel"], list)


def test_run_query_date_filter(context):
    result = run_query(
        context,
        RunQueryInput(
            investigation_ids=["flex", "flex2"],
            filters=[
                QueryFilter(
                    metric="test_date",
                    op="between",
                    min="2009-03-05",
                    max="2009-03-06",
                )
            ],
            metrics=["test_date", "test_count"],
            group_by=["investigation_id"],
            limit=10,
        ),
    )
    assert [row["investigation_id"] for row in result.data.rows] == ["flex"]
    assert result.data.rows[0]["test_date"]["start"] == "2009-03-05"


def test_run_query_rejects_bad_group_and_metric(context):
    with pytest.raises(ToolFault):
        run_query(context, RunQueryInput(group_by=["name"]))
    with pytest.raises(ToolFault):
        run_query(context, RunQueryInput(metrics=["nope"]))
    with pytest.raises(ToolFault):
        run_query(context, RunQueryInput(investigation_ids=["nope"]))


def test_score_investigations_moon(context):
    result = score_investigations(context, ScoreInput(environment_id="moon"))
    assert result.data.environment_id == "moon"
    assert result.data.weights["prevention"] == 30
    assert [item.investigation_id for item in result.data.items[:3]] == [
        "bre",
        "cfig",
        "flamedesign",
    ]
    assert result.data.items[0].score == 84
    assert result.data.items[0].gravity_match == 0.35
    assert result.data.items[0].scale_match == 0.8
    assert result.data.items[0].data_quality_factor == 1.0


def test_score_investigations_filters_and_unknown_environment(context):
    result = score_investigations(
        context, ScoreInput(environment_id="moon", filters={"theme": "detection"})
    )
    assert {item.investigation_id for item in result.data.items} == {"same", "samer"}

    with pytest.raises(ToolFault) as error:
        score_investigations(context, ScoreInput(environment_id="space"))
    assert error.value.code == "ENVIRONMENT_NOT_FOUND"
