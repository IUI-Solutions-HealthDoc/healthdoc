import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app.audit.models import AuditLog
from app.users.models import User
from scripts import repair_dev_identity as tool


@pytest.mark.parametrize("override", [
    {"environment": "production"}, {"keycloak_realm": "other"},
    {"keycloak_base_url": "https://identity.example.com/auth"},
    {"keycloak_base_url": "http://keycloak:8080.evil.test/auth"},
])
def test_repair_is_only_for_explicit_local_dev_realm(override):
    settings = dict(environment="dev", keycloak_realm="healthdoc",
                    keycloak_base_url="http://keycloak:8080/auth")
    tool.validate_environment(SimpleNamespace(**settings))
    with pytest.raises(tool.RepairRefused):
        tool.validate_environment(SimpleNamespace(**(settings | override)))


async def prepare(db, seed, monkeypatch, *, defect=None):
    _, _, doctor = seed
    old, new = uuid.uuid4(), uuid.uuid4()
    doctor.username = "dev.doctor"
    doctor.full_name = "Dev Doctor"
    doctor.keycloak_sub = str(old)
    doctor.registration_number = "TEST-PRESERVE"
    doctor.registration_identifier_type = "TEST-ONLY"
    doctor.registration_identifier_system = "https://registry.test"
    await db.commit()
    await db.refresh(doctor)
    monkeypatch.setattr(tool, "FACILITY_ID", doctor.facility_id)
    account = {"id": str(new), "username": doctor.username, "enabled": True,
               "firstName": "Dev", "lastName": "Doctor"}
    roles = ["doctor"]
    previous_status = 404
    if defect == "disabled":
        account["enabled"] = False
    elif defect == "foreign_subject":
        account["id"] = str(uuid.uuid4())
    elif defect == "different_name":
        account["lastName"] = "Someone Else"
    elif defect == "federated":
        account["federationLink"] = "external-provider"
    elif defect == "extra_role":
        roles.append("admin")
    elif defect == "missing_role":
        roles = []
    elif defect == "old_account_exists":
        previous_status = 200
    elif defect == "old_account_unavailable":
        previous_status = 503

    def handle(request):
        assert request.method == "GET", "Repair may not change Keycloak accounts"
        if request.url.path.endswith("/users"):
            assert request.url.params["exact"] == "true"
            return httpx.Response(200, json=[account])
        if request.url.path.endswith(f"/users/{old}"):
            return httpx.Response(previous_status, json={})
        assert request.url.path.endswith("/role-mappings/realm/composite")
        return httpx.Response(200, json=[{"name": role} for role in roles])

    kc = SimpleNamespace(base="http://keycloak:8080/auth", realm="healthdoc",
                         _token=AsyncMock(return_value="TEST-NOT-A-TOKEN"))
    args = dict(username=doctor.username, user_id=doctor.id, old_subject=old, new_subject=new)
    return doctor, kc, args, httpx.MockTransport(handle)


async def test_preview_does_not_modify_subject_or_create_audit(db, seed, monkeypatch):
    doctor, kc, args, transport = await prepare(db, seed, monkeypatch)
    audit = AsyncMock()
    monkeypatch.setattr(tool, "write_audit_log", audit)
    async with httpx.AsyncClient(transport=transport) as client:
        result = await tool.repair(db, client, kc, **args)
    assert result["eligible"] and not result["applied"]
    await db.refresh(doctor)
    assert doctor.keycloak_sub == str(args["old_subject"])
    audit.assert_not_awaited()


async def test_apply_changes_only_subject_and_timestamp_with_audit(db, seed, monkeypatch):
    doctor, kc, args, transport = await prepare(db, seed, monkeypatch)
    before = {col.name: getattr(doctor, col.name) for col in User.__table__.columns}
    async with httpx.AsyncClient(transport=transport) as client:
        result = await tool.repair(db, client, kc, **args, apply=True)
    await db.commit()
    await db.refresh(doctor)
    assert result["applied"] and result["staff_id_preserved"]
    assert doctor.keycloak_sub == str(args["new_subject"])
    for field, value in before.items():
        if field not in {"keycloak_sub", "updated_at"}:
            assert getattr(doctor, field) == value, field
    audit = (await db.execute(select(AuditLog).where(
        AuditLog.resource_id == doctor.id,
        AuditLog.reason.startswith("Explicit local operator repair"),
    ))).scalar_one()
    assert audit.old_value == {"keycloak_sub": str(args["old_subject"])}
    assert audit.new_value == {"keycloak_sub": str(args["new_subject"])}


@pytest.mark.parametrize("defect", [
    "disabled", "foreign_subject", "different_name", "federated", "extra_role",
    "missing_role", "old_account_exists", "old_account_unavailable",
])
async def test_unsafe_realm_identity_never_rebinds(db, seed, monkeypatch, defect):
    doctor, kc, args, transport = await prepare(db, seed, monkeypatch, defect=defect)
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(tool.RepairRefused):
            await tool.repair(db, client, kc, **args, apply=True)
    await db.refresh(doctor)
    assert doctor.keycloak_sub == str(args["old_subject"])


async def test_audit_failure_rolls_back_subject_repair(db, seed, monkeypatch):
    doctor, kc, args, transport = await prepare(db, seed, monkeypatch)
    monkeypatch.setattr(tool, "write_audit_log", AsyncMock(side_effect=RuntimeError("audit failed")))
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(RuntimeError, match="audit failed"):
            await tool.repair(db, client, kc, **args, apply=True)
    await db.rollback()
    await db.refresh(doctor)
    assert doctor.keycloak_sub == str(args["old_subject"])


@pytest.mark.parametrize("defect", ["old_subject", "user_id", "deactivated", "facility", "collision"])
async def test_stale_or_conflicting_app_identity_never_rebinds(db, seed, monkeypatch, defect):
    doctor, kc, args, transport = await prepare(db, seed, monkeypatch)
    if defect in {"old_subject", "user_id"}:
        args[defect] = uuid.uuid4()
    elif defect == "deactivated":
        doctor.is_active = False
    elif defect == "facility":
        monkeypatch.setattr(tool, "FACILITY_ID", uuid.uuid4())
    else:
        db.add(User(id=uuid.uuid4(), username="someone-else", full_name="Other",
                    keycloak_sub=str(args["new_subject"]), facility_id=doctor.facility_id))
    await db.flush()
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(tool.RepairRefused):
            await tool.repair(db, client, kc, **args, apply=True)
    kc._token.assert_not_awaited()
