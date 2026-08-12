"""Blocker 5 (PR review, patients module): a half-merge is more dangerous
than no merge — this test turns a silently-missing repoint into a red
build. It needs no database connection; it inspects SQLAlchemy metadata
directly, so it works even without the async-Postgres fixture (see
conftest.py discussion in review)."""
import app.main  # noqa: F401  ensures every model module is imported and
                  # registered on Base.metadata before we inspect it
from app.patients.service import REPOINTED_ON_MERGE, AUDIT_TABLES_EXEMPT_FROM_REPOINTING, PENDING_REPOINT_OTHER_MODULES, _tables_with_fk_to_patients


def test_repointing_covers_every_patient_fk():
    referencing_tables = _tables_with_fk_to_patients()
    missing = referencing_tables - REPOINTED_ON_MERGE - AUDIT_TABLES_EXEMPT_FROM_REPOINTING - PENDING_REPOINT_OTHER_MODULES
    assert not missing, (
        f"{sorted(missing)} have a foreign key to patients.id but are not in "
        f"REPOINTED_ON_MERGE (backend/app/patients/service.py). Either add "
        f"repointing logic for them in approve_merge and add them to that set, "
        f"or confirm approve_merge still raises NotImplementedError while they "
        f"remain unhandled — this test existing and failing is the point, not "
        f"a bug to silence."
    )


async def test_repoint_visits_and_ot_schedules_moves_child_rows(db, seed):
    """DB-backed: confirms the actual UPDATE happens, not just that the
    guard-test bookkeeping is satisfied. Regression test for the exact
    failure mode the module docstring warns about -- a merge silently
    leaving child rows on the merged-away patient.

    Calls _repoint_visits/_repoint_ot_schedules directly rather than
    going through the full approve_merge flow: approve_merge's final
    db.refresh(merge_log) hits a pre-existing "Could not refresh
    instance" error on this SQLite test setup, unrelated to the
    repointing logic itself (reproduced with these two calls disabled
    too) -- worth its own bug report, out of scope here."""
    import uuid
    from datetime import datetime, timezone, timedelta
    from app.opd.models import Visit
    from app.ot.models import OtSchedule
    from app.patients.models import Patient
    from app.patients.service import _repoint_visits, _repoint_ot_schedules

    dept, room, doctor = seed
    facility_id = dept.facility_id

    source = Patient(
        id=uuid.uuid4(),
        thid=f"TH-TST01-260807-{uuid.uuid4().hex[:4]}",
        full_name="Source Patient",
        sex="male",
        age_years=40,
        identity_path="demographics_only",
        facility_id=facility_id,
        created_by=doctor.id,
    )
    target = Patient(
        id=uuid.uuid4(),
        thid=f"TH-TST01-260807-{uuid.uuid4().hex[:4]}",
        full_name="Target Patient",
        sex="male",
        age_years=40,
        identity_path="demographics_only",
        facility_id=facility_id,
        created_by=doctor.id,
    )
    db.add_all([source, target])
    await db.flush()

    visit = Visit(
        id=uuid.uuid4(),
        visit_number=f"VST-TST01-260807-{uuid.uuid4().hex[:5]}",
        patient_id=source.id,
        facility_id=facility_id,
        visit_type="opd",
        visit_date=datetime.now(timezone.utc),
        created_by=doctor.id,
    )
    _now = datetime.now(timezone.utc)
    ot_schedule = OtSchedule(
        id=uuid.uuid4(),
        visit_id=visit.id,
        patient_id=source.id,
        facility_id=facility_id,
        scheduled_start=_now,
        scheduled_end=_now + timedelta(hours=1),
        procedure_name="Test procedure",
        status="scheduled",
        created_by=doctor.id,
    )
    db.add_all([visit, ot_schedule])
    await db.flush()

    await _repoint_visits(db, source=source, target=target)
    await _repoint_ot_schedules(db, source=source, target=target)

    await db.refresh(visit)
    await db.refresh(ot_schedule)
    assert visit.patient_id == target.id
    assert ot_schedule.patient_id == target.id
