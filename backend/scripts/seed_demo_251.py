"""Seed repeatable receptionist, doctor, and nurse demo journeys for #251.

Prerequisite: ``scripts/dev_setup.sh`` (or ``seed_dev_data.py``) has created
the three matching application users. This script is deliberately rejected in
non-demo environments and is safe to rerun without duplicating clinical rows.

Run from the repository root with::

    docker compose -f infra/docker-compose.yml --env-file .env exec -T backend \
        python -m scripts.seed_demo_251
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admissions.models import Admission, Bed, Ward
from app.audit.service import write_audit_log
from app.common.db import SessionLocal
from app.common.enums import (
    AdmissionStatus,
    BedStatus,
    IdentityPath,
    IdentityStatus,
    PatientStatus,
    QueuePriority,
    QueueTokenStatus,
    Sex,
    VisitStatus,
    VisitType,
)
from app.consent.models import ConsentPurpose, ConsentRecord
from app.departments.models import Department, Room
from app.dpdp import models as _dpdp_models  # noqa: F401 -- registers consent_managers FK
from app.nursing.models import Vitals
from app.opd.models import Visit
from app.patients.models import Patient
from app.queue.models import Queue, QueueToken
from app.users.models import User

FACILITY_ID = uuid.UUID("00000000-0000-0000-0000-000000000101")
PATIENT_ID = uuid.uuid5(uuid.NAMESPACE_URL, "healthdoc:demo-251-patient")
DEPARTMENT_ID = uuid.uuid5(uuid.NAMESPACE_URL, "healthdoc:demo-251-department")
ROOM_ID = uuid.uuid5(uuid.NAMESPACE_URL, "healthdoc:demo-251-room")
QUEUE_ID = uuid.uuid5(uuid.NAMESPACE_URL, "healthdoc:demo-251-queue")
TOKEN_ID = uuid.uuid5(uuid.NAMESPACE_URL, "healthdoc:demo-251-token")
OPD_VISIT_ID = uuid.uuid5(uuid.NAMESPACE_URL, "healthdoc:demo-251-opd-visit")
IPD_VISIT_ID = uuid.uuid5(uuid.NAMESPACE_URL, "healthdoc:demo-251-ipd-visit")
WARD_ID = uuid.uuid5(uuid.NAMESPACE_URL, "healthdoc:demo-251-ward")
BED_ID = uuid.uuid5(uuid.NAMESPACE_URL, "healthdoc:demo-251-bed")
ADMISSION_ID = uuid.uuid5(uuid.NAMESPACE_URL, "healthdoc:demo-251-admission")
VITALS_ID = uuid.uuid5(uuid.NAMESPACE_URL, "healthdoc:demo-251-vitals")
CONSENT_PURPOSE_ID = uuid.uuid5(uuid.NAMESPACE_URL, "healthdoc:demo-251-consent-purpose")
CONSENT_ID = uuid.uuid5(uuid.NAMESPACE_URL, "healthdoc:demo-251-consent")

_ALLOWED_ENVIRONMENTS = {"dev", "demo", "local", "test"}
ModelT = TypeVar("ModelT")


def _refuse_outside_demo() -> None:
    from app.common.config import get_settings

    environment = (get_settings().environment or "").lower()
    if environment not in _ALLOWED_ENVIRONMENTS:
        raise SystemExit(
            f"Refusing to seed fabricated clinical data in environment {environment!r}; "
            f"allowed values are {sorted(_ALLOWED_ENVIRONMENTS)}"
        )


async def _upsert(
    session: AsyncSession,
    model: type[ModelT],
    row_id: uuid.UUID,
    **values: Any,
) -> ModelT:
    row = await session.get(model, row_id)
    if row is None:
        row = model(id=row_id, **values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    await session.flush()
    return row


async def _insert_consent_if_missing(
    session: AsyncSession,
    **values: Any,
) -> ConsentRecord:
    """Insert the deterministic grant once; never rewrite its frozen evidence.

    The database deliberately permits only consent status transitions after
    insert. Treating this append-only evidence like the mutable demo rows makes
    a second seed run violate the freeze trigger even when the values happen to
    describe the same grant.
    """
    row = await session.get(ConsentRecord, CONSENT_ID)
    if row is not None:
        return row
    row = ConsentRecord(id=CONSENT_ID, **values)
    session.add(row)
    await session.flush()
    return row


async def seed() -> None:
    _refuse_outside_demo()
    now = datetime.now(UTC)
    async with SessionLocal() as session, session.begin():
        users = {
            user.username: user
            for user in (
                await session.execute(
                    select(User).where(
                        User.username.in_(["dev.receptionist", "dev.doctor", "dev.nurse"])
                    )
                )
            ).scalars()
        }
        missing = sorted({"dev.receptionist", "dev.doctor", "dev.nurse"} - users.keys())
        if missing:
            raise RuntimeError(
                f"Missing development users {missing}; run scripts/dev_setup.sh first"
            )
        receptionist, doctor, nurse = (
            users["dev.receptionist"],
            users["dev.doctor"],
            users["dev.nurse"],
        )

        await _upsert(
            session, Department, DEPARTMENT_ID,
            name="General Medicine Demo", code="DEMO251", facility_id=FACILITY_ID, is_active=True,
        )
        await _upsert(
            session, Room, ROOM_ID,
            department_id=DEPARTMENT_ID, room_number="Demo 251", is_active=True,
        )
        await _upsert(
            session, Patient, PATIENT_ID,
            uhid="DEMO251", thid=None, full_name="Demo Patient 251",
            sex=Sex.FEMALE.value, age_years=45, mobile="9000000251",
            identity_path=IdentityPath.DEMOGRAPHICS_ONLY.value,
            identity_status=IdentityStatus.VERIFIED.value,
            status=PatientStatus.ACTIVE.value, facility_id=FACILITY_ID,
            created_by=receptionist.id, updated_by=receptionist.id, deleted_at=None,
        )
        await _upsert(
            session, Visit, OPD_VISIT_ID,
            visit_number="DEMO251-OPD", patient_id=PATIENT_ID, facility_id=FACILITY_ID,
            department_id=DEPARTMENT_ID, visit_type=VisitType.OPD.value,
            status=VisitStatus.REGISTERED.value, visit_date=now,
            created_by=receptionist.id, updated_by=receptionist.id,
        )
        await _upsert(
            session, Queue, QUEUE_ID,
            facility_id=FACILITY_ID, department_id=DEPARTMENT_ID,
            doctor_user_id=doctor.id, room_id=ROOM_ID, display_label="Demo OPD",
            service_date=now.date(), is_open=True, now_serving_token_id=None,
        )
        await _upsert(
            session, QueueToken, TOKEN_ID,
            facility_id=FACILITY_ID, queue_id=QUEUE_ID, visit_id=OPD_VISIT_ID,
            sequence=1, token_display="DEMO-001",
            initial_priority=QueuePriority.NORMAL.value,
            priority=QueuePriority.NORMAL.value, priority_rank=6,
            status=QueueTokenStatus.WAITING.value, called_at=None, completed_at=None,
        )
        consent_purpose = (
            await session.execute(
                select(ConsentPurpose).where(ConsentPurpose.purpose_code == "clinical_review")
            )
        ).scalar_one_or_none()
        if consent_purpose is None:
            consent_purpose = await _upsert(
                session, ConsentPurpose, CONSENT_PURPOSE_ID,
                purpose_code="clinical_review", description="Direct clinical care demo consent",
                default_expiry_days=30, requires_explicit_consent=True, is_active=True,
            )
        await _insert_consent_if_missing(
            session,
            patient_id=PATIENT_ID, visit_id=OPD_VISIT_ID, purpose_id=consent_purpose.id,
            granted_by_type="patient", granted_by_user_id=None, channel="written",
            granted_at=now, expires_at=now + timedelta(days=30),
            scope=["clinical_record"], status="granted", status_changed_at=now,
            created_by=receptionist.id, updated_by=receptionist.id,
        )
        await _upsert(
            session, Visit, IPD_VISIT_ID,
            visit_number="DEMO251-IPD", patient_id=PATIENT_ID, facility_id=FACILITY_ID,
            department_id=DEPARTMENT_ID, visit_type=VisitType.IPD.value,
            status="completed", visit_date=now,
            created_by=doctor.id, updated_by=doctor.id,
        )
        await _upsert(
            session, Ward, WARD_ID,
            name="Demo Ward", department_id=DEPARTMENT_ID,
            facility_id=FACILITY_ID, is_active=True,
        )
        await _upsert(
            session, Bed, BED_ID,
            ward_id=WARD_ID, bed_number="D-01", status=BedStatus.OCCUPIED.value,
        )
        await _upsert(
            session, Admission, ADMISSION_ID,
            visit_id=IPD_VISIT_ID, patient_id=PATIENT_ID, ward_id=WARD_ID, bed_id=BED_ID,
            admitted_at=now, reason="Deterministic nurse demo admission",
            status=AdmissionStatus.ADMITTED.value, created_by=nurse.id, updated_by=nurse.id,
        )
        await _upsert(
            session, Vitals, VITALS_ID,
            admission_id=ADMISSION_ID, encounter_id=None, patient_id=PATIENT_ID,
            measured_at=now, temp_c=37.1, pulse_bpm=78, resp_rate=16,
            bp_systolic=118, bp_diastolic=76, spo2_pct=98, pain_score=1,
            created_by=nurse.id, updated_by=nurse.id,
        )
        await write_audit_log(
            session, facility_id=FACILITY_ID, action="seed", resource_type="demo_dataset",
            resource_id=PATIENT_ID, patient_id=PATIENT_ID, visit_id=OPD_VISIT_ID,
            user_id=receptionist.id, role="receptionist",
            new_value={"roles": ["receptionist", "doctor", "nurse"]},
            reason="Deterministic non-production demo seed for issue #251",
        )

    print("Seeded receptionist search, doctor queue, nurse admission, and vitals for #251.")


if __name__ == "__main__":
    asyncio.run(seed())
