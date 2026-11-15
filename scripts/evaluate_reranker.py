#!/usr/bin/env python
"""Compare BM25 and the optional ONNX reranker on a labeled query set.

The labels are manual relevance judgments over the local PSI catalog metadata,
not expert safety decisions. Recall@5 counts only direct matches (grade 2);
nDCG@10 uses both direct (gain 3) and related (gain 1) records.

Examples:
    uv run python scripts/evaluate_reranker.py --baseline-only
    uv run python scripts/evaluate_reranker.py --model-dir models/reranker-onnx

Exit code 0 when the comparison finishes, 2 when an input or model is invalid.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.data.psi_catalog import PsiCatalogIndex, load_psi_catalog, rerank_matches
from core.data.reranker import Reranker, load_reranker

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = REPO_ROOT / "data" / "reference" / "psi_catalog.json"
DEFAULT_QUERIES = REPO_ROOT / "data" / "eval" / "psi_catalog_queries.json"
RECALL_K = 5
NDCG_K = 10


@dataclass(frozen=True)
class EvalQuery:
    query: str
    relevant: dict[str, int]


@dataclass(frozen=True)
class QueryResult:
    query: str
    baseline_recall: float
    baseline_ndcg: float
    reranked_recall: float | None
    reranked_ndcg: float | None


def recall_at_k(ranked_ids: list[str], relevant: dict[str, int], k: int) -> float:
    """Fraction of direct matches (grade 2) found in the top k results."""
    direct = {psi_id for psi_id, grade in relevant.items() if grade >= 2}
    if not direct:
        return 0.0
    return len(direct & set(ranked_ids[:k])) / len(direct)


def ndcg_at_k(ranked_ids: list[str], relevant: dict[str, int], k: int) -> float:
    """Graded nDCG with gain 3 for a direct match and gain 1 for related."""
    dcg = 0.0
    for rank, psi_id in enumerate(ranked_ids[:k], start=1):
        grade = relevant.get(psi_id, 0)
        if grade:
            dcg += (2**grade - 1) / math.log2(rank + 1)
    ideal = sorted(relevant.values(), reverse=True)[:k]
    idcg = sum(
        (2**grade - 1) / math.log2(rank + 1)
        for rank, grade in enumerate(ideal, start=1)
        if grade
    )
    return dcg / idcg if idcg else 0.0


def load_queries(path: Path, valid_ids: set[str]) -> list[EvalQuery]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("queries") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError(f"{path} must contain a non-empty queries list")
    queries: list[EvalQuery] = []
    for item in items:
        if not isinstance(item, dict):
            raise TypeError(f"{path} query entries must be objects")
        query = item.get("query")
        relevant = item.get("relevant")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"{path} has a query with no text")
        if not isinstance(relevant, dict) or not relevant:
            raise ValueError(f"{path} query {query!r} has no relevant records")
        grades = {str(psi_id): int(grade) for psi_id, grade in relevant.items()}
        if any(grade not in (1, 2) for grade in grades.values()):
            raise ValueError(f"{path} query {query!r} uses a grade outside 1 and 2")
        unknown = sorted(set(grades) - valid_ids)
        if unknown:
            raise ValueError(
                f"{path} query {query!r} names unknown PSI IDs: {', '.join(unknown)}"
            )
        queries.append(EvalQuery(query=query.strip(), relevant=grades))
    return queries


def evaluate(
    index: PsiCatalogIndex,
    queries: list[EvalQuery],
    reranker: Reranker | None,
    pool_size: int,
) -> list[QueryResult]:
    results: list[QueryResult] = []
    for item in queries:
        matches = index.search(item.query)
        baseline_ids = [match.record.psi_id for match in matches]
        reranked_ids = None
        if reranker is not None:
            reranked_ids = [
                match.record.psi_id
                for match in rerank_matches(
                    item.query, matches, reranker, pool_size=pool_size
                )
            ]
        results.append(
            QueryResult(
                query=item.query,
                baseline_recall=recall_at_k(baseline_ids, item.relevant, RECALL_K),
                baseline_ndcg=ndcg_at_k(baseline_ids, item.relevant, NDCG_K),
                reranked_recall=(
                    recall_at_k(reranked_ids, item.relevant, RECALL_K)
                    if reranked_ids is not None
                    else None
                ),
                reranked_ndcg=(
                    ndcg_at_k(reranked_ids, item.relevant, NDCG_K)
                    if reranked_ids is not None
                    else None
                ),
            )
        )
    return results


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def _summary(results: list[QueryResult]) -> dict[str, Any]:
    baseline_recall = _mean([item.baseline_recall for item in results])
    baseline_ndcg = _mean([item.baseline_ndcg for item in results])
    reranked = [item for item in results if item.reranked_recall is not None]
    improved = sum(
        1
        for item in reranked
        if item.reranked_recall is not None
        and item.reranked_recall > item.baseline_recall
    )
    regressed = sum(
        1
        for item in reranked
        if item.reranked_recall is not None
        and item.reranked_recall < item.baseline_recall
    )
    return {
        "query_count": len(results),
        "baseline": {
            f"recall_at_{RECALL_K}": baseline_recall,
            f"ndcg_at_{NDCG_K}": baseline_ndcg,
        },
        "reranked": (
            {
                f"recall_at_{RECALL_K}": _mean(
                    [item.reranked_recall for item in reranked]
                ),
                f"ndcg_at_{NDCG_K}": _mean([item.reranked_ndcg for item in reranked]),
                "recall_improved": improved,
                "recall_regressed": regressed,
            }
            if reranked
            else None
        ),
    }


def _print_table(results: list[QueryResult]) -> None:
    has_rerank = any(item.reranked_recall is not None for item in results)
    if has_rerank:
        print(
            f"{'query':42} {'bm25_r':>7} {'rr_r':>7} {'bm25_n':>7} {'rr_n':>7}"
        )
    else:
        print(f"{'query':42} {'bm25_r':>7} {'bm25_n':>7}")
    for item in results:
        query = item.query[:42]
        if has_rerank:
            print(
                f"{query:42} {item.baseline_recall:7.3f} "
                f"{item.reranked_recall or 0.0:7.3f} "
                f"{item.baseline_ndcg:7.3f} {item.reranked_ndcg or 0.0:7.3f}"
            )
        else:
            print(f"{query:42} {item.baseline_recall:7.3f} {item.baseline_ndcg:7.3f}")

    summary = _summary(results)
    baseline = summary["baseline"]
    if has_rerank:
        reranked = summary["reranked"]
        assert reranked is not None
        print(
            f"\nmean: BM25 recall@{RECALL_K} "
            f"{baseline[f'recall_at_{RECALL_K}']:.3f}, nDCG@{NDCG_K} "
            f"{baseline[f'ndcg_at_{NDCG_K}']:.3f}"
        )
        print(
            f"      rerank recall@{RECALL_K} "
            f"{reranked[f'recall_at_{RECALL_K}']:.3f}, nDCG@{NDCG_K} "
            f"{reranked[f'ndcg_at_{NDCG_K}']:.3f}"
        )
        improved = reranked["recall_improved"]
        regressed = reranked["recall_regressed"]
        print(
            f"      recall@{RECALL_K} improved in {improved} queries, "
            f"regressed in {regressed}"
        )
    else:
        print(
            f"\nmean: recall@{RECALL_K} "
            f"{baseline[f'recall_at_{RECALL_K}']:.3f}, nDCG@{NDCG_K} "
            f"{baseline[f'ndcg_at_{NDCG_K}']:.3f}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=None,
        help="ONNX reranker directory; omit to run the BM25 baseline only",
    )
    parser.add_argument("--pool-size", type=int, default=30)
    parser.add_argument(
        "--baseline-only", action="store_true", help="ignore --model-dir"
    )
    parser.add_argument("--json", action="store_true", help="print JSON summary")
    args = parser.parse_args(argv)

    if args.pool_size < 1:
        print("error: --pool-size must be at least 1", file=sys.stderr)
        return 2
    try:
        index = load_psi_catalog(args.catalog)
        valid_ids = {document.record.psi_id for document in index.documents}
        queries = load_queries(args.queries, valid_ids)
    except (OSError, TypeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    reranker = None
    if args.model_dir is not None and not args.baseline_only:
        reranker = load_reranker(args.model_dir)
        if reranker is None:
            print(
                f"error: reranker model unavailable at {args.model_dir}",
                file=sys.stderr,
            )
            return 2

    results = evaluate(index, queries, reranker, pool_size=args.pool_size)
    summary = _summary(results)
    if args.json:
        print(
            json.dumps(
                {
                    **summary,
                    "queries": [
                        {
                            "query": item.query,
                            "baseline": {
                                f"recall_at_{RECALL_K}": item.baseline_recall,
                                f"ndcg_at_{NDCG_K}": item.baseline_ndcg,
                            },
                            "reranked": (
                                {
                                    f"recall_at_{RECALL_K}": item.reranked_recall,
                                    f"ndcg_at_{NDCG_K}": item.reranked_ndcg,
                                }
                                if item.reranked_recall is not None
                                else None
                            ),
                        }
                        for item in results
                    ],
                },
                indent=2,
            )
        )
    else:
        _print_table(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
