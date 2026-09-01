"""Seed a realistic day of clinic activity for demonstration.

WHY THIS IS SEPARATE FROM seed_dev_data.py

That script seeds the SCAFFOLDING a developer needs: one facility, thirteen
users, a department, a room, a roster, a tariff. This one seeds the WORK — a
day of patients moving through OPD, IPD and day care with orders, results,
prescriptions and theatre bookings behind them, so every role has something
real on screen when someone logs in.

They are kept apart because they have different lifetimes. The scaffolding must
exist for the app to function at all; this is disposable, and `--reset` throws
it away without touching the facility, users or tariff everything depends on.

WHAT IT DELIBERATELY DOES NOT DO

It writes through the database with every CHECK, foreign key and NOT NULL in
force — a demo dataset that bypassed constraints could show states the
application can never actually produce, which is worse than no data. It does
not drive the HTTP API: that would need a browser login per role for a script
that has to re-run in seconds before a demo.

Run:
  docker compose -f infra/docker-compose.yml --env-file .env exec -T backend \
    python -m scripts.seed_demo_clinic --reset
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Importing app.main registers every mapped model. Without it SQLAlchemy
# cannot resolve visits.department_id -> departments and raises
# NoReferencedTableError on the first flush — the FK targets a table whose
# model was never imported.
import app.main  # noqa: F401
from app.admissions.models import Admission, Bed, Ward
from app.billing.service import create_registration_invoice
from app.common.db import SessionLocal
from app.opd.models import Visit
from app.patients.models import Patient
from app.users.models import Facility, User

#: Every row this script creates carries it, so --reset finds its own work and
#: nothing else. A reset that guessed by date would take the dev fixtures too.
DEMO_TAG = "DEMOCLINIC"
SEED = 20260901  # fixed, so two runs of the same demo look the same
#: Enough beds that every admitted patient in PEOPLE gets one, with room to
#: admit another live during the demo.
BEDS_WANTED = 8

PEOPLE = [
    ("Aarti Deshmukh",  "female", 34, "opd",         "follow-up: thyroid review"),
    ("Rakesh Bhatia",   "male",   58, "opd",         "re-consultation: chest pain, second visit"),
    ("Sunita Rao",      "female", 41, "day_care",    "day care: upper GI endoscopy"),
    ("Imran Qureshi",   "male",   29, "opd",         "new: fever with rash"),
    ("Meera Iyer",      "female", 67, "ipd",         "admitted: pneumonia, day 2"),
    ("Vikram Chauhan",  "male",   45, "day_care",    "day care: haemodialysis session"),
    ("Fatima Sheikh",   "female", 52, "ipd",         "admitted: post-operative recovery"),
    ("Joseph Mathew",   "male",   38, "opd",         "follow-up: fracture review, 6 weeks"),
    ("Kavya Nair",      "female", 26, "teleconsult", "teleconsult: dermatology"),
    ("Harpreet Singh",  "male",   71, "emergency",   "emergency: fall, head injury"),
]

#: (test_code, display name, sample). The CODE must exist in
#: billing/pricing.py::_LAB_TEST_PRICES or the charge aggregates as an unpriced
#: line and build_invoice skips it — the bill would silently come out short.
LAB_TESTS = [("CBC", "Complete Blood Count", "blood"),
             ("LFT", "Liver Function Test", "blood"),
             ("KFT", "Kidney Function Test", "blood"),
             ("URINE_RE", "Urine Routine", "urine"),
             ("BLOOD_SUGAR_F", "Blood Sugar (Fasting)", "blood")]
#: Modality is lowercase for the same reason: _RADIOLOGY_MODALITY_PRICES keys
#: are lowercase, and a case mismatch prices at nothing.
SCANS = [("xray", "Chest PA view"), ("ct", "CT head plain"),
         ("usg", "Ultrasound abdomen"), ("mri", "MRI lumbar spine")]
THEATRE = [("Upper GI endoscopy", 30), ("Arteriovenous fistula check", 45),
           ("Wound debridement", 60)]


async def _reset(db: AsyncSession) -> dict[str, int]:
    """Remove only this script's rows, children before parents."""
    ids = [r[0] for r in (await db.execute(
        select(Patient.id).where(Patient.address_line == DEMO_TAG))).all()]
    counts: dict[str, int] = {}
    if not ids:
        return counts
    visit_ids = [r[0] for r in (await db.execute(
        select(Visit.id).where(Visit.patient_id.in_(ids)))).all()]

    order_sub = "SELECT id FROM orders WHERE patient_id = ANY(:ids)"
    for stmt, params in [
        (f"DELETE FROM lab_results WHERE lab_order_item_id IN (SELECT id FROM lab_order_items WHERE order_id IN ({order_sub}))", {"ids": ids}),
        (f"DELETE FROM radiology_reports WHERE radiology_order_item_id IN (SELECT id FROM radiology_order_items WHERE order_id IN ({order_sub}))", {"ids": ids}),
        (f"DELETE FROM lab_order_items WHERE order_id IN ({order_sub})", {"ids": ids}),
        (f"DELETE FROM radiology_order_items WHERE order_id IN ({order_sub})", {"ids": ids}),
        ("DELETE FROM prescriptions WHERE patient_id = ANY(:ids)", {"ids": ids}),
        ("DELETE FROM ot_schedules WHERE patient_id = ANY(:ids)", {"ids": ids}),
        ("DELETE FROM orders WHERE patient_id = ANY(:ids)", {"ids": ids}),
        ("DELETE FROM invoice_items WHERE invoice_id IN (SELECT id FROM invoices WHERE patient_id = ANY(:ids))", {"ids": ids}),
        ("DELETE FROM payments WHERE invoice_id IN (SELECT id FROM invoices WHERE patient_id = ANY(:ids))", {"ids": ids}),
        ("DELETE FROM invoices WHERE patient_id = ANY(:ids)", {"ids": ids}),
    ]:
        counts[stmt.split()[2]] = (await db.execute(text(stmt), params)).rowcount or 0

    if visit_ids:
        for t in ("queue_tokens", "encounters"):
            counts[t] = (await db.execute(
                text(f"DELETE FROM {t} WHERE visit_id = ANY(:v)"), {"v": visit_ids})).rowcount or 0

    # Free only the beds THIS script occupied. The blanket
    # "UPDATE beds SET status='vacant'" this replaced marked every bed in the
    # hospital free, including one holding a real admission from the dev seed —
    # so the status column said vacant while uq_admissions_active_bed still
    # (correctly) refused to reuse it.
    freed = [r[0] for r in (await db.execute(
        select(Admission.bed_id).where(Admission.patient_id.in_(ids)))).all()]
    counts["admissions"] = (await db.execute(
        delete(Admission).where(Admission.patient_id.in_(ids)))).rowcount or 0
    if freed:
        await db.execute(
            text("UPDATE beds SET status='vacant' WHERE id = ANY(:b)"), {"b": freed})
    counts["visits"] = (await db.execute(
        delete(Visit).where(Visit.patient_id.in_(ids)))).rowcount or 0
    counts["patients"] = (await db.execute(
        delete(Patient).where(Patient.id.in_(ids)))).rowcount or 0
    return counts


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="delete this script's previous rows first")
    ap.add_argument("--count", type=int, default=len(PEOPLE))
    args = ap.parse_args()

    rng = random.Random(SEED)
    now = datetime.now(UTC)

    async with SessionLocal() as db:
        facility = (await db.execute(
            select(Facility).where(Facility.code == "DEV001"))).scalar_one_or_none()
        doctor = (await db.execute(
            select(User).where(User.username == "dev.doctor"))).scalar_one_or_none()
        reception = (await db.execute(
            select(User).where(User.username == "dev.receptionist"))).scalar_one_or_none()
        # Results are authored by the technicians, not the ordering doctor, so
        # the audit trail reads the way it would in the hospital.
        labtech = (await db.execute(
            select(User).where(User.username == "dev.labtech"))).scalar_one_or_none()
        radiographer = (await db.execute(
            select(User).where(User.username == "dev.radiology"))).scalar_one_or_none()
        if not (facility and doctor and reception and labtech and radiographer):
            print("✗ DEV001 facility or dev users missing — run `make setup` first.")
            return 1
        labtech_id, radiographer_id = labtech.id, radiographer.id

        if args.reset:
            removed = await _reset(db)
            await db.commit()
            print("Reset removed: " + (", ".join(f"{v} {k}" for k, v in removed.items() if v)
                                       or "nothing from a previous run"))

        # The dev seed provides one ward with a single bed, which is enough to
        # prove the schema and not enough to demonstrate a ward. Top it up to
        # BEDS_WANTED so every bed-occupying patient below gets one — a demo
        # where three of four admissions read "NO FREE BED" shows a constraint
        # working and a hospital that cannot admit anybody.
        ward = (await db.execute(
            select(Ward).where(Ward.facility_id == facility.id))).scalars().first()
        if ward is None:
            ward = Ward(id=uuid.uuid4(), facility_id=facility.id,
                        department_id=None, name="Demo Ward")
            db.add(ward)
            await db.flush()

        beds = list((await db.execute(
            select(Bed).where(Bed.ward_id == ward.id))).scalars().all())
        for n in range(len(beds), BEDS_WANTED):
            bed = Bed(id=uuid.uuid4(), ward_id=ward.id, bed_number=f"B{n + 1:02d}",
                      status="vacant")
            db.add(bed)
            beds.append(bed)
        await db.flush()

        occupied = {
            r[0] for r in (await db.execute(
                select(Admission.bed_id).where(
                    Admission.status.in_(("admitted", "transferred"))))).all()
        }
        # Truth is "has no active admission", not beds.status — the column is a
        # projection and a stale one strands the bed for the whole demo.
        free_beds = [b for b in beds if b.id not in occupied]
        made: list[dict] = []
        for i, (name, sex, age, vtype, story) in enumerate(PEOPLE[: args.count]):
            patient = Patient(
                id=uuid.uuid4(), facility_id=facility.id, full_name=name, sex=sex,
                age_years=age, mobile=f"98{rng.randint(10**8, 10**9 - 1)}",
                address_line=DEMO_TAG, uhid=f"IN-DL-DEV001-2026-9{i:04d}-0",
                identity_path="demographics_only", identity_status="identity_unverified",
                created_by=reception.id,
            )
            db.add(patient)
            await db.flush()

            visit = Visit(
                id=uuid.uuid4(), patient_id=patient.id, facility_id=facility.id,
                visit_number=f"VST-DEMO-{now:%Y%m%d}-{i:04d}", visit_type=vtype,
                status="in_service", visit_date=now - timedelta(hours=rng.randint(1, 6)),
                created_by=reception.id,
            )
            db.add(visit)
            await db.flush()

            # Billing's preview/build endpoints 404 without this row: invoices
            # are raised at registration, never by the billing screen. Calling
            # the real service rather than inserting an Invoice here keeps the
            # registration line, the invoice number series and the charge-master
            # lookup identical to a patient registered through the desk — which
            # is the whole point, since the demo asks billing to produce a final
            # bill from these visits.
            await create_registration_invoice(
                db,
                visit_id=visit.id,
                patient_id=patient.id,
                facility_id=facility.id,
                business_date=visit.visit_date.date(),
                created_by=reception.id,
            )

            row = {"patient": name, "uhid": patient.uhid, "visit": visit.visit_number,
                   "type": vtype, "story": story, "labs": 0, "scans": 0, "drugs": 0,
                   "theatre": 0, "encounters": 0, "bed": "—"}

            # uq_admissions_active_bed allows one active admission per bed, so
            # beds are consumed from a pool rather than indexed by patient —
            # `beds[i % len(beds)]` double-books as soon as there are more
            # bed-occupying patients than beds, which the constraint correctly
            # refuses. Running out is reported, not worked around.
            if vtype in ("ipd", "day_care") and free_beds:
                bed = free_beds.pop(0)
                db.add(Admission(
                    id=uuid.uuid4(), visit_id=visit.id, patient_id=patient.id,
                    ward_id=ward.id, bed_id=bed.id, admitted_at=visit.visit_date,
                    status="admitted", reason=story, created_by=doctor.id))
                bed.status = "occupied"
                row["bed"] = f"{ward.name} / {bed.bed_number}"
            elif vtype in ("ipd", "day_care"):
                row["bed"] = "NO FREE BED"

            # Two consultations where the story is a follow-up or a
            # re-consultation, so the doctor's history has something to be a
            # history OF. One otherwise.
            n_enc = 2 if ("follow-up" in story or "re-consultation" in story) else 1
            last_encounter = None
            for n in range(n_enc):
                last_encounter = uuid.uuid4()
                await db.execute(text(
                    "INSERT INTO encounters (id, visit_id, provider_user_id, facility_id,"
                    " note_status, created_by, created_at, updated_at)"
                    " VALUES (:id, :v, :p, :f, :s, :u, :t, :t)"),
                    {"id": last_encounter, "v": visit.id, "p": doctor.id, "f": facility.id,
                     "s": "stored", "u": doctor.id,  # outbox state, not a clinical status
                     "t": visit.visit_date + timedelta(minutes=15 * n)})
                row["encounters"] += 1

            lab_order = uuid.uuid4()
            await db.execute(text(
                "INSERT INTO orders (id, order_number, encounter_id, patient_id, order_type,"
                " priority, status, ordered_at, facility_id, fulfilment_mode, created_by,"
                " created_at, updated_at) VALUES (:id, :num, :e, :p, 'lab', 'routine',"
                " 'placed', :t, :f, 'internal', :u, :t, :t)"),
                {"id": lab_order, "num": f"ORD-DEMO-L{i:04d}", "e": last_encounter,
                 "p": patient.id, "t": visit.visit_date, "f": facility.id, "u": doctor.id})
            for j in range(rng.randint(1, 3)):
                code, test, sample = rng.choice(LAB_TESTS)
                item_id = uuid.uuid4()
                item_status = ("placed", "accepted", "completed")[j % 3]
                await db.execute(text(
                    "INSERT INTO lab_order_items (id, order_id, accession_number, test_code,"
                    " test_name, sample_type, status, created_by, created_at, updated_at)"
                    " VALUES (:id, :o, :acc, :c, :t, :s, :st, :u, :ts, :ts)"),
                    {"id": item_id, "o": lab_order, "acc": f"LAB{i:03d}{j}", "c": code,
                     "t": test, "s": sample, "st": item_status,
                     "u": doctor.id, "ts": visit.visit_date})
                row["labs"] += 1

                # Billing charges a RESULTED test, never an ordered one
                # (_aggregate_lab_charges requires a current final/corrected
                # result). Only the completed items get one, so the lab tech
                # still has live work to do on screen — and billing has
                # something real to bill before anyone touches anything.
                if item_status == "completed":
                    await db.execute(text(
                        "INSERT INTO lab_results (id, lab_order_item_id, version, is_current,"
                        " result_data, status, created_by, created_at, updated_at)"
                        " VALUES (:id, :i, 1, true, CAST(:d AS jsonb), 'final', :u, :ts, :ts)"),
                        {"id": uuid.uuid4(), "i": item_id,
                         "d": '{"value": "within reference range"}',
                         "u": labtech_id, "ts": visit.visit_date + timedelta(hours=1)})
                    row["lab_results"] = row.get("lab_results", 0) + 1

            if rng.random() < 0.6:
                rad_order = uuid.uuid4()
                await db.execute(text(
                    "INSERT INTO orders (id, order_number, encounter_id, patient_id, order_type,"
                    " priority, status, ordered_at, facility_id, fulfilment_mode, created_by,"
                    " created_at, updated_at) VALUES (:id, :num, :e, :p, 'radiology', 'routine',"
                    " 'placed', :t, :f, 'internal', :u, :t, :t)"),
                    {"id": rad_order, "num": f"ORD-DEMO-R{i:04d}", "e": last_encounter,
                     "p": patient.id, "t": visit.visit_date, "f": facility.id, "u": doctor.id})
                modality, scan = rng.choice(SCANS)
                scan_id = uuid.uuid4()
                reported = i % 2 == 0   # half reported, half still on the worklist
                await db.execute(text(
                    "INSERT INTO radiology_order_items (id, order_id, accession_number, modality,"
                    " scan_type, status, created_by, created_at, updated_at)"
                    " VALUES (:id, :o, :acc, :m, :s, :st, :u, :ts, :ts)"),
                    {"id": scan_id, "o": rad_order, "acc": f"RAD{i:03d}", "m": modality,
                     "s": scan, "st": "released" if reported else "scheduled",
                     "u": doctor.id, "ts": visit.visit_date})
                row["scans"] += 1

                # Same rule as pathology: billable once reported, not once
                # ordered (_aggregate_radiology_charges requires a current
                # final/corrected report).
                if reported:
                    await db.execute(text(
                        "INSERT INTO radiology_reports (id, radiology_order_item_id, version,"
                        " is_current, findings, impression, status, created_by,"
                        " created_at, updated_at)"
                        " VALUES (:id, :i, 1, true, :f, :imp, 'final', :u, :ts, :ts)"),
                        {"id": uuid.uuid4(), "i": scan_id,
                         "f": "No acute abnormality identified.",
                         "imp": "Study within normal limits.",
                         "u": radiographer_id, "ts": visit.visit_date + timedelta(hours=2)})
                    row["rad_reports"] = row.get("rad_reports", 0) + 1

            for _ in range(rng.randint(1, 3)):
                await db.execute(text(
                    "INSERT INTO prescriptions (id, encounter_id, patient_id, facility_id,"
                    " created_by, created_at, updated_at) VALUES (:id, :e, :p, :f, :u, :t, :t)"),
                    {"id": uuid.uuid4(), "e": last_encounter, "p": patient.id,
                     "f": facility.id, "u": doctor.id, "t": visit.visit_date})
                row["drugs"] += 1

            if vtype == "day_care" or "post-operative" in story:
                proc, mins = rng.choice(THEATRE)
                start = visit.visit_date + timedelta(hours=1)
                await db.execute(text(
                    "INSERT INTO ot_schedules (id, visit_id, patient_id, facility_id,"
                    " scheduled_start, scheduled_end, procedure_name, status, created_by,"
                    " created_at, updated_at) VALUES (:id, :v, :p, :f, :s, :e, :n,"
                    " 'scheduled', :u, :t, :t)"),
                    {"id": uuid.uuid4(), "v": visit.id, "p": patient.id, "f": facility.id,
                     "s": start, "e": start + timedelta(minutes=mins), "n": proc,
                     "u": doctor.id, "t": visit.visit_date})
                row["theatre"] += 1

            made.append(row)

        await db.commit()

    print(f"\nSeeded {len(made)} demo patients at DEV001\n")
    head = (f"{'PATIENT':<19}{'TYPE':<12}{'VISIT':<25}"
            f"{'ENC':>4}{'LAB':>5}{'RAD':>5}{'RX':>4}{'OT':>4}  BED")
    print(head)
    print("-" * len(head))
    for r in made:
        print(f"{r['patient']:<19}{r['type']:<12}{r['visit']:<25}"
              f"{r['encounters']:>4}{r['labs']:>5}{r['scans']:>5}"
              f"{r['drugs']:>4}{r['theatre']:>4}  {r['bed']}")
    print("\nWhat each patient is here for:")
    for r in made:
        print(f"  {r['uhid']:<26} {r['patient']:<19} {r['story']}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
