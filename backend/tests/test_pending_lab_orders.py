"""Tests for task 8's pending lab orders (HOD dashboard). Tested
directly against the service layer, no HTTP/JWT needed.
"""
import uuid
from datetime import date

import pytest

from app.common.enums import OrderStatus
from app.departments.models import Department
from app.pathology.models import LabOrderItem
from app.queue import service
from app.users.models import Facility

pytestmark = pytest.mark.asyncio


async def _make_facility_and_department(db):
    facility_id = uuid.uuid4()
    department_id = uuid.uuid4()
    db.add(Facility(id=facility_id, code=f"F{uuid.uuid4().hex[:4]}", name="Test Facility", state_code="TS"))
    db.add(Department(id=department_id, code=f"D{uuid.uuid4().hex[:4]}", name="Test Dept", facility_id=facility_id))
    await db.flush()
    return facility_id, department_id


async def test_pending_lab_orders_excludes_completed_and_cancelled(db):
    facility_id, department_id = await _make_facility_and_department(db)
    order_id = uuid.uuid4()
    creator_id = uuid.uuid4()

    db.add_all([
        LabOrderItem(
            id=uuid.uuid4(), order_id=order_id, accession_number=f"LAB-{uuid.uuid4().hex[:8]}",
            test_name="CBC", sample_type="blood", department_id=department_id,
            status=OrderStatus.PLACED.value, created_by=creator_id,
        ),
        LabOrderItem(
            id=uuid.uuid4(), order_id=order_id, accession_number=f"LAB-{uuid.uuid4().hex[:8]}",
            test_name="Lipid Profile", sample_type="blood", department_id=department_id,
            status=OrderStatus.IN_PROGRESS.value, created_by=creator_id,
        ),
        LabOrderItem(
            id=uuid.uuid4(), order_id=order_id, accession_number=f"LAB-{uuid.uuid4().hex[:8]}",
            test_name="Blood Sugar", sample_type="blood", department_id=department_id,
            status=OrderStatus.COMPLETED.value, created_by=creator_id,
        ),
        LabOrderItem(
            id=uuid.uuid4(), order_id=order_id, accession_number=f"LAB-{uuid.uuid4().hex[:8]}",
            test_name="Urine Test", sample_type="urine", department_id=department_id,
            status=OrderStatus.CANCELLED.value, created_by=creator_id,
        ),
    ])
    await db.flush()

    result = await service.get_pending_lab_orders(db, department_id, facility_id)

    assert len(result) == 2
    test_names = {item["test_name"] for item in result}
    assert test_names == {"CBC", "Lipid Profile"}


async def test_pending_lab_orders_scoped_by_department(db):
    facility_id, dept_a = await _make_facility_and_department(db)
    _facility_id_b, dept_b = await _make_facility_and_department(db)
    order_id = uuid.uuid4()
    creator_id = uuid.uuid4()

    db.add_all([
        LabOrderItem(
            id=uuid.uuid4(), order_id=order_id, accession_number=f"LAB-{uuid.uuid4().hex[:8]}",
            test_name="CBC", sample_type="blood", department_id=dept_a,
            status=OrderStatus.PLACED.value, created_by=creator_id,
        ),
        LabOrderItem(
            id=uuid.uuid4(), order_id=order_id, accession_number=f"LAB-{uuid.uuid4().hex[:8]}",
            test_name="Other Dept Lab Work", sample_type="blood", department_id=dept_b,
            status=OrderStatus.PLACED.value, created_by=creator_id,
        ),
    ])
    await db.flush()

    result = await service.get_pending_lab_orders(db, dept_a, facility_id)

    assert len(result) == 1
    assert result[0]["test_name"] == "CBC"


async def test_pending_lab_orders_empty_when_nothing_pending(db):
    facility_id, department_id = await _make_facility_and_department(db)
    result = await service.get_pending_lab_orders(db, department_id, facility_id)
    assert result == []


async def test_pending_lab_orders_rejects_wrong_facility(db):
    facility_id, department_id = await _make_facility_and_department(db)
    other_facility_id = uuid.uuid4()

    with pytest.raises(Exception) as exc_info:
        await service.get_pending_lab_orders(db, department_id, other_facility_id)
    assert "404" in str(exc_info.value) or "not found" in str(exc_info.value).lower()
