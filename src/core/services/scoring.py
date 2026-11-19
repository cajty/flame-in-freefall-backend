from __future__ import annotations

from dataclasses import dataclass

from core.data.summary import js_round
from core.services.metrics import citation_context
from models import (
    DataQuality,
    EnvironmentRecord,
    Gravity,
    InvestigationRecord,
    Scale,
    ScoreItem,
)

# Starting weights. They are provisional and should be calibrated with a fire-safety
# domain expert; the dashboard shows the same weights so a ranking can be explained.
RELEVANCE_WEIGHTS = {
    "o2": 0.20,
    "gravity": 0.15,
    "scale": 0.30,
    "dataQuality": 0.20,
    "theme": 0.15,
}

# A single-condition test inside the environment window still informs one point.
# Without this floor, 21% tested against a 21-25% window scores zero coverage.
POINT_O2_COVERAGE = 0.35

# Microgravity data is a proxy for partial gravity, not a direct match.
GRAVITY_MATCH = {
    Gravity.microgravity: {Gravity.microgravity: 1.0, Gravity.partial: 0.35},
    Gravity.partial: {Gravity.microgravity: 0.5, Gravity.partial: 1.0},
    Gravity.mixed: {Gravity.microgravity: 0.85, Gravity.partial: 0.65},
    Gravity.ground: {Gravity.microgravity: 0.2, Gravity.partial: 0.1},
}

# Larger tests are closer to a habitat-scale fire, but they remain proxies.
SCALE_MATCH = {
    Scale.bench: 0.3,
    Scale.glovebox: 0.6,
    Scale.rack: 0.8,
    Scale.spacecraft: 1.0,
}

DATA_QUALITY_SCORE = {
    DataQuality.measured: 1.0,
    DataQuality.partial: 0.7,
    DataQuality.assumed_air: 0.45,
    DataQuality.planned: 0.0,
}


@dataclass(frozen=True)
class ScoreDetails:
    total: int
    o2_overlap: float
    gravity_match: float
    scale_match: float
    data_quality_factor: float
    theme_fraction: float
    theme_weight: int


def o2_overlap(investigation_o2: list[float], environment_o2: list[float]) -> float:
    width = environment_o2[1] - environment_o2[0]
    if width <= 0:
        return 0.0
    overlap = max(
        0.0,
        min(investigation_o2[1], environment_o2[1])
        - max(investigation_o2[0], environment_o2[0]),
    )
    coverage = min(1.0, overlap / width)
    if coverage > 0:
        return coverage
    point_inside = (
        investigation_o2[0] == investigation_o2[1]
        and environment_o2[0] <= investigation_o2[0] <= environment_o2[1]
    )
    return POINT_O2_COVERAGE if point_inside else 0.0


def gravity_match(investigation_gravity: Gravity, environment_gravity: Gravity) -> float:
    return GRAVITY_MATCH.get(investigation_gravity, {}).get(environment_gravity, 0.0)


def scale_match(scale: Scale) -> float:
    return SCALE_MATCH.get(scale, 0.0)


def data_quality_factor(data_quality: DataQuality) -> float:
    return DATA_QUALITY_SCORE.get(data_quality, 0.0)


def theme_fraction(theme_weight: int, weights: dict[str, int]) -> float:
    maximum = max(weights.values(), default=0)
    return theme_weight / maximum if maximum > 0 else 0.0


def score(
    record: InvestigationRecord,
    environment: EnvironmentRecord,
    weights: dict[str, int],
) -> ScoreDetails:
    o2 = o2_overlap(record.o2, environment.o2)
    gravity = gravity_match(record.gravity, environment.gravity)
    scale = scale_match(record.scale)
    quality = data_quality_factor(record.data_quality)
    theme_weight = weights[record.theme]
    theme = theme_fraction(theme_weight, weights)
    total = 0
    if record.data_quality != DataQuality.planned:
        total = int(
            js_round(
                100
                * (
                    RELEVANCE_WEIGHTS["o2"] * o2
                    + RELEVANCE_WEIGHTS["gravity"] * gravity
                    + RELEVANCE_WEIGHTS["scale"] * scale
                    + RELEVANCE_WEIGHTS["dataQuality"] * quality
                    + RELEVANCE_WEIGHTS["theme"] * theme
                )
            )
        )
    return ScoreDetails(
        total=total,
        o2_overlap=o2,
        gravity_match=gravity,
        scale_match=scale,
        data_quality_factor=quality,
        theme_fraction=theme,
        theme_weight=theme_weight,
    )


def rank(
    records: list[InvestigationRecord],
    environment: EnvironmentRecord,
    weights: dict[str, int],
) -> list[tuple[InvestigationRecord, ScoreDetails]]:
    scored = [(record, score(record, environment, weights)) for record in records]
    scored.sort(
        key=lambda item: (
            -item[1].total,
            -item[1].data_quality_factor,
            -item[1].scale_match,
            item[0].name,
        )
    )
    return scored


def to_score_items(
    ranked: list[tuple[InvestigationRecord, ScoreDetails]],
) -> list[ScoreItem]:
    return [
        ScoreItem(
            investigation_id=record.id,
            name=record.name,
            score=details.total,
            o2_overlap=details.o2_overlap,
            gravity_match=details.gravity_match,
            scale_match=details.scale_match,
            data_quality_factor=details.data_quality_factor,
            theme_fraction=details.theme_fraction,
            theme_weight=details.theme_weight,
            gravity=record.gravity,
            scale=record.scale,
            data_quality=record.data_quality,
            o2=record.o2,
            theme=record.theme,
            phase=record.phase,
            **citation_context(record),
        )
        for record, details in ranked
    ]
