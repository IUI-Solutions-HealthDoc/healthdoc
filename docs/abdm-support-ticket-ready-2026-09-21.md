# Copy-ready NHA sandbox support ticket (21 September 2026)

Status: **owner reports a new ticket submitted**; ticket number, exact submitted
text and response have not been independently verified. This file preserves
the prepared draft, not a submission receipt. Obtain the existing confirmation
and update this status; do not submit another duplicate ticket automatically.
If comparing against the submitted ticket, use the subject and body below.
Do not attach `.env`, client secrets, access/link tokens, OTPs, participant
ABHA/Aadhaar identifiers, raw callback bodies or unredacted screenshots.

The 11–13 September ticket used the same REQUEST-IDs. Those attempts are now
about eight days old. This text restates them with **fresh receiver evidence**
from 21 September after the origin was restored. We have **not** generated a
new token and have **not** started the outbound worker.

## Subject

M2 token callback still missing for REQUEST-ID d613360a (8 days); M3 sandbox requester policy — SBXID_053401

## Body

Hello ABDM Integration Support,

We are testing HealthDoc's M2 HIP and M3 HIU integration in the sandbox
(bridge/client `SBXID_053401`, HIP `SBXID_053401_HIP`, HIU `SBXID_053401_HIU`).
Registered callback base: `https://abdm.healthdoc.world`.
Expected token callback: `https://abdm.healthdoc.world/api/v3/hip/token/on-generate-token`.

We previously raised this for generate-token REQUEST-ID
`d613360a-99e5-5fc4-873c-b804d01dba8a` (original dispatch **11 September 2026
~12:40 UTC**; one same-ID retry **12 September 2026 ~18:25 UTC** returned
HTTP 202). There has been no support reply. The operation is still pending
locally with **no stored link token**. We have not sent another
generate-token request.

An earlier expired operation (token REQUEST-ID
`294710a4-7011-5add-8b78-a003c58dba3d`, care-context REQUEST-ID
`a27f2e55-78b3-511f-b80b-de1a6491a19e`, ~11 September 02:39–02:42 UTC)
remains expired and has not been revived.

### Fresh receiver checks — 21 September 2026

Our public origin had been returning HTTP 502 on the token callback while
the local stack was down. Origin and tunnel were restored on **21 September
2026 at approximately 10:21 UTC (15:51 IST)**. Since then:

1. `GET https://abdm.healthdoc.world/api/v3/hip/token/on-generate-token`
   returns **405 Method Not Allowed** (POST-only route is mounted; not 502).
2. Synthetic unauthenticated POST without ABDM headers: **400**
   `missing_abdm_headers` (receipt `a6927cdf-8e1d-4f5a-acaf-3402e45d87bd`).
3. Synthetic POST with valid headers for an unknown operation: **404**
   `link_not_found` (receipt `a65f6057-12a0-47eb-9530-426220c558ad`,
   REQUEST-ID `de5f9c13-8bb7-4f78-b923-751dc9626e96`,
   ~21 September 10:31 UTC). These probes do not prove NHA-to-HIP delivery.
4. Read-only `GET /api/hiecm/gateway/v3/bridge-services` on **21 September
   ~10:50 UTC** returned **200** (our REQUEST-ID
   `2200abf2-d7dc-4292-ad70-6e77162f164f`). Callback URL is still
   `https://abdm.healthdoc.world`; HIP and HIU services are active.
5. Existing-ABHA mobile OTP (M1 verification, not linking) succeeded the
   same day: request-otp HTTP 200 at **10:46:19 UTC**, verify-otp HTTP 200
   at **10:47:40 UTC** (16:16–16:17 IST). The verified identity is the same
   participant as the pending HIP operation.

We have not provisioned a user-initiated (MEDIATE) OTP relay. We are asking
NHA to complete the application-initiated token-callback path for the
existing REQUEST-ID rather than requiring a new generation or a mediated
OTP channel.

Please confirm:

1. What happened to REQUEST-ID `d613360a-99e5-5fc4-873c-b804d01dba8a` and
   its 12 September same-ID retry? Was callback delivery attempted after
   21 September 10:21 UTC when the origin stopped returning 502? Please
   provide destination URL, delivery timestamps, HTTP statuses and safe
   error codes.
2. Does reusing this REQUEST-ID cause deduplication without callback
   redelivery? What is the supported recovery procedure? Can the existing
   callback be redelivered **without** generating a new token?
3. Are any service permissions, subscriptions, source-network restrictions
   or callback-header requirements missing for this bridge/HIP?

### M3: approved sandbox requester

We still do not have an authorized clinician's professional registration
configured, and we will not invent one. The M3 v2.8 document requires
`requester.name` and `requester.identifier.{type,value,system}`, but
examples differ between `REGN01`, `REGNO1` and `REGNO`.

Please provide an approved sandbox test requester, or confirm the policy
for explicitly synthetic requester values, including accepted identifier
type, value and issuer URI. Is an HPR-registered professional mandatory
for these sandbox cases, or is an approved test identity sufficient?

We will not use an unrelated clinician's registration. Patient PHR consent
for record sharing will be obtained separately after linkage is confirmed.
No clinical bundle has been transferred.

Thank you,
HealthDoc Integration Team
