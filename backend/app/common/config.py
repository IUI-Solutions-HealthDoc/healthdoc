"""Central settings — every module reads config from here, never os.environ directly."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # Drives encrypt_pii's default key version going forward.
    # decrypt_pii reads its version from the ciphertext blob itself,
    # so this setting only affects new encryptions, not decryption.
    aadhaar_encryption_current_key_version: int = 1
    icd11_base_url: str = "http://icd11:80"
    icd11_release: str = "2025-01"
    icd11_linearization: str = "mms"

    # Crypto keys — MUST be base64-encoded 32 random bytes in production.
    # security.py refuses to start if these are still placeholders.
    # Generate: python3 -c "import os, base64; print(base64.b64encode(os.urandom(32)).decode())"
    pii_encryption_key: str = "change-me"
    aadhaar_hmac_key: str = "change-me"

    # CORS — comma-separated extra origins. Default is empty (only Electron + https://localhost).
    # Set to "http://localhost:3000" in .env for Next.js dev; never hardcode dev origins.
    cors_origins: str = ""

    # Where data_access_log rows go when the database write fails
    # (app/consent/access_log_fallback.py). MUST point at a mounted volume in
    # deployment — the whole point is surviving a Postgres outage, and a path
    # inside an ephemeral container filesystem doesn't.
    data_access_log_fallback_path: str = "/var/log/healthdoc/data_access_log_fallback.jsonl"


@lru_cache
def get_settings() -> Settings:
    return Settings()
