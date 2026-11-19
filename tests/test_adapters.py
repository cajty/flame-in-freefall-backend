from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from core.data.registry import ADAPTERS, ADAPTERS_PATH

REPO_ROOT = Path(__file__).resolve().parents[1]


def _definition_summary(adapter) -> dict:
    return {
        "files": [spec.path for spec in adapter.files],
        "variables": list(adapter.variables),
        "testLabel": adapter.test_label,
        "pressureUnit": adapter.pressure_unit,
        "o2Partial": adapter.o2_partial,
        "plannedOnly": adapter.planned_only,
        "hasCount": adapter.count_rule is not None,
    }


def test_bundled_adapters_match_json_definitions():
    raw = json.loads(ADAPTERS_PATH.read_text(encoding="utf-8"))["adapters"]

    assert tuple(ADAPTERS) == tuple(raw)
    for adapter_id, definition in raw.items():
        adapter = ADAPTERS[adapter_id]
        assert [spec.path for spec in adapter.files] == [
            file_spec["path"] for file_spec in definition["files"]
        ]
        assert list(adapter.variables) == definition["variables"]
        assert adapter.test_label == definition.get("testLabel", "tests")
        assert adapter.pressure_unit == definition.get("pressureUnit", "atm")
        assert adapter.o2_partial is definition.get("o2Partial", False)
        assert adapter.planned_only is definition.get("plannedOnly", False)
        assert (adapter.count_rule is not None) is ("countRule" in definition)


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_python_and_javascript_adapters_agree():
    script = """
import { ADAPTERS } from './scripts/lib/adapters.js';
const out = Object.fromEntries(Object.entries(ADAPTERS).map(([id, adapter]) => [id, {
  files: adapter.files.map((file) => file.path),
  variables: adapter.variables,
  testLabel: adapter.testLabel ?? 'tests',
  pressureUnit: adapter.pressureUnit ?? 'atm',
  o2Partial: adapter.o2Partial ?? false,
  plannedOnly: adapter.plannedOnly ?? false,
  hasCount: typeof adapter.count === 'function',
}]));
console.log(JSON.stringify(out));
"""
    completed = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    javascript = json.loads(completed.stdout)
    python = {
        adapter_id: _definition_summary(adapter)
        for adapter_id, adapter in ADAPTERS.items()
    }

    assert javascript == python
