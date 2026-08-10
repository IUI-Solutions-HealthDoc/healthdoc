"""
Service functions for the consent module.

Repo path: backend/app/consent/service.py

Only list_consent_records_for_patient exists here for now — it backs
the /patients/{patient_id}/records route, which exists mainly to prove
log_patient_data_access against a real endpoint rather than ship it as
unused utility code. Consent-grant/withdrawal write-path logic
(granting, revoking, cascade-on-withdrawal) is separate, larger work
not covered by this ticket.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.consent.models import ConsentRecord


async def list_consent_records_for_patient(
    db: AsyncSession, patient_id: uuid.UUID
) -> list[ConsentRecord]:
    result = await db.execute(
        sa.select(ConsentRecord)
        .where(ConsentRecord.patient_id == patient_id)
        .order_by(ConsentRecord.granted_at.desc())
    )
    return list(result.scalars().all())
