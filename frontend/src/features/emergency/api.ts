import { api, newIdempotencyKey } from "@/lib/api";

export interface EmergencyPatientInput {
  full_name?: string;
  sex: "male" | "female" | "other" | "unknown";
  age_years: number;
  mobile?: string;
}

export interface EmergencyPatient {
  id: string;
  thid: string | null;
  uhid: string | null;
  full_name: string;
  sex: string;
  age_years: number | null;
  identity_path: string;
  identity_status: string;
  facility_id: string;
}

/** Mirrors backend PromotionOut / patient_merge_log for THID→UHID. */
export interface PromotionLog {
  id: string;
  source_type: string;
  source_patient_id: string;
  target_patient_id: string;
  requested_by: string;
  requested_at: string;
  approved_by: string | null;
  approved_at: string | null;
  status: string;
  reason: string | null;
  unmerge_reason: string | null;
}

export function registerEmergencyPatient(
  payload: EmergencyPatientInput,
): Promise<EmergencyPatient> {
  return api<EmergencyPatient>("/emergency/patients", {
    method: "POST",
    idempotencyKey: newIdempotencyKey(),
    body: JSON.stringify(payload),
  });
}

/** Supervisor A: open a pending THID→UHID promotion (maker). */
export function requestThidPromotion(
  patientId: string,
  reason?: string,
): Promise<PromotionLog> {
  return api<PromotionLog>(`/emergency/patients/${patientId}/promote`, {
    method: "POST",
    body: JSON.stringify({ reason: reason?.trim() || null }),
    idempotencyKey: newIdempotencyKey(),
  });
}

/** Supervisor B: approve — different person from requester (checker). */
export function approveThidPromotion(mergeLogId: string): Promise<PromotionLog> {
  return api<PromotionLog>(`/emergency/patients/promotions/${mergeLogId}/approve`, {
    method: "POST",
    body: JSON.stringify({}),
    idempotencyKey: newIdempotencyKey(),
  });
}

/** Supervisor C: reverse an approved promotion — different from approver. */
export function unmergeThidPromotion(
  mergeLogId: string,
  reason?: string,
): Promise<PromotionLog> {
  return api<PromotionLog>(`/emergency/patients/promotions/${mergeLogId}/unmerge`, {
    method: "POST",
    body: JSON.stringify({ reason: reason?.trim() || null }),
    idempotencyKey: newIdempotencyKey(),
  });
}

export interface EmergencyWorklistItem {
  visit_id: string;
  visit_number: string;
  patient_id: string;
  thid?: string | null;
  uhid?: string | null;
  full_name: string;
  age_years?: number | null;
  sex: string;
  arrival_time: string;
  status: string;
  visit_type: string;
}

export function listEmergencyWorklist(): Promise<EmergencyWorklistItem[]> {
  return api<EmergencyWorklistItem[]>("/emergency/worklist");
}

export interface EmergencyVisitResult {
  id: string;
  visit_number: string;
  patient_id: string;
  visit_type: string;
  status: string;
}

export function createEmergencyVisit(patientId: string): Promise<EmergencyVisitResult> {
  return api<EmergencyVisitResult>("/visits", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    idempotencyKey: newIdempotencyKey(),
    body: JSON.stringify({
      patient_id: patientId,
      visit_type: "emergency",
      visit_date: new Date().toISOString(),
    }),
  });
}

