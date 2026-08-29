import { api } from "@/lib/api";

import type {
  Patient,
  PatientCreate,
  PatientSearchRequest,
  PatientSearchResponse,
  QueueSummary,
  QueueCreate,
  QueueCreated,
  QueueOpeningOptions,
  QueueToken,
  QueueTokenCreate,
  QueueTokenList,
  Visit,
  VisitCreate,
} from "./types";

/**
 * Register a patient.
 *
 * `idempotencyKey` is generated once when the form opens, not per submit, and
 * that is the whole point: a receptionist who double-clicks, or whose network
 * drops after the server committed, must not create a second chart for the same
 * person. The server reserves the key before doing any work and replays the
 * stored response, so a retry returns the original patient with the original
 * UHID rather than allocating a new one.
 */
export function registerPatient(
  payload: PatientCreate,
  idempotencyKey: string,
): Promise<Patient> {
  return api<Patient>("/patients", {
    method: "POST",
    body: JSON.stringify(payload),
    idempotencyKey,
  });
}

/**
 * Normalise a criterion before it is matched.
 *
 * From PR #412 (Kunal). A receptionist reading a UHID off a card types it as
 * printed — "in-rj-jpr001 2026 000041 3" — and an exact-match column never
 * sees it. Mobile and ABHA are the same: spaces, +91 and hyphens are how people
 * write numbers, not how they are stored.
 *
 * full_name is deliberately NOT normalised beyond trimming: it is matched
 * fuzzily server-side, and stripping punctuation would damage names that
 * legitimately contain it.
 */
function normaliseCriteria(criteria: PatientSearchRequest): PatientSearchRequest {
  const digitsOnly = (v: string) => v.replace(/\D/g, "");
  const out: PatientSearchRequest = { ...criteria };

  if (out.uhid) out.uhid = out.uhid.trim().toUpperCase().replace(/[\s\-_/]/g, "");
  if (out.mobile) out.mobile = digitsOnly(out.mobile);
  if (out.abha_number) out.abha_number = digitsOnly(out.abha_number);
  if (out.full_name) out.full_name = out.full_name.trim();

  return out;
}

/** At least one criterion is required — the server rejects an empty search. */
export function searchPatients(
  criteria: PatientSearchRequest,
  page = 1,
  pageSize = 20,
): Promise<PatientSearchResponse> {
  return api<PatientSearchResponse>("/patients/search", {
    method: "POST",
    // A search is a POST because the criteria include Aadhaar and ABHA numbers,
    // which must not end up in a query string, a browser history entry or an
    // access log.
    //
    // Aadhaar is never sent FROM this UI at all — PatientSearchRequest carries
    // the field because the endpoint accepts it, but the receptionist screen
    // offers no input for it. Also PR #412's call.
    body: JSON.stringify({
      page,
      page_size: pageSize,
      ...normaliseCriteria(criteria),
    }),
    idempotencyKey: null, // creates nothing
  });
}

/**
 * Open a visit.
 *
 * The registration invoice is raised inside the same server transaction (#389),
 * so this one call is what puts the patient into the billing chain. A retry
 * replays rather than opening a second visit — which would mean a second
 * registration fee.
 */
export function createVisit(
  payload: VisitCreate,
  idempotencyKey: string,
): Promise<Visit> {
  return api<Visit>("/visits", {
    method: "POST",
    body: JSON.stringify(payload),
    idempotencyKey,
  });
}

/** Today's queues at the caller's facility, shortest first. */
export function listQueues(): Promise<QueueSummary[]> {
  return api<QueueSummary[]>("/queue/queues");
}

/** Available named roster rows reception can use to open today's queue. */
export function listQueueOpeningOptions(): Promise<QueueOpeningOptions> {
  return api<QueueOpeningOptions>("/queue/opening-options");
}

/** Open one clinic queue from a roster option. */
export function createQueue(payload: QueueCreate): Promise<QueueCreated> {
  return api<QueueCreated>("/queue/queues", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** Tokens for one queue, with the current now_serving. */
export function listQueueTokens(queueId: string): Promise<QueueTokenList> {
  return api<QueueTokenList>(`/queue/queues/${queueId}/tokens`);
}

/** Issue a token against a visit. Retry-safe for the same reason as the visit. */
export function issueToken(
  payload: QueueTokenCreate,
  idempotencyKey: string,
): Promise<QueueToken> {
  return api<QueueToken>("/queue/tokens", {
    method: "POST",
    body: JSON.stringify({ priority: "normal", ...payload }),
    idempotencyKey,
  });
}
