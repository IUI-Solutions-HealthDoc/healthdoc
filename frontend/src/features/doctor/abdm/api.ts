import { api } from "@/lib/api";

export const HI_TYPES = ["OPConsultation", "Prescription", "DiagnosticReport", "DischargeSummary", "WellnessRecord"] as const;
export type HiType = (typeof HI_TYPES)[number];
export interface ExternalRecord {
  id: string; hi_type: string | null; source_hip_id: string | null;
  document_at: string | null; status: string; available: boolean;
}
export interface Artefact {
  id: string; status: string; hi_types: string[]; expires_at: string | null;
}
export interface ConsentRequest {
  id: string; status: string; delivery_status: string | null;
  hi_types: string[]; date_range_from: string; date_range_to: string; requested_expiry: string;
  artefacts: Artefact[];
  transfers: { id: string; status: string; delivery_status: string | null;
    received_pages: number; expected_pages: number | null; records: ExternalRecord[] }[];
}
export interface Workspace {
  patient_id: string; patient_name: string; abha_address: string | null;
  identity_verified: boolean; requests: ConsentRequest[]; next_offset: number | null;
}
export interface ConsentInput {
  patient_id: string; abha_address: string; purpose_code: "CAREMGT";
  hi_types: HiType[]; date_range_from: string; date_range_to: string; requested_expiry: string;
}
export const loadWorkspace = (id: string, offset = 0, signal?: AbortSignal) =>
  api<Workspace>(`/abdm/hiu/patients/${id}/workspace?offset=${offset}`, { signal, cache: "no-store" });
export const askConsent = (body: ConsentInput, key: string) =>
  api<{ id: string; status: string }>("/abdm/hiu/consent-requests", { method: "POST", body: JSON.stringify(body), idempotencyKey: key });
export const askRecords = (id: string, key: string) =>
  api<{ id: string; status: string }>(`/abdm/hiu/artefacts/${id}/health-information`, { method: "POST", idempotencyKey: key });
export const loadRecord = (id: string, signal?: AbortSignal) =>
  api<Record<string, unknown>>(`/abdm/hiu/records/${id}`, { signal, cache: "no-store" });
