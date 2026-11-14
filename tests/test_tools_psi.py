from __future__ import annotations

import pytest

from core.errors import ToolFault
from models import PsiRecordInput
from tools.psi import get_psi_record


def test_psi_lookup_maps_to_investigation(context):
    result = get_psi_record(context, PsiRecordInput(id="PSI-98"))
    assert result.data.psi_id == "PSI-98"
    assert result.data.investigations == [
        {
            "id": "saffire",
            "name": "Saffire",
            "sourceFiles": ["saffire/SAFFIRE-I_clean.csv"],
        }
    ]
    assert result.data.source_files == ["saffire/SAFFIRE-I_clean.csv"]
    assert result.data.urls == [
        "https://psi.nasa.gov/physci/repo/data/investigations/PSI-98"
    ]
    assert any(
        item.investigation_id == "saffire"
        and item.source_file == "saffire/SAFFIRE-I_clean.csv"
        for item in result.provenance
    )
    assert any("local reference" in warning for warning in result.warnings)


def test_psi_invalid_and_unknown(context):
    with pytest.raises(ToolFault):
        get_psi_record(context, PsiRecordInput(id="PSI-X"))
    with pytest.raises(ToolFault) as error:
        get_psi_record(context, PsiRecordInput(id="PSI-9999"))
    assert error.value.code == "PSI_NOT_FOUND"
    assert error.value.status_code == 404
