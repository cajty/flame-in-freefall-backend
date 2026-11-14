from __future__ import annotations

from core.data.reference import PSI_ID_RE
from core.data.registry import METRIC_NAMES
from core.errors import ToolFault
from models import Envelope, PsiRecordData, PsiRecordInput
from tools.common import provenance
from tools.context import AppContext


def get_psi_record(ctx: AppContext, request: PsiRecordInput) -> Envelope[PsiRecordData]:
    psi_id = request.id.strip()
    if not PSI_ID_RE.match(psi_id):
        raise ToolFault("INVALID_QUERY", "PSI ID must look like PSI-25.")

    investigations = []
    records = []
    source_files: list[str] = []
    for investigation_id, psi_ids in ctx.reference.psi_ids.items():
        if psi_id not in psi_ids:
            continue
        record = ctx.catalog.get(investigation_id)
        records.append(record)
        investigations.append(
            {
                "id": investigation_id,
                "name": record.name,
                "sourceFiles": list(record.source_files),
            }
        )
        source_files.extend(record.source_files)
    if not investigations:
        raise ToolFault("PSI_NOT_FOUND", f"Unknown PSI record: {psi_id}", status_code=404)

    url = ctx.reference.psi_url_template.format(id=psi_id)
    return Envelope(
        data=PsiRecordData(
            psi_id=psi_id,
            ids=[psi_id],
            urls=[url],
            investigations=investigations,
            source_files=source_files,
        ),
        provenance=provenance(records, list(METRIC_NAMES)),
        warnings=[
            "External NASA PSI metadata is not configured; this is the local reference URL only."
        ],
    )
