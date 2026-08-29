"""
Creating a patient must leave an audit row — on every route that creates one.

WHY THIS TEST EXISTS

Issue #290 is usually described as "audit coverage is 8 of ~90 models", which
reads like a completeness chore. The concrete part is not: registering a patient
is the moment a person's data first exists in this system, and it was writing no
audit row at all. Verified against the running dev stack before this was written
— six patients in the database, zero audit_logs rows referencing any of them,
including one created through the API minutes earlier.

Both routes are covered because the unit of repair is the route family. A
reader who fixes only POST /patients leaves the emergency registrar — the role
most likely to be creating records under pressure, on an unidentified patient —
with no trail.

Real Postgres, not the SQLite fixture: audit_logs carries migration-only
append-only triggers and a chain-seq assignment that the ORM-metadata fixture
never builds, so an audit assertion there would pass without exercising the
thing that actually stores the row.
"""
from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from tests._lab_seed import TEST_DATABASE_URL

from .conftest import RECEPTIONIST, NURSE


def _audit_rows_for(patient_id):
    """Read the audit rows back on a separate synchronous connection.

    Deliberately not the request's own session: that session wrote the row, so
    reading through it could be satisfied from the identity map and would prove
    only that the object was constructed. A fresh connection proves it was
    committed and survived the append-only trigger.
    """
    url = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2") if TEST_DATABASE_URL else ""
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(
                sa.text(
                    "SELECT action, resource_type, patient_id, new_value "
                    "FROM audit_logs WHERE resource_id = :pid"
                ),
                {"pid": patient_id},
            ).mappings().all()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "route, actor, payload, identifier_key",
    [
        (
            "/api/v1/patients",
            RECEPTIONIST,
            {
                "full_name": "Audit Coverage Patient",
                "sex": "female",
                "dob": "1991-02-03",
                "mobile": "9812345670",
            },
            "uhid",
        ),
        (
            "/api/v1/emergency/patients",
            NURSE,
            {"full_name": "Audit Coverage Emergency", "sex": "unknown", "age_years": 41},
            "thid",
        ),
    ],
    ids=["register_patient", "register_emergency_patient"],
)
def test_creating_a_patient_writes_exactly_one_audit_row(
    client_as, route, actor, payload, identifier_key
):
    client = client_as(actor)
    response = client.post(
        route, headers={"Idempotency-Key": str(uuid.uuid4())}, json=payload
    )
    assert response.status_code == 201, response.text
    patient_id = response.json()["data"]["id"]

    rows = _audit_rows_for(patient_id)
    assert len(rows) == 1, (
        f"{route} created a patient and wrote {len(rows)} audit rows. "
        f"Exactly one is required: zero is the #290 gap this closes, and more "
        f"than one means the automatic listener opt-in is now double-writing "
        f"alongside this explicit call."
    )

    row = rows[0]
    assert row["action"] == "create"
    assert row["resource_type"] == "patients"
    # patient_id, not just resource_id: a data-access log that cannot be
    # queried by whose data it was is not answering the DPDP question.
    assert str(row["patient_id"]) == patient_id

    recorded = row["new_value"] or {}
    assert recorded.get(identifier_key), (
        f"the audit row should record the {identifier_key} that was allocated"
    )
    # audit_logs is append-only, so anything written here survives an erasure
    # request. Identifiers are the compliance record; the personal data is not.
    for forbidden in ("full_name", "mobile", "dob", "aadhaar_number", "age_years"):
        assert forbidden not in recorded, (
            f"{forbidden} was copied into audit_logs. That table is append-only, "
            f"so this builds an indelible second copy of exactly the data a "
            f"patient can demand be erased under DPDP."
        )
