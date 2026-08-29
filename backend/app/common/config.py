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

    jwt_issuer: str = "https://localhost/auth/realms/healthdoc"
    jwt_jwks_url: str | None = None
    #: Expected `aud` on every access token. Unset disables the check.
    #:
    #: Keycloak only emits a resource-server audience when a client has an
    #: audience protocol mapper, so this stays unset until the realm is
    #: re-imported — enabling it against a realm that does not emit the claim
    #: locks out every user. app/main.py refuses to boot in production while it
    #: is unset, so the permissive default cannot reach production.
    jwt_audience: str | None = None
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

    # ABDM v3 OpenAPI paths already include /api/hiecm/gateway/v3. Keep the
    # origin here so joining a path cannot silently produce /gateway/v3/*.
    abdm_gateway_base_url: str = "https://dev.abdm.gov.in"
    abdm_client_id: str = "change-me"
    abdm_client_secret: str = "change-me"
    abdm_hfr_facility_id: str = "change-me"
    # Consent-manager id sent as X-CM-ID on every gateway call. 'sbx' is the
    # sandbox; production is 'abdm'. Wrong value returns a 400 the gateway
    # does not explain, so it is configuration rather than a constant.
    abdm_x_cm_id: str = "sbx"

    #: ABDM's PUBLIC certificate, used to encrypt Aadhaar numbers, mobile
    #: numbers and OTPs before transmission (see abdm/identity/crypto.py).
    #: Public key material, not a secret — but it rotates, so it is
    #: configuration rather than a constant. Accepts a PUBLIC KEY or a
    #: CERTIFICATE block; `\n` escapes are normalised.
    abdm_public_key_pem: str | None = None

    #: ABHA enrolment/login lives on a DIFFERENT host from the HIECM gateway.
    #: The session endpoint is on abdm_gateway_base_url; enrolment is here.
    #: Sandbox and production differ, so neither is hardcoded.
    abdm_abha_base_url: str = "https://abhasbx.abdm.gov.in/abha/api"

    #: v3 enrolment/login paths, relative to abdm_abha_base_url.
    #:
    #: CONFIRM THESE AGAINST THE SANDBOX BEFORE TRUSTING THEM. They are
    #: settings rather than constants precisely because they are the part of
    #: M1 most likely to be wrong: the previous ABHA call in this repo used
    #: `/v3/hip/token/on-generate`, which is a callback ABDM invokes on a HIP
    #: rather than an endpoint a HIP posts to, and it 401'd silently for the
    #: life of the file. A wrong path here is an env change, not a release.
    abdm_path_enrol_request_otp: str = "/v3/enrollment/request/otp"
    abdm_path_enrol_by_aadhaar: str = "/v3/enrollment/enrol/byAadhaar"
    abdm_path_login_request_otp: str = "/v3/profile/login/request/otp"
    abdm_path_login_verify: str = "/v3/profile/login/verify"

    # ------------------------------------------------------------------
    # M2 (HIP) and M3 (HIU) gateway paths, relative to abdm_gateway_base_url.
    #
    # UNVERIFIED, exactly like the M1 paths above, and for the same reason:
    # nobody here has run them against the sandbox. They are the documented
    # v3 shapes and they are SETTINGS so a wrong one is an env change rather
    # than a release. Do not promote any of them to a constant until a real
    # sandbox call has returned something other than 404.
    #
    # The trap this repo already fell into once is worth restating: the old
    # ABHA call used `/v3/hip/token/on-generate`, which is a callback the
    # gateway invokes ON a HIP, not an endpoint a HIP posts TO. The two
    # directions are easy to confuse in ABDM's documentation, so each path
    # below records which way it points.
    # ------------------------------------------------------------------

    #: HIP -> gateway. Link care contexts we already hold to an ABHA address.
    abdm_path_hip_link_add_contexts: str = "/api/hiecm/v3/link/carecontext"
    #: HIP -> gateway. Answer a discovery request the gateway sent us.
    abdm_path_hip_on_discover: str = "/api/hiecm/v3/hip/patient/care-context/on-discover"
    #: HIP -> gateway. Answer a link-init request.
    abdm_path_hip_on_link_init: str = "/api/hiecm/v3/link/on-init"
    #: HIP -> gateway. Answer a link-confirm request.
    abdm_path_hip_on_link_confirm: str = "/api/hiecm/v3/link/on-confirm"
    #: HIP -> gateway. Acknowledge a consent notification.
    abdm_path_hip_on_consent_notify: str = "/api/hiecm/v3/consent/hip/on-notify"
    #: HIP -> gateway. Acknowledge a health-information request.
    abdm_path_hip_on_hi_request: str = "/api/hiecm/v3/health-information/hip/on-request"
    #: HIP -> gateway. Report the outcome of a data push.
    abdm_path_hip_hi_notify: str = "/api/hiecm/v3/health-information/notify"

    #: HIU -> gateway. Ask the consent manager for a new consent.
    abdm_path_hiu_consent_request_init: str = "/api/hiecm/v3/consent-requests/init"
    #: HIU -> gateway. Fetch a granted consent artefact by id.
    abdm_path_hiu_consent_fetch: str = "/api/hiecm/v3/consents/fetch"
    #: HIU -> gateway. Ask for the data a consent artefact permits.
    abdm_path_hiu_hi_request: str = "/api/hiecm/v3/health-information/hiu/request"

    #: Shared secret the gateway is expected to present on inbound callbacks.
    #:
    #: None means callbacks are REFUSED, not accepted. See
    #: integrations/abdm/callback_auth.py — an unauthenticated inbound endpoint
    #: that writes consent artefacts and patient data is the single most
    #: dangerous thing in an HIP/HIU integration, and "we could not verify it
    #: yet, so we let it through" is how it gets shipped.
    abdm_callback_shared_secret: str | None = None

    #: Our own base URL, given to the gateway so HIPs know where to push data.
    #: Placeholder means HIU data-transfer requests are refused rather than
    #: sent with an address nobody can reach.
    abdm_hiu_callback_base_url: str = "change-me"
    
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
