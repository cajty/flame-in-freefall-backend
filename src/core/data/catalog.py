from __future__ import annotations

from dataclasses import dataclass, field

from core.data.reference import ReferenceData
from core.data.registry import ADAPTERS, CANONICAL_ORDER
from core.errors import ToolFault
from models import (
    GapItem,
    InvestigationMeta,
    InvestigationRecord,
    PsiLinks,
    SummaryRecord,
)


@dataclass(frozen=True)
class Catalog:
    reference: ReferenceData
    summaries: dict[str, SummaryRecord]
    generated_at: str

    def __post_init__(self) -> None:
        missing = set(CANONICAL_ORDER) - set(self.summaries)
        if missing:
            raise ValueError(f"missing generated summaries: {sorted(missing)}")
        records: dict[str, InvestigationRecord] = {}
        for investigation_id in CANONICAL_ORDER:
            meta: InvestigationMeta = self.reference.by_id[investigation_id]
            summary = self.summaries[investigation_id]
            derived = summary.o2 is not None and not summary.o2.partial
            o2 = [summary.o2.min, summary.o2.max] if derived else list(meta.o2)
            records[investigation_id] = InvestigationRecord(
                id=meta.id,
                name=meta.name,
                full=meta.full,
                theme=meta.theme,
                phase=meta.phase,
                gravity=meta.gravity,
                scale=meta.scale,
                data_quality=meta.data_quality,
                o2=o2,
                o2known=True if derived else meta.o2known,
                o2src=meta.o2src,
                hw=meta.hw,
                obj=meta.obj,
                fuel=meta.fuel,
                cond=meta.cond,
                meas=meta.meas,
                data=summary,
                psi=PsiLinks(
                    ids=list(self.reference.psi_ids[investigation_id]),
                    urls=[
                        self.reference.psi_url_template.format(id=psi_id)
                        for psi_id in self.reference.psi_ids[investigation_id]
                    ],
                ),
                source_files=list(summary.files),
                planned_only=ADAPTERS[investigation_id].planned_only,
            )
        object.__setattr__(self, "records", records)

    records: dict[str, InvestigationRecord] = field(init=False)

    def all(self) -> tuple[InvestigationRecord, ...]:
        return tuple(self.records[investigation_id] for investigation_id in CANONICAL_ORDER)

    def get(self, investigation_id: str) -> InvestigationRecord:
        record = self.records.get(investigation_id)
        if record is None:
            raise ToolFault(
                "INVESTIGATION_NOT_FOUND",
                f"Unknown investigation: {investigation_id}",
                status_code=404,
            )
        return record

    def environment(self, environment_id: str):
        for environment in self.reference.environments:
            if environment.id == environment_id:
                return environment
        raise ToolFault(
            "ENVIRONMENT_NOT_FOUND",
            f"Unknown environment: {environment_id}",
            status_code=404,
        )

    def coverage(self) -> dict[str, dict[str, bool]]:
        result: dict[str, dict[str, bool]] = {}
        for record in self.all():
            summary = record.data
            assert summary is not None
            result[record.id] = {
                "o2_pct": summary.o2 is not None,
                "pressure_atm": summary.pressure is not None,
                "airflow_cm_s": summary.airflow is not None,
                "test_date": summary.date is not None,
            }
        return result

    def gaps(self, ids: list[str] | None = None) -> list[GapItem]:
        records = self.all() if ids is None else tuple(self.get(item) for item in ids)
        items: list[GapItem] = []
        for record in records:
            summary = record.data
            assert summary is not None
            missing: list[str] = []
            partial: list[str] = []
            if summary.o2 is None:
                missing.append("o2")
            elif summary.o2.partial:
                partial.append("o2")
            if summary.pressure is None:
                missing.append("pressure")
            if summary.airflow is None:
                missing.append("airflow")
            items.append(
                GapItem(
                    investigation_id=record.id,
                    missing=missing,
                    partial=partial,
                    planned_only=record.planned_only,
                    source_files=list(record.source_files),
                    psi_ids=list(record.psi.ids),
                    psi_urls=list(record.psi.urls),
                )
            )
        return items


class ScopedCatalog:
    """Catalog view limited to the investigations selected by the request."""

    def __init__(self, catalog: Catalog, allowed_ids: set[str]) -> None:
        self._catalog = catalog
        self._allowed = frozenset(allowed_ids)

    @property
    def allowed_investigation_ids(self) -> frozenset[str]:
        return self._allowed

    @property
    def generated_at(self) -> str:
        return self._catalog.generated_at

    @property
    def summaries(self):
        return {
            investigation_id: summary
            for investigation_id, summary in self._catalog.summaries.items()
            if investigation_id in self._allowed
        }

    def all(self) -> tuple[InvestigationRecord, ...]:
        return tuple(
            record for record in self._catalog.all() if record.id in self._allowed
        )

    def get(self, investigation_id: str) -> InvestigationRecord:
        if investigation_id not in self._allowed:
            allowed = ", ".join(sorted(self._allowed))
            raise ToolFault(
                "OUT_OF_SCOPE",
                (
                    f"{investigation_id} is outside the PSI scope supplied with the request. "
                    f"Allowed investigations: {allowed}."
                ),
                status_code=400,
            )
        return self._catalog.get(investigation_id)

    def environment(self, environment_id: str):
        return self._catalog.environment(environment_id)

    def coverage(self) -> dict[str, dict[str, bool]]:
        return {
            investigation_id: coverage
            for investigation_id, coverage in self._catalog.coverage().items()
            if investigation_id in self._allowed
        }

    def gaps(self, ids: list[str] | None = None) -> list[GapItem]:
        selected = [record.id for record in self.all()] if ids is None else ids
        for investigation_id in selected:
            self.get(investigation_id)
        return self._catalog.gaps(selected)
