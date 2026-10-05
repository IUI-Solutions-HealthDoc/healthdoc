"""The offline bundle check: HealthDoc's HIP encoder, its HIU decoder and its
HIU document validator agree on every record type HealthDoc builds.

It found that a HealthDoc HIU refused a HealthDoc HIP's imaging report: the
report carries a PACS study reference as an application/json attachment, and
the HIU accepted embedded PDFs only.
"""

import base64
import copy
import json

import pytest

from app.integrations.abdm import hi_crypto
from app.integrations.abdm.hiu import records
from scripts import abdm_bundle_check as tool
from scripts.generate_abdm_fhir_samples import _samples


def test_every_sample_survives_encode_decode_and_the_hius_checks(capsys):
    assert tool.main(["roundtrip"]) == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out
    assert f"{len(_samples())} of {len(_samples())} passed" in out


def test_a_page_has_the_shape_the_hip_pushes_and_decodes_with_the_hius_keys():
    bundle = _samples()["OPConsultation"]
    page, keys = tool.encode(bundle, reference="ctx-1")
    assert set(page) == {"pageNumber", "pageCount", "transactionId", "entries", "keyMaterial"}
    assert page["keyMaterial"]["cryptoAlg"] == "ECDH" and page["keyMaterial"]["curve"] == "Curve25519"
    assert len(base64.b64decode(page["keyMaterial"]["nonce"])) == 32
    entry = page["entries"][0]
    assert entry["media"] == "application/fhir+json" and entry["careContextReference"] == "ctx-1"
    assert len(entry["checksum"]) == 32  # MD5 hex of the plaintext
    decoded = tool.decode(page, keys)[0]
    assert decoded["checksum_ok"] and decoded["bundle"] == bundle
    assert tool.check(bundle, decoded, reference="ctx-1") == []


def test_a_tampered_page_fails_authentication_rather_than_decoding():
    page, keys = tool.encode(_samples()["Prescription"], reference="ctx-1")
    raw = bytearray(base64.b64decode(page["entries"][0]["content"]))
    raw[10] ^= 1
    page["entries"][0]["content"] = base64.b64encode(bytes(raw)).decode()
    with pytest.raises(hi_crypto.HiCryptoError, match="authentication"):
        tool.decode(page, keys)


def test_a_wrong_checksum_is_reported():
    bundle = _samples()["WellnessRecord"]
    page, keys = tool.encode(bundle, reference="ctx-1")
    page["entries"][0]["checksum"] = "0" * 32
    decoded = tool.decode(page, keys)[0]
    assert tool.check(bundle, decoded, reference="ctx-1") == [
        "checksum: declared checksum does not match the plaintext"
    ]


def _pacs(**reference) -> dict:
    return {"contentType": "application/json",
            "data": base64.b64encode(json.dumps(reference).encode()).decode()}


def test_the_hiu_accepts_the_pacs_study_reference_an_imaging_report_carries():
    records._validate_attachment(_pacs(pacsStudyUid="1.2.3", modality="xray", report="Clear"))


@pytest.mark.parametrize("attachment", [
    _pacs(pacsStudyUid="1.2.3", modality="xray", report="Clear", script="<x>"),
    _pacs(pacsStudyUid="1.2.3", modality="xray"),
    _pacs(pacsStudyUid="", modality="xray", report="Clear"),
    {"contentType": "application/json", "data": base64.b64encode(b"[1, 2]").decode()},
    {"contentType": "application/json", "data": base64.b64encode(b"not json").decode()},
    {"contentType": "image/png", "data": base64.b64encode(b"\x89PNG").decode()},
])
def test_any_other_attachment_is_still_refused(attachment):
    with pytest.raises(records.RecordRefused):
        records._validate_attachment(attachment)


def test_a_binary_resource_stays_pdf_only():
    bundle = copy.deepcopy(_samples()["DiagnosticReportImaging"])
    # A Binary is a document in its own right; only a PDF may be one.
    media = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "Media")
    with pytest.raises(records.RecordRefused, match="PDF"):
        records._validate_pdf({**media["content"]})
