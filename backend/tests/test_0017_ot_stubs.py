"""Tests for migration/module 0017 (ot_schedules, ot_records) -- B3-W1-02 (#137).

The DB-backed insert/constraint tests for this module need
app.opd.models.Visit (lands in 0007, still unmerged) and db_session /
fake_facility / fake_user_row fixtures that don't exist in
tests/conftest.py yet. Rather than importing them here and aborting
collection for the whole suite, this file is metadata-only for now.
The DB-backed tests will be restored once 0007 merges and the shared
async-DB fixture is agreed (see #271, #265).
"""


def test_ot_tables_registered_on_base_metadata():
    from app.common.db import Base
    from app.ot.models import OtSchedule, OtRecord  # noqa: F401

    assert "ot_schedules" in Base.metadata.tables
    assert "ot_records" in Base.metadata.tables


def test_ot_schedules_has_expected_columns():
    from app.common.db import Base
    from app.ot import models  # noqa: F401

    columns = {c.name for c in Base.metadata.tables["ot_schedules"].columns}
    assert {
        "id",
        "visit_id",
        "patient_id",
        "facility_id",
        "scheduled_start",
        "scheduled_end",
        "procedure_name",
        "status",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    } <= columns


def test_ot_records_has_expected_columns():
    from app.common.db import Base
    from app.ot import models  # noqa: F401

    columns = {c.name for c in Base.metadata.tables["ot_records"].columns}
    assert {
        "id",
        "ot_schedule_id",
        "started_at",
        "ended_at",
        "surgeon_user_id",
        "anesthetist_user_id",
        "notes",
        "created_at",
        "updated_at",
    } <= columns
