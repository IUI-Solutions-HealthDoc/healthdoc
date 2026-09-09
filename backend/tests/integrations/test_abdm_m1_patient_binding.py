"""Do not spend an OTP before checking its staff/patient binding."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.integrations.abdm.identity import otp_session, router, service
from app.integrations.abdm.identity.otp_session import OtpPurpose
from app.patients.models import Patient
from tests.integrations.test_abdm_m1_identity import fake_redis as redis_fixture

fake_redis = redis_fixture


@pytest.mark.parametrize("flow", ["enrol", "login"])
@pytest.mark.parametrize(
    "defect", ["staff", "facility", "purpose", "deleted", "merged", "no_patient"]
)
async def test_invalid_session_never_reaches_gateway(
    db, seed, opd_visit, monkeypatch, flow, defect
):
    dept, _, doctor = seed
    visit = await opd_visit()
    patient = await db.get(Patient, visit.patient_id)
    purpose = OtpPurpose.ENROL_BY_AADHAAR if flow == "enrol" else OtpPurpose.LOGIN_BY_ABHA
    session = await otp_session.start(
        abdm_txn_id="synthetic-transaction",
        purpose=OtpPurpose.VERIFY_MOBILE if defect == "purpose" else purpose,
        facility_id=str(uuid.uuid4()) if defect == "facility" else str(dept.facility_id),
        started_by=str(uuid.uuid4()) if defect == "staff" else str(doctor.id),
        patient_id=None if defect == "no_patient" else str(patient.id),
    )
    if defect == "deleted":
        patient.deleted_at = datetime.now(UTC)
    elif defect == "merged":
        patient.merged_into_patient_id = uuid.uuid4()
    verify = AsyncMock()
    monkeypatch.setattr(
        service, "enrol_by_aadhaar_otp" if flow == "enrol" else "verify_login_otp", verify
    )
    handler = router.enrol_verify_otp if flow == "enrol" else router.login_verify_otp
    with pytest.raises(HTTPException) as caught:
        await handler(
            router.OtpVerifyRequest(session_id=session.session_id, otp="123456"),
            SimpleNamespace(id=doctor.id, facility_id=dept.facility_id),
            db,
        )
    assert caught.value.status_code == 404
    verify.assert_not_awaited()


@pytest.mark.parametrize("commit_fails", [True, False])
async def test_identity_is_committed_before_consuming_otp(
    db, seed, opd_visit, monkeypatch, commit_fails
):
    dept, _, doctor = seed
    visit = await opd_visit()
    session = await otp_session.start(
        abdm_txn_id="synthetic-transaction",
        purpose=OtpPurpose.ENROL_BY_AADHAAR,
        facility_id=str(dept.facility_id),
        started_by=str(doctor.id),
        patient_id=str(visit.patient_id),
    )
    events = []
    original_commit = db.commit

    async def commit():
        events.append("commit")
        if commit_fails:
            raise RuntimeError("Synthetic commit failure")
        await original_commit()

    async def finish(ident):
        assert ident == session.session_id
        events.append("consume")

    monkeypatch.setattr(db, "commit", commit)
    monkeypatch.setattr(otp_session, "finish", finish)
    kwargs = dict(
        db=db,
        current_db_user=SimpleNamespace(id=doctor.id, facility_id=dept.facility_id),
        session_id=session.session_id,
        purpose=OtpPurpose.ENROL_BY_AADHAAR,
        issued=service.AbhaIssued(
            "12345678901234",
            "test@sbx",
            "synthetic-account-token",
            "Synthetic Patient",
            "other",
            "1990-01-01",
        ),
    )
    if commit_fails:
        with pytest.raises(RuntimeError, match="Synthetic commit failure"):
            await router._persist_verified_identity(**kwargs)
        assert events == ["commit"]
    else:
        assert await router._persist_verified_identity(**kwargs) == visit.patient_id
        assert events == ["commit", "consume"]
