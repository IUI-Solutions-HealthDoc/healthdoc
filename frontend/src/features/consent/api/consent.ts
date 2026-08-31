/**
 * Consent records. Retired from fixtures (P1.1).
 *
 * PER-PATIENT, NOT FACILITY-WIDE.
 *
 * The fixture listed every consent in the facility when given no patient_id —
 * "facility console convenience until patient picker exists". No endpoint does
 * that, and building one is not trivial: `consent_records` has no facility_id,
 * so a facility-wide list needs a deliberate join through `patients`. It is
 * also a DPO-console question rather than a clinical one — deferred as a
 * product decision rather than invented here.
 *
 * So every read below takes a patient. The screen asks who first.
 */
import { api } from "@/lib/api";
import type {
  ConsentListFilters,
  ConsentPurpose,
  ConsentRecord,
  ConsentRecordCreate,
  ConsentStatusTransitionIn,
  ConsentWithdrawalCreate,
  DataAccessFilters,
  DataAccessLog,
} from "../types";

/** GET /consent/purposes — the catalogue. Facility-independent. */
export async function listConsentPurposes(): Promise<ConsentPurpose[]> {
  const response = await api<{ items: ConsentPurpose[] } | ConsentPurpose[]>(
    "/consent/purposes",
  );
  return Array.isArray(response) ? response : response.items;
}

/**
 * GET /consent/patients/{patient_id}/records.
 *
 * `patient_id` is required. Without one there is nothing to ask for — see the
 * module note. Returns [] rather than throwing so the screen can render its
 * "choose a patient" state without treating it as an error.
 *
 * `status` and `query` narrow the returned set client-side. Safe here in a way
 * it is not elsewhere: this is one patient's consents, not a paginated list, so
 * filtering sees every row rather than one page of them.
 */
export async function listConsentRecords(
  filters: ConsentListFilters = {},
): Promise<ConsentRecord[]> {
  if (!filters.patient_id) return [];

  const rows = await api<ConsentRecord[]>(
    `/consent/patients/${filters.patient_id}/records`,
  );

  const status = filters.status ?? "all";
  const q = filters.query?.trim().toLowerCase() ?? "";
  return rows.filter((row) => {
    if (status !== "all" && row.status !== status) return false;
    if (!q) return true;
    return [row.id, row.purpose_code, row.guardian_name, row.channel]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(q);
  });
}

/** GET /consent/patients/{patient_id}/records/{consent_id}. */
export async function getConsent(
  patientId: string,
  consentId: string,
): Promise<ConsentRecord> {
  return api<ConsentRecord>(`/consent/patients/${patientId}/records/${consentId}`);
}

/** POST /consent/patients/{patient_id}/records. */
export function createConsentRecord(
  patientId: string,
  body: ConsentRecordCreate,
  idempotencyKey: string,
): Promise<ConsentRecord> {
  return api<ConsentRecord>(`/consent/patients/${patientId}/records`, {
    method: "POST",
    idempotencyKey,
    body: JSON.stringify(body),
  });
}

/**
 * PATCH /consent/records/{consent_id}/status — requested -> granted|denied.
 *
 * Only from `requested`, and only to those two. That transition exists for the
 * ABDM consent-manager flow, where a request is raised and answered
 * asynchronously; every other channel grants immediately at creation. The
 * server enforces it — not duplicated here.
 */
export function transitionConsentStatus(
  consentId: string,
  body: ConsentStatusTransitionIn,
): Promise<ConsentRecord> {
  return api<ConsentRecord>(`/consent/records/${consentId}/status`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

/**
 * POST /consent/records/{consent_id}/withdraw — granted -> revoked.
 *
 * A withdrawal is recorded, not applied by deleting the consent: the record of
 * having consented, and then having withdrawn, is the DPDP artefact. Erasing
 * the original would destroy the evidence that processing was lawful while it
 * lasted.
 */
export function withdrawConsent(
  consentId: string,
  body: ConsentWithdrawalCreate,
): Promise<ConsentRecord> {
  return api<ConsentRecord>(`/consent/records/${consentId}/withdraw`, {
    method: "POST",
    idempotencyKey: null,
    body: JSON.stringify(body),
  });
}

/**
 * GET /audit/data-access — who read this patient's data, under what purpose.
 *
 * Lives on the audit router rather than consent, because it is the same ledger
 * the compliance console reads. Auditor/admin gated.
 */
export async function listDataAccessLogs(
  filters: DataAccessFilters = {},
): Promise<DataAccessLog[]> {
  const params = new URLSearchParams({ page: "1", page_size: "100" });
  if (filters.consent_id) params.set("consent_id", filters.consent_id);
  if (filters.patient_id) params.set("patient_id", filters.patient_id);

  const response = await api<{ items: DataAccessLog[] }>(
    `/audit/data-access?${params.toString()}`,
  );
  return response.items;
}

/**
 * data_access_log is append-only.
 *
 * The fixture simulated a rejected mutation to demonstrate it. There is nothing
 * to call — no update or delete endpoint exists, and a database trigger blocks
 * the write regardless. The absence IS the property.
 */
export async function attemptMutateDataAccessLog(): Promise<never> {
  throw new Error(
    "data_access_log is append-only — no update or delete endpoint exists, and " +
      "a database trigger rejects the write. It is the record of who looked at " +
      "what; an editable one would be worthless.",
  );
}
