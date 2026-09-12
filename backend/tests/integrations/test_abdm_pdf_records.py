"""Embedded PDFs must stay inside the same consent-bound external document."""

import base64
import copy

import pytest
from sqlalchemy import select

from app.integrations.abdm.hiu import records
from app.integrations.abdm.hiu.models import AbdmReceivedBundle
from tests.integrations.test_abdm_received_records import (
    ACTOR,
    FACILITY,
    push,
    receive,
)
from tests.integrations.test_abdm_received_records import hiu_db as hiu_fixture
from tests.integrations.test_abdm_received_records import received_case as received_fixture

hiu_db = hiu_fixture
received_case = received_fixture

PDF = base64.b64encode(b"%PDF-1.7\nSynthetic parser boundary fixture\n%%EOF").decode()


def attach(bundle, *, inline=False):
    bundle = copy.deepcopy(bundle)
    composition = bundle["entry"][0]["resource"]
    composition["section"] = [{"entry": [{"reference": "urn:uuid:attachment"}]}]
    if inline:
        resource = {
            "resourceType": "DocumentReference",
            "subject": {"reference": "Patient/p1"},
            "content": [{"attachment": {"contentType": "application/pdf", "data": PDF}}],
        }
    else:
        resource = {
            "resourceType": "Binary",
            "contentType": "application/pdf",
            "data": PDF,
            "securityContext": {"reference": "Patient/p1"},
        }
    bundle["entry"].append({"fullUrl": "urn:uuid:attachment", "resource": resource})
    return bundle


@pytest.mark.parametrize("inline", [False, True], ids=["binary", "document-reference"])
async def test_embedded_pdf_is_encrypted_viewable_and_denied_after_revocation(
    received_case, inline
):
    case = received_case
    bundle = attach(case.bundle, inline=inline)
    await receive(case, push(case, bundle))
    receipt = (await case.db.execute(select(AbdmReceivedBundle))).scalar_one()
    assert receipt.status == "stored"
    assert PDF.encode() not in bytes(receipt.content_encrypted)
    assert (
        await records.read_record(case.db, receipt.id, facility_id=FACILITY, actor_id=ACTOR)
        == bundle
    )
    case.artefact.status = "revoked"
    await case.db.flush()
    with pytest.raises(records.RecordRefused):
        await records.read_record(case.db, receipt.id, facility_id=FACILITY, actor_id=ACTOR)


@pytest.mark.parametrize(
    "defect",
    ["unreferenced", "other-patient", "html", "invalid-base64", "oversized", "size", "hash"],
)
async def test_unverifiable_or_unsafe_pdf_is_refused(received_case, defect):
    case = received_case
    bundle = attach(case.bundle)
    attachment = bundle["entry"][-1]["resource"]
    if defect == "unreferenced":
        bundle["entry"][0]["resource"]["section"] = []
    elif defect == "other-patient":
        attachment["securityContext"]["reference"] = "Patient/other"
    elif defect == "html":
        attachment["data"] = base64.b64encode(b"<html>unsafe</html>").decode()
    elif defect == "invalid-base64":
        attachment["data"] = "!invalid!"
    elif defect == "oversized":
        attachment["data"] = "A" * (4 * ((records.MAX_PDF_BYTES + 2) // 3) + 4)
    elif defect == "size":
        attachment["size"] = 1
    elif defect == "hash":
        attachment["hash"] = "incorrect"
    grant = await records.grant_for(case.db, case.request, now=case.now)
    with pytest.raises(records.RecordRefused):
        records.validate_document(bundle, grant, "visit-1")
