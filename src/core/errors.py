from __future__ import annotations

from typing import Any


class ToolFault(Exception):
    """A tool failure that maps to a documented API error code and status."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or []

    def as_error(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            error["details"] = self.details
        return error


def not_found(code: str, message: str) -> ToolFault:
    return ToolFault(code, message, 404)
