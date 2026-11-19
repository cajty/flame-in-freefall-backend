from __future__ import annotations

from core.context import AppContext
from core.errors import DomainError, ErrorCode, ToolFault
from core.services import psi_search
from models import (
    Envelope,
    PsiCatalogSearchData,
    PsiCatalogSearchInput,
    PsiRecordData,
    PsiRecordInput,
)

_STATUS_BY_CODE = {
    ErrorCode.PSI_CATALOG_UNAVAILABLE: 503,
    ErrorCode.PSI_NOT_FOUND: 404,
}


def _tool_fault(error: DomainError) -> ToolFault:
    return ToolFault(
        error.code,
        error.message,
        status_code=_STATUS_BY_CODE.get(error.code, 400),
        details=error.details,
    )


def search_psi_catalog(
    ctx: AppContext, request: PsiCatalogSearchInput
) -> Envelope[PsiCatalogSearchData]:
    try:
        result = psi_search.search_catalog(ctx, request.q, request.limit)
    except DomainError as error:
        raise _tool_fault(error) from error
    return Envelope(data=result.data, warnings=result.warnings)


def get_psi_record(ctx: AppContext, request: PsiRecordInput) -> Envelope[PsiRecordData]:
    try:
        result = psi_search.get_record(ctx, request.id.strip())
    except DomainError as error:
        raise _tool_fault(error) from error
    return Envelope(
        data=result.data,
        provenance=result.provenance,
        warnings=result.warnings,
    )
