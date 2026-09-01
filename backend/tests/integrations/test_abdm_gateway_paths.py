"""ABDM v3 gateway paths — pinned by shape, not by spelling.

Confirmed against the sandbox on 2026-09-01 with a real session token: every
path below answered 405 to a GET (route exists, wrong method) or 400, while the
ten paths this repo carried before all answered 404.

These are Settings fields, so a wrong value is an env change rather than a
release — but nothing in the suite noticed when all ten were wrong, which is
how they stayed wrong. This file makes the number move.
"""
import pytest

from app.common.config import Settings

#: ABDM segments its v3 API by capability. `/api/hiecm/v3/...` as a single base
#: is the assumption that produced ten 404s, so it is asserted against directly.
VALID_SEGMENTS = (
    "/api/hiecm/gateway/v3/",
    "/api/hiecm/hip/v3/",
    "/api/hiecm/user-initiated-linking/v3/",
    "/api/hiecm/consent/v3/",
    "/api/hiecm/data-flow/v3/",
    "/api/hiecm/patient-share/v3/",
    # HIP-initiated linking's token exchange genuinely sits at the bare base.
    "/api/hiecm/v3/token/",
)

GATEWAY_PATH_FIELDS = sorted(
    name for name in Settings.model_fields
    if name.startswith("abdm_path_") and name not in {
        # M1 lives on abhasbx.abdm.gov.in, not the gateway — different base.
        "abdm_path_enrol_request_otp", "abdm_path_enrol_by_aadhaar",
        "abdm_path_login_request_otp", "abdm_path_login_verify",
    }
)


def _default(name: str) -> str:
    return Settings.model_fields[name].default


def test_there_are_gateway_paths_to_check():
    """Guards the filter above: an empty list would make every test below vacuous."""
    assert len(GATEWAY_PATH_FIELDS) >= 12


@pytest.mark.parametrize("field", GATEWAY_PATH_FIELDS)
def test_path_sits_under_a_known_capability_segment(field):
    value = _default(field)
    assert value.startswith(VALID_SEGMENTS), (
        f"{field} = {value!r} is not under a confirmed ABDM v3 segment. "
        "Check the official Postman collection rather than pattern-matching a sibling."
    )


@pytest.mark.parametrize("field", GATEWAY_PATH_FIELDS)
def test_path_is_not_the_disproven_single_base(field):
    """`/api/hiecm/v3/<anything-but-token>` is the shape that 404'd ten times."""
    value = _default(field)
    if value.startswith("/api/hiecm/v3/"):
        assert value.startswith("/api/hiecm/v3/token/"), (
            f"{field} = {value!r} uses the disproven single-base prefix."
        )


def test_bridge_management_is_v3_not_v1():
    """`/gateway/v1/bridges` answers 403 900908 — a retired version, not a
    missing subscription. Reverting to it costs days of misdirected support."""
    for field in ("abdm_path_bridge_services", "abdm_path_bridge_service",
                  "abdm_path_bridge_url"):
        value = _default(field)
        assert "/gateway/v1/" not in value, f"{field} reverted to the v1 bridge API"
        assert value.startswith("/api/hiecm/gateway/v3/"), field
