"""B2-W4-01: patient merge tool — pure-logic tests (no DB required).
Full request_merge()/approve_merge()/reject_merge() flows need a real DB
session (db.get/flush) — pending the same async-DB fixture decision noted
in test_patient_search.py.
"""
import uuid

from app.patients.service import _patient_snapshot


class _FakePatient:
    def __init__(self, id, uhid=None, thid=None, status="active", merged_into_patient_id=None):
        self.id = id
        self.uhid = uhid
        self.thid = thid
        self.status = status
        self.merged_into_patient_id = merged_into_patient_id


def test_patient_snapshot_captures_expected_fields():
    pid = uuid.uuid4()
    patient = _FakePatient(id=pid, uhid="IN-RJ-JPR001-2026-000001-8", status="active")
    snapshot = _patient_snapshot(patient)
    assert snapshot["id"] == str(pid)
    assert snapshot["uhid"] == "IN-RJ-JPR001-2026-000001-8"
    assert snapshot["status"] == "active"
    assert snapshot["merged_into_patient_id"] is None


def test_patient_snapshot_handles_merged_patient():
    pid = uuid.uuid4()
    target_id = uuid.uuid4()
    patient = _FakePatient(id=pid, thid="TH-JPR001-260714-0007", status="merged", merged_into_patient_id=target_id)
    snapshot = _patient_snapshot(patient)
    assert snapshot["status"] == "merged"
    assert snapshot["merged_into_patient_id"] == str(target_id)
    assert snapshot["thid"] == "TH-JPR001-260714-0007"


def test_patient_snapshot_only_includes_documented_fields():
    # Guards against accidentally leaking full_name/dob/mobile/etc into
    # patient_merge_log's JSONB snapshot — it should only ever capture the
    # identity/merge-state fields the merge action itself changes.
    patient = _FakePatient(id=uuid.uuid4())
    snapshot = _patient_snapshot(patient)
    assert set(snapshot.keys()) == {"id", "uhid", "thid", "status", "merged_into_patient_id"}
