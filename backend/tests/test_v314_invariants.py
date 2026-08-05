"""Executable proofs for the three v3.14 gaps.

Each test states the harm it prevents, not just the behaviour it asserts. If one of
these ever fails, someone has reintroduced a way to hurt a patient or overcharge one.

The migration-level tests parse the migration source rather than running Postgres, so
they work in CI before 0006/0012/0014/0015 have merged. They verify that the constraint
is *declared* — the live-DB behaviour is covered by the integration tests that land with
the service layer.
"""
import re
from pathlib import Path

import pytest

from app.allergies.service import OVERRIDE_REASON_MIN_CHARS
from app.common.enums import AllergenType, AllergySeverity, AllergyStatus

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _src(name: str) -> str:
    matches = list(MIGRATIONS.glob(f"{name}*.py"))
    assert matches, f"migration {name} not found"
    return matches[0].read_text()


# --------------------------------------------------------------------------
# 0032 — allergies
# --------------------------------------------------------------------------

def test_allergy_matching_key_is_ingredient_not_stock_item():
    """The harm: a patient allergic to penicillin is prescribed amoxicillin.

    They are different `inventory_items` rows sharing an ingredient. If the schema only
    offered `inventory_item_id`, the check would pass and the patient would react. The
    ingredient column on BOTH tables is what makes class-level matching possible.
    """
    src = _src("0032")
    # the column exists on the allergy row...
    assert re.search(r'"ingredient_code",\s*sa\.String\(50\)', src)
    # ...and on the stock item, which is what makes the two sides comparable
    assert '"inventory_items"' in src
    assert "ix_inventory_items_ingredient_code" in src


def test_uncoded_allergy_cannot_block_but_is_still_stored():
    """The harm: losing the attendant's words because we could not code them.

    `substance_text` is NOT NULL so the human description always survives;
    `ingredient_code` is nullable so an uncodeable allergy is still recorded. The pairing
    is deliberate — display-only, never silently dropped.
    """
    src = _src("0032")
    assert re.search(r'"substance_text",\s*sa\.Text\(\),\s*nullable=False', src)
    assert re.search(r'"ingredient_code",\s*sa\.String\(50\),\s*nullable=True', src)


def test_anaphylaxis_is_a_distinct_severity_value():
    """The harm: anaphylaxis treated as merely 'severe' and overridden by a busy clinician.

    It is a separate enum value precisely so the service can refuse the override.
    """
    assert "anaphylaxis" in AllergySeverity.values()
    assert "severe" in AllergySeverity.values()
    assert AllergySeverity.ANAPHYLAXIS.value != AllergySeverity.SEVERE.value


def test_allergies_are_corrected_never_deleted():
    """The harm: a real allergy deleted as a 'mistake' and lost forever.

    Correction is a status transition, so the row and its history survive.
    """
    assert {"active", "inactive", "refuted", "entered_in_error"} == set(AllergyStatus.values())


def test_override_reason_floor_is_enforced_in_db_not_just_python():
    """The harm: 'ok' recorded as the clinical justification for overriding an allergy.

    A Python-side check is bypassed by any other writer; the CHECK constraint is not.
    """
    src = _src("0032")
    assert "char_length(allergy_override_reason) >= 20" in src
    assert OVERRIDE_REASON_MIN_CHARS == 20, "service floor and DB CHECK must agree"


def test_partial_verification_is_impossible():
    """The harm: an allergy showing as verified with nobody accountable for verifying it."""
    assert "(verified_by IS NULL) = (verified_at IS NULL)" in _src("0032")


# --------------------------------------------------------------------------
# 0033 — charge_master
# --------------------------------------------------------------------------

def test_double_billing_is_structurally_impossible():
    """The harm: a lab result finalised twice bills the patient twice.

    This is the single most important constraint in 0033. The accrual service runs on
    flaky rural links and after crash recovery, so it WILL retry — the database has to
    be what makes the retry safe.
    """
    src = _src("0033")
    assert "uq_invoice_items_source" in src
    assert '"invoice_id", "reference_type", "reference_id"' in src
    assert "unique=True" in src


def test_hand_entered_lines_are_not_blocked_by_the_source_unique():
    """The harm: over-correcting. A unique index over NULLable source columns would
    collide across every manually added line, so it must be partial."""
    src = _src("0033")
    m = re.search(r"uq_invoice_items_source.*?\)\n", src, re.S)
    assert m and "postgresql_where" in m.group(0)


def test_price_history_is_reconstructible():
    """The harm: 'what was the tariff on 12 March' has no answer, so a billing dispute
    cannot be settled. Effective dating + a version unique means prices supersede rather
    than overwrite."""
    src = _src("0033")
    assert "effective_from" in src and "effective_to" in src
    assert "uq_charge_master_version" in src
    assert "effective_to IS NULL OR effective_to > effective_from" in src


# --------------------------------------------------------------------------
# 0034 — IPD bed integrity
# --------------------------------------------------------------------------

def test_one_active_admission_per_bed():
    """The harm: two patients assigned the same bed, and the data says both are correct.

    Left to the service layer this is a race; as a partial unique index it stops existing.
    """
    src = _src("0034")
    assert "uq_admissions_active_bed" in src
    assert "unique=True" in src
    assert "status = 'admitted'" in src


def test_migration_refuses_to_run_on_already_double_booked_data():
    """The harm: the index creation fails with a raw duplicate-key error at 2am and
    nobody can tell which bed caused it."""
    src = _src("0034")
    assert "HAVING count(*) > 1" in src
    assert "RuntimeError" in src


def test_transferred_discharge_must_name_a_destination():
    """The harm: a patient leaves the system with no forward reference, exactly when the
    next clinician most needs to know where the record continues."""
    src = _src("0034")
    assert "ck_discharges_transfer_destination" in src
    assert "destination_facility_id" in src and "destination_facility_name" in src


# --------------------------------------------------------------------------
# chain integrity
# --------------------------------------------------------------------------

@pytest.mark.parametrize("rev,down", [("0032", "0031"), ("0033", "0032"), ("0034", "0033")])
def test_migrations_chain_linearly_and_have_downgrades(rev, down):
    src = _src(rev)
    assert re.search(rf'^revision = "{rev}"', src, re.M)
    assert re.search(rf'^down_revision = "{down}"', src, re.M)
    body = src.split("def downgrade()")[1]
    assert "pass" not in body.split("\n")[1], f"{rev} downgrade is a stub"
