"""Forms, Clinical Order Sets, and CSV Administration router (HD-30)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, DbSession, require_roles
from app.forms import service
from app.common.clinical_write import ClinicalWriteKey, clinical_write
from app.common.patient_scope import require_patient_access, require_visit_scope
from app.forms.schemas import (
    ApplyOrderSetRequest,
    ApplyOrderSetResult,
    ClinicalOrderSetCreate,
    ClinicalOrderSetOut,
    CsvImportRequest,
    CsvImportResult,
    CsvValidateRequest,
    CsvValidationResult,
    FormDefinitionCreate,
    FormDefinitionOut,
    FormSubmissionCreate,
    FormSubmissionOut,
)

router = APIRouter(tags=["forms"])


# ---------------- 1. CONFIGURABLE FORMS ----------------

@router.get(
    "/forms/definitions",
    response_model=list[FormDefinitionOut],
    dependencies=[Depends(require_roles("doctor", "nurse", "admin", "receptionist"))],
)
async def list_form_definitions(
    db: DbSession,
    current_user: CurrentDbUser,
    status_filter: str | None = Query(default="published", alias="status"),
) -> list[FormDefinitionOut]:
    """List active published form definitions."""
    await service.ensure_defaults_seeded(db, current_user.id)
    defs = await service.list_form_definitions(db, status_filter=status_filter)
    return [FormDefinitionOut.model_validate(d) for d in defs]


@router.post(
    "/forms/definitions",
    response_model=FormDefinitionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("admin"))],
)
async def create_form_definition(
    payload: FormDefinitionCreate,
    current_user: CurrentDbUser,
    db: DbSession,
    idempotency_key: ClinicalWriteKey,
) -> FormDefinitionOut:
    """Create or publish a new dynamic form definition."""
    return await clinical_write(db, idempotency_key, "POST /forms/definitions", payload,
        current_user, FormDefinitionOut,
        lambda: service.create_form_definition(db, payload, current_user.id))


@router.post(
    "/forms/submissions",
    response_model=FormSubmissionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("doctor", "nurse", "admin"))],
)
async def submit_form(
    payload: FormSubmissionCreate,
    current_user: CurrentDbUser,
    db: DbSession,
    idempotency_key: ClinicalWriteKey,
) -> FormSubmissionOut:
    """Submit responses to a configurable form definition."""
    await require_patient_access(db, payload.patient_id, current_user)
    await require_visit_scope(db, payload.visit_id, payload.patient_id, current_user.facility_id)
    try:
        return await clinical_write(db, idempotency_key, "POST /forms/submissions", payload,
            current_user, FormSubmissionOut,
            lambda: service.create_submission(db, payload, current_user.id))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/forms/patients/{patient_id}",
    response_model=list[FormSubmissionOut],
    dependencies=[Depends(require_roles("doctor", "nurse", "admin", "patient"))],
)
async def list_patient_form_submissions(
    patient_id: uuid.UUID,
    current_user: CurrentDbUser,
    db: DbSession,
) -> list[FormSubmissionOut]:
    """Retrieve historical form submissions for a patient."""
    await require_patient_access(db, patient_id, current_user)
    return await service.list_patient_submissions(db, patient_id)


# ---------------- 2. CLINICAL ORDER SETS ----------------

@router.get(
    "/order-sets",
    response_model=list[ClinicalOrderSetOut],
    dependencies=[Depends(require_roles("doctor", "nurse", "admin"))],
)
async def list_order_sets(
    db: DbSession,
    current_user: CurrentDbUser,
    category: str | None = Query(default=None),
) -> list[ClinicalOrderSetOut]:
    """List standard clinical order sets (e.g., Sepsis, ACS, Pre-op)."""
    await service.ensure_defaults_seeded(db, current_user.id)
    return await service.list_order_sets(db, category=category)


@router.post(
    "/order-sets/{code}/apply",
    response_model=ApplyOrderSetResult,
    dependencies=[Depends(require_roles("doctor", "admin"))],
)
async def apply_order_set(
    code: str,
    payload: ApplyOrderSetRequest,
    current_user: CurrentDbUser,
    db: DbSession,
) -> ApplyOrderSetResult:
    """Clinician confirmation to atomically place all orders in an order set."""
    await require_patient_access(db, payload.patient_id, current_user)
    await require_visit_scope(db, payload.visit_id, payload.patient_id, current_user.facility_id)
    try:
        return await service.apply_order_set(db, code, payload.patient_id, payload.visit_id, current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ---------------- 3. CSV ADMINISTRATION ----------------

@router.post(
    "/admin/csv/validate",
    response_model=CsvValidationResult,
    dependencies=[Depends(require_roles("admin"))],
)
async def validate_admin_csv(
    payload: CsvValidateRequest,
) -> CsvValidationResult:
    """Validate CSV structure and scan for spreadsheet formula injection attempts."""
    return service.validate_csv(payload.csv_content, payload.entity_type)


@router.post(
    "/admin/csv/import",
    response_model=CsvImportResult,
    dependencies=[Depends(require_roles("admin"))],
)
async def import_admin_csv(
    payload: CsvImportRequest,
    current_user: CurrentDbUser,
    db: DbSession,
    idempotency_key: ClinicalWriteKey,
) -> CsvImportResult:
    """Safely import sanitized CSV records for platform entities."""
    try:
        return await clinical_write(db, idempotency_key, "POST /admin/csv/import", payload,
            current_user, CsvImportResult,
            lambda: service.import_csv(payload.csv_content, payload.entity_type, db, current_user.id), status=200)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/admin/csv/export",
    dependencies=[Depends(require_roles("admin"))],
)
async def export_admin_csv(
    db: DbSession,
    entity_type: str = Query(default="vaccines"),
) -> Response:
    """Export platform entity dataset to CSV with formula escaping."""
    if entity_type not in {"vaccines", "order_sets"}:
        raise HTTPException(400, "CSV export is not implemented for this entity")
    csv_text = await service.export_csv(entity_type, db)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{entity_type}_export.csv"'},
    )
