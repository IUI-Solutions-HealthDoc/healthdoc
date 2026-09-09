"""Explicit historical registration; real source graphs, no patient-data scans."""

import importlib.util
import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text

from app.admissions.models import Discharge
from app.audit.context import AuditActor, actor_context, get_current_actor
from app.audit.models import AuditLog
from app.integrations.abdm.hip import historical
from app.integrations.abdm.hip.historical import (
    HistoricalManifest,
    HistoricalRefused,
    register_historical_documents,
)
from app.integrations.abdm.hip.models import AbdmCareContext
from app.integrations.abdm.jobs import AbdmJob
from app.nursing.models import Vitals
from app.patients.models import Patient
from app.users.models import User
from tests.integrations.test_abdm_document_exports import documents as documents_fixture

documents = documents_fixture


def manifest_for(documents):
    facility, encounters, prescriptions, _, context = documents
    selected = context("prescription", prescriptions[0].id, "Prescription")
    return HistoricalManifest(
        facility_id=facility.id,
        operator_id=encounters[0].provider_user_id,
        documents=[{"patient_id": selected.patient_id, "reference": selected.reference}],
    )


async def rows(db, model):
    return (await db.scalars(select(model))).all()


async def test_preview_apply_replay_and_outer_rollback(db, documents):
    manifest = manifest_for(documents)
    audit_count = len(await rows(db, AuditLog))
    preview = await register_historical_documents(db, manifest)
    assert [r.status for r in preview] == ["eligible"]
    assert preview[0].document_at is not None
    assert await rows(db, AbdmCareContext) == await rows(db, AbdmJob) == []
    assert len(await rows(db, AuditLog)) == audit_count

    previous_actor = get_current_actor()
    applied = await register_historical_documents(db, manifest, apply=True)
    assert get_current_actor() is previous_actor
    assert [r.status for r in applied] == ["created"]
    contexts, jobs = await rows(db, AbdmCareContext), await rows(db, AbdmJob)
    assert len(contexts) == len(jobs) == 1
    assert contexts[0].reference == manifest.documents[0].reference
    assert contexts[0].created_by == manifest.operator_id
    assert jobs[0].target_id == contexts[0].id and jobs[0].kind == "context_notify"
    audit = (
        await db.scalars(
            select(AuditLog).where(
                AuditLog.resource_type == "abdm_care_contexts",
                AuditLog.resource_id == contexts[0].id,
            )
        )
    ).all()
    assert len(audit) == 1 and audit[0].user_id == manifest.operator_id

    jobs[0].status, jobs[0].attempts = "done", 3
    await db.flush()
    repeated = await register_historical_documents(db, manifest, apply=True)
    assert [r.status for r in repeated] == ["existing"]
    assert repeated[0].context_id == applied[0].context_id
    assert jobs[0].status == "done" and jobs[0].attempts == 3
    assert len(await rows(db, AbdmCareContext)) == len(await rows(db, AbdmJob)) == 1
    await db.rollback()
    assert await rows(db, AbdmCareContext) == await rows(db, AbdmJob) == []


@pytest.mark.parametrize(
    "invalid",
    [
        "open",
        "wrong_patient",
        "deleted",
        "merged",
        "missing_author_registration",
        "foreign_author",
        "legacy_context",
        "foreign_context",
        "changed_date",
    ],
)
async def test_refusal_does_not_create_context_or_job(db, documents, invalid):
    manifest = manifest_for(documents)
    facility, encounters, prescriptions, _, context = documents
    if invalid == "open":
        encounters[0].ended_at = None
    elif invalid == "wrong_patient":
        manifest.documents[0].patient_id = uuid.uuid4()
    elif invalid in ("deleted", "merged"):
        patient = await db.get(Patient, manifest.documents[0].patient_id)
        if invalid == "deleted":
            patient.deleted_at = datetime.now(UTC)
        else:
            patient.merged_into_patient_id = uuid.uuid4()
    elif invalid in ("missing_author_registration", "foreign_author"):
        author = await db.get(User, prescriptions[0].created_by)
        if invalid == "missing_author_registration":
            author.registration_number = " "
        else:
            # Keep today's operator in-scope, but point the document at a
            # different clinician from another facility.
            other = User(
                id=uuid.uuid4(),
                keycloak_sub=str(uuid.uuid4()),
                username="foreign",
                full_name="Other clinician",
                facility_id=uuid.uuid4(),
                registration_number="TEST-REG",
            )
            db.add(other)
            prescriptions[0].created_by = other.id
    else:
        existing = context("prescription", prescriptions[0].id, "Prescription")
        if invalid == "legacy_context":
            existing.document_at = None
        elif invalid == "foreign_context":
            existing.facility_id = uuid.uuid4()
        else:
            existing.document_at -= timedelta(days=1)
        db.add(existing)
    await db.flush()
    before = len(await rows(db, AbdmCareContext))
    preview = await register_historical_documents(db, manifest)
    assert preview[0].model_dump() == {
        "reference": manifest.documents[0].reference,
        "status": "refused",
        "context_id": None,
        "document_at": None,
    }
    with pytest.raises(HistoricalRefused, match="manifest_refused"):
        await register_historical_documents(db, manifest, apply=True)
    assert len(await rows(db, AbdmCareContext)) == before
    assert await rows(db, AbdmJob) == []


@pytest.mark.parametrize(
    "invalid",
    [
        "absent_operator",
        "inactive_operator",
        "foreign_operator",
        "inactive_facility",
    ],
)
async def test_active_operator_must_belong_to_explicit_facility(db, documents, invalid):
    manifest = manifest_for(documents)
    operator = await db.get(User, manifest.operator_id)
    if invalid == "absent_operator":
        manifest.operator_id = uuid.uuid4()
    elif invalid == "inactive_operator":
        operator.is_active = False
    elif invalid == "foreign_operator":
        operator.facility_id = uuid.uuid4()
    else:
        documents[0].is_active = False
    await db.flush()
    with pytest.raises(HistoricalRefused, match="active_facility_operator_required"):
        await register_historical_documents(db, manifest, apply=True)
    assert await rows(db, AbdmCareContext) == await rows(db, AbdmJob) == []


async def test_operator_is_not_substituted_for_original_clinical_author(db, documents):
    manifest = manifest_for(documents)
    author = await db.get(User, manifest.operator_id)
    author.is_active = False  # Former clinician's finalized record is still valid.
    operator = User(
        id=uuid.uuid4(),
        keycloak_sub=str(uuid.uuid4()),
        username="repair-operator",
        full_name="Maintenance Operator",
        facility_id=manifest.facility_id,
        registration_number=None,
    )
    db.add(operator)
    manifest.operator_id = operator.id
    await db.flush()
    await register_historical_documents(db, manifest, apply=True)
    assert documents[2][0].created_by == author.id
    assert (await rows(db, AbdmCareContext))[0].created_by == operator.id


async def test_one_refusal_rejects_whole_batch_before_writes(db, documents):
    manifest = manifest_for(documents)
    manifest.documents.append(
        historical.HistoricalDocument(
            patient_id=manifest.documents[0].patient_id,
            reference=f"prescription/{uuid.uuid4()}",
        )
    )
    assert [r.status for r in await register_historical_documents(db, manifest)] == [
        "eligible",
        "refused",
    ]
    with pytest.raises(HistoricalRefused):
        await register_historical_documents(db, manifest, apply=True)
    assert await rows(db, AbdmCareContext) == await rows(db, AbdmJob) == []


async def test_later_write_failure_rolls_back_batch_even_if_caller_commits(
    db, documents, monkeypatch
):
    manifest = manifest_for(documents)
    manifest.documents.append(
        historical.HistoricalDocument(
            patient_id=manifest.documents[0].patient_id,
            reference=f"prescription/{documents[2][1].id}",
        )
    )
    publish = historical.publish_document
    calls = 0

    async def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Simulated source/write failure")
        return await publish(*args, **kwargs)

    monkeypatch.setattr(historical, "publish_document", fail_second)
    original_actor = AuditActor(uuid.uuid4(), "test-existing-actor", None, None)
    with actor_context(original_actor):
        with pytest.raises(RuntimeError, match="Simulated"):
            await register_historical_documents(db, manifest, apply=True)
        assert get_current_actor() is original_actor
    await db.commit()
    assert calls == 2
    assert await rows(db, AbdmCareContext) == await rows(db, AbdmJob) == []
    assert (
        await db.scalars(
            select(AuditLog).where(
                AuditLog.resource_type == "abdm_care_contexts",
            )
        )
    ).all() == []


@pytest.mark.parametrize(
    "kind", ["encounter", "prescription", "lab-result", "radiology-report", "wellness"]
)
async def test_supported_sources_use_exact_finalized_document_date(db, documents, kind):
    manifest = manifest_for(documents)
    _, encounters, prescriptions, results, _ = documents
    source = (
        prescriptions[0]
        if kind == "prescription"
        else results[kind][0]
        if kind in results
        else encounters[0]
    )
    manifest.documents[0].reference = f"{kind}/{source.id}"
    if kind == "wellness":
        assert (await register_historical_documents(db, manifest))[0].status == "refused"
        db.add(
            Vitals(
                id=uuid.uuid4(),
                patient_id=manifest.documents[0].patient_id,
                encounter_id=source.id,
                measured_at=source.ended_at - timedelta(minutes=1),
                pulse_bpm=70,
                created_by=manifest.operator_id,
            )
        )
        await db.flush()
    preview = await register_historical_documents(db, manifest)
    applied = await register_historical_documents(db, manifest, apply=True)
    assert applied[0].status == "created"
    assert applied[0].document_at == preview[0].document_at
    assert (await rows(db, AbdmCareContext))[0].reference == manifest.documents[0].reference


@pytest.mark.parametrize("kind", ["lab-result", "radiology-report"])
@pytest.mark.parametrize("invalid", ["preliminary", "superseded"])
async def test_unreleased_reports_are_never_registered(db, documents, kind, invalid):
    manifest = manifest_for(documents)
    row = documents[3][kind][0]
    manifest.documents[0].reference = f"{kind}/{row.id}"
    if invalid == "preliminary":
        row.status = "preliminary"
    else:
        row.is_current = False
    await db.flush()
    assert (await register_historical_documents(db, manifest))[0].status == "refused"
    with pytest.raises(HistoricalRefused):
        await register_historical_documents(db, manifest, apply=True)


async def test_discharge_without_opd_encounter(db, documents, nursing_seed):
    manifest = manifest_for(documents)
    discharge = Discharge(
        id=uuid.uuid4(),
        admission_id=nursing_seed["admission_id"],
        discharged_at=datetime.now(UTC),
        discharge_type="discharged",
        discharge_summary="Final synthetic discharge summary",
        created_by=manifest.operator_id,
    )
    db.add(discharge)
    await db.flush()
    manifest.documents[0].patient_id = nursing_seed["patient_id"]
    manifest.documents[0].reference = f"discharge/{discharge.id}"
    assert (await register_historical_documents(db, manifest, apply=True))[0].status == "created"
    assert (await rows(db, AbdmCareContext))[0].hi_type == "DischargeSummary"


@pytest.mark.parametrize(
    "invalid", ["unknown_kind", "uuid", "noncanonical", "extra", "empty", "duplicate", "too_many"]
)
def test_manifest_contract_rejects_ambiguous_or_unbounded_input(invalid):
    item = {"patient_id": str(uuid.uuid4()), "reference": f"encounter/{uuid.uuid4()}"}
    data = {"facility_id": str(uuid.uuid4()), "operator_id": str(uuid.uuid4()), "documents": [item]}
    if invalid == "unknown_kind":
        item["reference"] = f"visit/{uuid.uuid4()}"
    elif invalid == "uuid":
        item["reference"] = "encounter/not-a-uuid"
    elif invalid == "noncanonical":
        item["reference"] = f"encounter/{uuid.uuid4().hex}"
    elif invalid == "extra":
        item["document_at"] = "2026-01-01T00:00:00Z"
    elif invalid == "empty":
        data["documents"] = []
    elif invalid == "duplicate":
        data["documents"].append(dict(item))
    else:
        data["documents"] = [dict(item, reference=f"encounter/{uuid.uuid4()}") for _ in range(101)]
    with pytest.raises(ValidationError):
        HistoricalManifest.model_validate(data)


@pytest.fixture
def cli():
    script = Path(__file__).resolve().parents[3] / "scripts/maintenance/backfill_care_contexts.py"
    spec = importlib.util.spec_from_file_location("historical_backfill_cli", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "invalid",
    ["extra_input", "too_large", "missing_file", "missing_confirmation", "wrong_confirmation"],
)
def test_cli_refuses_before_database_and_never_echoes_input(
    cli, tmp_path, capsys, monkeypatch, invalid
):
    path = tmp_path / "input.json"
    data = {
        "facility_id": str(uuid.uuid4()),
        "operator_id": str(uuid.uuid4()),
        "documents": [{"patient_id": str(uuid.uuid4()), "reference": f"encounter/{uuid.uuid4()}"}],
    }
    sentinel = "PRIVATE-INPUT-MUST-NOT-BE-PRINTED"
    if invalid == "extra_input":
        data["private"] = sentinel
    path.write_text(
        json.dumps(data) if invalid != "too_large" else sentinel * cli.MAX_MANIFEST_BYTES
    )
    args = ["--manifest", str(path)]
    if invalid == "missing_file":
        args = ["--manifest", str(tmp_path / "absent.json")]
    elif invalid in ("missing_confirmation", "wrong_confirmation"):
        args.append("--apply")
        if invalid == "wrong_confirmation":
            args.extend(["--confirm-facility", str(uuid.uuid4())])

    async def unexpected(*args, **kwargs):
        pytest.fail("Invalid invocation reached database")

    monkeypatch.setattr(cli, "execute", unexpected)
    assert cli.main(args) == 2
    output = capsys.readouterr().out
    assert sentinel not in output and json.loads(output)["error"]


async def test_cli_preview_rolls_back_and_apply_commits(cli, db, documents, monkeypatch):
    @asynccontextmanager
    async def sessions():
        yield db

    monkeypatch.setattr(cli, "SessionLocal", sessions)
    # Commit only synthetic fixture setup so preview's rollback preserves it.
    manifest = manifest_for(documents)
    await db.commit()
    assert (await cli.execute(manifest, apply=False))[0]["status"] == "eligible"
    assert await rows(db, AbdmCareContext) == []
    assert (await cli.execute(manifest, apply=True))[0]["status"] == "created"
    await db.rollback()
    assert len(await rows(db, AbdmCareContext)) == len(await rows(db, AbdmJob)) == 1


def test_cli_hides_driver_exception_and_flags_uncertain_outcome(cli, tmp_path, capsys, monkeypatch):
    path = tmp_path / "input.json"
    path.write_text(
        json.dumps(
            {
                "facility_id": str(uuid.uuid4()),
                "operator_id": str(uuid.uuid4()),
                "documents": [
                    {"patient_id": str(uuid.uuid4()), "reference": f"encounter/{uuid.uuid4()}"}
                ],
            }
        )
    )

    async def failed(*args, **kwargs):
        raise RuntimeError("PRIVATE-SQL-PARAMETERS")

    monkeypatch.setattr(cli, "execute", failed)
    assert cli.main(["--manifest", str(path)]) == 1
    output = capsys.readouterr().out
    assert "PRIVATE" not in output
    assert json.loads(output)["error"] == "transaction_not_confirmed_preview_before_retry"


async def test_cli_rolls_back_on_commit_failure(cli, db, documents, monkeypatch):
    @asynccontextmanager
    async def sessions():
        yield db

    manifest = manifest_for(documents)
    await db.commit()
    # sqlite3 legacy mode does not BEGIN on SELECT/SAVEPOINT. Make its
    # transaction explicit so releasing the service savepoint cannot commit
    # outside the caller's transaction. PostgreSQL is proved separately.
    # https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#legacy-transaction-mode-with-the-sqlite3-driver
    await db.execute(text("BEGIN"))

    async def failed_commit():
        raise RuntimeError("Synthetic commit failure")

    monkeypatch.setattr(cli, "SessionLocal", sessions)
    monkeypatch.setattr(db, "commit", failed_commit)
    with pytest.raises(RuntimeError, match="Synthetic"):
        await cli.execute(manifest, apply=True)
    assert await rows(db, AbdmCareContext) == await rows(db, AbdmJob) == []
