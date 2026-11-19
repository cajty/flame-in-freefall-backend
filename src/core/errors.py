from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    INVALID_QUERY = "INVALID_QUERY"
    INVALID_REQUEST = "INVALID_REQUEST"
    INVALID_CITATION = "INVALID_CITATION"
    UNKNOWN_METRIC = "UNKNOWN_METRIC"
    UNKNOWN_COLUMN = "UNKNOWN_COLUMN"
    INVALID_EXPORT_COLUMNS = "INVALID_EXPORT_COLUMNS"
    DATE_FILTER_UNSUPPORTED = "DATE_FILTER_UNSUPPORTED"
    INVESTIGATION_NOT_FOUND = "INVESTIGATION_NOT_FOUND"
    ENVIRONMENT_NOT_FOUND = "ENVIRONMENT_NOT_FOUND"
    PSI_NOT_FOUND = "PSI_NOT_FOUND"
    EXPORT_NOT_FOUND = "EXPORT_NOT_FOUND"
    NOT_FOUND = "NOT_FOUND"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    PSI_CATALOG_UNAVAILABLE = "PSI_CATALOG_UNAVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    EXPORT_EXPIRED = "EXPORT_EXPIRED"
    EXPORT_TOO_LARGE = "EXPORT_TOO_LARGE"
    UNAUTHORIZED = "UNAUTHORIZED"
    RATE_LIMITED = "RATE_LIMITED"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    REPEATED_TOOL_CALL = "REPEATED_TOOL_CALL"
    REQUEST_TOO_LARGE = "REQUEST_TOO_LARGE"
    MODEL_NOT_CONFIGURED = "MODEL_NOT_CONFIGURED"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    ANALYZE_TIMEOUT = "ANALYZE_TIMEOUT"
    ANALYZE_LIMIT_EXCEEDED = "ANALYZE_LIMIT_EXCEEDED"
    UNGROUNDED_ANSWER = "UNGROUNDED_ANSWER"
    UNGROUNDED_CITATION = "UNGROUNDED_CITATION"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    HTTP_ERROR = "HTTP_ERROR"
    DOMAIN_ERROR = "DOMAIN_ERROR"


def error_body(
    code: ErrorCode | str, message: str, details: list[str] | None = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return error


class DomainError(Exception):
    """A domain failure that carries no HTTP transport details."""

    code: ErrorCode | str = ErrorCode.DOMAIN_ERROR

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode | str | None = None,
        details: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code or type(self).code
        self.message = message
        self.details = details or []

    def as_error(self) -> dict[str, Any]:
        return error_body(self.code, self.message, self.details)


class InvalidRequest(DomainError):
    code = ErrorCode.INVALID_QUERY


class NotFound(DomainError):
    code = ErrorCode.NOT_FOUND


class OutOfScope(DomainError):
    code = ErrorCode.OUT_OF_SCOPE


class Unavailable(DomainError):
    code = ErrorCode.UNAVAILABLE


class ExportNotFound(DomainError):
    code = ErrorCode.EXPORT_NOT_FOUND


class ExportExpired(DomainError):
    code = ErrorCode.EXPORT_EXPIRED


class ToolFault(Exception):
    """A tool failure that maps to a documented API error code and status."""

    def __init__(
        self,
        code: ErrorCode | str,
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
        return error_body(self.code, self.message, self.details)
