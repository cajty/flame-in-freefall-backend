from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from config import Settings, get_settings
from core.data.catalog import Catalog, ScopedCatalog
from core.data.generated import load_generated
from core.data.loader import CsvRepository
from core.data.reference import ReferenceData, load_reference
from core.data.registry import ADAPTERS, CANONICAL_ORDER
from core.data.reranker import load_reranker
from core.services.conversations import ConversationStore
from core.services.exports import ExportStore


@dataclass
class AppContext:
    settings: Settings
    reference: ReferenceData
    catalog: Catalog | ScopedCatalog
    repo: CsvRepository
    exports: ExportStore
    conversations: ConversationStore
    clock: Callable[[], float]
    table_count: int = 0


def build_context(
    settings: Settings | None = None,
    clock: Callable[[], float] = time.time,
    load_csv: bool = True,
) -> AppContext:
    settings = settings or get_settings()
    reference = load_reference(settings.reference_dir)
    summaries, generated_at = load_generated(
        settings.generated_json_path, CANONICAL_ORDER
    )
    catalog = Catalog(reference, summaries, generated_at)
    repo = CsvRepository(settings.data_processed_dir)
    if load_csv:
        for adapter in ADAPTERS.values():
            repo.validate_adapter(adapter)
    exports = ExportStore(settings.export_ttl_seconds, clock=clock)
    conversations = ConversationStore(
        settings.conversation_ttl_seconds,
        clock=clock,
        max_entries=settings.conversation_max_entries,
        max_turns=settings.conversation_max_turns,
    )
    table_count = sum(1 for _ in settings.data_processed_dir.rglob("*.csv"))
    if settings.reranker_enabled:
        # Warm the optional model so the first search does not pay the load
        # cost. A missing model only logs a warning and leaves BM25 active.
        load_reranker(settings.reranker_model_dir)
    return AppContext(
        settings=settings,
        reference=reference,
        catalog=catalog,
        repo=repo,
        exports=exports,
        conversations=conversations,
        clock=clock,
        table_count=table_count,
    )


def with_scope(ctx: AppContext, investigation_ids: list[str]) -> AppContext:
    return replace(ctx, catalog=ScopedCatalog(ctx.catalog, set(investigation_ids)))
