"""Multi-hostname token issuers.

Keycloak derives `iss` from the Host header it was reached on, so one realm
mints a different issuer for a developer on https://localhost than for a ward
PC on the LAN. These tests pin the allowlist's shape, because the failure it
prevents is silent: login succeeds and then every API call 401s.
"""
from app.common.config import Settings, allowed_jwt_issuers


def _settings(**kw) -> Settings:
    """Settings with every field this module reads passed explicitly.

    `_env_file=None` is not enough on its own: pydantic-settings still reads
    os.environ, and the dev container really does export
    JWT_ADDITIONAL_ISSUERS — which silently decided the result of the first
    version of these tests.
    """
    kw.setdefault("jwt_additional_issuers", "")
    return Settings(_env_file=None, **kw)


def test_additional_issuers_default_to_none_configured():
    """The shipped default must be empty, so single-host stays strict."""
    assert Settings.model_fields["jwt_additional_issuers"].default == ""


def test_single_issuer_when_none_are_added():
    s = _settings(jwt_issuer="https://a/realms/r")
    assert allowed_jwt_issuers(s) == ("https://a/realms/r",)


def test_additional_issuers_are_appended_in_order():
    s = _settings(
        jwt_issuer="https://a/realms/r",
        jwt_additional_issuers="https://b/realms/r,https://c/realms/r",
    )
    assert allowed_jwt_issuers(s) == (
        "https://a/realms/r",
        "https://b/realms/r",
        "https://c/realms/r",
    )


def test_whitespace_and_empty_entries_are_ignored():
    """A trailing comma or a padded entry must not become an issuer of "".

    An empty string in the allowlist would be inert with PyJWT, but it reads as
    a configured value and would survive review as one.
    """
    s = _settings(
        jwt_issuer="https://a/realms/r",
        jwt_additional_issuers="  https://b/realms/r  , ,,",
    )
    assert allowed_jwt_issuers(s) == ("https://a/realms/r", "https://b/realms/r")


def test_primary_issuer_is_not_duplicated():
    s = _settings(
        jwt_issuer="https://a/realms/r",
        jwt_additional_issuers="https://a/realms/r,https://b/realms/r",
    )
    assert allowed_jwt_issuers(s) == ("https://a/realms/r", "https://b/realms/r")


def test_no_wildcard_is_honoured():
    """`*` is a literal issuer, never "accept anything".

    Stated as a test because the natural next request when a third address is
    added is to wildcard it, and PyJWT would then accept only the literal "*".
    """
    s = _settings(jwt_issuer="https://a/realms/r", jwt_additional_issuers="*")
    allowed = allowed_jwt_issuers(s)
    assert allowed == ("https://a/realms/r", "*")
    assert "https://evil.example/realms/r" not in allowed
