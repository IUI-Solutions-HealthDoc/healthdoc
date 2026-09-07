"""The purpose we accept must be the purpose shown by the consent manager."""
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.integrations.abdm.hiu.router import ConsentRequestIn


def _payload(purpose):
    now = datetime.now(UTC)
    return dict(
        abha_address="synthetic@sbx", purpose_code=purpose,
        hi_types=["Prescription"], date_range_from=now - timedelta(days=1),
        date_range_to=now, requested_expiry=now + timedelta(days=1),
    )


@pytest.mark.parametrize("purpose", ["BTG", "PUBHLTH", "HPAYMT", "DSRCH", "PATRQT"])
def test_unmapped_purposes_are_refused_before_recording_or_dispatch(purpose):
    # The service recognizes these codes, but the outbound product workflow
    # currently implements only care management. Silently sending CAREMGT for
    # one of these is a different request from the one the staff member made.
    with pytest.raises(ValidationError):
        ConsentRequestIn.model_validate(_payload(purpose))


def test_care_management_remains_supported():
    assert ConsentRequestIn.model_validate(_payload("CAREMGT")).purpose_code == "CAREMGT"
