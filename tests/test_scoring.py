from __future__ import annotations

import pytest

from core.errors import DomainError
from core.query_filters import matches_filter
from core.services.scoring import o2_overlap, rank, score
from models import QueryFilter


def _record(context, investigation_id):
    return context.catalog.get(investigation_id)


def test_overlap_and_score_known_values(context):
    moon = context.catalog.environment("moon")
    bre = _record(context, "bre")
    flex2 = _record(context, "flex2")
    weights = context.reference.theme_weights["moon"]

    details = score(bre, moon, weights)
    assert details.total == 84
    assert details.o2_overlap == 1.0
    assert details.gravity_match == 0.35
    assert details.scale_match == 0.8
    assert details.data_quality_factor == 1.0
    assert details.theme_weight == 30

    details = score(flex2, moon, weights)
    assert details.total == 0
    assert details.o2_overlap == 0.0
    assert details.data_quality_factor == 0.0

    assert o2_overlap([17, 30], [30, 40]) == 0.0
    assert o2_overlap([21, 21], [21, 25]) == 0.35
    assert o2_overlap([19.8, 85], [30, 40]) == 1.0


def test_rank_uses_weighted_score_then_reliability(context):
    moon = context.catalog.environment("moon")
    ranked = rank(
        list(context.catalog.all()),
        moon,
        context.reference.theme_weights["moon"],
    )
    top_ids = [record.id for record, _ in ranked[:3]]
    assert top_ids == ["bre", "cfig", "flamedesign"]

    scores = {record.id: details.total for record, details in ranked}
    assert scores["saffire"] > scores["bass"]
    assert scores["flex2"] == 0
    order = [record.id for record, _ in ranked]
    assert order[-1] == "flex2"


def test_saffire_has_spacecraft_scale_but_partial_data(context):
    iss = context.catalog.environment("iss")
    weights = context.reference.theme_weights["iss"]
    saffire = _record(context, "saffire")
    flex = _record(context, "flex")
    bass = _record(context, "bass")

    saffire_details = score(saffire, iss, weights)
    flex_details = score(flex, iss, weights)
    bass_details = score(bass, iss, weights)
    assert saffire_details.scale_match == 1.0
    assert saffire_details.gravity_match == 0.85
    assert saffire_details.data_quality_factor == 0.7
    assert flex_details.o2_overlap == 1.0
    assert bass_details.o2_overlap == 0.35
    assert bass_details.data_quality_factor == 0.45
    assert saffire_details.total > bass_details.total


def test_query_filter_range_contains_and_overlap(context):
    bass2 = _record(context, "bass2")

    assert matches_filter(bass2, QueryFilter(metric="o2_pct", op="between", min=17, max=22))
    assert matches_filter(bass2, QueryFilter(metric="o2_pct", op="eq", min=20))
    assert not matches_filter(bass2, QueryFilter(metric="o2_pct", op="eq", min=30))
    assert matches_filter(bass2, QueryFilter(metric="o2_pct", op="gt", min=20))
    assert matches_filter(bass2, QueryFilter(metric="test_count", op="gte", min=129))
    assert matches_filter(bass2, QueryFilter(metric="fuel", op="eq", values=["PMMA"]))


def test_query_filter_null_never_matches(context):
    bass2 = _record(context, "bass2")
    assert not matches_filter(bass2, QueryFilter(metric="pressure_atm", op="between", min=0, max=10))
    assert not matches_filter(bass2, QueryFilter(metric="pressure_atm", op="neq", min=1))


def test_query_filter_normalizes_pressure(context):
    cfig = _record(context, "cfig")
    assert cfig.data.pressure.unit == "bar"
    assert matches_filter(
        cfig, QueryFilter(metric="pressure_atm", op="between", min=0.5, max=1.0)
    )


def test_query_filter_rejects_unknown_metric(context):
    bass = _record(context, "bass")
    with pytest.raises(DomainError) as error:
        matches_filter(bass, QueryFilter(metric="burn_rate", op="eq", min=1))
    assert error.value.code == "UNKNOWN_METRIC"
