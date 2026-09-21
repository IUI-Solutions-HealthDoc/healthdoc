"""Patient-portal reads whose patient identity comes only from a verified binding."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.auth.deps import CurrentDbUser, require_roles
from app.common.enums import AccessChannel
from app.consent.models import ConsentPurpose, ConsentRecord, DataAccessLog
from app.patients.models import Patient, PatientPortalBinding
from app.patients.portal_router import ActivePatientBinding, DbSession
from app.users.models import Facility, User
from app.opd.models import Encounter, Visit

router = APIRouter(
    prefix="/patient-portal/me",
    tags=["patient-portal"],
    dependencies=[Depends(require_roles("patient"))],
)


class MyAbhaOut(BaseModel):
    patient_id: uuid.UUID
    abha_number: str | None
    linked_at: datetime | None
    linked: bool


class MyConsentOut(BaseModel):
    id: uuid.UUID
    purpose_code: str
    purpose_description: str | None
    status: str
    granted_at: datetime
    expires_at: datetime | None
    scope: list[str] | None
    channel: str


class MyAccessItem(BaseModel):
    accessed_at: datetime
    staff_name: str | None
    role: str | None
    resource_type: str | None
    purpose_code: str | None
    access_channel: str
    emergency_access: bool


class MyAccessHistoryOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[MyAccessItem]


async def _record_self_access(
    db: DbSession,
    *,
    caller: CurrentDbUser,
    binding: PatientPortalBinding,
    resource_type: str,
) -> None:
    db.add(
        DataAccessLog(
            id=uuid.uuid4(),
            user_id=caller.id,
            role="patient",
            resource_type=resource_type,
            resource_id=binding.patient_id,
            patient_id=binding.patient_id,
            purpose_code="self_review",
            access_channel=AccessChannel.API.value,
            emergency_access=False,
            consent_required=False,
            consent_verified=None,
        )
    )
    await db.flush()


@router.get("/abha", response_model=MyAbhaOut)
async def get_my_abha(
    binding: ActivePatientBinding,
    caller: CurrentDbUser,
    db: DbSession,
) -> MyAbhaOut:
    await _record_self_access(db, caller=caller, binding=binding, resource_type="abha_identity")
    patient = await db.get(Patient, binding.patient_id)
    return MyAbhaOut(
        patient_id=patient.id,
        abha_number=patient.abha_number,
        linked_at=patient.abha_linked_at,
        linked=patient.abha_number is not None,
    )


@router.get("/consents", response_model=list[MyConsentOut])
async def get_my_consents(
    binding: ActivePatientBinding,
    caller: CurrentDbUser,
    db: DbSession,
) -> list[MyConsentOut]:
    await _record_self_access(db, caller=caller, binding=binding, resource_type="consent_records")
    rows = (
        await db.execute(
            select(ConsentRecord, ConsentPurpose)
            .join(ConsentPurpose, ConsentPurpose.id == ConsentRecord.purpose_id)
            .where(ConsentRecord.patient_id == binding.patient_id)
            .order_by(ConsentRecord.granted_at.desc())
        )
    ).all()
    return [
        MyConsentOut(
            id=record.id,
            purpose_code=purpose.purpose_code,
            purpose_description=purpose.description,
            status=record.status,
            granted_at=record.granted_at,
            expires_at=record.expires_at,
            scope=record.scope,
            channel=record.channel,
        )
        for record, purpose in rows
    ]


@router.get("/access-history", response_model=MyAccessHistoryOut)
async def get_my_access_history(
    binding: ActivePatientBinding,
    caller: CurrentDbUser,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MyAccessHistoryOut:
    await _record_self_access(db, caller=caller, binding=binding, resource_type="data_access_log")
    base = DataAccessLog.patient_id == binding.patient_id
    total = (
        await db.execute(select(func.count()).select_from(DataAccessLog).where(base))
    ).scalar_one()
    rows = (
        await db.execute(
            select(DataAccessLog, User.full_name)
            .outerjoin(User, User.id == DataAccessLog.user_id)
            .where(base)
            .order_by(DataAccessLog.accessed_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return MyAccessHistoryOut(
        total=total,
        limit=limit,
        offset=offset,
        items=[
            MyAccessItem(
                accessed_at=entry.accessed_at,
                staff_name=staff_name,
                role=entry.role,
                resource_type=entry.resource_type,
                purpose_code=entry.purpose_code,
                access_channel=entry.access_channel,
                emergency_access=entry.emergency_access,
            )
            for entry, staff_name in rows
        ],
    )


class MyDocumentItem(BaseModel):
    id: uuid.UUID
    document_type: str  # prescription, lab_report, radiology, discharge_summary, vaccine
    title: str
    date: datetime
    doctor_name: str | None = None
    facility_name: str | None = None
    status: str = "released"
    summary: str
    details: Any | None = None


class MyDocumentsOut(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[MyDocumentItem]


class MyDocumentDetailOut(BaseModel):
    id: uuid.UUID
    document_type: str
    title: str
    date: datetime
    doctor_name: str | None = None
    facility_name: str | None = None
    facility_address: str | None = None
    patient_uhid: str | None = None
    patient_name: str
    patient_age_gender: str | None = None
    status: str = "released"
    summary: str
    content: dict[str, Any]
    verified_at: datetime | None = None


@router.get("/documents", response_model=MyDocumentsOut)
async def get_my_documents(
    binding: ActivePatientBinding,
    caller: CurrentDbUser,
    db: DbSession,
    category: Annotated[str | None, Query(description="Filter by type: all, prescription, lab_report, radiology, discharge_summary, vaccine")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> MyDocumentsOut:
    """Retrieve released clinical documents for the bound patient."""
    await _record_self_access(db, caller=caller, binding=binding, resource_type="clinical_documents")
    docs: list[MyDocumentItem] = []
    pid = binding.patient_id

    # 1. Prescriptions
    if not category or category in ("all", "prescription"):
        from app.orders.models import Prescription, PrescriptionItem
        rx_rows = (
            await db.execute(
                select(Prescription, User.full_name, Facility.name)
                .join(Encounter, Encounter.id == Prescription.encounter_id)
                .join(Visit, Visit.id == Encounter.visit_id)
                .outerjoin(User, User.id == Prescription.created_by)
                .outerjoin(Facility, Facility.id == Prescription.facility_id)
                .where(
                    Prescription.patient_id == pid, Prescription.facility_id == binding.facility_id,
                    Encounter.ended_at.is_not(None), Encounter.facility_id == binding.facility_id,
                    Visit.patient_id == pid, Visit.facility_id == binding.facility_id,
                )
                .order_by(Prescription.created_at.desc())
            )
        ).all()
        for rx, doc_name, fac_name in rx_rows:
            items = (
                await db.execute(
                    select(PrescriptionItem).where(PrescriptionItem.prescription_id == rx.id)
                )
            ).scalars().all()
            item_names = [it.medicine_name for it in items]
            summary = f"{len(items)} medication(s): {', '.join(item_names[:3])}"
            if len(items) > 3:
                summary += f" +{len(items) - 3} more"
            if rx.notes:
                summary += f" ({rx.notes})"
            docs.append(
                MyDocumentItem(
                    id=rx.id,
                    document_type="prescription",
                    title="Prescription",
                    date=rx.created_at,
                    doctor_name=doc_name,
                    facility_name=fac_name,
                    status="released",
                    summary=summary,
                    details=[
                        {
                            "medicine_name": it.medicine_name,
                            "dosage": it.dosage,
                            "frequency": it.frequency,
                            "duration": getattr(it, "duration", None),
                            "instructions": getattr(it, "instructions", None),
                        }
                        for it in items
                    ],
                )
            )

    # 2. Lab Reports
    if not category or category in ("all", "lab_report"):
        from app.orders.models import Order
        from app.pathology.models import LabOrderItem, LabResult
        lab_rows = (
            await db.execute(
                select(LabOrderItem, LabResult, Order, Facility.name, User.full_name)
                .join(Order, Order.id == LabOrderItem.order_id)
                .join(LabResult, LabResult.lab_order_item_id == LabOrderItem.id)
                .outerjoin(Facility, Facility.id == Order.facility_id)
                .outerjoin(User, User.id == Order.created_by)
                .where(
                    Order.patient_id == pid,
                    LabResult.is_current.is_(True),
                    LabOrderItem.status.in_(["completed", "released", "approved"]),
                )
                .order_by(LabResult.created_at.desc())
            )
        ).all()
        for item, result, order, fac_name, doc_name in lab_rows:
            docs.append(
                MyDocumentItem(
                    id=item.id,
                    document_type="lab_report",
                    title=f"Lab Report - {item.test_name}",
                    date=result.created_at,
                    doctor_name=doc_name,
                    facility_name=fac_name,
                    status="released",
                    summary=f"Sample: {item.sample_type} | Accession: {item.accession_number}",
                    details=result.result_data if hasattr(result, "result_data") else {},
                )
            )

    # 3. Radiology Reports
    if not category or category in ("all", "radiology"):
        from app.orders.models import Order
        from app.radiology.models import RadiologyOrderItem, RadiologyReport
        rad_rows = (
            await db.execute(
                select(RadiologyOrderItem, RadiologyReport, Order, Facility.name, User.full_name)
                .join(Order, Order.id == RadiologyOrderItem.order_id)
                .join(RadiologyReport, RadiologyReport.radiology_order_item_id == RadiologyOrderItem.id)
                .outerjoin(Facility, Facility.id == Order.facility_id)
                .outerjoin(User, User.id == RadiologyReport.created_by)
                .where(
                    Order.patient_id == pid,
                    RadiologyReport.is_current.is_(True),
                    RadiologyReport.status.in_(["signed", "finalized", "released"]),
                )
                .order_by(RadiologyReport.created_at.desc())
            )
        ).all()
        for r_item, report, order, fac_name, doc_name in rad_rows:
            docs.append(
                MyDocumentItem(
                    id=r_item.id,
                    document_type="radiology",
                    title=f"Radiology - {r_item.modality.upper()} {r_item.scan_type}",
                    date=report.created_at,
                    doctor_name=doc_name,
                    facility_name=fac_name,
                    status="released",
                    summary=f"Impression: {report.impression[:160] if report.impression else 'Report available'}",
                    details={"findings": report.findings, "impression": report.impression, "modality": r_item.modality},
                )
            )

    # 4. Discharge Summaries
    if not category or category in ("all", "discharge_summary"):
        from app.admissions.models import Admission, Discharge
        dc_rows = (
            await db.execute(
                select(Discharge, Admission, Facility.name, User.full_name)
                .join(Admission, Admission.id == Discharge.admission_id)
                .join(Visit, Visit.id == Admission.visit_id)
                .outerjoin(Facility, Facility.id == Visit.facility_id)
                .outerjoin(User, User.id == Discharge.created_by)
                .where(Admission.patient_id == pid)
                .order_by(Discharge.discharged_at.desc())
            )
        ).all()
        for dc, adm, fac_name, doc_name in dc_rows:
            docs.append(
                MyDocumentItem(
                    id=dc.id,
                    document_type="discharge_summary",
                    title="Inpatient Discharge Summary",
                    date=dc.discharged_at,
                    doctor_name=doc_name,
                    facility_name=fac_name,
                    status="released",
                    summary=f"Discharge: {dc.discharge_type}. Follow-up: {dc.follow_up_date or 'As advised'}",
                    details={"summary": dc.discharge_summary, "discharge_type": dc.discharge_type, "follow_up_date": str(dc.follow_up_date) if dc.follow_up_date else None},
                )
            )

    # 5. Vaccination Certificates
    if not category or category in ("all", "vaccine"):
        from app.immunization.models import ImmunizationRecord, VaccineCatalogue
        vac_rows = (
            await db.execute(
                select(ImmunizationRecord, VaccineCatalogue, User.full_name)
                .join(VaccineCatalogue, VaccineCatalogue.id == ImmunizationRecord.vaccine_id)
                .outerjoin(User, User.id == ImmunizationRecord.administered_by)
                .where(ImmunizationRecord.patient_id == pid)
                .order_by(ImmunizationRecord.administered_at.desc())
            )
        ).all()
        for rec, cat, vac_name in vac_rows:
            docs.append(
                MyDocumentItem(
                    id=rec.id,
                    document_type="vaccine",
                    title=f"Immunization - {cat.name}",
                    date=rec.administered_at,
                    doctor_name=vac_name,
                    facility_name=None,
                    status="released",
                    summary=f"Dose {rec.dose_number} | Batch {rec.batch_number} | Route: {rec.route or cat.route}",
                    details={
                        "vaccine_name": cat.name,
                        "target_disease": cat.target_disease,
                        "dose_number": rec.dose_number,
                        "batch_number": rec.batch_number,
                        "manufacturer": rec.manufacturer,
                        "site": rec.site,
                        "route": rec.route,
                        "expiry_date": str(rec.expiry_date),
                    },
                )
            )

    # Sort all documents chronologically descending
    def _doc_sort_key(d: MyDocumentItem) -> datetime:
        dt = d.date
        return dt.replace(tzinfo=datetime.now().astimezone().tzinfo) if dt.tzinfo is None else dt

    docs.sort(key=_doc_sort_key, reverse=True)
    total = len(docs)
    paginated = docs[offset : offset + limit]

    return MyDocumentsOut(
        total=total,
        limit=limit,
        offset=offset,
        items=paginated,
    )


@router.get("/documents/{doc_type}/{doc_id}", response_model=MyDocumentDetailOut)
async def get_my_document_detail(
    doc_type: str,
    doc_id: uuid.UUID,
    binding: ActivePatientBinding,
    current_user: CurrentDbUser,
    db: DbSession,
) -> MyDocumentDetailOut:
    """Retrieve detailed view and printable record of a specific clinical document."""
    from fastapi import HTTPException
    await _record_self_access(
        db, caller=current_user, binding=binding, resource_type=f"clinical_document_{doc_type}"
    )
    pid = binding.patient_id
    patient = await db.get(Patient, pid)
    if patient is None:
        raise HTTPException(status_code=404, detail={"code": "patient_not_found", "message": "Patient not found"})

    age_gender = f"{patient.age_years or 'Unknown'}y / {patient.sex.capitalize() if patient.sex else 'Unknown'}"

    if doc_type == "prescription":
        from app.orders.models import Prescription, PrescriptionItem
        rx_row = (
            await db.execute(
                select(Prescription, User.full_name, Facility.name)
                .join(Encounter, Encounter.id == Prescription.encounter_id)
                .join(Visit, Visit.id == Encounter.visit_id)
                .outerjoin(User, User.id == Prescription.created_by)
                .outerjoin(Facility, Facility.id == Prescription.facility_id)
                .where(
                    Prescription.id == doc_id, Prescription.patient_id == pid,
                    Prescription.facility_id == binding.facility_id,
                    Encounter.ended_at.is_not(None), Encounter.facility_id == binding.facility_id,
                    Visit.patient_id == pid, Visit.facility_id == binding.facility_id,
                )
            )
        ).first()
        if rx_row is None:
            raise HTTPException(status_code=404, detail={"code": "document_not_found", "message": "Prescription not found"})
        rx, doc_name, fac_name = rx_row
        items = (
            await db.execute(select(PrescriptionItem).where(PrescriptionItem.prescription_id == rx.id))
        ).scalars().all()
        return MyDocumentDetailOut(
            id=rx.id,
            document_type="prescription",
            title="Official Clinical Prescription",
            date=rx.created_at,
            doctor_name=doc_name,
            facility_name=fac_name,
            facility_address="Hospital Outpatient Department",
            patient_uhid=patient.uhid,
            patient_name=patient.full_name,
            patient_age_gender=age_gender,
            status="released",
            summary=f"{len(items)} medication(s) prescribed",
            content={
                "notes": rx.notes,
                "items": [
                    {
                        "medicine_name": it.medicine_name,
                        "dosage": it.dosage,
                        "frequency": it.frequency,
                        "duration": getattr(it, "duration", None),
                        "instructions": getattr(it, "instructions", None),
                    }
                    for it in items
                ],
            },
            verified_at=rx.created_at,
        )

    elif doc_type == "lab_report":
        from app.orders.models import Order
        from app.pathology.models import LabOrderItem, LabResult
        row = (
            await db.execute(
                select(LabOrderItem, LabResult, Order, Facility.name, User.full_name)
                .join(Order, Order.id == LabOrderItem.order_id)
                .join(LabResult, LabResult.lab_order_item_id == LabOrderItem.id)
                .outerjoin(Facility, Facility.id == Order.facility_id)
                .outerjoin(User, User.id == Order.created_by)
                .where(LabOrderItem.id == doc_id, Order.patient_id == pid, LabResult.is_current.is_(True))
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "document_not_found", "message": "Lab report not found"})
        item, result, order, fac_name, doc_name = row
        return MyDocumentDetailOut(
            id=item.id,
            document_type="lab_report",
            title=f"Diagnostic Laboratory Report - {item.test_name}",
            date=result.created_at,
            doctor_name=doc_name,
            facility_name=fac_name,
            facility_address="Central Laboratory & Pathology Services",
            patient_uhid=patient.uhid,
            patient_name=patient.full_name,
            patient_age_gender=age_gender,
            status="released",
            summary=f"Accession: {item.accession_number} | Specimen: {item.sample_type}",
            content={
                "test_name": item.test_name,
                "test_code": item.test_code,
                "sample_type": item.sample_type,
                "accession_number": item.accession_number,
                "collected_at": str(item.collected_at) if item.collected_at else None,
                "result_data": result.result_data if hasattr(result, "result_data") else {},
            },
            verified_at=result.created_at,
        )

    elif doc_type == "radiology":
        from app.orders.models import Order
        from app.radiology.models import RadiologyOrderItem, RadiologyReport
        row = (
            await db.execute(
                select(RadiologyOrderItem, RadiologyReport, Order, Facility.name, User.full_name)
                .join(Order, Order.id == RadiologyOrderItem.order_id)
                .join(RadiologyReport, RadiologyReport.radiology_order_item_id == RadiologyOrderItem.id)
                .outerjoin(Facility, Facility.id == Order.facility_id)
                .outerjoin(User, User.id == RadiologyReport.created_by)
                .where(RadiologyOrderItem.id == doc_id, Order.patient_id == pid, RadiologyReport.is_current.is_(True))
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "document_not_found", "message": "Radiology report not found"})
        r_item, report, order, fac_name, doc_name = row
        return MyDocumentDetailOut(
            id=r_item.id,
            document_type="radiology",
            title=f"Radiology Imaging Report - {r_item.modality.upper()} {r_item.scan_type}",
            date=report.created_at,
            doctor_name=doc_name,
            facility_name=fac_name,
            facility_address="Department of Radiodiagnosis & Imaging",
            patient_uhid=patient.uhid,
            patient_name=patient.full_name,
            patient_age_gender=age_gender,
            status="released",
            summary=f"Modality: {r_item.modality.upper()} | Accession: {r_item.accession_number}",
            content={
                "modality": r_item.modality,
                "scan_type": r_item.scan_type,
                "accession_number": r_item.accession_number,
                "findings": report.findings,
                "impression": report.impression,
            },
            verified_at=report.created_at,
        )

    elif doc_type == "discharge_summary":
        from app.admissions.models import Admission, Discharge
        row = (
            await db.execute(
                select(Discharge, Admission, Facility.name, User.full_name)
                .join(Admission, Admission.id == Discharge.admission_id)
                .join(Visit, Visit.id == Admission.visit_id)
                .outerjoin(Facility, Facility.id == Visit.facility_id)
                .outerjoin(User, User.id == Discharge.created_by)
                .where(Discharge.id == doc_id, Admission.patient_id == pid)
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "document_not_found", "message": "Discharge summary not found"})
        dc, adm, fac_name, doc_name = row
        return MyDocumentDetailOut(
            id=dc.id,
            document_type="discharge_summary",
            title="Inpatient Discharge Summary",
            date=dc.discharged_at,
            doctor_name=doc_name,
            facility_name=fac_name,
            facility_address="Inpatient Services",
            patient_uhid=patient.uhid,
            patient_name=patient.full_name,
            patient_age_gender=age_gender,
            status="released",
            summary=f"Disposition: {dc.discharge_type}",
            content={
                "admitted_at": str(adm.admitted_at),
                "discharged_at": str(dc.discharged_at),
                "discharge_type": dc.discharge_type,
                "discharge_summary": dc.discharge_summary,
                "follow_up_date": str(dc.follow_up_date) if dc.follow_up_date else None,
            },
            verified_at=dc.discharged_at,
        )

    elif doc_type == "vaccine":
        from app.immunization.models import ImmunizationRecord, VaccineCatalogue
        row = (
            await db.execute(
                select(ImmunizationRecord, VaccineCatalogue, User.full_name)
                .join(VaccineCatalogue, VaccineCatalogue.id == ImmunizationRecord.vaccine_id)
                .outerjoin(User, User.id == ImmunizationRecord.administered_by)
                .where(ImmunizationRecord.id == doc_id, ImmunizationRecord.patient_id == pid)
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "document_not_found", "message": "Immunization record not found"})
        rec, cat, vac_name = row
        return MyDocumentDetailOut(
            id=rec.id,
            document_type="vaccine",
            title=f"Digital Immunization Certificate - {cat.name}",
            date=rec.administered_at,
            doctor_name=vac_name,
            facility_name="National Immunization Center",
            facility_address="Vaccination & Preventive Healthcare Wing",
            patient_uhid=patient.uhid,
            patient_name=patient.full_name,
            patient_age_gender=age_gender,
            status="released",
            summary=f"Vaccine: {cat.name} (Dose {rec.dose_number})",
            content={
                "vaccine_name": cat.name,
                "vaccine_code": cat.code,
                "target_disease": cat.target_disease,
                "dose_number": rec.dose_number,
                "batch_number": rec.batch_number,
                "manufacturer": rec.manufacturer,
                "route": rec.route or cat.route,
                "site": rec.site or cat.site,
                "expiry_date": str(rec.expiry_date),
            },
            verified_at=rec.administered_at,
        )

    else:
        raise HTTPException(status_code=400, detail={"code": "invalid_doc_type", "message": f"Invalid document type '{doc_type}'"})
