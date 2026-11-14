from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConversationTurn:
    messages: tuple[Any, ...]
    provenance: frozenset[tuple[str, str]]


@dataclass(frozen=True)
class ConversationSnapshot:
    messages: tuple[Any, ...] = ()
    provenance: frozenset[tuple[str, str]] = frozenset()


@dataclass
class ConversationEntry:
    turns: tuple[ConversationTurn, ...]
    updated_at: float
    expires_at: float


class ConversationStore:
    """In-memory conversation history with an idle TTL.

    Single-process only: history is lost on restart and is not shared between
    workers. The caller owns the ID, so the ID must be unguessable when the
    endpoint is reachable by more than one client.
    """

    def __init__(
        self,
        ttl_seconds: int,
        clock: Callable[[], float] = time.time,
        max_entries: int = 100,
        max_turns: int = 8,
    ) -> None:
        self._ttl = ttl_seconds
        self._clock = clock
        self._max_entries = max(1, max_entries)
        self._max_turns = max(1, max_turns)
        self._items: dict[str, ConversationEntry] = {}
        self._lock = threading.Lock()

    def _purge(self, now: float) -> None:
        expired = [
            conversation_id
            for conversation_id, entry in self._items.items()
            if entry.expires_at <= now
        ]
        for conversation_id in expired:
            self._items.pop(conversation_id, None)

    def snapshot(self, conversation_id: str) -> ConversationSnapshot:
        now = self._clock()
        with self._lock:
            self._purge(now)
            entry = self._items.get(conversation_id)
            if entry is None:
                return ConversationSnapshot()
            entry.updated_at = now
            entry.expires_at = now + self._ttl
            messages = tuple(
                message for turn in entry.turns for message in turn.messages
            )
            provenance = frozenset(
                pair for turn in entry.turns for pair in turn.provenance
            )
            return ConversationSnapshot(messages=messages, provenance=provenance)

    def append(
        self,
        conversation_id: str,
        messages: tuple[Any, ...],
        provenance: set[tuple[str, str]],
    ) -> None:
        now = self._clock()
        with self._lock:
            self._purge(now)
            entry = self._items.get(conversation_id)
            turns = list(entry.turns) if entry is not None else []
            turns.append(
                ConversationTurn(
                    messages=tuple(messages),
                    provenance=frozenset(provenance),
                )
            )
            if entry is None:
                while len(self._items) >= self._max_entries:
                    oldest = min(
                        self._items,
                        key=lambda key: self._items[key].updated_at,
                    )
                    self._items.pop(oldest, None)
            self._items[conversation_id] = ConversationEntry(
                turns=tuple(turns[-self._max_turns :]),
                updated_at=now,
                expires_at=now + self._ttl,
            )

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
