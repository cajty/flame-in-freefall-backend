from __future__ import annotations

import pytest

from core.errors import DomainError, ToolFault
from models import GapsInput, GetInvestigationInput, SearchInput
from core.services.investigations import (
    find_data_gaps,
    get_environments,
    get_investigation,
    search_investigations,
)


def test_search_text_theme_phase_and_paging(context):
    result = search_investigations(context, SearchInput(q="solid", limit=2, offset=0))
    assert result.data.total >= 2
    assert len(result.data.items) == 2
    assert result.data.limit == 2
    assert {item.investigation_id for item in result.provenance} == {
        item.id for item in result.data.items
    }

    prevention = search_investigations(context, SearchInput(theme="prevention"))
    assert prevention.data.total == 5
    assert all(item.theme == "prevention" for item in prevention.data.items)

    gas = search_investigations(context, SearchInput(phase="gas", limit=200))
    assert gas.data.total == 7
    assert all(item.phase == "gas" for item in gas.data.items)


def test_search_o2_fuel_and_has_data_filters(context):
    o2 = search_investigations(context, SearchInput(o2_min=30, o2_max=40, limit=200))
    assert {item.id for item in o2.data.items} >= {"bre", "flex2", "sflame"}

    fuel = search_investigations(context, SearchInput(fuel="pmma", limit=200))
    assert {item.id for item in fuel.data.items} >= {"bass", "bass2"}

    measured = search_investigations(context, SearchInput(has_data=True, limit=200))
    assert "flex2" not in {item.id for item in measured.data.items}


def test_search_rejects_unknown_theme_and_inverted_window(context):
    with pytest.raises(DomainError) as error:
        search_investigations(context, SearchInput(theme="science"))
    assert error.value.code == "INVALID_QUERY"

    with pytest.raises(ToolFault):
        search_investigations(context, SearchInput(o2_min=30, o2_max=20))


def test_get_investigation_and_missing_id(context):
    result = get_investigation(context, GetInvestigationInput(id="bass2"))
    assert result.data.name == "BASS-II"
    assert result.data.data.tests == 129
    assert result.data.psi.ids == ["PSI-25"]
    assert any("pressure" in warning for warning in result.warnings)

    with pytest.raises(DomainError) as error:
        get_investigation(context, GetInvestigationInput(id="nope"))
    assert error.value.code == "INVESTIGATION_NOT_FOUND"


def test_environments_have_weights(context):
    result = get_environments(context)
    assert [item.id for item in result.data.items] == ["iss", "moon", "mars", "rover"]
    assert result.data.items[1].theme_weights["prevention"] == 30


def test_gaps_match_contract_examples(context):
    result = find_data_gaps(context, GapsInput(ids=["bass2", "flex2", "saffire"]))
    items = {item.investigation_id: item for item in result.data.items}
    assert items["bass2"].missing == ["pressure"]
    assert items["bass2"].planned_only is False
    assert items["flex2"].missing == []
    assert items["flex2"].planned_only is True
    assert items["saffire"].partial == ["o2"]
    assert {item.investigation_id for item in result.provenance} == {
        "bass2",
        "flex2",
        "saffire",
    }


def test_gaps_unknown_id_raises(context):
    with pytest.raises(DomainError):
        find_data_gaps(context, GapsInput(ids=["nope"]))
