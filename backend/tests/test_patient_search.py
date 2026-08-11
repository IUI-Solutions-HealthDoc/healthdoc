"""B2-W2-02: patient search — pure-logic tests (no DB required).
DB-integration tests for search_patients() itself are pending a shared
async-DB test fixture — see note at bottom of file.
"""
import pytest
from pydantic import ValidationError

from app.patients.schemas import PatientSearchRequest
from app.patients.service import mask_mobile


def test_mask_mobile_keeps_last_four_digits():
    assert mask_mobile("9876543210") == "******3210"


def test_mask_mobile_none_input():
    assert mask_mobile(None) is None


def test_mask_mobile_short_input_fully_masked():
    assert mask_mobile("123") == "***"


def test_search_request_requires_at_least_one_criterion():
    with pytest.raises(ValidationError):
        PatientSearchRequest()


def test_search_request_accepts_name_only():
    req = PatientSearchRequest(full_name="Ramesh Kumar")
    assert req.full_name == "Ramesh Kumar"


def test_search_request_page_size_capped_at_100():
    with pytest.raises(ValidationError):
        PatientSearchRequest(full_name="test", page_size=101)


def test_search_request_page_must_be_positive():
    with pytest.raises(ValidationError):
        PatientSearchRequest(full_name="test", page=0)


# --- Not yet covered: search_patients() itself ---
# Needs a real Postgres session (trigram similarity, joins, sequences aren't
# mockable meaningfully). No async-DB test fixture exists anywhere in the
# repo yet (conftest.py only has a plain TestClient, no DB). A team decision
# is needed on the test-DB pattern before writing integration tests here —
# e.g. a fixture spinning up a disposable scratch Postgres container, or
# something else, so future DB-dependent tests follow one consistent approach.
