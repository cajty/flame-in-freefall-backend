from __future__ import annotations

from core.data.generated import load_generated
from core.data.registry import ADAPTERS, CANONICAL_ORDER, METRIC_NAMES
from core.data.summary import summarize_investigation
from models import InvestigationRecord


def test_reference_ids_match_generated_registry_and_psi(context):
    reference = context.reference
    assert len(reference.investigations) == 15
    assert {item.id for item in reference.investigations} == set(CANONICAL_ORDER)
    assert set(context.catalog.summaries) == set(CANONICAL_ORDER)
    assert set(ADAPTERS) == set(CANONICAL_ORDER)
    assert set(reference.psi_ids) == set(CANONICAL_ORDER)


def test_reference_windows_and_weights_are_valid(context):
    for item in context.reference.investigations:
        assert 0 <= item.o2[0] <= item.o2[1] <= 100
        assert item.gravity in {"microgravity", "partial", "ground", "mixed"}
        assert item.scale in {"bench", "glovebox", "rack", "spacecraft"}
        assert item.data_quality in {"measured", "assumed-air", "partial", "planned"}
    for environment in context.reference.environments:
        assert set(environment.theme_weights) == set(context.reference.pillar_order)
        assert environment.gravity in {"microgravity", "partial"}
        assert 0 <= environment.p[0] <= environment.p[1]


def test_registry_covers_all_files_and_columns(context):
    assert len(ADAPTERS) == 15
    assert sum(len(adapter.files) for adapter in ADAPTERS.values()) == 17
    for adapter in ADAPTERS.values():
        context.repo.validate_adapter(adapter)
        for spec in adapter.files:
            assert "cld_flame_data_dictionary.csv" not in spec.path


def test_quality_fields_match_generated_flags(context):
    by_id = {item.id: item for item in context.reference.investigations}
    for item in by_id.values():
        if item.o2src == "air":
            assert item.data_quality == "assumed-air"
    assert by_id["saffire"].data_quality == "partial"
    assert by_id["flex2"].data_quality == "planned"


def test_generated_flags_only_saffire_partial_and_flex2_planned(context):
    summaries = context.catalog.summaries
    partial = [key for key, value in summaries.items() if value.o2 and value.o2.partial]
    planned = [key for key, adapter in ADAPTERS.items() if adapter.planned_only]
    assert partial == ["saffire"]
    assert planned == ["flex2"]
    assert summaries["saffire"].tests == 2
    assert summaries["spice"].tests == 368
    assert summaries["flex2"].tests == 8


def test_python_summary_matches_generated_json(settings):
    expected, _ = load_generated(settings.generated_json_path, CANONICAL_ORDER)
    from core.data.loader import CsvRepository

    repo = CsvRepository(settings.data_processed_dir)
    for investigation_id, adapter in ADAPTERS.items():
        actual = summarize_investigation(repo, adapter)
        assert actual == expected[investigation_id], investigation_id


def test_catalog_merge_rules(context):
    records: dict[str, InvestigationRecord] = {record.id: record for record in context.catalog.all()}
    assert records["bass2"].o2 == [13.6, 22.2]
    assert records["bass2"].o2known is True
    assert records["saffire"].o2 == [21.5, 22.1]
    assert records["saffire"].data.o2.partial is True
    assert records["bass"].o2 == [21, 21]
    assert records["bass"].o2src == "air"
    assert records["flex2"].planned_only is True
    assert records["bass"].data is not None


def test_schema_reads_canonical_metric_names(context):
    from tools.summary_tools import get_schema

    schema = get_schema(context)
    assert [metric.name for metric in schema.data.metrics] == list(METRIC_NAMES)
    assert schema.data.investigation_ids == list(CANONICAL_ORDER)
    assert schema.data.coverage["bass2"]["o2_pct"] is True
    assert schema.data.coverage["bass"]["pressure_atm"] is False
