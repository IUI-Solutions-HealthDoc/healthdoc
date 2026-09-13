# Copy-ready NHA sandbox support ticket

Status: prepared, **not submitted**. Copy only the subject and body below.

## Subject

M2 generate-token returns 202 without callback; M3 test requester clarification — SBXID_053401

## Body

Hello ABDM Integration Support,

We are testing HealthDoc's M2 HIP and M3 HIU integration in the sandbox. Please
help trace a missing token callback and clarify the permitted M3 test requester.

### Environment

- Bridge/client ID: `SBXID_053401`
- HIP service: `SBXID_053401_HIP`
- HIU service: `SBXID_053401_HIU`
- Registered callback base: `https://abdm.healthdoc.world`
- Expected token callback: `https://abdm.healthdoc.world/api/v3/hip/token/on-generate-token`
- Outbound endpoint: `POST https://dev.abdm.gov.in/api/hiecm/v3/token/generate-token`
- Token-generation REQUEST-ID: `d613360a-99e5-5fc4-873c-b804d01dba8a`

### M2: observed behavior

The original request was dispatched on **11 September 2026 at approximately
12:40:42 UTC**; its exact HTTP success status was not retained. After inspecting
our receiver and obtaining participant permission, we performed **one controlled
retry using the same REQUEST-ID** on **12 September at approximately 18:25:41
UTC (23:55:41 IST)**. This retry explicitly returned **HTTP 202**.

At our last check, **12 September 23:31:44 UTC / 13 September 05:01:44 IST**,
the operation remained pending with no stored HIP link token or confirmation.
We have not sent another token-generation request.

Verified checks:

- Gateway session access works with the existing credentials.
- `GET /api/hiecm/gateway/v3/bridge-services` returns 200; the callback URL
  matches, and both HIP and HIU services are active.
- All 16 configured public callback routes are reachable over HTTPS and
  reject empty unauthenticated probes. This does **not** prove connectivity
  from NHA's infrastructure or acceptance of a genuine callback.
- Fresh M1 existing-ABHA OTP verification completed, and the verified identity
  matches the pending HIP operation.
- No clinical bundle has been transferred. The selected document is an
  explicitly synthetic, participant-approved WellnessRecord.

Please confirm:

1. What happened to the original request and its retry? Was callback delivery
   attempted? Please provide the destination URL, delivery timestamps, HTTP
   statuses and safe error codes.
2. Does reusing this REQUEST-ID cause deduplication without callback redelivery?
   What is the supported recovery procedure, retry interval and token-generation
   limit? Can the existing callback be redelivered without generating a new token?
3. Are any service permissions, subscriptions, source-network restrictions or
   callback-header requirements missing for this bridge/HIP? Please identify
   the specific failed check rather than requesting repeated token generation.

### M3: approved sandbox requester

We do not currently have an authorized clinician's registration configured.
The supplied M3 v2.8 document requires `requester.name` and
`requester.identifier.{type,value,system}`, but examples differ between
`REGN01`, `REGNO1` and `REGNO`.

Please provide an approved sandbox test requester or confirm the policy for
explicitly synthetic requester values, including the accepted identifier type,
value and issuer URI. Is an HPR-registered professional mandatory for these
sandbox cases, or is an approved test identity sufficient?

We will not use an unrelated clinician's registration or represent documentation
examples as verified professional identities. Patient PHR consent will be
obtained separately before any clinical transfer.

### Related earlier linking failure, if useful for tracing

On **11 September, approximately 02:39–02:42 UTC**, an earlier operation failed
at `POST /api/hiecm/hip/v3/link/carecontext`, REQUEST-ID
`a27f2e55-78b3-511f-b80b-de1a6491a19e`. Its token-generation REQUEST-ID was
`294710a4-7011-5add-8b78-a003c58dba3d`. Our older diagnostics did not retain the
precise gateway rejection code. Please provide that code if available. This
operation has expired; we have not revived it or reused its cleared credential.

Thank you,
HealthDoc Integration Team

---

Do not attach `.env`, client secrets, access/link tokens, OTPs, participant
ABHA/Aadhaar identifiers, raw callback bodies or unredacted screenshots. This
ticket can be submitted without any of those values; REQUEST-IDs identify the
requests for NHA's investigation.
