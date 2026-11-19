from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.context import AppContext


@dataclass
class ToolCallRecord:
    name: str
    envelope: Any = None
    error: dict[str, Any] | None = None
    arguments: dict[str, Any] | None = None
    duration_ms: int | None = None

    @property
    def ok(self) -> bool:
        return self.envelope is not None and self.error is None


@dataclass
class ToolDeps:
    ctx: AppContext
    timeout_seconds: float
    calls: list[ToolCallRecord] = field(default_factory=list)
    scope_psi_ids: list[str] = field(default_factory=list)
    scope_investigation_ids: list[str] = field(default_factory=list)
    history_provenance: set[tuple[str, str]] = field(default_factory=set)

    @property
    def current_provenance(self) -> set[tuple[str, str]]:
        return {
            (item.investigation_id, item.source_file)
            for call in self.calls
            if call.ok
            for item in call.envelope.provenance
        }

    @property
    def grounded_provenance(self) -> set[tuple[str, str]]:
        return self.current_provenance | set(self.history_provenance)

    def repeated(self, name: str, arguments: dict[str, Any] | None) -> bool:
        """True when this run already called the tool with the same arguments."""
        return any(
            call.name == name and call.arguments == arguments for call in self.calls
        )

    def repeated_rejections(
        self, name: str, arguments: dict[str, Any] | None
    ) -> int:
        """Count earlier repeat-guard rejections for this exact call."""
        return sum(
            1
            for call in self.calls
            if call.name == name
            and call.arguments == arguments
            and call.error is not None
            and call.error.get("code") == "REPEATED_TOOL_CALL"
        )

    def record(
        self,
        name: str,
        *,
        envelope=None,
        error=None,
        arguments: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        self.calls.append(
            ToolCallRecord(
                name=name,
                envelope=envelope,
                error=error,
                arguments=arguments,
                duration_ms=duration_ms,
            )
        )
