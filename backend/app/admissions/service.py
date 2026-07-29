import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.admissions.models import Admission, Discharge, Bed, PatientMovementLog
from app.users.models import User
from app.audit import service as audit_service


async def _resolve_user(db: AsyncSession, keycloak_sub: str) -> User:
    """JWT sub -> users row. No shared helper exists yet in this codebase
    (confirmed: grep for AuthUser/keycloak_sub found no lookup utility) —
    each caller resolves it inline, same pattern as app/common/modules.py.
    """
    result = await db.execute(select(User).where(User.keycloak_sub == keycloak_sub))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not provisioned")
    return user


async def admit_patient(db: AsyncSession, data, auth_user) -> Admission:
    user = await _resolve_user(db, auth_user.sub)

    bed = await db.get(Bed, data.bed_id)
    if bed is None or bed.status != "vacant":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Bed not available")

    admission = Admission(
        visit_id=data.visit_id,
        patient_id=data.patient_id,
        ward_id=data.ward_id,
        bed_id=data.bed_id,
        admitted_at=data.admitted_at,
        reason=data.reason,
        status="admitted",
        created_by=user.id,
    )
    bed.status = "occupied"

    db.add(admission)
    db.add(bed)
    await db.flush()
    await db.refresh(admission)

    await audit_service.write_audit_log(
        db,
        facility_id=user.facility_id,
        user_id=user.id,
        role=",".join(auth_user.roles) if auth_user.roles else None,
        action="admission.create",
        resource_type="admission",
        resource_id=admission.id,
        patient_id=admission.patient_id,
        visit_id=admission.visit_id,
        new_value={
            "ward_id": str(admission.ward_id),
            "bed_id": str(admission.bed_id),
            "status": admission.status,
        },
    )

    return admission


async def transfer_patient(db: AsyncSession, admission_id: uuid.UUID, data, auth_user) -> PatientMovementLog:
    user = await _resolve_user(db, auth_user.sub)

    admission = await db.get(Admission, admission_id)
    if admission is None or admission.status != "admitted":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Admission not active")

    to_bed = await db.get(Bed, data.to_bed_id)
    if to_bed is None or to_bed.status != "vacant":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Target bed not available")

    old_ward_id, old_bed_id = admission.ward_id, admission.bed_id
    old_bed = await db.get(Bed, old_bed_id)

    movement = PatientMovementLog(
        admission_id=admission.id,
        from_ward_id=old_ward_id,
        from_bed_id=old_bed_id,
        to_ward_id=data.to_ward_id,
        to_bed_id=data.to_bed_id,
        moved_at=datetime.now(timezone.utc).replace(tzinfo=None),
        reason=data.reason,
        moved_by=user.id,
    )

    admission.ward_id = data.to_ward_id
    admission.bed_id = data.to_bed_id
    old_bed.status = "vacant"
    to_bed.status = "occupied"

    db.add_all([movement, admission, old_bed, to_bed])
    await db.flush()
    await db.refresh(movement)

    await audit_service.write_audit_log(
        db,
        facility_id=user.facility_id,
        user_id=user.id,
        role=",".join(auth_user.roles) if auth_user.roles else None,
        action="admission.transfer",
        resource_type="admission",
        resource_id=admission.id,
        patient_id=admission.patient_id,
        visit_id=admission.visit_id,
        old_value={"ward_id": str(old_ward_id), "bed_id": str(old_bed_id)},
        new_value={"ward_id": str(data.to_ward_id), "bed_id": str(data.to_bed_id)},
    )

    return movement


async def discharge_patient(db: AsyncSession, admission_id: uuid.UUID, data, auth_user) -> Discharge:
    user = await _resolve_user(db, auth_user.sub)

    admission = await db.get(Admission, admission_id)
    if admission is None or admission.status != "admitted":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Admission not active")

    # Per schema doc §3-0015: discharge is never hard-blocked for
    # emergency/DAMA/deceased cases, even if billing settlement is incomplete.

    discharge = Discharge(
        admission_id=admission.id,
        discharged_at=datetime.now(timezone.utc).replace(tzinfo=None),
        discharge_type=data.discharge_type,
        discharge_summary=data.discharge_summary,
        follow_up_date=data.follow_up_date,
        created_by=user.id,
    )
    admission.status = "discharged"

    bed = await db.get(Bed, admission.bed_id)
    if bed:
        bed.status = "vacant"
        db.add(bed)

    db.add_all([discharge, admission])
    await db.flush()
    await db.refresh(discharge)

    await audit_service.write_audit_log(
        db,
        facility_id=user.facility_id,
        user_id=user.id,
        role=",".join(auth_user.roles) if auth_user.roles else None,
        action="admission.discharge",
        resource_type="admission",
        resource_id=admission.id,
        patient_id=admission.patient_id,
        visit_id=admission.visit_id,
        new_value={
            "discharge_type": discharge.discharge_type,
            "discharged_at": discharge.discharged_at.isoformat(),
        },
    )
    # TODO(fhir/notifications): app/fhir and app/notifications don't exist
    # yet either — confirm with B4/B7 before wiring these in.

    return discharge