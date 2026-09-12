"""Settings error diagnostics must not display sandbox credentials."""

import uuid

import pytest
from pydantic import ValidationError

from app.common.config import Settings


def test_abdm_secrets_are_excluded_from_settings_repr():
    values = {
        "abdm_client_secret": "unit-test-client-secret",
        "abdm_callback_shared_secret": "unit-test-callback-secret",
        "abdm_link_otp_delivery_token": "unit-test-relay-secret",
    }
    settings = Settings.model_construct(**values)
    for field, value in values.items():
        assert value not in repr(settings)
        assert getattr(settings, field) == value


def test_sandbox_context_allowlist_defaults_closed_and_rejects_wildcards():
    assert Settings.model_construct().abdm_sandbox_local_author_context_ids == ()
    with pytest.raises(ValidationError):
        Settings(_env_file=None, abdm_sandbox_local_author_context_ids=["*"])
    context_id = uuid.uuid4()
    assert Settings(
        _env_file=None, abdm_sandbox_local_author_context_ids=[str(context_id)]
    ).abdm_sandbox_local_author_context_ids == (context_id,)
