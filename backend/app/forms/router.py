"""Forms, Clinical Order Sets, and CSV Administration router (HD-30)."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentDbUser, DbSession, require_roles
from app.forms import service
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
    dependencies=[Depends(require_roles("doctor", "nurse", "admin", "superadmin", "receptionist"))],
)
async def list_form_definitions(
    db: DbSession,
    db_user: CurrentDbUser,
    status_filter: str | None = Query(default="published", alias="status"),
) -> list[FormDefinitionOut]:
    """List active published form definitions."""
    await service.ensure_defaults_seeded(db, db_user.id)
    defs = await service.list_form_definitions(db, status_filter=status_filter)
    return [FormDefinitionOut.model_validate(d) for d in defs]


@router.post(
    "/forms/definitions",
    response_model=FormDefinitionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("admin", "superadmin"))],
)
async def create_form_definition(
    payload: FormDefinitionCreate,
    db_user: CurrentDbUser,
    db: DbSession,
) -> FormDefinitionOut:
    """Create or publish a new dynamic form definition."""
    return await service.create_form_definition(db, payload, db_user.id)


@router.post(
    "/forms/submissions",
    response_model=FormSubmissionOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("doctor", "nurse", "admin", "superadmin"))],
)
async def submit_form(
    payload: FormSubmissionCreate,
    db_user: CurrentDbUser,
    db: DbSession,
) -> FormSubmissionOut:
    """Submit responses to a configurable form definition."""
    try:
        return await service.create_submission(db, payload, db_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/forms/patients/{patient_id}",
    response_model=list[FormSubmissionOut],
    dependencies=[Depends(require_roles("doctor", "nurse", "admin", "superadmin", "patient"))],
)
async def list_patient_form_submissions(
    patient_id: uuid.UUID,
    db: DbSession,
) -> list[FormSubmissionOut]:
    """Retrieve historical form submissions for a patient."""
    return await service.list_patient_submissions(db, patient_id)


# ---------------- 2. CLINICAL ORDER SETS ----------------

@router.get(
    "/order-sets",
    response_model=list[ClinicalOrderSetOut],
    dependencies=[Depends(require_roles("doctor", "nurse", "admin", "superadmin"))],
)
async def list_order_sets(
    db: DbSession,
    db_user: CurrentDbUser,
    category: str | None = Query(default=None),
) -> list[ClinicalOrderSetOut]:
    """List standard clinical order sets (e.g., Sepsis, ACS, Pre-op)."""
    await service.ensure_defaults_seeded(db, db_user.id)
    return await service.list_order_sets(db, category=category)


@router.post(
    "/order-sets/{code}/apply",
    response_model=ApplyOrderSetResult,
    dependencies=[Depends(require_roles("doctor", "admin", "superadmin"))],
)
async def apply_order_set(
    code: str,
    payload: ApplyOrderSetRequest,
    db_user: CurrentDbUser,
    db: DbSession,
) -> ApplyOrderSetResult:
    """Clinician confirmation to atomically place all orders in an order set."""
    try:
        return await service.apply_order_set(db, code, payload.patient_id, payload.visit_id, db_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ---------------- 3. CSV ADMINISTRATION ----------------

@router.post(
    "/admin/csv/validate",
    response_model=CsvValidationResult,
    dependencies=[Depends(require_roles("admin", "superadmin"))],
)
async def validate_admin_csv(
    payload: CsvValidateRequest,
) -> CsvValidationResult:
    """Validate CSV structure and scan for spreadsheet formula injection attempts."""
    return service.validate_csv(payload.csv_content, payload.entity_type)


@router.post(
    "/admin/csv/import",
    response_model=CsvImportResult,
    dependencies=[Depends(require_roles("admin", "superadmin"))],
)
async def import_admin_csv(
    payload: CsvImportRequest,
    db_user: CurrentDbUser,
    db: DbSession,
) -> CsvImportResult:
    """Safely import sanitized CSV records for platform entities."""
    try:
        return await service.import_csv(payload.csv_content, payload.entity_type, db, db_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get(
    "/admin/csv/export",
    dependencies=[Depends(require_roles("admin", "superadmin"))],
)
async def export_admin_csv(
    db: DbSession,
    entity_type: str = Query(default="vaccines"),
) -> Response:
    """Export platform entity dataset to CSV with formula escaping."""
    csv_text = await service.export_csv(entity_type, db)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{entity_type}_export.csv"'},
    )
