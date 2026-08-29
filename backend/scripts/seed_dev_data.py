"""Idempotent local-development identities required by authenticated smoke tests.

Keycloak owns credentials and roles. This script creates only the matching
application-side ``facilities`` and ``users`` rows after dev_setup has read the
real Keycloak subjects. It is never run by migrations or production startup.
"""
from __future__ import annotations

import argparse
import asyncio
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.sql.elements import TextClause

from app.common.db import SessionLocal

FACILITY_ID = uuid.UUID("00000000-0000-0000-0000-000000000101")

#: A department, so the HOD dashboard has something to scope to.
#:
#: /users/me returns the caller's department and the HOD screen is per-department;
#: a seeded HOD with department_id NULL lands on "your account is not attached to
#: a department" and the dashboard cannot be exercised at all — which is exactly
#: where it stood until this seed existed.
DEPARTMENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000102")
ROOM_ID = uuid.UUID("00000000-0000-0000-0000-000000000103")

#: Users given DEPARTMENT_ID. Clinical roles belong to a department; admin and
#: auditor deliberately do not, which is why /users/me's join is OUTER.
DEPARTMENTAL_USERS = {"dev.hod", "dev.doctor", "dev.nurse"}

DISPLAY_NAMES = {
    "dev.receptionist": "Dev Receptionist",
    "dev.doctor": "Dev Doctor",
    "dev.nurse": "Dev Nurse",
    "dev.labtech": "Dev Lab Technician",
    "dev.radiology": "Dev Radiology Technician",
    "dev.pharmacist": "Dev Pharmacist",
    "dev.admin": "Dev Admin",
    "dev.auditor": "Dev Auditor",
    "dev.patient": "Dev Patient",
    "dev.hod": "Dev Head of Department",
    "dev.emergency": "Dev Emergency Registrar",
    "dev.supervisor": "Dev Records Supervisor",
    "dev.superadmin": "Dev Platform Superadmin",
}


UPDATE_USER = text(
    """
    UPDATE users
       SET keycloak_sub = :subject,
           username = :username,
           full_name = :full_name,
           email = :email,
           facility_id = :facility_id,
           department_id = :department_id,
           is_active = true,
           updated_at = now()
     WHERE id = :id
    """
)

UPSERT_USER = text(
    """
    INSERT INTO users
        (id, keycloak_sub, username, full_name, email, facility_id,
         department_id, is_active)
    VALUES
        (:id, :subject, :username, :full_name, :email, :facility_id,
         :department_id, true)
    ON CONFLICT (keycloak_sub) DO UPDATE SET
        username = EXCLUDED.username,
        full_name = EXCLUDED.full_name,
        email = EXCLUDED.email,
        facility_id = EXCLUDED.facility_id,
        department_id = EXCLUDED.department_id,
        is_active = true,
        updated_at = now()
    """
)


def _user_parameters(
    username: str,
    subject: str,
    user_id: uuid.UUID,
    department_id: uuid.UUID | None,
) -> dict[str, Any]:
    """One parameter shape shared by both the UPDATE and INSERT paths."""
    return {
        "id": user_id,
        "subject": subject,
        "username": username,
        "full_name": DISPLAY_NAMES.get(username, username),
        # @healthdoc.example, NOT @healthdoc.local.
        #
        # `.local` is RFC 6761 special-use, and email-validator — which backs
        # pydantic's EmailStr — refuses it: "the part after the @-sign is a
        # special-use or reserved name". So every seeded account carried an
        # address the system's OWN API rejects with 422, and editing a seeded
        # user through /admin/users failed on a field nothing had ever typed.
        #
        # `.example` is RFC 2606, reserved for exactly this purpose, and
        # validates. Fixing the seed rather than loosening EmailStr: the
        # validation is right, the data was wrong.
        "email": f"{username}@healthdoc.example",
        "facility_id": FACILITY_ID,
        "department_id": department_id,
    }


def _assert_exact_bind_parameters(
    statement: TextClause, parameters: Mapping[str, Any]
) -> None:
    """Fail at the seed call site if SQL placeholders and parameters drift."""
    expected = set(statement._bindparams)
    actual = set(parameters)
    if expected != actual:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(
            "seed SQL bind mismatch: "
            f"missing={missing or 'none'}, unexpected={unexpected or 'none'}"
        )


def parse_user(value: str) -> tuple[str, str]:
    username, separator, subject = value.partition("=")
    if not separator or not username or not subject:
        raise argparse.ArgumentTypeError("expected USERNAME=KEYCLOAK_SUB")
    return username, subject


async def seed(users: list[tuple[str, str]]) -> None:
    async with SessionLocal() as session, session.begin():
        await session.execute(
            text(
                """
                INSERT INTO facilities
                    (id, code, name, state_code, timezone, facility_type, is_active)
                VALUES
                    (:id, 'DEV001', 'HealthDoc Development Hospital', 'DL',
                     'Asia/Kolkata', 'hospital', true)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    timezone = EXCLUDED.timezone,
                    is_active = true
                """
            ),
            {"id": FACILITY_ID},
        )

        # This facility is inserted with raw SQL, so Facility.after_insert does
        # not run. Pre-create the sequence that normal patient registration
        # advances; otherwise the first POST /patients sees an undefined
        # relation and the transaction is already aborted before its fallback
        # can execute DDL.
        local_year = datetime.now(ZoneInfo("Asia/Kolkata")).year
        await session.execute(
            text(f'CREATE SEQUENCE IF NOT EXISTS "seq_uhid_dev001_{local_year}"')
        )

        await session.execute(
            text(
                """
                INSERT INTO departments (id, name, code, facility_id)
                VALUES (:id, 'General Medicine', 'GENMED', :facility_id)
                ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
                """
            ),
            {"id": DEPARTMENT_ID, "facility_id": FACILITY_ID},
        )

        await session.execute(
            text(
                """
                INSERT INTO rooms (id, department_id, room_number, is_active)
                VALUES (:id, :department_id, '101', true)
                ON CONFLICT (id) DO UPDATE SET
                    department_id = EXCLUDED.department_id,
                    room_number = EXCLUDED.room_number,
                    is_active = true
                """
            ),
            {"id": ROOM_ID, "department_id": DEPARTMENT_ID},
        )

        for username, subject in users:
            # Computed once and used by BOTH branches below.
            #
            # The first version of this repeated the ternary inside each
            # parameter dict and I added it to only one of them — the two dicts
            # are indented differently, so a find-and-replace matched the UPDATE
            # and missed the INSERT, and `make setup` died on "A value is
            # required for bind parameter 'department_id'". One expression, two
            # readers: they cannot disagree.
            department_id = DEPARTMENT_ID if username in DEPARTMENTAL_USERS else None

            existing = (
                await session.execute(
                    text("SELECT id FROM users WHERE username = :username"),
                    {"username": username},
                )
            ).scalar_one_or_none()
            statement = UPDATE_USER if existing else UPSERT_USER
            parameters = _user_parameters(
                username,
                subject,
                existing or uuid.uuid5(uuid.NAMESPACE_URL, f"healthdoc:{username}"),
                department_id,
            )
            # SQLAlchemy eventually reports a missing bind, but only after the
            # branch is reached inside Docker. This guard makes a half-edited
            # statement fail here and names both sides of the mismatch.
            _assert_exact_bind_parameters(statement, parameters)
            await session.execute(statement, parameters)

        # Reception can open today's queue from the real roster picker. A
        # deterministic doctor without a roster still leaves the OPD journey
        # at a dead end on every fresh development stack.
        doctor_user_id = (
            await session.execute(
                text("SELECT id FROM users WHERE username = 'dev.doctor'")
            )
        ).scalar_one()
        roster_date = datetime.now(ZoneInfo("Asia/Kolkata")).date()
        roster_id = uuid.uuid5(
            uuid.NAMESPACE_URL, f"healthdoc:dev.doctor:roster:{roster_date.isoformat()}"
        )
        await session.execute(
            text(
                """
                INSERT INTO rosters
                    (id, staff_user_id, department_id, room_id, shift,
                     roster_date, is_available)
                VALUES
                    (:id, :staff_user_id, :department_id, :room_id, 'morning',
                     :roster_date, true)
                ON CONFLICT (staff_user_id, roster_date, shift) DO UPDATE SET
                    department_id = EXCLUDED.department_id,
                    room_id = EXCLUDED.room_id,
                    is_available = true,
                    updated_at = now()
                """
            ),
            {
                "id": roster_id,
                "staff_user_id": doctor_user_id,
                "department_id": DEPARTMENT_ID,
                "room_id": ROOM_ID,
                "roster_date": roster_date,
            },
        )

        # ------------------------------------------------------------------
        # The REGISTRATION tariff.
        #
        # WITHOUT THIS ROW NOBODY CAN CREATE AN OPD VISIT.
        #
        # opd.create_visit calls billing.create_registration_invoice inside the
        # registration transaction, and that raises 409
        # `registration_tariff_not_configured` when the facility has no active
        # REGISTRATION row in charge_master. The 409 is deliberate and correct —
        # the alternative is a zero-rupee invoice that looks legitimate and is
        # discovered at month-end reconciliation — but the dev seed never
        # created the row, so every fresh environment hit it.
        #
        # The blast radius is the whole product: no visit means no queue token,
        # which means doctor, nurse, pharmacist, lab and radiology cannot reach
        # their primary workflows at all. Registration is the first step of
        # every clinical journey, so a missing seed row reads as "the entire
        # application is broken".
        #
        # WHY NOT ON CONFLICT
        #
        # uq_charge_master_version is (facility_id, charge_code, scheme_code,
        # effective_from) and scheme_code is NULL for a general tariff. In
        # Postgres NULL <> NULL, so the unique index does not dedupe these rows
        # and ON CONFLICT would never fire — re-running the seed would insert a
        # second identical tariff every time. charge_for() takes the newest and
        # would still work, which is exactly why the duplicates would go
        # unnoticed until someone debugged a pricing question. WHERE NOT EXISTS
        # is NULL-safe and actually idempotent.
        #
        # effective_from is deliberately far in the past: charge_for() filters
        # `effective_from <= business_date`, and a row dated today is invisible
        # to any test that bills a backdated visit.
        # ------------------------------------------------------------------
        tariff_author = (
            await session.execute(
                text("SELECT id FROM users WHERE username = 'dev.admin'")
            )
        ).scalar_one_or_none()
        if tariff_author is not None:
            await session.execute(
                text(
                    """
                    INSERT INTO charge_master
                        (id, facility_id, charge_code, description, charge_category,
                         unit_price, scheme_code, effective_from, effective_to,
                         is_active, created_by)
                    SELECT
                        :id, :facility_id, 'REGISTRATION',
                        'OPD registration fee', 'registration',
                        50.00, NULL, DATE '2020-01-01', NULL, true, :created_by
                    WHERE NOT EXISTS (
                        SELECT 1 FROM charge_master
                         WHERE facility_id = :facility_id
                           AND charge_code = 'REGISTRATION'
                           AND scheme_code IS NULL
                           AND is_active
                    )
                    """
                ),
                {
                    "id": uuid.uuid5(uuid.NAMESPACE_URL, "healthdoc:tariff:registration"),
                    "facility_id": FACILITY_ID,
                    "created_by": tariff_author,
                },
            )

        # Prove it landed. The seed's whole job is to leave an environment where
        # a visit can be created; asserting that here turns a silent seed failure
        # into a `make setup` error, instead of a 409 the first tester meets on
        # the registration screen and reports as "the application is broken".
        resolved = (
            await session.execute(
                text(
                    """
                    SELECT count(*) FROM charge_master
                     WHERE facility_id = :facility_id
                       AND charge_code = 'REGISTRATION'
                       AND is_active
                       AND effective_from <= CURRENT_DATE
                       AND (effective_to IS NULL OR effective_to >= CURRENT_DATE)
                    """
                ),
                {"facility_id": FACILITY_ID},
            )
        ).scalar_one()
        if resolved != 1:
            raise RuntimeError(
                f"expected exactly 1 active REGISTRATION tariff for the dev facility, "
                f"found {resolved}. Zero means OPD visits will 409 with "
                f"registration_tariff_not_configured; more than one means charge_for() "
                f"picks by ordering and the effective price is ambiguous."
            )

        patient_user_id = (
            await session.execute(
                text("SELECT id FROM users WHERE username = 'dev.patient'")
            )
        ).scalar_one_or_none()
        verifier_id = (
            await session.execute(
                text("SELECT id FROM users WHERE username = 'dev.admin'")
            )
        ).scalar_one_or_none()
        if patient_user_id is not None and verifier_id is not None:
            patient_id = uuid.uuid5(uuid.NAMESPACE_URL, "healthdoc:dev.patient:patient")
            await session.execute(
                text(
                    """
                    INSERT INTO patients
                        (id, thid, full_name, sex, dob, abha_number, identity_path,
                         identity_status, status, facility_id, created_by)
                    VALUES
                        (:id, 'TH-DEV001-PORTAL', 'Dev Patient', 'unknown', DATE '1990-01-01',
                         '91123456789012', 'abdm', 'verified', 'active', :facility_id, :verifier_id)
                    ON CONFLICT (id) DO UPDATE SET
                        abha_number = EXCLUDED.abha_number,
                        identity_status = 'verified', status = 'active', deleted_at = NULL,
                        updated_at = now(), updated_by = :verifier_id
                    """
                ),
                {
                    "id": patient_id,
                    "facility_id": FACILITY_ID,
                    "verifier_id": verifier_id,
                },
            )
            await session.execute(
                text(
                    """
                    INSERT INTO patient_portal_bindings
                        (id, user_id, patient_id, facility_id, verification_method,
                         verification_reference, verified_by)
                    VALUES
                        (:id, :user_id, :patient_id, :facility_id, 'abha_otp',
                         'DEV-ABHA-OTP-TXN', :verifier_id)
                    ON CONFLICT (id) DO UPDATE SET
                        patient_id = EXCLUDED.patient_id,
                        verification_method = EXCLUDED.verification_method,
                        verification_reference = EXCLUDED.verification_reference,
                        verified_by = EXCLUDED.verified_by,
                        verified_at = now(), revoked_at = NULL, revoked_by = NULL,
                        revocation_reason = NULL, updated_at = now()
                    """
                ),
                {
                    "id": uuid.uuid5(uuid.NAMESPACE_URL, "healthdoc:dev.patient:binding"),
                    "user_id": patient_user_id,
                    "patient_id": patient_id,
                    "facility_id": FACILITY_ID,
                    "verifier_id": verifier_id,
                },
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--user",
        action="append",
        type=parse_user,
        required=True,
        help="Application username and Keycloak subject: USERNAME=SUB",
    )
    args = parser.parse_args()
    asyncio.run(seed(args.user))
    print(f"Seeded development facility and {len(args.user)} authenticated users")


if __name__ == "__main__":
    main()
