"""Forms, Order Sets, and CSV Administration service (HD-30)."""
from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from app.common.patient_scope import actor_facility, require_patient_scope, require_visit_scope

from app.forms.models import ClinicalOrderSet, FormDefinition, FormSubmission
from app.forms.validation import validate_submission
from app.forms.schemas import (
    ApplyOrderSetResult,
    ClinicalOrderSetCreate,
    ClinicalOrderSetOut,
    CsvImportResult,
    CsvValidationResult,
    FormDefinitionCreate,
    FormDefinitionOut,
    FormFieldDef,
    FormSubmissionCreate,
    FormSubmissionOut,
)
from app.immunization.models import VaccineCatalogue
from app.opd.models import Visit
from app.patients.models import Patient

DEFAULT_FORMS = [
    {
        "code": "SURGICAL_PRE_OP",
        "title": "Surgical Pre-Operative Assessment",
        "version": 1,
        "status": "published",
        "fields_schema": [
            {"id": "npo_hours", "label": "NPO Duration (Hours)", "type": "number", "required": True},
            {"id": "airway_mallampati", "label": "Mallampati Score", "type": "select", "required": True, "options": [
                {"label": "Class I", "value": "I"},
                {"label": "Class II", "value": "II"},
                {"label": "Class III", "value": "III"},
                {"label": "Class IV", "value": "IV"},
            ]},
            {"id": "consent_signed", "label": "Informed Consent Signed and Verified", "type": "checkbox", "required": True},
            {"id": "pac_fitness", "label": "PAC Clearance Notes", "type": "textarea", "required": False},
        ],
    },
    {
        "code": "DIABETES_MANAGEMENT",
        "title": "Longitudinal Diabetes Follow-Up Form",
        "version": 1,
        "status": "published",
        "fields_schema": [
            {"id": "fbs_mg_dl", "label": "Fasting Blood Sugar (mg/dL)", "type": "number", "required": True},
            {"id": "ppbs_mg_dl", "label": "Post-Prandial Blood Sugar (mg/dL)", "type": "number", "required": False},
            {"id": "hba1c_pct", "label": "HbA1c (%)", "type": "number", "required": False},
            {"id": "hypo_episodes", "label": "Hypoglycemia Episodes in Past Month", "type": "number", "required": True},
            {"id": "foot_exam_abnormal", "label": "Abnormalities on Diabetic Foot Exam", "type": "checkbox", "required": False},
            {"id": "dietary_compliance", "label": "Dietary & Lifestyle Compliance", "type": "select", "required": True, "options": [
                {"label": "Excellent", "value": "excellent"},
                {"label": "Moderate", "value": "moderate"},
                {"label": "Poor", "value": "poor"},
            ]},
        ],
    },
]

DEFAULT_ORDER_SETS = [
    {
        "code": "SEPSIS_BUNDLE",
        "title": "Sepsis Resuscitation Care Bundle (Hour-1)",
        "category": "emergency",
        "orders": [
            {"type": "lab", "test_name": "Blood Lactate", "urgency": "stat"},
            {"type": "lab", "test_name": "Blood Cultures (2 sets prior to antibiotics)", "urgency": "stat"},
            {"type": "lab", "test_name": "Complete Blood Count (CBC)", "urgency": "stat"},
            {"type": "nursing", "directive": "Administer 30 mL/kg crystalloid IV for hypotension or lactate >= 4 mmol/L"},
            {"type": "nursing", "directive": "Apply vasopressors if hypotensive during or after fluid resuscitation to maintain MAP >= 65 mm Hg"},
        ],
    },
    {
        "code": "ACUTE_CORONARY_SYNDROME",
        "title": "Acute Coronary Syndrome (ACS) Protocol",
        "category": "cardiology",
        "orders": [
            {"type": "lab", "test_name": "High Sensitivity Troponin-I", "urgency": "stat"},
            {"type": "lab", "test_name": "Serum Electrolytes (Na, K, Cl)", "urgency": "stat"},
            {"type": "radiology", "scan_name": "Chest X-Ray PA View Bedside", "urgency": "urgent"},
            {"type": "nursing", "directive": "12-Lead ECG within 10 minutes of arrival"},
            {"type": "nursing", "directive": "Maintain continuous cardiac monitoring & continuous SpO2"},
        ],
    },
    {
        "code": "PRE_OP_LAB_PANEL",
        "title": "Standard Pre-Operative Assessment Panel",
        "category": "pre_op",
        "orders": [
            {"type": "lab", "test_name": "Complete Blood Count (CBC)", "urgency": "routine"},
            {"type": "lab", "test_name": "Prothrombin Time / INR (PT-INR)", "urgency": "routine"},
            {"type": "lab", "test_name": "Blood Grouping & Crossmatch", "urgency": "routine"},
            {"type": "lab", "test_name": "Serum Creatinine & Blood Urea", "urgency": "routine"},
            {"type": "radiology", "scan_name": "Chest X-Ray PA View", "urgency": "routine"},
        ],
    },
]

FORMULA_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


async def ensure_defaults_seeded(db: AsyncSession, admin_id: uuid.UUID) -> None:
    try:
        f_res = await db.execute(select(FormDefinition).limit(1))
        if f_res.scalars().first() is None:
            for f in DEFAULT_FORMS:
                db.add(FormDefinition(id=uuid.uuid4(), **f, created_by=admin_id))

        o_res = await db.execute(select(ClinicalOrderSet).limit(1))
        if o_res.scalars().first() is None:
            for o in DEFAULT_ORDER_SETS:
                db.add(ClinicalOrderSet(id=uuid.uuid4(), **o))
        await db.commit()
    except Exception:
        await db.rollback()


async def list_form_definitions(
    db: AsyncSession, status_filter: str | None = None
) -> list[FormDefinition]:
    query = select(FormDefinition).order_by(FormDefinition.title)
    if status_filter:
        query = query.where(FormDefinition.status == status_filter.strip())
    res = await db.execute(query)
    return list(res.scalars().all())


async def create_form_definition(
    db: AsyncSession, payload: FormDefinitionCreate, user_id: uuid.UUID
) -> FormDefinitionOut:
    form = FormDefinition(
        id=uuid.uuid4(),
        code=payload.code.strip(),
        title=payload.title.strip(),
        version=payload.version,
        status=payload.status,
        fields_schema=payload.fields_schema,
        created_by=user_id,
    )
    db.add(form)
    await db.commit()
    await db.refresh(form)
    return FormDefinitionOut.model_validate(form)


async def create_submission(
    db: AsyncSession, payload: FormSubmissionCreate, user_id: uuid.UUID
) -> FormSubmissionOut:
    facility_id = await actor_facility(db, user_id)
    await require_patient_scope(db, payload.patient_id, facility_id)
    await require_visit_scope(db, payload.visit_id, payload.patient_id, facility_id)
    f_res = await db.execute(select(FormDefinition).where(FormDefinition.id == payload.form_id))
    form = f_res.scalar_one_or_none()
    if not form or form.status != "published":
        raise ValueError(f"Form definition {payload.form_id} not found")

    # Existing schema versions are not silently rewritten. Refuse malformed
    # legacy definitions and require administrator review before new submissions.
    try:
        fields = [FormFieldDef.model_validate(field) for field in form.fields_schema]
        if not fields or len({field.id for field in fields}) != len(fields):
            raise ValueError("Invalid field definitions")
    except ValueError as exc:
        raise HTTPException(409, {
            "code": "form_schema_unavailable",
            "message": "This form definition requires administrator review",
        }) from exc
    validate_submission(fields, payload.form_data)

    sub = FormSubmission(
        id=uuid.uuid4(),
        patient_id=payload.patient_id,
        visit_id=payload.visit_id,
        form_id=form.id,
        form_version=form.version,
        form_data=payload.form_data,
        submitted_by=user_id,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return FormSubmissionOut.model_validate(sub)


async def list_patient_submissions(
    db: AsyncSession, patient_id: uuid.UUID
) -> list[FormSubmissionOut]:
    res = await db.execute(
        select(FormSubmission)
        .where(FormSubmission.patient_id == patient_id)
        .order_by(FormSubmission.submitted_at.desc())
    )
    return [FormSubmissionOut.model_validate(s) for s in res.scalars().all()]


async def list_order_sets(
    db: AsyncSession, category: str | None = None
) -> list[ClinicalOrderSetOut]:
    query = select(ClinicalOrderSet).where(ClinicalOrderSet.is_active == True).order_by(ClinicalOrderSet.title)
    if category:
        query = query.where(ClinicalOrderSet.category == category.strip())
    res = await db.execute(query)
    return [ClinicalOrderSetOut.model_validate(o) for o in res.scalars().all()]


async def apply_order_set(
    db: AsyncSession, code: str, patient_id: uuid.UUID, visit_id: uuid.UUID, user_id: uuid.UUID
) -> ApplyOrderSetResult:
    facility_id = await actor_facility(db, user_id)
    await require_patient_scope(db, patient_id, facility_id)
    await require_visit_scope(db, visit_id, patient_id, facility_id)
    p_res = await db.execute(select(Patient).where(Patient.id == patient_id))
    if not p_res.scalar_one_or_none():
        raise ValueError(f"Patient {patient_id} not found")

    v_res = await db.execute(select(Visit).where(Visit.id == visit_id))
    if not v_res.scalar_one_or_none():
        raise ValueError(f"Visit {visit_id} not found")

    os_res = await db.execute(select(ClinicalOrderSet).where(ClinicalOrderSet.code == code.strip()))
    order_set = os_res.scalar_one_or_none()
    if not order_set:
        raise ValueError(f"Order set {code} not found")

    # Free-text protocols have no validated order catalogue mapping. Never
    # claim orders were placed until the real transactional writer exists.
    raise HTTPException(409, {"code": "order_set_execution_unavailable",
        "message": "Order sets are preview-only. Place individual orders through the clinical order workflow."})


def sanitize_csv_cell(value: str) -> str:
    """Escape spreadsheet formula injection characters (=, +, -, @, \\t, \\r)."""
    val_str = str(value)
    if val_str and val_str.startswith(FORMULA_INJECTION_PREFIXES):
        return "'" + val_str
    return val_str


def validate_csv(csv_content: str, entity_type: str) -> CsvValidationResult:
    errors: list[str] = []
    warnings: list[str] = []
    if entity_type != "vaccines":
        errors.append("CSV import is only implemented for vaccines")
    if not csv_content.strip():
        return CsvValidationResult(
            valid=False,
            entity_type=entity_type,
            row_count=0,
            columns=[],
            errors=["CSV content is empty"],
        )

    f = io.StringIO(csv_content.strip())
    reader = csv.reader(f)
    try:
        headers = next(reader, None)
    except Exception as exc:
        return CsvValidationResult(
            valid=False,
            entity_type=entity_type,
            row_count=0,
            columns=[],
            errors=[f"Failed to parse CSV: {exc}"],
        )

    if not headers:
        return CsvValidationResult(
            valid=False,
            entity_type=entity_type,
            row_count=0,
            columns=[],
            errors=["Missing header row"],
        )

    rows = list(reader)
    required = {"code", "name", "target_disease", "standard_doses", "min_age_days", "route", "site", "dose_quantity"}
    if entity_type == "vaccines" and not required.issubset(headers):
        errors.append("Missing columns: " + ", ".join(sorted(required - set(headers))))
    if len(headers) != len(set(headers)):
        errors.append("Duplicate column names are not allowed")
    if not rows:
        errors.append("CSV contains no data rows")
    codes: set[str] = set()
    # Check for formula injection attempts
    for r_idx, row in enumerate(rows, start=2):
        if len(row) != len(headers):
            errors.append(f"Row {r_idx}: column count does not match header")
        if entity_type == "vaccines" and required.issubset(headers):
            values = dict(zip(headers, row))
            if any(not values.get(key, "").strip() for key in required):
                errors.append(f"Row {r_idx}: required vaccine value is blank")
            code = values.get("code", "").strip()
            if code in codes:
                errors.append(f"Row {r_idx}: duplicate vaccine code")
            codes.add(code)
            try:
                if int(values.get("standard_doses", "")) < 1 or int(values.get("min_age_days", "")) < 0:
                    raise ValueError
            except ValueError:
                errors.append(f"Row {r_idx}: invalid dose count or minimum age")
        for c_idx, cell in enumerate(row):
            if cell.lstrip().startswith(FORMULA_INJECTION_PREFIXES):
                errors.append(f"Row {r_idx} Column {c_idx+1}: formula-like values are not accepted")
                warnings.append(
                    f"Row {r_idx} Column {c_idx+1} ({headers[c_idx] if c_idx < len(headers) else ''}) "
                    f"contains formula injection prefix: '{cell[:5]}...'"
                )

    return CsvValidationResult(
        valid=len(errors) == 0,
        entity_type=entity_type,
        row_count=len(rows),
        columns=headers,
        errors=errors,
        warnings=warnings,
    )


async def import_csv(
    csv_content: str, entity_type: str, db: AsyncSession, user_id: uuid.UUID
) -> CsvImportResult:
    val = validate_csv(csv_content, entity_type)
    if not val.valid:
        raise ValueError("; ".join(val.errors))

    f = io.StringIO(csv_content.strip())
    reader = csv.DictReader(f)
    imported = 0

    if entity_type == "vaccines":
        for row in reader:
            code = row.get("code", "").strip()
            name = row.get("name", "").strip()
            disease = row.get("target_disease", "").strip()
            if not code or not name:
                continue
            # Sanitized values
            clean_code = code.lstrip("=+-@\t\r")
            existing = await db.execute(select(VaccineCatalogue).where(VaccineCatalogue.code == clean_code))
            if not existing.scalar_one_or_none():
                vc = VaccineCatalogue(
                    code=clean_code,
                    name=name.lstrip("=+-@\t\r"),
                    target_disease=disease.lstrip("=+-@\t\r") or "General",
                    standard_doses=int(row.get("standard_doses", 1)),
                    min_age_days=int(row.get("min_age_days", 0)),
                    route=row.get("route", "intramuscular"),
                    site=row.get("site", "left_upper_arm"),
                    dose_quantity=row.get("dose_quantity", "0.5 ml"),
                )
                db.add(vc)
                imported += 1
        await db.commit()
    else:
        raise ValueError("CSV import is not implemented for this entity")

    return CsvImportResult(
        entity_type=entity_type,
        imported_count=imported,
        message=f"Successfully sanitized and imported {imported} records for {entity_type}",
    )


async def export_csv(entity_type: str, db: AsyncSession) -> str:
    out = io.StringIO()
    writer = csv.writer(out)

    if entity_type == "vaccines":
        writer.writerow(["code", "name", "target_disease", "standard_doses", "min_age_days", "route", "site", "dose_quantity"])
        res = await db.execute(select(VaccineCatalogue).order_by(VaccineCatalogue.code))
        for v in res.scalars().all():
            writer.writerow([
                sanitize_csv_cell(v.code),
                sanitize_csv_cell(v.name),
                sanitize_csv_cell(v.target_disease),
                v.standard_doses,
                v.min_age_days,
                sanitize_csv_cell(v.route),
                sanitize_csv_cell(v.site),
                sanitize_csv_cell(v.dose_quantity),
            ])
    elif entity_type == "order_sets":
        writer.writerow(["code", "title", "category", "orders_count"])
        res = await db.execute(select(ClinicalOrderSet).order_by(ClinicalOrderSet.code))
        for o in res.scalars().all():
            writer.writerow([
                sanitize_csv_cell(o.code),
                sanitize_csv_cell(o.title),
                sanitize_csv_cell(o.category),
                len(o.orders),
            ])
    else:
        raise ValueError("CSV export is not implemented for this entity")

    return out.getvalue()
