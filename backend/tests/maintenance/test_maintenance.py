"""Acceptance proofs for issue #453 machine maintenance APIs."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from sqlalchemy import select

from app.audit.models import AuditLog
from app.auth.deps import (
    AuthUser,
    DbUser,
    get_current_db_user,
    get_current_user,
)
from app.common.db import get_db
from app.departments.models import Department
from app.maintenance import schemas, service
from app.maintenance.router import router as maintenance_router
from app.maintenance.schemas import MaintenanceLogCreate
from app.users.models import Facility


def _payload(department_id, **overrides) -> MaintenanceLogCreate:
    values = {
        "machine_id": "XR-01",
        "department_id": department_id,
        "maintenance_type": "preventive",
        "performed_at": datetime.now(UTC) - timedelta(hours=1),
        "performed_by_vendor": "Acme Biomedical",
        "downtime_minutes": 20,
        "notes": "Quarterly inspection completed",
    }
    values.update(overrides)
    return MaintenanceLogCreate(**values)


async def test_create_maintenance_log_derives_actor_and_writes_audit(db, seed):
    department, _room, actor = seed
    row = await service.create_maintenance_log(
        db,
        payload=_payload(department.id),
        facility_id=department.facility_id,
        actor_id=actor.id,
    )

    assert row.created_by == actor.id
    assert row.updated_by is None
    audit = (
        await db.execute(
            select(AuditLog).where(
                AuditLog.resource_type == "machine_maintenance_logs",
                AuditLog.resource_id == row.id,
            )
        )
    ).scalar_one()
    assert audit.facility_id == department.facility_id
    assert audit.user_id == actor.id


async def test_department_and_reads_are_non_disclosing_across_facilities(db, seed):
    department, _room, actor = seed
    row = await service.create_maintenance_log(
        db,
        payload=_payload(department.id),
        facility_id=department.facility_id,
        actor_id=actor.id,
    )
    other_facility = Facility(
        id=uuid.uuid4(), code="MTN02", name="Other Facility", state_code="TS"
    )
    other_department = Department(
        id=uuid.uuid4(),
        facility_id=other_facility.id,
        code="RAD",
        name="Other Radiology",
    )
    db.add_all([other_facility, other_department])
    await db.flush()

    with pytest.raises(service.DepartmentNotFound):
        await service.create_maintenance_log(
            db,
            payload=_payload(other_department.id),
            facility_id=department.facility_id,
            actor_id=actor.id,
        )
    with pytest.raises(service.MaintenanceLogNotFound):
        await service.get_maintenance_log(
            db, log_id=row.id, facility_id=other_facility.id
        )
    rows, total = await service.list_maintenance_logs(
        db, facility_id=other_facility.id
    )
    assert rows == []
    assert total == 0


async def test_list_filters_and_orders_newest_performed_first(db, seed):
    department, _room, actor = seed
    older = await service.create_maintenance_log(
        db,
        payload=_payload(
            department.id,
            machine_id="CT-02",
            maintenance_type="breakdown",
            performed_at=datetime.now(UTC) - timedelta(days=2),
        ),
        facility_id=department.facility_id,
        actor_id=actor.id,
    )
    newer = await service.create_maintenance_log(
        db,
        payload=_payload(
            department.id,
            machine_id="CT-02",
            maintenance_type="calibration",
            performed_at=datetime.now(UTC) - timedelta(days=1),
        ),
        facility_id=department.facility_id,
        actor_id=actor.id,
    )

    rows, total = await service.list_maintenance_logs(
        db,
        facility_id=department.facility_id,
        machine_id="CT-02",
        department_id=department.id,
        performed_from=datetime.now(UTC) - timedelta(days=3),
        performed_to=datetime.now(UTC),
    )
    assert [row.id for row in rows] == [newer.id, older.id]
    assert total == 2

    filtered, filtered_total = await service.list_maintenance_logs(
        db,
        facility_id=department.facility_id,
        maintenance_type="calibration",
    )
    assert [row.id for row in filtered] == [newer.id]
    assert filtered_total == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"downtime_minutes": -1},
        {"performed_at": datetime(2026, 1, 1)},
        {"machine_id": "   "},
    ],
)
def test_create_contract_rejects_invalid_evidence(overrides):
    with pytest.raises(ValidationError):
        _payload(uuid.uuid4(), **overrides)


@pytest.mark.parametrize("offset_microseconds", [-1, 0, 1])
def test_performed_at_boundary_uses_a_fixed_validation_clock(monkeypatch, offset_microseconds):
    # Collection can precede this test by minutes in CI. A timestamp created
    # in parametrize must not age from invalid-future into valid-past.
    now = datetime(2026, 9, 8, 12, tzinfo=UTC)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(schemas, "datetime", FixedDateTime)
    performed_at = now + timedelta(microseconds=offset_microseconds)
    if offset_microseconds > 0:
        with pytest.raises(ValidationError, match="cannot be in the future"):
            _payload(uuid.uuid4(), performed_at=performed_at)
    else:
        assert _payload(uuid.uuid4(), performed_at=performed_at).performed_at == performed_at


def _http_client(db, *, actor, roles: list[str]) -> httpx.AsyncClient:
    async def override_db():
        yield db

    app = FastAPI()
    app.include_router(maintenance_router)
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: AuthUser(
        sub=actor.keycloak_sub, username=actor.username, roles=roles
    )
    app.dependency_overrides[get_current_db_user] = lambda: DbUser(
        id=actor.id,
        keycloak_sub=actor.keycloak_sub,
        username=actor.username,
        facility_id=actor.facility_id,
        roles=roles,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_http_role_gate_and_idempotent_retry(db, seed):
    department, _room, actor = seed
    body = _payload(department.id).model_dump(mode="json")
    headers = {"Idempotency-Key": "maintenance-log-retry"}

    async with _http_client(db, actor=actor, roles=["doctor"]) as client:
        forbidden = await client.post(
            "/maintenance/logs", headers=headers, json=body
        )
    assert forbidden.status_code == 403

    async with _http_client(db, actor=actor, roles=["lab_tech"]) as client:
        first = await client.post("/maintenance/logs", headers=headers, json=body)
        retry = await client.post("/maintenance/logs", headers=headers, json=body)
    assert first.status_code == 201, first.text
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == first.json()["id"]


def test_router_exposes_no_update_or_delete_route():
    exposed = {
        (route.path, method)
        for route in maintenance_router.routes
        for method in route.methods
    }
    assert ("/maintenance/logs", "POST") in exposed
    assert ("/maintenance/logs", "GET") in exposed
    assert ("/maintenance/logs/{log_id}", "GET") in exposed
    assert not any(method in {"PATCH", "PUT", "DELETE"} for _, method in exposed)
