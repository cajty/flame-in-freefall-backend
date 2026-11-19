from __future__ import annotations

import pytest

from core.errors import ToolFault
from models import AggregateTestsInput, QueryTestsInput
from core.services.row_queries import aggregate_tests, query_tests


def test_query_tests_saffire_returns_burns_only(context):
    result = query_tests(context, QueryTestsInput(investigation_id="saffire"))
    assert result.data.row_count == 2
    assert [row["rowIndex"] for row in result.data.rows] == [1, 2]
    assert all(row["sourceFile"] == "saffire/SAFFIRE-I_clean.csv" for row in result.data.rows)
    assert any(
        item.investigation_id == "saffire"
        and item.source_file == "saffire/SAFFIRE-I_clean.csv"
        for item in result.provenance
    )


def test_query_tests_spice_analysis_rows_and_pagination(context):
    first = query_tests(context, QueryTestsInput(investigation_id="spice", limit=5))
    assert first.data.row_count == 5
    assert first.data.next_cursor is not None

    second = query_tests(
        context,
        QueryTestsInput(investigation_id="spice", limit=5, cursor=first.data.next_cursor),
    )
    assert second.data.offset == 5
    assert {row["rowIndex"] for row in first.data.rows}.isdisjoint(
        {row["rowIndex"] for row in second.data.rows}
    )

    with pytest.raises(ToolFault):
        query_tests(
            context,
            QueryTestsInput(
                investigation_id="spice", limit=5, cursor=first.data.next_cursor, offset=5
            ),
        )


def test_query_tests_filters_and_columns(context):
    result = query_tests(
        context,
        QueryTestsInput(
            investigation_id="flex",
            metric="o2_percent",
            min=20,
            max=30,
            fuel="methanol",
            columns=["rowIndex", "sourceFile", "fuel", "o2_percent"],
            limit=10,
        ),
    )
    assert result.data.row_count > 0
    for row in result.data.rows:
        assert row["fuel"] == "methanol"
        assert 20 <= float(row["o2_percent"]) <= 30
        assert set(row) == {"rowIndex", "sourceFile", "fuel", "o2_percent"}


def test_query_tests_date_filter_unsupported(context):
    with pytest.raises(ToolFault) as error:
        query_tests(
            context,
            QueryTestsInput(investigation_id="cfig", date_start="2020-01-01"),
        )
    assert error.value.code == "DATE_FILTER_UNSUPPORTED"


def test_query_tests_unknown_column_and_investigation(context):
    with pytest.raises(ToolFault) as error:
        query_tests(
            context,
            QueryTestsInput(investigation_id="flex", columns=["not_a_column"]),
        )
    assert error.value.code == "INVALID_EXPORT_COLUMNS"

    with pytest.raises(ToolFault) as error:
        query_tests(context, QueryTestsInput(investigation_id="nope"))
    assert error.value.code == "INVESTIGATION_NOT_FOUND"


def test_aggregate_tests_grouped_mean(context):
    result = aggregate_tests(
        context,
        AggregateTestsInput(
            investigation_id="flex",
            metric="o2_percent",
            group_by=["fuel"],
            stat="mean",
        ),
    )
    groups = {group.group["fuel"]: group for group in result.data.groups}
    assert set(groups) == {"heptane", "methanol"}
    assert groups["heptane"].count == 117
    assert groups["methanol"].count == 157
    assert result.data.row_count == 274
    assert any(
        item.investigation_id == "flex" and item.source_file
        for item in result.provenance
    )


def test_aggregate_tests_canonical_metric_across_files(context):
    result = aggregate_tests(
        context,
        AggregateTestsInput(investigation_id="cfig", metric="o2_pct", stat="count"),
    )
    assert result.data.groups[0].count == 333
    assert result.data.groups[0].value == 333.0
    assert result.data.row_count == 333


def test_aggregate_tests_rejects_non_numeric_and_too_many_groups(context):
    with pytest.raises(ToolFault):
        aggregate_tests(
            context,
            AggregateTestsInput(investigation_id="flex", metric="fuel"),
        )
    with pytest.raises(ToolFault):
        aggregate_tests(
            context,
            AggregateTestsInput(
                investigation_id="flex",
                metric="o2_percent",
                group_by=["fuel", "test_end", "regime"],
            ),
        )


def test_aggregate_tests_planned_warning(context):
    result = aggregate_tests(
        context,
        AggregateTestsInput(investigation_id="flex2", metric="o2_pct", stat="max"),
    )
    assert any("planned" in warning for warning in result.warnings)
