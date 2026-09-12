# ABDM callback header contract — 11 September 2026

## Confirmed implementation defect and correction

HealthDoc inferred `X-CM-ID` requirements for inbound callbacks from outbound
API requests. The supplied **M2 and M3 v2.8** documents use different header
sets. Ten additional callback paths now accept an absent CM header. A supplied
CM header must still match; recipient ID, request UUID, timestamp freshness,
replay checks and business-level patient/facility/correlation checks remain.

This does **not** authenticate gateway origin. Gateway Authorization validation
and a verified edge-origin policy remain a separate security acceptance item.
Do not deploy a public production callback receiver based only on routing
headers. Do not introduce a private shared-secret requirement NHA cannot send.

Sources are the user-supplied files under `ABDM DOCS/`:

- `M2_Document_16_02_2026_11822aedc7.docx`
- `M3_Dcoument_16_02_2026_2319bac7bf.docx`

Paragraph locations below count all `w:p` nodes in `word/document.xml`, including
table cells, starting at one. They locate the header table's endpoint paragraph,
not a Word page number.

| Callback path | Recipient checked | CM header | Source paragraph |
|---|---|---|---|
| `/api/v3/hip/token/on-generate-token` | X-HIP-ID | Optional; fixed earlier | M2 1099 |
| `/api/v3/link/on_carecontext` | X-HIP-ID | Optional; fixed earlier | M2 1973 |
| `/api/v3/links/context/on-notify` | X-HIP-ID | Optional | M2 2457 |
| `/api/v3/hip/patient/care-context/discover` | X-HIP-ID | Optional | M2 3091 |
| `/api/v3/hip/link/care-context/init` | X-HIP-ID | Optional | M2 3799 |
| `/api/v3/hip/link/care-context/confirm` | X-HIP-ID, unchanged; see discrepancy | Optional | M2 4476 |
| `/api/v3/consent/request/hip/notify` | X-HIP-ID | Optional | M2 4813 |
| `/api/v3/hip/health-information/request` | X-HIP-ID | Optional | M2 5085 |
| `/api/v3/hiu/consent/request/on-init` | X-HIU-ID | **Required, unchanged** | M3 1562 |
| `/api/v3/hiu/consent/request/notify` | X-HIU-ID | Optional | M3 1629 |
| `/api/v3/hiu/consent/request/on-status` | X-HIU-ID | Optional | M3 2024 |
| `/api/v3/hiu/consent/on-fetch` | X-HIU-ID | Optional | M3 2235 |
| `/api/v3/hiu/health-information/on-request` | X-HIU-ID | Optional | M3 2917 |

Unknown paths remain CM-required. Direct HIP-to-HIU data push continues using
its separate transaction-scoped capability and encryption checks; it does not
inherit gateway header requirements.

### Document discrepancy kept explicit

The M2 link-confirm table says `X-HIU-ID` even though the callback addresses a
HIP. This change does **not** relax or substitute the existing HIP recipient
check. Resolve that discrepancy against an authenticated NHA delivery or explicit
support clarification before altering recipient attribution.

## Regression evidence

Before the correction, the new endpoint-specific test failed with HTTP 400
`missing_abdm_headers` on `/api/v3/links/context/on-notify`. After the correction,
all **125 callback-auth/client tests** passed. The suite independently lists
the ten paths, checks their actual route dependencies, rejects wrong/empty CM
values when present, rejects missing/wrong recipients and stale timestamps,
and keeps HIU on-init plus unknown routes strict.

## Linking diagnostics

The [NHA reference header builder](https://github.com/NHA-ABDM/ABDM-wrapper/blob/master/src/main/java/in/nha/abdm/wrapper/v1/common/Utils.java)
sends the link token raw in `X-LINK-TOKEN`, matching HealthDoc. Do not prefix it
with `Bearer`; the gateway session token uses Authorization separately.

Safe error summaries now preserve stage (`session` or `request`), HTTP status,
ABDM error codes and the bounded WSO2 authentication-code range 900900–900910.
They retain no arbitrary messages or raw auth-error bodies. This avoids calling
every operation-level 401 a bad client secret. WSO2 distinguishes token,
subscription and scope failures in its [official error reference](https://apim.docs.wso2.com/en/4.6.0/reference/troubleshooting/error-handling/).
An observed code must still be interpreted for the actual endpoint; it is not
proof that NHA has disabled the integration.
