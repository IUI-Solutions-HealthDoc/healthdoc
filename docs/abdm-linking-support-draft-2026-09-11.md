# NHA sandbox linking investigation — draft, not submitted

Use the registered sandbox support account. This draft contains no participant
ABHA, demographics, tokens, secrets or clinical payloads. Do not attach raw
callback bodies, `.env`, browser storage, or unredacted screenshots.

## Suggested ticket

**Subject:** HIP linking rejection and missing fresh v3 token callback — HealthDoc sandbox

We are testing one participant-approved, explicitly synthetic WellnessRecord.
We have not completed its link and have not sent clinical data or an HIU
consent request. Please help trace the following sequence on 11 September 2026.

- Bridge/client ID: `SBXID_053401`
- HIP: `SBXID_053401_HIP`; HIU: `SBXID_053401_HIU`
- Registered callback base: `https://abdm.healthdoc.world`
- Generate-token REQUEST-ID: `294710a4-7011-5add-8b78-a003c58dba3d`
- Link-carecontext REQUEST-ID: `a27f2e55-78b3-511f-b80b-de1a6491a19e`
- Outbound link endpoint: `POST /api/hiecm/hip/v3/link/carecontext`

### Observed sequence (UTC)

1. At 02:20:37 our first token callback returned HTTP 400. We found and fixed
   our receiver's requirement for `X-CM-ID`, which is not listed on this
   callback in M2 v2.8 §4.3.2. The precise missing header on that original live
   delivery was not logged, so we cannot prove it retrospectively.
2. One controlled recovery reused the original generate-token REQUEST-ID.
   At approximately 02:38:23 the callback succeeded with HTTP 202 and the link
   token was stored encrypted. Two total generate-token job attempts occurred.
3. Between approximately 02:39 and 02:42 we attempted the same link request:
   first a gateway 4xx rejection other than 401/403, then a session endpoint
   HTTP 500, then an authentication failure. Our previous worker retained only
   the error class for the first/last failures, not their full status/code.
   We have corrected that diagnostic limitation without logging payloads.
4. No successful `/api/v3/link/on_carecontext` acknowledgement was observed.
   Our conservative local token-use window expired at 02:43:23; we cleared
   the credential and marked this operation expired. We did not extend it or
   generate another token.
5. After restoring the local origin/tunnel, at approximately 07:27 UTC,
   session authentication and `GET /api/hiecm/gateway/v3/bridge-services`
   returned 200. Both IDs above are active with their expected HIP/HIU types.
   The callback URL was reachable again after 07:29 UTC.
6. With the **same configured secret**, a fresh participant-approved operation
   dispatched at **12:40:42 UTC**, token REQUEST-ID
   `d613360a-99e5-5fc4-873c-b804d01dba8a`. The call returned without a client
   error and its one-attempt job completed; our diagnostic did not retain the
   exact success HTTP status. At **12 September 04:04:06 UTC**, no token callback, token or
   context-link job exists for this operation. Our nginx logs show public
   probes reaching the backend but no corresponding NHA token delivery.
   Session/bridge-services still return 200 and the registered `bridge.url`
   matches the callback base above. This makes three recorded token-generation
   job attempts on 11 September, including the original recovery; no fourth
   was sent. These counters are job attempts, not a proven HTTP request count.
7. Further read-only service-specific lookups returned 200, both services
   remain active, and no service-specific URL override was returned. We have
   corrected the client to reject redirects and unexpected success statuses
   rather than mark them done. This does not establish what status the old
   request received. No clinical transfer or HIU consent request has been sent.
8. On 12 September the owner signed in to the Sandbox portal. The account is
   approved and lists M1/M2/M3 in its requested scope. The inspected account,
   exit and integrator dashboards provide no request-level callback trace.
   The local request was still pending without a token at 04:19:20 UTC. We
   have not submitted exit declarations or changed the bridge configuration.

### Please confirm

1. What exact status and ABDM error code did the link-carecontext REQUEST-ID
   receive? Was the refusal payload validation, token validation, API
   subscription/service permission, or another cause?
2. Does this bridge/HIP have permission for the v3 HIP linking endpoint,
   independently of session acquisition and bridge-services access?
3. For this endpoint, are `hiType: WellnessRecord`, canonical document
   references containing `/`, and a clearly labelled synthetic display
   supported? Our supplied Postman collection uses title-case HI types while
   some M2 v2.8 examples show uppercase. We have not changed casing by guess.
4. Is reusing the original REQUEST-ID the supported recovery when the outbound
   request succeeded but our callback receiver rejected delivery? What retry
   interval/limit should we follow without exhausting token generation limits?
5. Please trace the fresh token REQUEST-ID above: was it accepted for processing,
   rate-limited, or was callback delivery attempted? Please provide the delivery
   time, destination, response status and safe error code. Confirm when another
   attempt is safe; we will not repeatedly regenerate tokens.

We will keep any subsequent run to the same approved document and obtain
separate participant PHR consent before clinical transfer.

## Internal prerequisites for the next controlled run

- The owner explicitly requested continuing with the same secret, and it was
  used unchanged for this investigation. Earlier accidental diagnostic exposure
  still warrants a separate owner-controlled rotation; do not include either
  secret in this ticket or make an unproven bad-secret diagnosis.
- Preserve the expired operation and all existing request IDs; do not reset
  its counters or resurrect its cleared token.
- Resolve the rejection from the above evidence, then plan one fresh attempt
  with safe status/code logging and a stable callback origin. Do not run the
  general queue consumer or repeatedly request linking tokens.
- Local participant consent expired at 23:59 IST on 11 September. Obtain a
  new explicit local access decision before accessing the record. M3 also
  needs a genuine or NHA-approved clinician requester identifier configured
  in the user's profile and the participant's separate PHR approval.
- Header routing checks do not authenticate callback origin. Complete the
  documented gateway Authorization/edge-control review before production.
