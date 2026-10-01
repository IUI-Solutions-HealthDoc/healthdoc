"""Retried registration writes must not create a second record.

Emergency registration and the patient photo are both written at a desk under
pressure, over networks that drop responses. Before these routes took an
Idempotency-Key, a lost 201 followed by a resend issued a second THID for one
unidentified arrival, and a resent photo left the first upload stored with
nothing pointing at it.

Real Postgres and real MinIO: the receipt table, the append-only audit trigger
and the erased object are exactly what these tests need to observe.
"""
from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from tests._lab_seed import TEST_DATABASE_URL

from .conftest import NURSE, RECEPTIONIST

_EMERGENCY = "/api/v1/emergency/patients"


def _jpeg() -> bytes:
    # Distinct bytes per call so one test's photo never matches another's.
    return b"\xff\xd8\xff\xe0" + uuid.uuid4().bytes + b"\x00" * 64


def _rows(sql: str, **params):
    url = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2") if TEST_DATABASE_URL else ""
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return conn.execute(sa.text(sql), params).mappings().all()
    finally:
        engine.dispose()


def _key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


@pytest.fixture
def receptionist(client_as, seeded_patient_id):
    return client_as(RECEPTIONIST)


def _new_patient(client) -> str:
    response = client.post(
        "/api/v1/patients",
        headers=_key(),
        json={"full_name": "Photo Retry Patient", "sex": "female", "age_years": 33},
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]["id"]


def _upload(client, patient_id: str, data: bytes, headers: dict[str, str], name="p.jpg"):
    return client.post(
        f"/api/v1/patients/{patient_id}/photo",
        headers=headers,
        files={"upload": (name, data, "image/jpeg")},
    )


class TestEmergencyRegistrationRetry:
    def test_same_key_and_body_returns_the_original_thid(self, client_as, seeded_patient_id):
        client = client_as(NURSE)
        name = f"ER Retry {uuid.uuid4().hex[:10]}"
        payload = {"full_name": name, "sex": "unknown", "age_years": 30}
        headers = _key()

        first = client.post(_EMERGENCY, headers=headers, json=payload)
        second = client.post(_EMERGENCY, headers=headers, json=payload)

        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert second.json()["data"]["id"] == first.json()["data"]["id"]
        assert second.json()["data"]["thid"] == first.json()["data"]["thid"]
        assert len(_rows("SELECT id FROM patients WHERE full_name = :n", n=name)) == 1

    def test_reusing_a_key_for_a_different_arrival_is_refused(self, client_as, seeded_patient_id):
        client = client_as(NURSE)
        headers = _key()
        first = client.post(_EMERGENCY, headers=headers, json={"sex": "male", "age_years": 50})
        reused = client.post(_EMERGENCY, headers=headers, json={"sex": "female", "age_years": 20})

        assert first.status_code == 201, first.text
        assert reused.status_code == 409, reused.text

    def test_a_key_is_required(self, client_as, seeded_patient_id):
        response = client_as(NURSE).post(_EMERGENCY, json={"sex": "unknown", "age_years": 40})
        assert response.status_code == 422, response.text
        assert response.json()["error"]["message"][0]["loc"] == ["header", "Idempotency-Key"]

    def test_an_unreachable_mobile_is_refused(self, client_as, seeded_patient_id):
        response = client_as(NURSE).post(
            _EMERGENCY, headers=_key(),
            json={"sex": "unknown", "age_years": 40, "mobile": "12345"},
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["message"][0]["loc"] == ["body", "mobile"]

    def test_a_valid_mobile_is_stored_normalised(self, client_as, seeded_patient_id):
        response = client_as(NURSE).post(
            _EMERGENCY, headers=_key(),
            json={"sex": "unknown", "age_years": 40, "mobile": "98765 43210"},
        )
        assert response.status_code == 201, response.text
        rows = _rows("SELECT mobile FROM patients WHERE id = :id", id=response.json()["data"]["id"])
        assert rows[0]["mobile"] == "+919876543210"


class TestPatientPhotoRetry:
    def test_upload_requires_a_key(self, receptionist):
        patient_id = _new_patient(receptionist)
        response = _upload(receptionist, patient_id, _jpeg(), {})
        assert response.status_code == 400, response.text

    def test_a_pdf_is_not_a_photo(self, receptionist):
        patient_id = _new_patient(receptionist)
        response = _upload(
            receptionist, patient_id, b"%PDF-1.4\n" + b"\x00" * 64, _key(), name="p.pdf",
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["message"]["code"] == "photo_must_be_image"

    def test_a_resent_upload_stores_one_file(self, receptionist):
        patient_id = _new_patient(receptionist)
        data, headers = _jpeg(), _key()

        first = _upload(receptionist, patient_id, data, headers)
        second = _upload(receptionist, patient_id, data, headers)

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert second.json()["data"]["photo_file_id"] == first.json()["data"]["photo_file_id"]
        files = _rows(
            "SELECT id FROM files WHERE patient_id = :p AND owner_module = 'patients'", p=patient_id,
        )
        assert len(files) == 1

    def test_replacing_a_photo_erases_the_previous_one(self, receptionist):
        patient_id = _new_patient(receptionist)
        old = _upload(receptionist, patient_id, _jpeg(), _key()).json()["data"]["photo_file_id"]
        new = _upload(receptionist, patient_id, _jpeg(), _key()).json()["data"]["photo_file_id"]

        assert new != old
        erased = _rows("SELECT erased_at, object_key FROM files WHERE id = :id", id=old)[0]
        assert erased["erased_at"] is not None
        assert erased["object_key"] is None
        assert _rows("SELECT erased_at FROM files WHERE id = :id", id=new)[0]["erased_at"] is None

    def test_delete_erases_audits_and_replays(self, receptionist):
        patient_id = _new_patient(receptionist)
        file_id = _upload(receptionist, patient_id, _jpeg(), _key()).json()["data"]["photo_file_id"]
        headers = _key()

        first = receptionist.delete(f"/api/v1/patients/{patient_id}/photo", headers=headers)
        replay = receptionist.delete(f"/api/v1/patients/{patient_id}/photo", headers=headers)

        assert first.status_code == 200, first.text
        assert replay.status_code == 200, replay.text
        assert _rows("SELECT photo_file_id FROM patients WHERE id = :id", id=patient_id)[0][
            "photo_file_id"
        ] is None
        assert _rows("SELECT erased_at FROM files WHERE id = :id", id=file_id)[0]["erased_at"] is not None

        audits = _rows(
            "SELECT old_value, new_value FROM audit_logs "
            "WHERE resource_type = 'patients' AND resource_id = :id AND action = 'update' "
            "ORDER BY chain_seq",
            id=patient_id,
        )
        assert [a["new_value"] for a in audits] == [
            {"photo_file_id": file_id}, {"photo_file_id": None},
        ]
        assert audits[-1]["old_value"] == {"photo_file_id": file_id}

    def test_delete_without_a_photo_is_404(self, receptionist):
        patient_id = _new_patient(receptionist)
        response = receptionist.delete(f"/api/v1/patients/{patient_id}/photo", headers=_key())
        assert response.status_code == 404, response.text

    def test_delete_requires_a_key(self, receptionist):
        patient_id = _new_patient(receptionist)
        response = receptionist.delete(f"/api/v1/patients/{patient_id}/photo")
        assert response.status_code == 400, response.text
