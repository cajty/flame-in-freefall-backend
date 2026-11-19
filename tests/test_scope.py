from __future__ import annotations

import pytest

from agents.runner import resolve_psi_scope
from core.errors import DomainError, ToolFault
from core.context import with_scope


def test_scope_filters_catalog(context):
    scoped = with_scope(context, ["bass2"])

    assert [record.id for record in scoped.catalog.all()] == ["bass2"]
    assert set(scoped.catalog.coverage()) == {"bass2"}
    assert scoped.catalog.get("bass2").name == "BASS-II"

    with pytest.raises(DomainError) as error:
        scoped.catalog.get("flex2")
    assert error.value.code == "OUT_OF_SCOPE"

    with pytest.raises(DomainError):
        scoped.catalog.gaps(["flex2"])


def test_resolve_psi_scope_maps_and_deduplicates(context):
    assert resolve_psi_scope(context, None) is None
    assert resolve_psi_scope(context, []) is None
    assert resolve_psi_scope(context, ["PSI-25"]) == (["PSI-25"], ["bass2"])
    assert resolve_psi_scope(context, ["PSI-98", "PSI-99", "PSI-98"]) == (
        ["PSI-98", "PSI-99"],
        ["saffire"],
    )


def test_resolve_psi_scope_rejects_invalid_and_unknown(context):
    with pytest.raises(ToolFault) as error:
        resolve_psi_scope(context, ["PSI-X"])
    assert error.value.code == "INVALID_REQUEST"

    with pytest.raises(ToolFault) as error:
        resolve_psi_scope(context, ["PSI-9999"])
    assert error.value.code == "PSI_NOT_FOUND"
    assert error.value.status_code == 404
