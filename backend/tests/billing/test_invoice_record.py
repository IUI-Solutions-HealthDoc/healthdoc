"""An issued invoice is one shareable NRCeS InvoiceRecord (the eighth HI type).

Issuing offers a care context in the same transaction, dated by the new
issued_at, which the freeze trigger holds fixed so a payment cannot move the
document's date. The transfer builds an InvoiceRecord authored by the
facility, with one ChargeItem per line. Real PostgreSQL (tests/billing/conftest.py),
because trg_invoices_freeze is a database trigger.
"""
from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.billing import service
from app.integrations.abdm.fhir.builder import build_clinical_bundle, validate_min
from app.integrations.abdm.hip.documents import (
    DocumentUnavailable,
    resolve_context_document,
    resolve_document,
)
from app.integrations.abdm.hip.models import AbdmCareContext
from app.integrations.abdm.hip.worker import _clinical_facts
from app.integrations.abdm.jobs import AbdmJob
from app.users.models import Facility

pytestmark = pytest.mark.asyncio


async def _add_line(db, invoice_id: uuid.UUID, category: str, description: str, amount: str) -> None:
    await db.execute(
        sa.text(
            "INSERT INTO invoice_items (id, invoice_id, charge_category, description, quantity, "
            "unit_price, amount, created_at) VALUES (:id, :invoice_id, :category, :description, 1, :amount, :amount, "
            "clock_timestamp())"
        ),
        {"id": uuid.uuid4(), "invoice_id": invoice_id, "category": category,
         "description": description, "amount": amount},
    )
    await db.execute(
        sa.text("UPDATE invoices SET gross_amount = gross_amount + :amount, "
                "net_amount = net_amount + :amount WHERE id = :id"),
        {"amount": amount, "id": invoice_id},
    )


async def _issue(db, invoice_id: uuid.UUID, user: uuid.UUID):
    version = (await db.execute(sa.text("SELECT row_version FROM invoices WHERE id = :id"),
                                {"id": invoice_id})).scalar_one()
    return await service.issue_invoice(db, invoice_id=invoice_id, updated_by=user, expected_row_version=version)


@pytest.fixture
async def issued(db, draft_invoice, user, facility):
    await db.execute(sa.text("UPDATE facilities SET hfr_facility_id = 'TEST-HFR' WHERE id = :id"), {"id": facility})
    await _add_line(db, draft_invoice, "consultation", "OPD consultation", "500.00")
    await _add_line(db, draft_invoice, "lab", "Complete blood count", "250.00")
    invoice = await _issue(db, draft_invoice, user)
    context = (
        await db.execute(select(AbdmCareContext).where(AbdmCareContext.reference == f"invoice/{invoice.id}"))
    ).scalar_one()
    return invoice, context


async def test_issuing_offers_one_invoice_document_dated_by_its_issue(db, issued):
    invoice, context = issued
    assert invoice.issued_at is not None
    assert context.hi_type == "Invoice" and context.visit_id == invoice.visit_id
    assert context.document_at == invoice.issued_at
    # No amounts or lines in the display; ABDM cuts it at 50 characters.
    assert context.display.startswith("Invoice — ") and invoice.invoice_number in context.display
    assert "750" not in context.display and len(context.display) <= 50
    job = (await db.execute(select(AbdmJob).where(AbdmJob.target_id == context.id))).scalar_one()
    assert job.kind == "context_notify"


async def test_the_transfer_builds_an_invoice_record_authored_by_the_facility(db, issued, facility):
    invoice, context = issued
    facts = await _clinical_facts(db, context, facility=await db.get(Facility, facility))
    bundle = build_clinical_bundle(context.hi_type, **facts)
    assert validate_min(bundle) == []
    kinds = [entry["resource"]["resourceType"] for entry in bundle["entry"]]
    assert kinds == ["Composition", "Organization", "Patient", "Invoice", "ChargeItem", "ChargeItem"]
    composition, organization = bundle["entry"][0]["resource"], bundle["entry"][1]["resource"]
    assert composition["meta"]["profile"] == ["https://nrces.in/ndhm/fhir/r4/StructureDefinition/InvoiceRecord"]
    assert composition["type"] == {"text": "Invoice Record"} and "encounter" not in composition
    assert composition["author"][0]["reference"] == f"urn:uuid:{organization['id']}"
    resource = bundle["entry"][3]["resource"]
    assert resource["identifier"] == [{"value": invoice.invoice_number}]
    assert resource["status"] == "issued"
    assert resource["totalNet"] == {"value": 750.0, "currency": "INR"} == resource["totalGross"]
    assert [line["priceComponent"][0]["amount"]["value"] for line in resource["lineItem"]] == [500.0, 250.0]
    codes = [entry["resource"]["code"]["coding"][0]["code"] for entry in bundle["entry"][4:]]
    assert codes == ["00", "04"]  # Consultation, Pathology


async def test_a_payment_does_not_move_the_documents_date(db, issued):
    invoice, context = issued
    await db.execute(sa.text("UPDATE invoices SET status = 'paid', updated_at = now() WHERE id = :id"),
                     {"id": invoice.id})
    source = await resolve_context_document(db, context)
    assert source.authored_at == invoice.issued_at


async def test_the_issue_date_is_frozen_once_issued(db, issued):
    invoice, _context = issued
    with pytest.raises(DBAPIError, match="frozen columns"):
        await db.execute(sa.text("UPDATE invoices SET issued_at = now() - interval '1 day' WHERE id = :id"),
                         {"id": invoice.id})
        await db.flush()


@pytest.mark.parametrize("status", ["draft", "cancelled"])
async def test_a_draft_or_cancelled_invoice_is_not_shareable(db, draft_invoice, patient, facility, status):
    await db.execute(sa.text("UPDATE invoices SET status = :status, issued_at = now() WHERE id = :id"),
                     {"status": status, "id": draft_invoice})
    with pytest.raises(DocumentUnavailable):
        await resolve_document(db, reference=f"invoice/{draft_invoice}", hi_type="Invoice",
                               patient_id=patient, facility_id=facility, visit_id=None)


async def test_an_invoice_issued_before_0094_has_no_date_and_is_not_offered(db, draft_invoice, patient, facility):
    await db.execute(sa.text("UPDATE invoices SET status = 'issued' WHERE id = :id"), {"id": draft_invoice})
    with pytest.raises(DocumentUnavailable):
        await resolve_document(db, reference=f"invoice/{draft_invoice}", hi_type="Invoice",
                               patient_id=patient, facility_id=facility, visit_id=None)
