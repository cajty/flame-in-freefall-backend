from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from core.data.psi_catalog import load_psi_catalog, rerank_matches
from core.data.reranker import load_reranker
from core.errors import ToolFault
from models import PsiCatalogSearchInput
from core.context import with_scope
from tools.psi import search_psi_catalog

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import fetch_psi_catalog  # noqa: E402

REAL_CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "reference" / "psi_catalog.json"
)


def _record(
    psi_id: str,
    title: str,
    acronym: str = "",
    objective: str = "",
    research_area: str = "Combustion Science",
    sub_research_area: str = "Spacecraft Fire Safety",
) -> dict:
    return {
        "psiId": psi_id,
        "title": title,
        "acronym": acronym,
        "researchArea": research_area,
        "subResearchArea": sub_research_area,
        "projectType": "Microgravity Investigation",
        "flightProgram": "International Space Station (ISS)",
        "experimentHardware": "Microgravity Science Glovebox",
        "objective": objective,
        "approach": "",
        "hypothesis": "",
        "researchImpacts": "",
        "modifiedDate": "01-Jan-2026",
        "restricted": False,
        "sourceHash": "0" * 64,
    }


def _write_catalog(path: Path, items: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "generatedAt": "2026-01-01T00:00:00Z",
                "source": "https://psi.nasa.gov/geode-py/ws/studies",
                "count": len(items),
                "items": items,
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture()
def catalog_path(tmp_path: Path) -> Path:
    path = tmp_path / "psi_catalog.json"
    _write_catalog(
        path,
        [
            _record(
                "PSI-25",
                "Burning and Suppression of Solids - II",
                acronym="BASS-II",
                objective="Flame spread and extinction limits for solid fuels in low-velocity flows.",
            ),
            _record(
                "PSI-26",
                "Burning and Suppression of Solids",
                acronym="BASS",
                objective="Solid fuel ignition and suppression in microgravity.",
            ),
            _record(
                "PSI-902",
                "Flame Spread in Low Oxygen",
                objective="Flame spread over wire insulation in reduced oxygen microgravity.",
            ),
            _record(
                "PSI-903",
                "Water Recovery System",
                objective="Urine processing and water recovery for life support.",
                research_area="Life Support Systems",
                sub_research_area="Water Recovery",
            ),
        ],
    )
    return path


def _use_catalog(context, path: Path) -> None:
    context.settings.psi_catalog_path = path


def test_search_ranks_title_match_and_marks_uncurated(context, catalog_path):
    _use_catalog(context, catalog_path)

    result = search_psi_catalog(
        context, PsiCatalogSearchInput(q="flame spread oxygen")
    )

    assert result.data.items[0].psi_id == "PSI-902"
    assert result.data.items[0].curated is False
    assert result.data.items[0].investigation_ids == []
    assert "metadata only" in result.warnings[0]
    assert any("leads, not evidence" in warning for warning in result.warnings)


def test_search_maps_curated_record_to_investigation(context, catalog_path):
    _use_catalog(context, catalog_path)

    result = search_psi_catalog(context, PsiCatalogSearchInput(q="BASS-II"))

    top = result.data.items[0]
    assert top.psi_id == "PSI-25"
    assert top.curated is True
    assert top.investigation_ids == ["bass2"]
    assert top.url.endswith("/PSI-25")
    assert result.provenance == []
    assert result.data.catalog_size == 4


def test_search_finds_record_by_accession(context, catalog_path):
    _use_catalog(context, catalog_path)

    result = search_psi_catalog(context, PsiCatalogSearchInput(q="PSI-903"))

    assert result.data.items[0].psi_id == "PSI-903"
    assert result.data.total == 1


def test_scoped_search_returns_only_curated_scope(context, catalog_path):
    _use_catalog(context, catalog_path)
    scoped = with_scope(context, ["bass2"])

    result = search_psi_catalog(scoped, PsiCatalogSearchInput(q="flame"))

    assert [item.psi_id for item in result.data.items] == ["PSI-25"]
    assert all(item.curated for item in result.data.items)
    assert any("limited to the PSI scope" in warning for warning in result.warnings)


def test_scoped_search_drops_curated_record_outside_scope(context, catalog_path):
    _use_catalog(context, catalog_path)
    scoped = with_scope(context, ["bass2"])

    result = search_psi_catalog(scoped, PsiCatalogSearchInput(q="PSI-26"))

    assert result.data.items == []
    assert result.data.total == 0
    assert any("No PSI catalog record matched" in warning for warning in result.warnings)


def test_restricted_hit_adds_warning(context, tmp_path):
    path = tmp_path / "psi_catalog.json"
    record = _record("PSI-904", "Restricted Furnace", objective="Combustion furnace study.")
    record["restricted"] = True
    _write_catalog(path, [record])
    _use_catalog(context, path)

    result = search_psi_catalog(context, PsiCatalogSearchInput(q="furnace"))

    assert result.data.items[0].restricted is True
    assert any("restricted" in warning for warning in result.warnings)


def test_missing_catalog_is_unavailable(context, tmp_path):
    _use_catalog(context, tmp_path / "missing.json")

    with pytest.raises(ToolFault) as error:
        search_psi_catalog(context, PsiCatalogSearchInput(q="flame"))

    assert error.value.code == "PSI_CATALOG_UNAVAILABLE"
    assert error.value.status_code == 503


def test_malformed_catalog_is_unavailable(context, tmp_path):
    path = tmp_path / "psi_catalog.json"
    path.write_text("{not json", encoding="utf-8")
    _use_catalog(context, path)

    with pytest.raises(ToolFault) as error:
        search_psi_catalog(context, PsiCatalogSearchInput(q="flame"))

    assert error.value.code == "PSI_CATALOG_UNAVAILABLE"


def test_empty_catalog_is_unavailable(context, tmp_path):
    path = tmp_path / "psi_catalog.json"
    _write_catalog(path, [])
    _use_catalog(context, path)

    with pytest.raises(ToolFault) as error:
        search_psi_catalog(context, PsiCatalogSearchInput(q="flame"))

    assert error.value.code == "PSI_CATALOG_UNAVAILABLE"


def test_query_without_searchable_words_is_rejected(context, catalog_path):
    _use_catalog(context, catalog_path)

    with pytest.raises(ToolFault) as error:
        search_psi_catalog(context, PsiCatalogSearchInput(q="a the of"))

    assert error.value.code == "INVALID_QUERY"


class _FakeReranker:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    def score(self, query: str, documents: list[str]) -> list[float]:
        if self._error is not None:
            raise self._error
        return [1.0 if "Suppression" in document else 0.1 for document in documents]


def test_reranker_reorders_matches_and_keeps_bm25_score(
    context, catalog_path, monkeypatch
):
    _use_catalog(context, catalog_path)
    context.settings.reranker_enabled = True
    context.settings.reranker_pool_size = 10
    monkeypatch.setattr(
        "core.services.psi_search.load_reranker", lambda model_dir: _FakeReranker()
    )

    result = search_psi_catalog(
        context, PsiCatalogSearchInput(q="flame spread oxygen")
    )

    assert [item.psi_id for item in result.data.items] == ["PSI-25", "PSI-902"]
    assert result.data.items[0].rerank_score == 1.0
    assert result.data.items[0].score > 0


def test_reranker_runs_after_scope_filter(context, catalog_path, monkeypatch):
    _use_catalog(context, catalog_path)
    context.settings.reranker_enabled = True
    context.settings.reranker_pool_size = 1
    monkeypatch.setattr(
        "core.services.psi_search.load_reranker", lambda model_dir: _FakeReranker()
    )
    scoped = with_scope(context, ["bass2"])

    result = search_psi_catalog(
        scoped, PsiCatalogSearchInput(q="flame spread oxygen")
    )

    assert [item.psi_id for item in result.data.items] == ["PSI-25"]
    assert result.data.items[0].rerank_score == 1.0


def test_reranker_disabled_keeps_bm25_order(context, catalog_path):
    _use_catalog(context, catalog_path)

    result = search_psi_catalog(
        context, PsiCatalogSearchInput(q="flame spread oxygen")
    )

    assert result.data.items[0].psi_id == "PSI-902"
    assert all(item.rerank_score is None for item in result.data.items)


def test_missing_reranker_falls_back_to_bm25(context, catalog_path, monkeypatch):
    _use_catalog(context, catalog_path)
    context.settings.reranker_enabled = True
    monkeypatch.setattr("core.services.psi_search.load_reranker", lambda model_dir: None)

    result = search_psi_catalog(
        context, PsiCatalogSearchInput(q="flame spread oxygen")
    )

    assert result.data.items[0].psi_id == "PSI-902"
    assert any("BM25 order" in warning for warning in result.warnings)


def test_reranker_failure_falls_back_to_bm25(context, catalog_path, monkeypatch):
    _use_catalog(context, catalog_path)
    context.settings.reranker_enabled = True
    monkeypatch.setattr(
        "core.services.psi_search.load_reranker",
        lambda model_dir: _FakeReranker(RuntimeError("inference failed")),
    )

    result = search_psi_catalog(
        context, PsiCatalogSearchInput(q="flame spread oxygen")
    )

    assert result.data.items[0].psi_id == "PSI-902"
    assert any("Reranker failed" in warning for warning in result.warnings)


class _ShortReranker:
    def score(self, query: str, documents: list[str]) -> list[float]:
        return [1.0]


def test_reranker_rejects_wrong_score_count(catalog_path):
    index = load_psi_catalog(catalog_path)
    matches = index.search("flame spread oxygen")

    with pytest.raises(ValueError, match="returned 1 scores"):
        rerank_matches("flame spread oxygen", matches, _ShortReranker(), pool_size=2)


def test_load_reranker_returns_none_for_missing_model(tmp_path):
    assert load_reranker(tmp_path / "missing-model") is None


@pytest.mark.skipif(
    not REAL_CATALOG_PATH.exists(),
    reason="run npm run catalog to generate the PSI catalog",
)
def test_real_catalog_contains_curated_records(context):
    index = load_psi_catalog(context.settings.psi_catalog_path)

    assert index.size >= 130
    by_id = {document.record.psi_id: document.record for document in index.documents}
    curated_ids = {
        psi_id
        for psi_ids in context.reference.psi_ids.values()
        for psi_id in psi_ids
    }
    assert curated_ids <= set(by_id)
    assert "Burning and Suppression of Solids" in by_id["PSI-25"].title


def test_extract_entry_drops_file_lists_and_keeps_metadata():
    record = {
        "accession": "PSI-25",
        "title": "  Burning   and Suppression of Solids ",
        "investigationAcronym": "BASS-II",
        "objective": "Line one\nline two",
        "public": True,
        "restricted": False,
        "added": [{"file_name": "huge.bin"}],
        "removed": [{"file_name": "old.bin"}],
    }

    entry = fetch_psi_catalog.extract_entry("PSI-25", record, "a" * 64)

    assert entry["title"] == "Burning and Suppression of Solids"
    assert entry["acronym"] == "BASS-II"
    assert entry["objective"] == "Line one line two"
    assert "added" not in entry
    assert "removed" not in entry
    assert entry["psiId"] == "PSI-25"
    assert entry["sourceHash"] == "a" * 64


def test_extract_entry_caps_and_strips_field_text():
    record = {
        "accession": "PSI-25",
        "title": "word " * 2_000,
        "objective": "line\u0000one\nline two",
    }

    entry = fetch_psi_catalog.extract_entry("PSI-25", record, "a" * 64)

    assert len(entry["title"]) == fetch_psi_catalog.MAX_FIELD_CHARS
    assert entry["objective"] == "lineone line two"


def test_parse_study_ids_validates_and_sorts():
    assert fetch_psi_catalog.parse_study_ids(
        {"content": ["PSI-10", "PSI-2", "PSI-10"]}
    ) == ["PSI-2", "PSI-10"]

    with pytest.raises(ValueError, match="invalid PSI ID"):
        fetch_psi_catalog.parse_study_ids({"content": ["PSI-x"]})
    with pytest.raises(TypeError):
        fetch_psi_catalog.parse_study_ids({"content": "PSI-2"})


def test_extract_entry_rejects_accession_mismatch():
    record = {"accession": "PSI-1", "title": "Wrong record"}

    with pytest.raises(ValueError, match="does not match"):
        fetch_psi_catalog.extract_entry("PSI-25", record, "a" * 64)
