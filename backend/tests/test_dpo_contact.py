"""The DPO's published contact must be reachable (QA 12 Oct 2026: "abc" was accepted)."""
import uuid

import pytest
from pydantic import ValidationError

from app.dpdp.schemas import DpoAppointmentCreate


@pytest.mark.parametrize("contact", ["dpo@hospital.gov.in", "+91 98765 43210", "DPO office, 011-23456789",
                                     "Write to privacy@dh.in or call 0612 2234567"])
def test_an_email_or_phone_is_accepted(contact):
    assert DpoAppointmentCreate(user_id=uuid.uuid4(), contact_published=True, published_contact=contact)


@pytest.mark.parametrize("contact", ["abc", "dpo", "room 12", "12345"])
def test_text_with_no_way_to_reach_anyone_is_refused(contact):
    with pytest.raises(ValidationError, match="email address or a phone number"):
        DpoAppointmentCreate(user_id=uuid.uuid4(), contact_published=True, published_contact=contact)
