from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from core.data.registry import CANONICAL_ORDER
from models import EnvironmentRecord, InvestigationMeta

PSI_ID_RE = re.compile(r"^PSI-\d+$")


@dataclass(frozen=True)
class ReferenceData:
    investigations: tuple[InvestigationMeta, ...]
    by_id: dict[str, InvestigationMeta]
    environments: tuple[EnvironmentRecord, ...]
    theme_weights: dict[str, dict[str, int]]
    psi_ids: dict[str, list[str]]
    psi_url_template: str
    pillar_order: list[str]
    phases: dict[str, dict[str, str]]
    pillars: dict[str, dict[str, str]]


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_o2_window(value: list[float], label: str) -> None:
    if len(value) != 2 or value[0] > value[1]:
        raise ValueError(f"{label}: invalid O2 window {value}")
    if value[0] < 0 or value[1] > 100:
        raise ValueError(f"{label}: O2 window outside 0-100: {value}")


def load_reference(reference_dir: Path) -> ReferenceData:
    investigations_raw = _read_json(reference_dir / "investigations.json")
    environments_raw = _read_json(reference_dir / "environments.json")
    theme_weights = _read_json(reference_dir / "theme_weights.json")
    psi_raw = _read_json(reference_dir / "psi.json")
    pillars_raw = _read_json(reference_dir / "pillars.json")

    if not isinstance(investigations_raw, list):
        raise TypeError("investigations.json must contain a list")
    investigations = tuple(InvestigationMeta.model_validate(item) for item in investigations_raw)

    ids = [item.id for item in investigations]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate investigation IDs in investigations.json")
    if set(ids) != set(CANONICAL_ORDER):
        missing = sorted(set(CANONICAL_ORDER) - set(ids))
        extra = sorted(set(ids) - set(CANONICAL_ORDER))
        raise ValueError(f"investigation ID mismatch: missing={missing} extra={extra}")

    pillar_order = list(pillars_raw["pillarOrder"])
    phases = pillars_raw["phases"]
    for item in investigations:
        if item.theme not in pillar_order:
            raise ValueError(f"{item.id}: unknown theme {item.theme}")
        if item.phase not in phases:
            raise ValueError(f"{item.id}: unknown phase {item.phase}")
        _validate_o2_window(item.o2, item.id)

    psi_ids = {
        key: list(value) for key, value in psi_raw["ids"].items()
    }
    if set(psi_ids) != set(CANONICAL_ORDER):
        raise ValueError("psi.json IDs do not match investigation IDs")
    for investigation_id, values in psi_ids.items():
        for psi_id in values:
            if not PSI_ID_RE.match(psi_id):
                raise ValueError(f"{investigation_id}: invalid PSI ID {psi_id}")

    if not isinstance(environments_raw, list):
        raise TypeError("environments.json must contain a list")
    environments: list[EnvironmentRecord] = []
    for item in environments_raw:
        env_id = item["id"]
        if item.get("gravity") not in ("microgravity", "partial"):
            raise ValueError(f"environment {env_id} needs gravity microgravity or partial")
        weights = theme_weights.get(env_id)
        if weights is None:
            raise ValueError(f"environment {env_id} has no theme weights")
        missing = set(pillar_order) - set(weights)
        if missing:
            raise ValueError(f"environment {env_id} missing theme weights: {sorted(missing)}")
        _validate_o2_window(item["o2"], env_id)
        environments.append(
            EnvironmentRecord.model_validate({**item, "themeWeights": weights})
        )

    if len({env.id for env in environments}) != len(environments):
        raise ValueError("duplicate environment IDs")

    return ReferenceData(
        investigations=investigations,
        by_id={item.id: item for item in investigations},
        environments=tuple(environments),
        theme_weights={key: dict(value) for key, value in theme_weights.items()},
        psi_ids=psi_ids,
        psi_url_template=str(psi_raw["urlTemplate"]),
        pillar_order=pillar_order,
        phases=phases,
        pillars=dict(pillars_raw["pillars"]),
    )
