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

export type EmergencyAcuity = "resuscitation" | "emergent" | "urgent" | "non_urgent";
export type EmergencyTriageStatus = "waiting" | "in_treatment" | "admitted" | "discharged" | "lwbs";
export type EmergencyDisposition = "admit" | "discharge" | "lwbs" | "transfer";

export interface EmergencyTriageOut {
  id: string;
  facility_id: string;
  patient_id: string;
  visit_id: string;
  acuity_level: EmergencyAcuity;
  chief_complaint: string;
  triage_notes: string | null;
  assigned_doctor_id: string | null;
  assigned_bay: string | null;
  status: EmergencyTriageStatus;
  triaged_at: string;
  triaged_by: string;
  clinician_seen_at: string | null;
  disposition: EmergencyDisposition | null;
  disposition_at: string | null;
  disposition_notes: string | null;
  door_to_clinician_minutes: number | null;
}

export interface EmergencyMetricsOut {
  active_census: number;
  waiting_count: number;
  in_treatment_count: number;
  resuscitation_count: number;
  emergent_count: number;
  urgent_count: number;
  non_urgent_count: number;
  avg_door_to_clinician_minutes: number | null;
  lwbs_count: number;
  facility_id?: string;
  generated_at?: string;
  total_census?: number;
  lwbs_rate?: number;
}

export interface EmergencyTriageCreateInput {
  patient_id: string;
  visit_id: string;
  acuity_level: EmergencyAcuity;
  chief_complaint: string;
  triage_notes?: string | null;
  assigned_doctor_id?: string | null;
  assigned_bay?: string | null;
}

export interface EmergencyTriageUpdateInput {
  status?: EmergencyTriageStatus | null;
  assigned_doctor_id?: string | null;
  assigned_bay?: string | null;
  clinician_seen_at?: string | null;
  disposition?: EmergencyDisposition | null;
  disposition_notes?: string | null;
}

export function listEmergencyTriages(status?: string): Promise<EmergencyTriageOut[]> {
  if (status) {
    return api<EmergencyTriageOut[]>(`/emergency/triages?status=${encodeURIComponent(status)}`);
  }
  return api<EmergencyTriageOut[]>("/emergency/triages");
}


export function getEmergencyMetrics(): Promise<EmergencyMetricsOut> {
  return api<EmergencyMetricsOut>("/emergency/metrics");
}

export function createEmergencyTriage(
  payload: EmergencyTriageCreateInput
): Promise<EmergencyTriageOut> {
  return api<EmergencyTriageOut>("/emergency/triages", {
    method: "POST",
    body: JSON.stringify(payload),
    idempotencyKey: newIdempotencyKey(),
  });
}

export function reTriageEmergencyPatient(
  triageId: string,
  newAcuity: EmergencyAcuity,
  reason: string
): Promise<EmergencyTriageOut> {
  return api<EmergencyTriageOut>(`/emergency/triages/${triageId}/re-triage`, {
    method: "POST",
    body: JSON.stringify({
      new_acuity: newAcuity,
      reason: reason.trim(),
    }),
    idempotencyKey: newIdempotencyKey(),
  });
}

export function updateEmergencyTriage(
  triageId: string,
  payload: EmergencyTriageUpdateInput
): Promise<EmergencyTriageOut> {
  return api<EmergencyTriageOut>(`/emergency/triages/${triageId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
    idempotencyKey: newIdempotencyKey(),
  });
}


