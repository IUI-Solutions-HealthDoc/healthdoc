"""Real PostgreSQL regressions for catalogue-based automatic accrual.

Clinical sources and tariffs are seeded independently: a completed test without
a configured tariff must not accidentally acquire a price from the test helper.
"""
import importlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
import sqlalchemy as sa
from fastapi import HTTPException

from app.billing import service
from tests.billing.conftest import seed_facility, seed_user
from tests.billing.test_billing_flows import _seed_billable_lab_charge

pytestmark = pytest.mark.asyncio
VISIT_DATE = date(2026, 6, 1)


async def source(db, visit, category):
    if category == "lab":
        return await _seed_billable_lab_charge(db, visit_id=visit)
    row = (await db.execute(sa.text(
        "SELECT patient_id, facility_id, created_by FROM visits WHERE id=:id"
    ), {"id": visit})).one()
    encounter, order, item = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await db.execute(sa.text(
        "INSERT INTO encounters (id, visit_id, facility_id, provider_user_id, created_by) "
        "VALUES (:id, :visit, :facility, :actor, :actor)"
    ), {"id": encounter, "visit": visit, "facility": row.facility_id, "actor": row.created_by})
    await db.execute(sa.text(
        "INSERT INTO orders (id, encounter_id, order_number, patient_id, order_type, facility_id, created_by) "
        "VALUES (:id, :encounter, :number, :patient, 'radiology', :facility, :actor)"
    ), {"id": order, "encounter": encounter, "number": f"T-{order.hex[:12]}",
        "patient": row.patient_id, "facility": row.facility_id, "actor": row.created_by})
    await db.execute(sa.text(
        "INSERT INTO radiology_order_items (id, order_id, accession_number, modality, scan_type, created_by) "
        "VALUES (:id, :order, :accession, 'xray', 'Synthetic chest study', :actor)"
    ), {"id": item, "order": order, "accession": f"R-{item.hex[:12]}", "actor": row.created_by})
    await db.execute(sa.text(
        "INSERT INTO radiology_reports (id, radiology_order_item_id, version, is_current, "
        "findings, impression, status, created_by) "
        "VALUES (:id, :item, 1, true, 'Synthetic findings', 'Synthetic impression', 'final', :actor)"
    ), {"id": uuid.uuid4(), "item": item, "actor": row.created_by})
    return item


async def tariff(db, facility, actor, category="lab", **overrides):
    args = dict(
        facility_id=facility, created_by=actor,
        charge_code="CBC" if category == "lab" else "xray",
        charge_category=category, description="Synthetic configured tariff",
        unit_price=Decimal("413.27"), effective_from=date(2026, 1, 1),
    )
    args.update(overrides)
    return await service.create_tariff(db, **args)


@pytest.fixture(autouse=True)
async def visit_time(db, visit):
    # 23:30 UTC on May 31 is June 1 in this facility. Billing on UTC or on
    # today's date selects the wrong effective-dated row.
    await db.execute(sa.text("UPDATE visits SET visit_date=:at WHERE id=:id"), {
        "id": visit, "at": datetime(2026, 5, 31, 23, 30, tzinfo=UTC),
    })


@pytest.mark.parametrize("category", ["lab", "radiology"])
async def test_preview_and_build_use_configured_tariff_and_pin_it(
    db, facility, user, visit, draft_invoice, category,
):
    item = await source(db, visit, category)
    tariff_id = await tariff(db, facility, user, category)
    preview = await service.preview_invoice(db, visit)
    line, = preview.new_charge_lines
    assert line.unit_price == Decimal("413.27")  # neither old static price
    assert line.charge_master_id == tariff_id
    assert line.pricing_date == VISIT_DATE
    assert line.charge_code == ("CBC" if category == "lab" else "xray")
    assert preview.model_dump(mode="json")["new_charge_lines"][0]["amount"] == "413.27"
    assert (await db.execute(sa.text(
        "SELECT count(*) FROM invoice_items WHERE invoice_id=:id"
    ), {"id": draft_invoice})).scalar_one() == 0
    built = await service.build_invoice(db, visit, user)
    assert built.gross_amount == Decimal("413.27")
    persisted = (await db.execute(sa.text(
        "SELECT reference_id, unit_price, charge_master_id FROM invoice_items WHERE invoice_id=:id"
    ), {"id": draft_invoice})).one()
    assert persisted.reference_id == item
    assert persisted.unit_price == Decimal("413.27")
    assert persisted.charge_master_id == tariff_id
    again = await service.build_invoice(db, visit, user)
    assert again.lines_added == 0
    assert again.gross_amount == Decimal("413.27")


@pytest.mark.parametrize("category", ["lab", "radiology"])
@pytest.mark.parametrize("invalid", ["missing", "foreign", "inactive", "future", "expired", "wrong_category", "other_scheme"])
async def test_no_matching_tariff_never_bills_static_or_zero(
    db, facility, user, visit, draft_invoice, category, invalid,
):
    await source(db, visit, category)
    if invalid != "missing":
        options = {}
        target, actor = facility, user
        if invalid == "foreign":
            target = await seed_facility(db)
            actor = await seed_user(db, facility_id=target)
        if invalid == "future":
            options["effective_from"] = date(2026, 6, 2)
        if invalid == "wrong_category":
            options["charge_category"] = "other"
        if invalid == "other_scheme":
            options["scheme_code"] = "OTHER"
        tid = await tariff(db, target, actor, category, **options)
        if invalid == "inactive":
            await service.deactivate_tariff(db, tid, updated_by=actor, facility_id=target)
        if invalid == "expired":
            await db.execute(sa.text("UPDATE charge_master SET effective_to='2026-05-31' WHERE id=:id"), {"id": tid})
    preview = await service.preview_invoice(db, visit)
    line, = preview.new_charge_lines
    assert not line.priced
    assert line.charge_master_id is None
    assert line.pricing_note
    assert preview.unpriced_count == 1
    built = await service.build_invoice(db, visit, user)
    assert built.lines_added == 0
    assert built.lines_skipped_unpriced == 1
    assert built.gross_amount == Decimal("0.00")


@pytest.mark.parametrize("category", ["lab", "radiology"])
async def test_scheme_and_visit_local_date_win_over_current_prices(
    db, facility, user, visit, draft_invoice, category,
):
    await source(db, visit, category)
    await tariff(db, facility, user, category)
    await tariff(db, facility, user, category, scheme_code="TEST", unit_price=Decimal("71.10"))
    expected = await tariff(db, facility, user, category, scheme_code="TEST",
                            effective_from=VISIT_DATE, unit_price=Decimal("82.25"))
    await tariff(db, facility, user, category, scheme_code="TEST",
                 effective_from=date(2026, 6, 2), unit_price=Decimal("999.00"))
    await db.execute(sa.text("UPDATE invoices SET scheme_code='TEST' WHERE id=:id"), {"id": draft_invoice})
    line, = (await service.preview_invoice(db, visit)).new_charge_lines
    assert line.unit_price == Decimal("82.25")
    assert line.charge_master_id == expected


async def test_tariff_changes_do_not_reprice_posted_lines(db, facility, user, visit, draft_invoice):
    await source(db, visit, "lab")
    first = await tariff(db, facility, user)
    await service.build_invoice(db, visit, user)
    await tariff(db, facility, user, effective_from=VISIT_DATE, unit_price=Decimal("501.38"))
    await source(db, visit, "lab")
    await service.build_invoice(db, visit, user)
    rows = (await db.execute(sa.text(
        "SELECT unit_price, charge_master_id FROM invoice_items WHERE invoice_id=:id ORDER BY unit_price"
    ), {"id": draft_invoice})).all()
    assert [(r.unit_price, r.charge_master_id == first) for r in rows] == [
        (Decimal("413.27"), True), (Decimal("501.38"), False),
    ]
    await db.execute(sa.text("UPDATE invoices SET status='issued' WHERE id=:id"), {"id": draft_invoice})
    await tariff(db, facility, user, effective_from=date(2026, 6, 2), unit_price=Decimal("600.00"))
    with pytest.raises(HTTPException) as exc:
        await service.build_invoice(db, visit, user)
    assert exc.value.status_code == 409
    assert (await db.execute(sa.text("SELECT gross_amount FROM invoices WHERE id=:id"), {"id": draft_invoice})).scalar_one() == Decimal("914.65")


@pytest.mark.parametrize("category", ["lab", "radiology"])
async def test_explicit_zero_tariff_is_priced_and_unknown_scheme_uses_general(
    db, facility, user, visit, draft_invoice, category,
):
    await source(db, visit, category)
    expected = await tariff(db, facility, user, category, unit_price=Decimal("0.00"))
    await db.execute(sa.text("UPDATE invoices SET scheme_code='UNCONFIGURED' WHERE id=:id"), {"id": draft_invoice})
    line, = (await service.preview_invoice(db, visit)).new_charge_lines
    assert line.priced
    assert line.unit_price == Decimal("0.00")
    assert line.charge_master_id == expected
    assert (await service.build_invoice(db, visit, user)).lines_added == 1


async def test_inclusive_date_migration_roundtrip_and_guard_preserve_rows(db, monkeypatch):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.exc import DBAPIError

    migration = importlib.import_module("migrations.versions.0068_tariff_inclusive_dates")
    # A connection-local shadow table tests the actual migration code without
    # downgrading the shared test database or touching any application table.
    await db.execute(sa.text(
        "CREATE TEMP TABLE charge_master (id integer PRIMARY KEY, effective_from date NOT NULL, "
        "effective_to date, CONSTRAINT ck_charge_master_ck_charge_master_effective_range "
        "CHECK (effective_to IS NULL OR effective_to > effective_from))"
    ))
    connection = await db.connection()

    def run(sync_connection, operation):
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(sync_connection)))
        operation()

    await connection.run_sync(run, migration.upgrade)
    await connection.run_sync(run, migration.downgrade)
    await connection.run_sync(run, migration.upgrade)
    await db.execute(sa.text("INSERT INTO charge_master VALUES (1, '2026-06-01', '2026-06-01')"))
    with pytest.raises(DBAPIError, match="check constraint"):
        async with db.begin_nested():
            await db.execute(sa.text("INSERT INTO charge_master VALUES (2, '2026-06-02', '2026-06-01')"))
    with pytest.raises(DBAPIError, match="One-day tariffs exist"):
        # Migration Operations executes on the connection, bypassing the
        # Session's lazily opened savepoint. Protect that same connection.
        async with connection.begin_nested():
            await connection.run_sync(run, migration.downgrade)
    assert (await db.execute(sa.text("SELECT count(*) FROM charge_master"))).scalar_one() == 1
