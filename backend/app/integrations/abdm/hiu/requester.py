"""The real staff identity behind a consent ask, never a facility placeholder.

M3 v2.8 requires consent.requester.name and identifier.{type,value,system}.
The issuer cannot be guessed from a registration number: staff administration
must record it explicitly. This validates completeness, not registry membership.

One exception: an explicitly allowlisted dev.* account on the NHA sandbox asks
as NHA's own published sample requester, labelled as a test.
"""

from collections.abc import Mapping
from urllib.parse import urlsplit

from app.common.config import get_settings
from app.users.models import User

#: NHA's own sample requester identifier from its Milestone 3 Postman
#: collection (16 Feb 2026). Taken from the Postman rather than the docs page
#: (REGNO / MH1001 / https://www.mciindia.org) because its registry URI is not
#: a real host, so it cannot claim anyone's actual licence. The name says what
#: it is instead of borrowing the sample's doctor name.
SANDBOX_TEST_REQUESTER = {
    "name": "ABDM SANDBOX TEST REQUESTER",
    "identifier": {"type": "REGNO1", "value": "MH1001", "system": "https://www.mciindia.9985"},
}


class RequesterUnavailable(ValueError):
    """A complete, active, facility-scoped requester identity is required."""


def validate_requester(value: object) -> dict:
    if not isinstance(value, Mapping) or not isinstance(value.get("identifier"), Mapping):
        raise RequesterUnavailable("ABDM requester identity is incomplete")
    identifier = value["identifier"]
    result = {}
    for key, raw, maximum in (
        ("name", value.get("name"), 200),
        ("type", identifier.get("type"), 50),
        ("value", identifier.get("value"), 50),
        ("system", identifier.get("system"), 255),
    ):
        if (
            not isinstance(raw, str)
            or not raw.strip()
            or len(raw.strip()) > maximum
            or raw.strip().lower() in {"change-me", "placeholder"}
        ):
            raise RequesterUnavailable("ABDM requester identity is incomplete")
        result[key] = raw.strip()
    try:
        uri = urlsplit(result["system"])
        if (
            uri.scheme not in {"http", "https"}
            or not uri.hostname
            or uri.username is not None
            or uri.password is not None
            or uri.query
            or uri.fragment
            or any(char.isspace() for char in result["system"])
        ):
            raise ValueError
    except ValueError as exc:
        raise RequesterUnavailable("ABDM requester registry URI is invalid") from exc
    return {
        "name": result["name"],
        "identifier": {key: result[key] for key in ("type", "value", "system")},
    }


def uses_sandbox_test_requester(user: User) -> bool:
    """True only for an allowlisted dev.* account against the NHA sandbox."""
    settings = get_settings()
    return (
        settings.environment == "dev"
        and settings.abdm_gateway_base_url == "https://dev.abdm.gov.in"
        and settings.abdm_x_cm_id == "sbx"
        and user.id in settings.abdm_sandbox_test_requester_user_ids
        and user.username.startswith("dev.")
    )


def from_staff(user: User | None, facility_id) -> dict:
    if user is None or not user.is_active or user.facility_id != facility_id:
        raise RequesterUnavailable("ABDM requester is unavailable")
    # The allowlist wins over whatever the dev account's profile holds, so a
    # snapshot taken at request time and re-derived by the worker always agree.
    if uses_sandbox_test_requester(user):
        return validate_requester(SANDBOX_TEST_REQUESTER)
    return validate_requester(
        {
            "name": user.full_name,
            "identifier": {
                "type": user.registration_identifier_type,
                "value": user.registration_number,
                "system": user.registration_identifier_system,
            },
        }
    )
