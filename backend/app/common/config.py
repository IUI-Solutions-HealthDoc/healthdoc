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
    #: Additional issuers to accept, comma-separated. Empty by default.
    #:
    #: Keycloak derives `iss` from the Host header it was reached on, so the
    #: SAME realm mints `https://localhost/...` for a developer and
    #: `https://192.168.7.106/...` for a ward PC on the LAN. One pinned issuer
    #: means whichever address is not pinned gets 401 on every call after a
    #: successful login — the confusing failure this exists to prevent.
    #:
    #: This is not a weakening of token verification. Signatures are checked
    #: against JWKS fetched from `jwt_jwks_url`, a fixed internal endpoint that
    #: does not depend on the token, so an attacker cannot introduce an issuer
    #: here by controlling a Host header. Entries must be listed explicitly;
    #: there is no wildcard, and the empty default keeps single-host
    #: deployments strict.
    jwt_additional_issuers: str = ""
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
    #: Our identities ON the gateway, registered with
    #: PUT /api/hiecm/gateway/v3/bridge-service. These are NOT the client id:
    #: one bridge carries many services, and every M2/M3 call has to say which
    #: one is speaking (X-HIP-ID / X-HIU-ID). They also have to match
    #: facilities.hfr_facility_id, or an inbound callback resolves to no
    #: facility and 404s.
    abdm_hip_id: str = "change-me"
    abdm_hiu_id: str = "change-me"
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
    #: VERIFIED against the sandbox on 2026-08-31 with a real session token.
    #: All four returned HTTP 400 naming the fields they wanted — otpSystem,
    #: scope, authData, consent — which is what a correct path looks like when
    #: you post an empty body to it: the endpoint exists and the auth was
    #: accepted. A wrong path returns 404, as the M2/M3 block below did.
    #:
    #: The original note is kept because it is still the right instinct. They are
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
    # CONFIRMED 2026-09-01 against the sandbox with a real session token, using
    # the official ABDM v3 Postman collection as the source.
    #
    # The probe was an EXISTENCE check, not a method check: GET each path and
    # treat 404 as "no such route" and anything else as "route exists". It is
    # deliberately non-destructive — none of these paths were actually invoked.
    # What came back:
    #
    #   405  the POST-only paths (most of them) — route exists, wrong method
    #   400  /consent/v3/request/init — routed, then rejected the empty request
    #   200  the bridge and certs routes below, where GET IS the real method
    #
    # The ten paths this file carried before all answered 404. A non-404 says a
    # route is there; it does NOT prove the request shape is right, and none of
    # these has yet completed a real exchange with the gateway.
    #
    # The mistake they encoded is worth keeping: we assumed ONE base,
    # /api/hiecm/v3/..., because the session endpoint lives under
    # /api/hiecm/gateway/v3/. ABDM does not work that way — it segments by
    # capability, and the segment is part of the contract:
    #
    #   /api/hiecm/gateway/v3/...                 sessions, bridge, certs
    #   /api/hiecm/hip/v3/...                     HIP-initiated linking
    #   /api/hiecm/user-initiated-linking/v3/...  patient-initiated discovery
    #   /api/hiecm/consent/v3/...                 consent requests and artefacts
    #   /api/hiecm/data-flow/v3/...               health-information transfer
    #   /api/hiecm/patient-share/v3/...           scan-and-share
    #
    # No amount of care on a single prefix would have found this, which is why
    # two guesses were spent before the collection arrived. Do not extend this
    # list by pattern-matching a sibling; check the collection.
    #
    # The trap this repo already fell into once still applies: the old ABHA call
    # used `/v3/hip/token/on-generate`, a callback the gateway invokes ON a HIP,
    # not an endpoint a HIP posts TO. Each path below records its direction.
    # ------------------------------------------------------------------

    #: HIP -> gateway. Link care contexts we already hold to an ABHA address.
    abdm_path_hip_link_add_contexts: str = "/api/hiecm/hip/v3/link/carecontext"
    #: HIP -> gateway. Notify the CM that a care context was added.
    abdm_path_hip_context_notify: str = "/api/hiecm/hip/v3/link/context/notify"
    #: HIP -> gateway. Answer a discovery request the gateway sent us.
    abdm_path_hip_on_discover: str = (
        "/api/hiecm/user-initiated-linking/v3/patient/care-context/on-discover"
    )
    #: HIP -> gateway. Answer a link-init request.
    abdm_path_hip_on_link_init: str = (
        "/api/hiecm/user-initiated-linking/v3/link/care-context/on-init"
    )
    #: HIP -> gateway. Answer a link-confirm request.
    abdm_path_hip_on_link_confirm: str = (
        "/api/hiecm/user-initiated-linking/v3/link/care-context/on-confirm"
    )
    #: HIP -> gateway. Acknowledge a consent notification.
    abdm_path_hip_on_consent_notify: str = "/api/hiecm/consent/v3/request/hip/on-notify"
    #: HIP -> gateway. Acknowledge a health-information request.
    abdm_path_hip_on_hi_request: str = "/api/hiecm/data-flow/v3/health-information/hip/on-request"
    #: HIP -> gateway. Report the outcome of a data push.
    abdm_path_hip_hi_notify: str = "/api/hiecm/data-flow/v3/health-information/notify"
    #: HIP -> gateway. Exchange patient demographics for a link token.
    abdm_path_hip_token_generate: str = "/api/hiecm/v3/token/generate-token"
    #: HIP -> gateway. Acknowledge a scan-and-share patient profile.
    abdm_path_hip_profile_on_share: str = "/api/hiecm/patient-share/v3/on-share"

    #: HIU -> gateway. Ask the consent manager for a new consent.
    abdm_path_hiu_consent_request_init: str = "/api/hiecm/consent/v3/request/init"
    #: HIU -> gateway. Fetch a granted consent artefact by id.
    abdm_path_hiu_consent_fetch: str = "/api/hiecm/consent/v3/fetch"
    #: HIU -> gateway. Ask for the data a consent artefact permits.
    abdm_path_hiu_hi_request: str = "/api/hiecm/data-flow/v3/health-information/request"
    #: HIU -> gateway. Poll a consent request. A backstop for a callback that
    #: never lands, which is otherwise indistinguishable from a patient who has
    #: simply not answered yet.
    abdm_path_hiu_consent_request_status: str = "/api/hiecm/consent/v3/request/status"
    #: HIU -> gateway. Acknowledge a consent notification. Note this is the HIU
    #: sibling of abdm_path_hip_on_consent_notify and takes a LIST where the HIP
    #: one takes an object — ABDM's asymmetry, not ours.
    abdm_path_hiu_on_consent_notify: str = "/api/hiecm/consent/v3/request/hiu/on-notify"

    #: Bridge management. NOT /gateway/v1/bridges — that path answers 403
    #: "900908 API Subscription validation failed" for a sandbox client, which
    #: reads as a missing entitlement and is really a retired API version. The
    #: v3 equivalents below answer 200 with the same credentials and headers.
    #:
    #: Reserved by design: these three (and abdm_path_gateway_certs below) have
    #: NO caller in app/. Bridge provisioning is a one-time operations task run
    #: through scripts/abdm_sandbox.sh, not the running app — so unlike the
    #: abdm_path_hip_*/hiu_* settings, a zero-caller here is expected, not the
    #: dead-limb bug the wiring audit hunts for.
    abdm_path_bridge_services: str = "/api/hiecm/gateway/v3/bridge-services"
    abdm_path_bridge_service: str = "/api/hiecm/gateway/v3/bridge-service"
    abdm_path_bridge_url: str = "/api/hiecm/gateway/v3/bridge/url"
    #: Gateway JWKS discovery endpoint. Reserved, no in-app caller yet: the
    #: published v3 callback contract defines no signature header or canonical
    #: input to verify with these keys, so callback_auth.py cannot use them. This
    #: is the home a callback-signature verifier grows into once NHA publishes a
    #: scheme — the compensating control for the forgeable v3 callback surface
    #: (see docs/ABDM_BREAKING_POINTS_AND_FIX_PLAN.md, F1).
    abdm_path_gateway_certs: str = "/api/hiecm/gateway/v3/certs"

    #: NOTE (2026-08-31): bridge management — PATCH /gateway/v1/bridges and
    #: /bridges/addUpdateServices, the steps in NHA's onboarding email — returns
    #: 403 "900908 API Subscription validation failed" for this client id, with
    #: tokens from BOTH /gateway/v0.5/sessions and /api/hiecm/gateway/v3/sessions
    #: and with the full REQUEST-ID / TIMESTAMP / X-CM-ID header set. That is an
    #: entitlement on the ABDM account, not something configuration can fix:
    #: either register the bridge URL through the sandbox portal, or ask NHA to
    #: add the subscription.
    #:
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
    #: HTTPS relay owned by the deployment for delivering the HIP's mediated
    #: user-linking OTP. It receives the documented JSON contract from
    #: integrations/abdm/hip/link_otp.py. Unset means the linking callback
    #: fails closed; accepting an unverified confirmation is never a fallback.
    abdm_link_otp_delivery_url: str | None = None
    abdm_link_otp_delivery_token: str | None = None

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


def allowed_jwt_issuers(settings: "Settings") -> tuple[str, ...]:
    """Every issuer string a token may legitimately carry.

    Returns a tuple rather than a set because PyJWT accepts any Container[str]
    and a tuple keeps the primary issuer first when this is logged.
    """
    extra = [i.strip() for i in settings.jwt_additional_issuers.split(",") if i.strip()]
    return (settings.jwt_issuer, *[i for i in extra if i != settings.jwt_issuer])


@lru_cache
def get_settings() -> Settings:
    return Settings()
