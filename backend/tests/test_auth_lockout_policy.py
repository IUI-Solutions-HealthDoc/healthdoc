"""Auth lockout policy (#158).

The backend never sees a password — Keycloak authenticates, and
`app/auth/deps.py` only validates the resulting JWT. So "5 failed attempts ->
15-minute lockout" cannot be implemented in application code; it is realm
configuration, and this is where it is asserted.

`bruteForceProtected: true` was already set, which reads as "we have brute-force
protection" and looks finished in a review. It was not: with none of the tuning
keys present, Keycloak applies its own defaults — 30 failures and a 60-second
wait — so the realm was protected, and calibrated to something nobody chose.
That gap is exactly the kind a test makes visible and prose does not.

These assertions are cheap and they guard a security control that is otherwise
one careless realm export away from silently reverting.
"""
from __future__ import annotations

import json
import pathlib

import pytest

REALM_PATH = (pathlib.Path(__file__).resolve().parents[2]
              / "infra" / "keycloak" / "realm-healthdoc.json")


@pytest.fixture(scope="module")
def realm() -> dict:
    assert REALM_PATH.is_file(), f"realm file not found at {REALM_PATH}"
    return json.loads(REALM_PATH.read_text())


def test_brute_force_protection_is_on(realm):
    assert realm.get("bruteForceProtected") is True


def test_lockout_triggers_on_the_fifth_failure(realm):
    """#158: five failed attempts."""
    assert realm.get("failureFactor") == 5, (
        "Keycloak's default is 30. Without an explicit failureFactor, "
        "bruteForceProtected alone does not give the policy #158 specifies."
    )


def test_lockout_lasts_fifteen_minutes(realm):
    """#158: a 15-minute lockout, and not an escalating one.

    waitIncrementSeconds sets the first wait; maxFailureWaitSeconds caps it.
    Leaving the cap unset lets the wait escalate past 15 minutes on repeated
    failures, which is a different policy from the one that was agreed.
    """
    assert realm.get("waitIncrementSeconds") == 900
    assert realm.get("maxFailureWaitSeconds") == 900


def test_lockout_is_temporary_not_permanent(realm):
    """A permanent lockout on a clinical system is a denial-of-service vector.

    An attacker who knows a clinician's username could lock them out of the
    ward terminal indefinitely. Temporary lockout still defeats brute force
    while letting legitimate staff back in.
    """
    assert realm.get("permanentLockout") is False


def test_failure_counter_resets_within_a_shift(realm):
    """maxDeltaTimeSeconds is the window over which failures accumulate.

    12 hours covers a long shift: two typos in the morning and three in the
    evening should not combine into a lockout, but a sustained attack inside
    one shift still trips it.
    """
    assert realm.get("maxDeltaTimeSeconds") == 43200


def test_direct_access_grants_are_disabled_on_the_public_client(realm):
    """Belt and braces for the same issue.

    Direct access grants (password grant) let a client exchange a username and
    password for a token without the browser flow — the easiest surface to
    brute-force, and unnecessary for an authorization-code + PKCE frontend.
    """
    frontend = next(c for c in realm["clients"] if c["clientId"] == "healthdoc-frontend")
    assert frontend.get("directAccessGrantsEnabled") is False
    assert frontend.get("publicClient") is True
    assert frontend["attributes"]["pkce.code.challenge.method"] == "S256"


def test_healthdoc_login_theme_is_selected_and_shipped(realm):
    assert realm.get("loginTheme") == "healthdoc"
    theme = REALM_PATH.parent / "themes" / "healthdoc" / "login"
    assert (theme / "theme.properties").is_file()
    assert (theme / "resources" / "css" / "login.css").is_file()
    assert (theme / "resources" / "img" / "healthdoc-logo.png").is_file()
