from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import evaluate_reranker

from core.data.psi_catalog import load_psi_catalog


def test_recall_at_k_counts_direct_matches_only():
    relevant = {"PSI-1": 2, "PSI-2": 2, "PSI-3": 1}

    assert evaluate_reranker.recall_at_k(["PSI-1", "PSI-3"], relevant, 5) == 0.5
    assert evaluate_reranker.recall_at_k(["PSI-3"], relevant, 5) == 0.0


def test_ndcg_at_k_perfect_ranking_is_one():
    relevant = {"A": 2, "B": 1}

    assert evaluate_reranker.ndcg_at_k(["A", "B"], relevant, 10) == pytest.approx(1.0)


def test_ndcg_at_k_penalizes_a_missing_direct_match():
    relevant = {"A": 2}

    assert evaluate_reranker.ndcg_at_k(["X", "A"], relevant, 10) == pytest.approx(
        1 / math.log2(3)
    )


def test_ndcg_at_k_uses_graded_relevance():
    relevant = {"A": 2, "B": 1}
    dcg = 1 / 1 + 3 / math.log2(3)
    idcg = 3 / 1 + 1 / math.log2(3)

    assert evaluate_reranker.ndcg_at_k(["B", "A"], relevant, 10) == pytest.approx(
        dcg / idcg
    )


def test_load_queries_rejects_unknown_psi_id(tmp_path):
    path = tmp_path / "queries.json"
    path.write_text(
        json.dumps({"queries": [{"query": "fire", "relevant": {"PSI-999": 2}}]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown PSI IDs"):
        evaluate_reranker.load_queries(path, {"PSI-1"})


def test_load_queries_rejects_grade_outside_one_and_two(tmp_path):
    path = tmp_path / "queries.json"
    path.write_text(
        json.dumps({"queries": [{"query": "fire", "relevant": {"PSI-1": 3}}]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="grade outside"):
        evaluate_reranker.load_queries(path, {"PSI-1"})


@pytest.mark.skipif(
    not evaluate_reranker.DEFAULT_CATALOG.exists(),
    reason="run npm run catalog to generate the PSI catalog",
)
def test_default_query_labels_exist_in_the_local_catalog():
    index = load_psi_catalog(evaluate_reranker.DEFAULT_CATALOG)
    valid_ids = {document.record.psi_id for document in index.documents}

    queries = evaluate_reranker.load_queries(
        evaluate_reranker.DEFAULT_QUERIES, valid_ids
    )

    assert len(queries) >= 20
