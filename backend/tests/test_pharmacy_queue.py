import uuid
from datetime import datetime

from app.pharmacy.service import get_prescription_queue
from tests.conftest import FakeResult


async def test_prescription_queue_default_excludes_dispensed_and_cancelled(fake_session):
    facility_id = uuid.uuid4()
    row = {
        "prescription_id": uuid.uuid4(), "patient_id": uuid.uuid4(),
        "patient_full_name": "Asha Devi", "uhid": "UH123", "thid": None,
        "visit_id": uuid.uuid4(), "encounter_id": uuid.uuid4(),
        "prescribed_at": datetime(2026, 7, 26, 9, 0), "item_count": 3,
        "dispense_status": None,
    }
    fake_session.expect("SELECT count(*)", FakeResult(scalar=1))
    fake_session.expect("SELECT\n            p.id AS prescription_id", FakeResult(rows=[row]))

    result = await get_prescription_queue(
        fake_session, facility_id=facility_id, department_id=None,
        status=None, page=1, page_size=20,
    )

    assert result.total == 1
    assert result.items[0].patient_full_name == "Asha Devi"
    count_sql = fake_session.calls[0][0]
    assert "NOT IN ('dispensed', 'cancelled')" in count_sql


async def test_prescription_queue_explicit_status_filters_instead_of_default(fake_session):
    fake_session.expect("SELECT count(*)", FakeResult(scalar=0))
    fake_session.expect("SELECT\n            p.id AS prescription_id", FakeResult(rows=[]))

    await get_prescription_queue(
        fake_session, facility_id=uuid.uuid4(), department_id=None,
        status="dispensed", page=1, page_size=20,
    )

    count_sql, params = fake_session.calls[0]
    assert "pd.status = :status" in count_sql
    assert "NOT IN ('dispensed', 'cancelled')" not in count_sql
    assert params["status"] == "dispensed"


async def test_prescription_queue_page_size_is_capped_at_100(fake_session):
    fake_session.expect("SELECT count(*)", FakeResult(scalar=0))
    fake_session.expect("SELECT\n            p.id AS prescription_id", FakeResult(rows=[]))

    result = await get_prescription_queue(
        fake_session, facility_id=uuid.uuid4(), department_id=None,
        status=None, page=1, page_size=500,
    )

    assert result.page_size == 100
    _, params = fake_session.calls[-1]
    assert params["limit"] == 100


async def test_prescription_queue_department_filter_adds_join_condition(fake_session):
    department_id = uuid.uuid4()
    fake_session.expect("SELECT count(*)", FakeResult(scalar=0))
    fake_session.expect("SELECT\n            p.id AS prescription_id", FakeResult(rows=[]))

    await get_prescription_queue(
        fake_session, facility_id=uuid.uuid4(), department_id=department_id,
        status=None, page=1, page_size=20,
    )

    count_sql, params = fake_session.calls[0]
    assert "e.department_id = :department_id" in count_sql
    assert params["department_id"] == str(department_id)
