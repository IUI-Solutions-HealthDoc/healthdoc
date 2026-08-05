"""Central settings — every module reads config from here, never os.environ directly."""
import base64
import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER = "change-me-in-env"
_MIN_KEY_BYTES = 32  # AES-256 key size / minimum acceptable HMAC entropy


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "dev"
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://healthdoc:change-me@localhost:5432/healthdoc"
    mongo_uri: str = "mongodb://localhost:27017/healthdoc"
    redis_url: str = "redis://localhost:6379/0"
    jwt_issuer: str = "http://keycloak:8080/realms/healthdoc"
    oidc_audience: str = "account"
    keycloak_base_url: str = "http://keycloak:8080/auth"
    keycloak_realm: str = "healthdoc"
    keycloak_admin: str = "admin"
    keycloak_admin_password: str = "change-me"
    minio_endpoint: str = "localhost:9000"
    minio_root_user: str = "healthdoc"
    minio_root_password: str = "change-me"
    minio_bucket_files: str = "hd-files"
    minio_bucket_reports: str = "hd-reports"
    abdm_gateway_base_url: str = "https://dev.abdm.gov.in/gateway"
    abdm_client_id: str = "change-me"
    abdm_client_secret: str = "change-me"
    abdm_hfr_facility_id: str = "change-me"

    aadhaar_hmac_key: str = "change-me-in-env"
    aadhaar_encryption_key: str = "change-me-in-env"
    aadhaar_hmac_keys_json: str = ""
    aadhaar_encryption_keys_json: str = ""

    aadhaar_hmac_current_key_version: int = 1
    # Separate from the HMAC version pointer (PR review blocker 7) — HMAC and
    # AES keys rotate independently (schema §3 0006: "never the same key"),
    # so sharing one version setting means rotating one silently breaks the
    # other. decrypt_pii reads its version from the ciphertext blob itself,
    # so this setting only drives encrypt_pii's default going forward.
    aadhaar_encryption_current_key_version: int = 1

    icd11_base_url: str = "http://icd11:80"
    icd11_release: str = "2025-01"
    icd11_linearization: str = "mms"

    @model_validator(mode="after")
    def _validate_aadhaar_keys(self) -> "Settings":
        """Fail loudly at boot, not silently at rest (PR review blockers 1, 2).
        A placeholder or weak key looks like it works — everything encrypts
        and decrypts fine — but the confidentiality guarantee is gone.
        Skip only for tests that don't touch crypto at all; never set this
        in a real environment.

        Covers both the legacy single-key fields AND the rotation-capable
        *_json fields — every key inside the JSON blob is validated
        individually, not just the current one, since an old key is still
        used for lookups during rotation (this was a gap: the *_json path
        originally bypassed validation entirely)."""
        if os.environ.get("HEALTHDOC_SKIP_KEY_VALIDATION") == "1":
            return self

        if self.aadhaar_hmac_keys_json:
            for version, key in self._parse_keys_json(
                self.aadhaar_hmac_keys_json, "aadhaar_hmac_keys_json"
            ).items():
                self._check_hmac_key(key, f"aadhaar_hmac_keys_json[{version}]")
        else:
            self._check_hmac_key(self.aadhaar_hmac_key, "aadhaar_hmac_key")

        if self.aadhaar_encryption_keys_json:
            for version, key in self._parse_keys_json(
                self.aadhaar_encryption_keys_json, "aadhaar_encryption_keys_json"
            ).items():
                self._check_encryption_key(key, f"aadhaar_encryption_keys_json[{version}]")
        else:
            self._check_encryption_key(self.aadhaar_encryption_key, "aadhaar_encryption_key")

        return self

    @staticmethod
    def _parse_keys_json(raw_json: str, field_name: str) -> dict[str, str]:
        import json
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field_name} is not valid JSON") from exc
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError(f"{field_name} must be a non-empty JSON object of {{version: key}}")
        return parsed

    @staticmethod
    def _check_hmac_key(key: str, field_name: str) -> None:
        if not key or key == _PLACEHOLDER:
            raise ValueError(
                f"{field_name} is unset or still the placeholder value — set it "
                f"to a real secret (or set aadhaar_hmac_keys_json instead) before starting."
            )
        if len(key.encode("utf-8")) < _MIN_KEY_BYTES:
            raise ValueError(
                f"{field_name} is too short ({len(key.encode('utf-8'))} bytes) — "
                f"needs at least {_MIN_KEY_BYTES} bytes of entropy."
            )

    @staticmethod
    def _check_encryption_key(key: str, field_name: str) -> None:
        if not key or key == _PLACEHOLDER:
            raise ValueError(
                f"{field_name} is unset or still the placeholder value — set it to "
                f"a base64-encoded 32-byte random key before starting."
            )
        try:
            decoded = base64.b64decode(key, validate=True)
        except Exception as exc:
            raise ValueError(
                f"{field_name} must be base64-encoded random bytes, not a passphrase "
                f"(a SHA-256-derived key from a human passphrase is brute-forceable)."
            ) from exc
        if len(decoded) != _MIN_KEY_BYTES:
            raise ValueError(
                f"{field_name} must decode to exactly {_MIN_KEY_BYTES} bytes "
                f"(AES-256 key), got {len(decoded)}."
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()
