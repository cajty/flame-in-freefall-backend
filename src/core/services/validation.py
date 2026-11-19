from __future__ import annotations

from core.context import AppContext
from core.errors import InvalidRequest


def validate_theme_phase(
    ctx: AppContext, theme: str | None, phase: str | None
) -> None:
    if theme is not None and theme not in ctx.reference.pillar_order:
        raise InvalidRequest(
            f"Unsupported theme: {theme}. Use get_schema for supported themes."
        )
    if phase is not None and phase not in ctx.reference.phases:
        raise InvalidRequest(
            f"Unsupported phase: {phase}. Use get_schema for supported phases."
        )
