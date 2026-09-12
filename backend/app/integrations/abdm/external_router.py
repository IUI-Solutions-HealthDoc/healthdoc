"""Official ABDM v3 callbacks mounted at their exact public paths.

Internal staff APIs stay under ``/api/v1/abdm`` and use HealthDoc's response
envelope. These routes are the wire contract ABDM calls, so their paths,
camelCase bodies and empty 202 responses follow the NHA reference wrapper.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.config import get_settings
from app.common.db import get_db
from app.integrations.abdm import callback_replies
from app.integrations.abdm.callback_auth import (
    GatewayCallback,
    hip_gateway_callback,
    hip_link_gateway_callback,
    hiu_gateway_callback,
    profile_gateway_callback,
)
from app.integrations.abdm.client import AbdmError
from app.integrations.abdm.contracts_v3 import (
    ConsentOnFetchCallback,
    ConsentOnInitCallback,
    ConsentOnStatusCallback,
    DiscoverCallback,
    GenericCallback,
    HealthInformationPush,
    HipConsentCallback,
    HipHealthInformationCallback,
    HiuConsentNotifyCallback,
    HiuHealthInformationOnRequestCallback,
    LinkConfirmCallback,
    LinkInitCallback,
    LinkTokenCallback,
    ProfileShareCallback,
    raw_dict,
)
from app.integrations.abdm.hip import gateway as hip_gateway
from app.integrations.abdm.hip import link_otp
from app.integrations.abdm.hip import service as hip_service
from app.integrations.abdm.hip.documents import DocumentUnavailable, resolve_context_document
from app.integrations.abdm.hip.models import (
    AbdmCareContext,
    AbdmCareContextLink,
    AbdmHipConsentArtefact,
    AbdmHipHealthInformationRequest,
)
from app.integrations.abdm.hiu import records as hiu_records
from app.integrations.abdm.hiu import service as hiu_service
from app.integrations.abdm.hiu.models import (
    AbdmConsentRequest,
    AbdmHiuConsentArtefact,
    AbdmHiuHealthInformationRequest,
    AbdmReceivedBundle,
)
from app.integrations.abdm.jobs import AbdmJob
from app.integrations.abdm.jobs import job_id as durable_job_id
from app.patients import service as patient_service
from app.patients.models import Patient
from app.users.models import Facility, User

log = logging.getLogger("healthdoc.abdm.callbacks")
router = APIRouter(tags=["abdm-v3-callbacks"], include_in_schema=False)
_PLACEHOLDER = "change-me"
DbSession = Annotated[AsyncSession, Depends(get_db)]
HipCallback = Annotated[GatewayCallback, Depends(hip_gateway_callback)]
HipLinkCallback = Annotated[GatewayCallback, Depends(hip_link_gateway_callback)]
HiuCallback = Annotated[GatewayCallback, Depends(hiu_gateway_callback)]
ProfileCallback = Annotated[GatewayCallback, Depends(profile_gateway_callback)]


def _accepted() -> Response:
    return Response(status_code=202)


async def _facility_id(db: AsyncSession) -> uuid.UUID:
    hfr_id = get_settings().abdm_hfr_facility_id
    if not hfr_id or hfr_id == _PLACEHOLDER:
        raise HTTPException(
            503,
            {
                "code": "abdm_hfr_not_configured",
                "message": "ABDM_HFR_FACILITY_ID is not configured",
            },
        )
    facility = (
        await db.execute(select(Facility).where(Facility.hfr_facility_id == hfr_id))
    ).scalar_one_or_none()
    if facility is None:
        raise HTTPException(
            503,
            {
                "code": "abdm_hfr_not_seeded",
                "message": "No HealthDoc facility matches ABDM_HFR_FACILITY_ID",
            },
        )
    return facility.id


async def _patient_by_address(
    db: AsyncSession, *, facility_id: uuid.UUID, abha_address: str
) -> Patient | None:
    return (
        await db.execute(
            select(Patient).where(
                Patient.facility_id == facility_id,
                Patient.abha_address == abha_address,
                Patient.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()


async def _abdm_service_user(db: AsyncSession, facility: Facility) -> User:
    """Explicit non-human actor for records created by scan-and-share."""
    subject = f"service:abdm:{facility.id}"
    user = (await db.execute(select(User).where(User.keycloak_sub == subject))).scalar_one_or_none()
    if user is not None:
        return user
    user = User(
        keycloak_sub=subject,
        username=f"abdm.integration.{facility.code}".lower(),
        full_name="ABDM Profile Share Integration",
        designation="Service account",
        facility_id=facility.id,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _contexts(
    db: AsyncSession,
    *,
    facility_id: uuid.UUID,
    patient_id: uuid.UUID,
    references: set[str] | None = None,
) -> list[AbdmCareContext]:
    stmt = select(AbdmCareContext).where(
        AbdmCareContext.facility_id == facility_id,
        AbdmCareContext.patient_id == patient_id,
        AbdmCareContext.document_at.is_not(None),
    )
    if references is not None:
        stmt = stmt.where(AbdmCareContext.reference.in_(references))
    contexts = []
    for context in (await db.execute(stmt)).scalars().all():
        try:
            await resolve_context_document(db, context)
        except DocumentUnavailable:
            # Do not advertise a legacy, draft or superseded record that the
            # transfer worker will rightly refuse after the patient links it.
            continue
        contexts.append(context)
    return contexts


def _groups(patient: Patient, contexts: list[AbdmCareContext]) -> list[dict]:
    grouped: dict[str, list[AbdmCareContext]] = defaultdict(list)
    for context in contexts:
        grouped[context.hi_type].append(context)
    patient_reference = patient.uhid or str(patient.id)
    return [
        {
            "referenceNumber": patient_reference,
            "display": patient.full_name,
            "careContexts": [
                {"referenceNumber": row.reference, "display": row.display} for row in rows
            ],
            "hiType": hi_type,
            "count": len(rows),
        }
        for hi_type, rows in sorted(grouped.items())
    ]


async def _outbound(label: str, call) -> None:
    try:
        await call
    except (AbdmError, RuntimeError, ValueError) as exc:
        log.error("ABDM %s response failed (%s)", label, type(exc).__name__)
        raise HTTPException(
            502,
            {
                "code": "abdm_response_failed",
                "message": f"Could not send the {label} response to ABDM",
            },
        ) from exc


# ------------------------------------------------------------------ HIP M2


@router.post("/api/v3/hip/patient/care-context/discover", status_code=202)
async def discover(
    payload: DiscoverCallback,
    callback: HipCallback,
    db: DbSession,
) -> Response:
    if callback.replayed:
        return _accepted()
    facility_id = await _facility_id(db)
    patient = await _patient_by_address(
        db, facility_id=facility_id, abha_address=payload.patient.id
    )
    patient_groups: list[dict] = []
    matched_by: list[str] = []
    if patient is not None:
        patient_groups = _groups(
            patient,
            await _contexts(db, facility_id=facility_id, patient_id=patient.id),
        )
        matched_by = ["ABHA_ADDRESS"]
    await _outbound(
        "discovery",
        hip_gateway.respond_to_discovery_groups(
            transaction_id=payload.transaction_id,
            gateway_request_id=callback.request_id,
            patient_groups=patient_groups,
            matched_by=matched_by,
        ),
    )
    return _accepted()


@router.post("/api/v3/hip/link/care-context/init", status_code=202)
async def link_init(
    payload: LinkInitCallback,
    callback: HipCallback,
    db: DbSession,
) -> Response:
    if callback.replayed:
        return _accepted()
    facility_id = await _facility_id(db)
    patient = await _patient_by_address(
        db, facility_id=facility_id, abha_address=payload.abha_address
    )
    if patient is None:
        raise HTTPException(404, {"code": "patient_not_found", "message": "Patient not found"})
    requested = {
        context.reference_number for group in payload.patient for context in group.care_contexts
    }
    rows = await _contexts(db, facility_id=facility_id, patient_id=patient.id, references=requested)
    if not requested or {row.reference for row in rows} != requested:
        raise HTTPException(
            422,
            {
                "code": "unknown_care_context",
                "message": "One or more requested care contexts do not belong to this patient",
            },
        )

    link = (
        await db.execute(
            select(AbdmCareContextLink).where(
                AbdmCareContextLink.facility_id == facility_id,
                AbdmCareContextLink.transaction_id == payload.transaction_id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        link = AbdmCareContextLink(
            facility_id=facility_id,
            patient_id=patient.id,
            abha_address=payload.abha_address,
            link_ref_number=str(uuid.uuid4()),
            transaction_id=payload.transaction_id,
            gateway_request_id=callback.request_id,
            care_context_references=sorted(requested),
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
        )
        db.add(link)
        await db.flush()
    if not patient.mobile:
        raise HTTPException(
            409,
            {
                "code": "patient_mobile_missing",
                "message": "The patient has no mobile number for mediated linking",
            },
        )
    try:
        communication_hint = await link_otp.issue(
            link_ref_number=link.link_ref_number,
            mobile=patient.mobile,
        )
    except link_otp.LinkOtpUnavailable as exc:
        raise HTTPException(
            503,
            {
                "code": "link_otp_unavailable",
                "message": "The patient linking OTP could not be delivered",
            },
        ) from exc
    expiry = (link.expires_at or datetime.now(UTC) + timedelta(minutes=10)).astimezone(UTC)
    await _outbound(
        "link-init",
        hip_gateway.respond_to_link_init(
            transaction_id=payload.transaction_id,
            gateway_request_id=callback.request_id,
            link_ref_number=link.link_ref_number,
            authentication_type="MEDIATE",
            communication_hint=communication_hint,
            communication_expiry=expiry.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        ),
    )
    return _accepted()


@router.post("/api/v3/hip/link/care-context/confirm", status_code=202)
async def link_confirm(
    payload: LinkConfirmCallback,
    callback: HipCallback,
    db: DbSession,
) -> Response:
    if callback.replayed:
        return _accepted()
    if payload.error is not None or payload.confirmation is None:
        raise HTTPException(
            422, {"code": "link_confirmation_failed", "message": "ABDM did not confirm the link"}
        )
    link = (
        await db.execute(
            select(AbdmCareContextLink).where(
                AbdmCareContextLink.link_ref_number == payload.confirmation.link_ref_number,
                AbdmCareContextLink.status == "pending",
            )
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(404, {"code": "link_not_found", "message": "Link request not found"})
    expiry = link.expires_at
    if expiry and (expiry if expiry.tzinfo else expiry.replace(tzinfo=UTC)) <= datetime.now(UTC):
        link.status = "expired"
        raise HTTPException(410, {"code": "link_expired", "message": "Link request expired"})
    try:
        await link_otp.verify(
            link_ref_number=link.link_ref_number,
            otp=payload.confirmation.token or "",
        )
    except (link_otp.LinkOtpInvalid, link_otp.LinkOtpExpired) as exc:
        if isinstance(exc, link_otp.LinkOtpExpired):
            link.status = "expired"
            link.failure_reason = "link_otp_expired"
        await _outbound(
            "link-confirm refusal",
            hip_gateway.respond_to_link_confirm_error(
                gateway_request_id=callback.request_id,
                code="ABDM-1035",
                message="Incorrect OTP",
            ),
        )
        return _accepted()
    patient = await db.get(Patient, link.patient_id)
    if patient is None:
        raise HTTPException(404, {"code": "patient_not_found", "message": "Patient not found"})
    refs = set(link.care_context_references or [])
    rows = await _contexts(db, facility_id=link.facility_id, patient_id=patient.id, references=refs)
    link.status = "confirmed"
    link.confirmed_at = datetime.now(UTC)
    await db.flush()
    await _outbound(
        "link-confirm",
        hip_gateway.respond_to_link_confirm_groups(
            gateway_request_id=callback.request_id,
            patient_groups=_groups(patient, rows),
        ),
    )
    return _accepted()


@router.post("/api/v3/hip/token/on-generate-token", status_code=202)
async def generated_link_token(
    payload: LinkTokenCallback,
    callback: HipLinkCallback,
    db: DbSession,
) -> Response:
    if callback.replayed:
        return _accepted()
    link = (
        await db.execute(
            select(AbdmCareContextLink)
            .where(
                AbdmCareContextLink.token_request_id == payload.response.request_id,
                AbdmCareContextLink.facility_id == await _facility_id(db),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if link is None:
        raise HTTPException(404, {"code": "link_not_found", "message": "Link request not found"})
    if link.status != "pending":
        return _accepted()
    if payload.error is not None or not payload.link_token:
        link.status = "failed"
        link.failure_reason = payload.error.code if payload.error else "missing_link_token"
        return _accepted()
    from app.integrations.abdm.hip.linking import accept_token

    try:
        await accept_token(db, link, payload.link_token, payload.abha_address)
    except DocumentUnavailable as exc:
        raise HTTPException(422, {"code": "link_token_mismatch", "message": str(exc)}) from exc
    return _accepted()


@router.post("/api/v3/link/on_carecontext", status_code=202)
async def on_care_context(
    payload: GenericCallback,
    callback: HipLinkCallback,
    db: DbSession,
) -> Response:
    if callback.replayed:
        return _accepted()
    if payload.response is None:
        return _accepted()
    link = (
        await db.execute(
            select(AbdmCareContextLink)
            .where(
                AbdmCareContextLink.gateway_request_id == payload.response.request_id,
                AbdmCareContextLink.facility_id == await _facility_id(db),
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if link is not None and link.status == "pending":
        link.status = "failed" if payload.error else "confirmed"
        link.failure_reason = payload.error.code if payload.error else None
        link.confirmed_at = None if payload.error else datetime.now(UTC)
        link.link_token_encrypted = None
        link.token_use_until = None
    return _accepted()


@router.post("/api/v3/links/context/on-notify", status_code=202)
async def context_notify_ack(
    payload: GenericCallback,
    callback: HipCallback,
) -> Response:
    return _accepted()


@router.post("/api/v3/patients/sms/on-notify", status_code=202)
async def deep_link_sms_notify_ack(
    payload: GenericCallback,
    callback: HipCallback,
) -> Response:
    """Receive the gateway acknowledgement for a deep-linking SMS request."""
    return _accepted()


@router.post("/api/v3/hip/patient/share", status_code=202)
async def profile_share(
    payload: ProfileShareCallback,
    callback: ProfileCallback,
    db: DbSession,
) -> Response:
    """Receive ABDM scan-and-share demographics and return a facility token."""
    if callback.replayed:
        return _accepted()
    settings = get_settings()
    if payload.meta_data.hip_id and payload.meta_data.hip_id != settings.abdm_hip_id:
        raise HTTPException(404, {"code": "unknown_service", "message": "Unknown ABDM service"})
    facility_id = await _facility_id(db)
    facility = await db.get(Facility, facility_id)
    if facility is None:
        raise HTTPException(
            503, {"code": "facility_not_found", "message": "Facility is unavailable"}
        )
    shared = payload.profile.patient
    patient = await _patient_by_address(
        db,
        facility_id=facility_id,
        abha_address=shared.abha_address,
    )
    if patient is None:
        actor = await _abdm_service_user(db, facility)
        birth_date = None
        age_years = None
        try:
            if shared.year_of_birth and shared.month_of_birth and shared.day_of_birth:
                birth_date = datetime(
                    int(shared.year_of_birth),
                    int(shared.month_of_birth),
                    int(shared.day_of_birth),
                ).date()
            elif shared.year_of_birth:
                age_years = max(datetime.now(UTC).year - int(shared.year_of_birth), 0)
        except ValueError as exc:
            raise HTTPException(
                422,
                {
                    "code": "invalid_birth_date",
                    "message": "ABDM profile contains an invalid date of birth",
                },
            ) from exc
        if birth_date is None and age_years is None:
            raise HTTPException(
                422,
                {
                    "code": "birth_date_missing",
                    "message": "ABDM profile does not contain a usable birth year",
                },
            )
        abha_number = (
            "".join(character for character in (shared.abha_number or "") if character.isdigit())
            or None
        )
        if abha_number is not None and len(abha_number) != 14:
            raise HTTPException(
                422,
                {
                    "code": "invalid_abha_number",
                    "message": "ABDM profile contains an invalid ABHA number",
                },
            )
        mobile_digits = "".join(
            character for character in (shared.phone_number or "") if character.isdigit()
        )
        if len(mobile_digits) >= 10:
            mobile_digits = mobile_digits[-10:]
        mobile = f"+91{mobile_digits}" if len(mobile_digits) == 10 else None
        sex = {
            "m": "male",
            "f": "female",
            "o": "other",
            "u": "unknown",
        }.get((shared.gender or "unknown").lower(), (shared.gender or "unknown").lower())
        if sex not in {"male", "female", "other", "unknown"}:
            sex = "unknown"
        full_name = shared.name.strip()
        if not full_name:
            raise HTTPException(
                422,
                {
                    "code": "patient_name_missing",
                    "message": "ABDM profile does not contain a patient name",
                },
            )
        if abha_number is not None:
            duplicate_number = (
                await db.execute(
                    select(Patient.id).where(
                        Patient.facility_id == facility_id,
                        Patient.abha_number == abha_number,
                        Patient.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if duplicate_number is not None:
                raise HTTPException(
                    409,
                    {
                        "code": "abha_identity_conflict",
                        "message": "This ABHA number is already linked to another patient",
                    },
                )
        patient = Patient(
            id=uuid.uuid4(),
            uhid=await patient_service.generate_uhid(
                db,
                facility.state_code,
                facility.code,
                facility.timezone,
            ),
            full_name=full_name,
            sex=sex,
            dob=birth_date,
            age_years=age_years,
            mobile=mobile,
            abha_number=abha_number,
            abha_address=shared.abha_address,
            identity_path="abdm",
            identity_status="verified",
            status="active",
            facility_id=facility_id,
            created_by=actor.id,
            updated_by=actor.id,
            abha_linked_at=datetime.now(UTC),
        )
        db.add(patient)
        await db.flush()

    token_number = (patient.uhid or str(patient.id)).split("-")[-2].lstrip("0") or "0"
    await _outbound(
        "profile-share acknowledgement",
        hip_gateway.acknowledge_profile_share(
            gateway_request_id=callback.request_id,
            abha_address=shared.abha_address,
            context=payload.meta_data.context,
            token_number=token_number,
            expiry_seconds=1800,
        ),
    )
    return _accepted()


@router.post("/api/v3/consent/request/hip/notify", status_code=202)
async def hip_consent_notify(
    payload: HipConsentCallback,
    callback: HipCallback,
    db: DbSession,
) -> Response:
    if callback.replayed:
        return _accepted()
    detail = payload.notification.consent_detail
    if detail is None:
        raise HTTPException(
            422, {"code": "consent_detail_missing", "message": "Consent detail is required"}
        )
    facility_id = await _facility_id(db)
    status = payload.notification.status.lower()
    await hip_service.record_consent_notification(
        db,
        facility_id=facility_id,
        artefact_id=payload.notification.consent_id,
        abha_address=detail.patient.id,
        status=status,
        hi_types=detail.hi_types,
        date_range_from=detail.permission.date_range.from_,
        date_range_to=detail.permission.date_range.to,
        expires_at=detail.permission.data_erase_at,
        raw=raw_dict(payload),
    )
    await callback_replies.schedule(
        db,
        facility_id=facility_id,
        kind="hip_consent",
        gateway_request_id=callback.request_id,
        payload=payload,
        subject_ids=[payload.notification.consent_id],
    )
    return _accepted()


@router.post("/api/v3/hip/health-information/request", status_code=202)
async def hip_health_information_request(
    payload: HipHealthInformationCallback,
    background_tasks: BackgroundTasks,
    callback: HipCallback,
    db: DbSession,
) -> Response:
    if callback.replayed:
        return _accepted()
    facility_id = await _facility_id(db)
    consent_id = payload.hi_request.consent.id
    artefact = (
        await db.execute(
            select(AbdmHipConsentArtefact)
            .where(
                AbdmHipConsentArtefact.facility_id == facility_id,
                AbdmHipConsentArtefact.consent_artefact_id == consent_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if artefact is None:
        raise HTTPException(
            403, {"code": "consent_not_valid", "message": "No usable consent artefact"}
        )
    already = (
        await db.execute(
            select(AbdmHipHealthInformationRequest).where(
                AbdmHipHealthInformationRequest.transaction_id == payload.transaction_id
            )
        )
    ).scalar_one_or_none()
    if already is not None:
        if (
            already.facility_id != facility_id
            or already.consent_artefact_id != consent_id
            or already.data_push_url != str(payload.hi_request.data_push_url)
            or already.hiu_key_material
            != payload.hi_request.key_material.model_dump(mode="json", by_alias=True)
            or hiu_service._aware(already.requested_from)
            != hiu_service._aware(payload.hi_request.date_range.from_)
            or hiu_service._aware(already.requested_to)
            != hiu_service._aware(payload.hi_request.date_range.to)
        ):
            raise HTTPException(409, {"code": "transaction_replay_conflict"})
        await callback_replies.schedule(
            db,
            facility_id=facility_id,
            kind="hip_request",
            gateway_request_id=callback.request_id,
            payload=payload,
            subject_ids=[payload.transaction_id],
            target_id=already.id,
        )
        return _accepted()
    try:
        authorisation = await hip_service.authorise_hi_request(
            db,
            facility_id=facility_id,
            consent_artefact_id=consent_id,
            requested_hi_types=list(artefact.hi_types or []),
            requested_from=payload.hi_request.date_range.from_,
            requested_to=payload.hi_request.date_range.to,
        )
    except hip_service.HipError as exc:
        raise HTTPException(403, {"code": exc.code, "message": exc.message}) from exc
    row = await hip_service.record_hi_request(
        db,
        facility_id=facility_id,
        transaction_id=payload.transaction_id,
        consent_artefact_id=consent_id,
        hiu_key_material=payload.hi_request.key_material.model_dump(mode="json", by_alias=True),
        data_push_url=str(payload.hi_request.data_push_url),
        gateway_request_id=callback.request_id,
        authorisation=authorisation,
    )
    row.bundles_sent = "0"
    row.status = "transferring"
    ack_id = await callback_replies.schedule(
        db,
        facility_id=facility_id,
        kind="hip_request",
        gateway_request_id=callback.request_id,
        payload=payload,
        subject_ids=[payload.transaction_id],
        target_id=row.id,
    )
    # Acknowledgement intent and request become durable together. The reply
    # worker creates the transfer job only after the gateway acknowledges it.
    await db.commit()
    from app.integrations.abdm.job_runner import run_once

    background_tasks.add_task(run_once, ack_id)
    background_tasks.add_task(run_once, durable_job_id("hip_transfer", row.id))
    return _accepted()


# ------------------------------------------------------------------ HIU M3


async def _consent_request_by_gateway_id(
    db: AsyncSession, request_id: str
) -> AbdmConsentRequest | None:
    facility_id = await _facility_id(db)
    return (
        await db.execute(
            select(AbdmConsentRequest)
            .where(
                AbdmConsentRequest.gateway_request_id == request_id,
                AbdmConsentRequest.facility_id == facility_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()


def _advance_consent_status(row: AbdmConsentRequest, status: str) -> bool:
    """Callbacks can arrive out of order. A terminal decision never reopens."""
    allowed = {
        "requested": {"granted", "denied", "expired", "revoked", "failed"},
        "granted": {"expired", "revoked"},
    }
    if status == row.status:
        return True
    if status in allowed.get(row.status, set()):
        row.status = status
        return True
    return False


@router.post("/api/v3/hiu/consent/request/on-init", status_code=202)
async def consent_on_init(
    payload: ConsentOnInitCallback,
    callback: HiuCallback,
    db: DbSession,
) -> Response:
    if callback.replayed:
        return _accepted()
    row = await _consent_request_by_gateway_id(db, payload.response.request_id)
    if row is None:
        raise HTTPException(
            404, {"code": "consent_request_not_found", "message": "Consent request not found"}
        )
    if payload.error:
        if row.status == "requested" and row.consent_request_id is None:
            row.status = "failed"
            row.failure_reason = payload.error.code or "ABDM rejected consent request"
    elif payload.consent_request:
        if row.consent_request_id not in {None, payload.consent_request.id}:
            raise HTTPException(409, {"code": "consent_correlation_conflict"})
        if row.status not in {"failed", "denied", "expired", "revoked"}:
            row.consent_request_id = payload.consent_request.id
    return _accepted()


@router.post("/api/v3/hiu/consent/request/on-status", status_code=202)
async def consent_on_status(
    payload: ConsentOnStatusCallback,
    callback: HiuCallback,
    db: DbSession,
) -> Response:
    if callback.replayed:
        return _accepted()
    row = await _consent_request_by_gateway_id(db, payload.response.request_id)
    if row is None:
        raise HTTPException(
            404, {"code": "consent_request_not_found", "message": "Consent request not found"}
        )
    # A failed status lookup is not the patient's revocation or denial.
    if not payload.error and payload.consent_request:
        if payload.consent_request.id not in {None, row.consent_request_id}:
            raise HTTPException(409, {"code": "consent_correlation_conflict"})
        status = payload.consent_request.status.lower()
        if _advance_consent_status(row, status):
            await hiu_service.end_consent_request(db, row)
    return _accepted()


@router.post("/api/v3/hiu/consent/request/notify", status_code=202)
async def hiu_consent_notify(
    payload: HiuConsentNotifyCallback,
    callback: HiuCallback,
    db: DbSession,
) -> Response:
    if callback.replayed:
        return _accepted()
    facility_id = await _facility_id(db)
    row = (
        await db.execute(
            select(AbdmConsentRequest)
            .where(
                AbdmConsentRequest.consent_request_id == payload.notification.consent_request_id,
                AbdmConsentRequest.facility_id == facility_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            404, {"code": "consent_request_not_found", "message": "Consent request not found"}
        )
    status = payload.notification.status.lower()
    applicable = _advance_consent_status(row, status)
    if applicable:
        await hiu_service.end_consent_request(db, row)
    for reference in payload.notification.consent_artefacts:
        if not applicable:
            continue  # Still acknowledge late notifications; never restore permission.
        await _record_hiu_artefact(
            db,
            facility_id=row.facility_id,
            consent_request=row,
            artefact_id=reference.id,
            status="granted"
            if status == "granted"
            else ("revoked" if status == "revoked" else "expired"),
            hi_types=[],
            date_range_from=None,
            date_range_to=None,
            expires_at=None,
            raw=raw_dict(payload),
        )
    await callback_replies.schedule(
        db,
        facility_id=facility_id,
        kind="hiu_consent",
        gateway_request_id=callback.request_id,
        payload=payload,
        subject_ids=[reference.id for reference in payload.notification.consent_artefacts],
    )
    return _accepted()


@router.post("/api/v3/hiu/consent/on-fetch", status_code=202)
async def consent_on_fetch(
    payload: ConsentOnFetchCallback,
    callback: HiuCallback,
    db: DbSession,
) -> Response:
    if callback.replayed:
        return _accepted()
    if payload.error or payload.consent is None:
        raise HTTPException(
            422, {"code": "consent_fetch_failed", "message": "Consent artefact was not returned"}
        )
    detail = payload.consent.consent_detail
    facility_id = await _facility_id(db)
    existing = (
        await db.execute(
            select(AbdmHiuConsentArtefact).where(
                AbdmHiuConsentArtefact.consent_artefact_id == detail.consent_id,
                AbdmHiuConsentArtefact.facility_id == facility_id,
            )
        )
    ).scalar_one_or_none()
    if existing is None:
        raise HTTPException(
            404,
            {"code": "consent_artefact_not_found", "message": "Consent artefact was not announced"},
        )
    expected_fetch = durable_job_id("hiu_fetch", existing.id)
    fetch_job = await db.get(AbdmJob, expected_fetch)
    if (
        payload.response.request_id != str(expected_fetch)
        or fetch_job is None
        or fetch_job.facility_id != facility_id
        or fetch_job.attempts < 1
    ):
        raise HTTPException(409, {"code": "consent_fetch_correlation_mismatch"})
    # Same lock order as revocation: request, artefact, then transfer rows.
    # Fetch-vs-revoke must not deadlock with each transaction holding one side.
    request_row = (
        await db.execute(
            select(AbdmConsentRequest)
            .where(
                AbdmConsentRequest.id == existing.consent_request_id,
                AbdmConsentRequest.facility_id == facility_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if request_row is None or request_row.facility_id != facility_id:
        raise HTTPException(404, {"code": "consent_request_not_found"})
    await db.refresh(existing, with_for_update=True)
    if existing.status in {"revoked", "expired"} or request_row.status in {
        "revoked",
        "expired",
        "denied",
        "failed",
    }:
        return _accepted()
    if (
        detail.patient.id != request_row.abha_address
        or detail.hiu.id != callback.recipient_id
        or not detail.hi_types
        or not set(detail.hi_types).issubset(request_row.hi_types)
        or detail.permission.date_range.from_ > detail.permission.date_range.to
        or hiu_service._aware(detail.permission.date_range.from_)
        < hiu_service._aware(request_row.date_range_from)
        or hiu_service._aware(detail.permission.date_range.to)
        > hiu_service._aware(request_row.date_range_to)
        or hiu_service._aware(detail.permission.data_erase_at)
        > hiu_service._aware(request_row.requested_expiry)
    ):
        raise HTTPException(422, {"code": "consent_scope_mismatch"})
    await _record_hiu_artefact(
        db,
        facility_id=existing.facility_id,
        consent_request=request_row,
        artefact_id=detail.consent_id,
        status=payload.consent.status.lower(),
        hi_types=detail.hi_types,
        date_range_from=detail.permission.date_range.from_,
        date_range_to=detail.permission.date_range.to,
        expires_at=detail.permission.data_erase_at,
        raw=raw_dict(payload.consent),
    )
    return _accepted()


async def _record_hiu_artefact(db: AsyncSession, **kwargs):
    try:
        return await hiu_service.record_artefact(db, **kwargs)
    except hiu_service.HiuError as exc:
        raise HTTPException(409, {"code": exc.code, "message": exc.message}) from exc


@router.post("/api/v3/hiu/health-information/on-request", status_code=202)
async def hiu_health_information_on_request(
    payload: HiuHealthInformationOnRequestCallback,
    callback: HiuCallback,
    db: DbSession,
) -> Response:
    if callback.replayed:
        return _accepted()
    facility_id = await _facility_id(db)
    row = (
        await db.execute(
            select(AbdmHiuHealthInformationRequest)
            .where(
                AbdmHiuHealthInformationRequest.gateway_request_id == payload.response.request_id,
                AbdmHiuHealthInformationRequest.facility_id == facility_id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            404, {"code": "hi_request_not_found", "message": "Health-information request not found"}
        )
    if payload.hi_request and row.transaction_id not in {None, payload.hi_request.transaction_id}:
        raise HTTPException(409, {"code": "transaction_correlation_conflict"})
    if row.status != "requested":
        return _accepted()
    if payload.error or payload.hi_request is None:
        row.status = "failed"
        row.failure_reason = payload.error.code if payload.error else "missing_hi_request"
    else:
        row.transaction_id = payload.hi_request.transaction_id
        status = payload.hi_request.session_status.upper()
        row.status = "acknowledged" if status == "ACKNOWLEDGED" else "failed"
    if row.status == "failed":
        hiu_service._clear_key(row)
    return _accepted()


@router.post("/api/v3/hiu/health-information/transfer", status_code=202)
async def receive_health_information(
    payload: HealthInformationPush,
    db: DbSession,
) -> Response:
    """Direct HIP→HIU push: authorised by transaction and authenticated crypto."""
    request = (
        await db.execute(
            select(AbdmHiuHealthInformationRequest)
            .where(AbdmHiuHealthInformationRequest.transaction_id == payload.transaction_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if request is None:
        raise HTTPException(404, {"code": "unknown_transaction", "message": "Unknown transaction"})
    # A replay must contain the exact accepted page. A changed ciphertext or a
    # previously rejected entry is never upgraded to success.
    existing_entries = list(
        (
            await db.execute(
                select(AbdmReceivedBundle)
                .where(
                    AbdmReceivedBundle.hi_request_id == request.id,
                    AbdmReceivedBundle.page_number == payload.page_number,
                )
                .order_by(AbdmReceivedBundle.entry_index)
            )
        )
        .scalars()
        .all()
    )
    if payload.page_number in (request.received_pages or []):
        if (
            request.expected_page_count != payload.page_count
            or len(existing_entries) != len(payload.entries)
            or any(
                row.status != "stored"
                or row.wire_sha256
                != hiu_records.wire_digest(
                    content=entry.content,
                    public_key=payload.key_material.dh_public_key.key_value,
                    nonce=payload.key_material.nonce,
                    reference=entry.care_context_reference,
                    media=entry.media,
                    checksum=entry.checksum,
                )
                for row, entry in zip(existing_entries, payload.entries, strict=False)
            )
        ):
            raise HTTPException(
                409,
                {
                    "code": "page_replay_changed",
                    "message": "Received page does not match its earlier delivery",
                },
            )
        return _accepted()
    if request.status not in {"requested", "acknowledged", "partial"}:
        raise HTTPException(
            409, {"code": "transaction_closed", "message": "Transaction is not accepting data"}
        )
    artefact = await db.get(AbdmHiuConsentArtefact, request.artefact_id)
    artefact_expiry = artefact.expires_at if artefact is not None else None
    if (
        artefact is None
        or artefact.status != "granted"
        or artefact_expiry is None
        or (
            artefact_expiry is not None
            and (artefact_expiry if artefact_expiry.tzinfo else artefact_expiry.replace(tzinfo=UTC))
            <= datetime.now(UTC)
        )
    ):
        raise HTTPException(
            403, {"code": "consent_not_valid", "message": "Consent is no longer usable"}
        )
    if payload.page_number >= payload.page_count:
        raise HTTPException(
            422, {"code": "invalid_page", "message": "pageNumber must be below pageCount"}
        )
    if request.expected_page_count not in (None, payload.page_count):
        raise HTTPException(
            409, {"code": "page_count_changed", "message": "pageCount changed during transfer"}
        )
    request.expected_page_count = payload.page_count
    key = payload.key_material
    if key.crypto_alg != "ECDH" or key.curve != "Curve25519":
        raise HTTPException(
            422, {"code": "unsupported_crypto", "message": "Expected ECDH Curve25519 key material"}
        )
    key_expiry = key.dh_public_key.expiry
    if (key_expiry if key_expiry.tzinfo else key_expiry.replace(tzinfo=UTC)) <= datetime.now(UTC):
        raise HTTPException(
            422, {"code": "sender_key_expired", "message": "Sender key material has expired"}
        )

    for index, entry in enumerate(payload.entries):
        duplicate = (
            await db.execute(
                select(AbdmReceivedBundle).where(
                    AbdmReceivedBundle.hi_request_id == request.id,
                    AbdmReceivedBundle.page_number == payload.page_number,
                    AbdmReceivedBundle.entry_index == index,
                )
            )
        ).scalar_one_or_none()
        if duplicate is None:
            try:
                await hiu_service.receive_bundle(
                    db,
                    request=request,
                    ciphertext_b64=entry.content,
                    hip_public_key_b64=key.dh_public_key.key_value,
                    hip_nonce_b64=key.nonce,
                    care_context_reference=entry.care_context_reference,
                    page_number=payload.page_number,
                    entry_index=index,
                    media_type=entry.media,
                    declared_checksum=entry.checksum,
                )
            except hiu_service.HiuError as exc:
                # Preserve the authenticated rejection receipt. Letting the
                # dependency roll this transaction back would make a tampered
                # push indistinguishable from one that never arrived.
                await db.commit()
                raise HTTPException(422, {"code": exc.code, "message": exc.message}) from exc
        elif duplicate.status != "stored" or duplicate.wire_sha256 != hiu_records.wire_digest(
            content=entry.content,
            public_key=key.dh_public_key.key_value,
            nonce=key.nonce,
            reference=entry.care_context_reference,
            media=entry.media,
            checksum=entry.checksum,
        ):
            raise HTTPException(
                409,
                {
                    "code": "entry_replay_changed",
                    "message": "Entry is rejected or does not match its earlier delivery; start a new transfer",
                },
            )

    pages = set(request.received_pages or [])
    pages.add(payload.page_number)
    request.received_pages = sorted(pages)
    if len(pages) == payload.page_count:
        request.status = "received"
        await hiu_service.complete_request(db, request=request)
        from app.integrations.abdm.jobs import enqueue

        # Persist reception and retryable notification atomically. A gateway
        # outage must not roll back the accepted document or retain its key.
        await enqueue(db, kind="hiu_notify", target_id=request.id, facility_id=request.facility_id)
    return _accepted()
