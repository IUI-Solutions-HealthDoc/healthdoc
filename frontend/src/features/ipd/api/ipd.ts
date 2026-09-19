import { api, newIdempotencyKey } from "@/lib/api";

import type { AddAdmissionSchema } from "@/features/ipd/components/AdmissionForm/validation";
import type { AddDischargeSchema } from "@/features/ipd/components/DischargeForm/validation";
import type { Ward } from "@/features/nurse/components/WardSelector/WardSelector.types";
import type { BedGridResponse } from "@/components/BedGrid/BedGrid.types";

export type AdmissionStatus =
  | "admitted"
  | "transferred"
  | "discharged"
  | "dama"
  | "deceased"
  | "absconded";

export interface Admission {
  id: string;
  visit_id: string;
  patient_id: string;
  ward_id: string;
  bed_id: string;
  admitted_at: string;
  reason?: string | null;
  status: AdmissionStatus;
}

export interface Discharge {
  id: string;
  admission_id: string;
  discharged_at: string;
  discharge_type: "discharged" | "dama" | "deceased" | "absconded" | "transferred";
  discharge_summary: string;
  follow_up_date?: string | null;
}

export interface Movement {
  id: string;
  admission_id: string;
  from_ward_id: string | null;
  from_bed_id: string | null;
  to_ward_id: string;
  to_bed_id: string;
  moved_at: string;
  reason: string | null;
}

export interface DischargeSummary {
  admission: Admission;
  discharge: Discharge | null;
  movements: Movement[];
}

export async function admitPatient(data: AddAdmissionSchema) {
  return api<Admission>("/admissions", {
    method: "POST",
    body: JSON.stringify(data),
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function dischargePatient(data: AddDischargeSchema) {
  const { admission_id, follow_up_date, ...rest } = data;
  const payload = {
    ...rest,
    // Two mismatches, both fatal, both fixed here because this function
    // already owns the wire shape. `DischargeRequest.follow_up_date` is a
    // `date`, but the form collects it with a datetime-local input; and an
    // untouched optional date arrives as "", which is neither a date nor
    // absent. The server answered 422 to every discharge until this, and the
    // screen surfaced no reason.
    follow_up_date: follow_up_date ? follow_up_date.slice(0, 10) : undefined,
  };
  return api<Discharge>(`/admissions/${admission_id}/discharge`, {
    method: "POST",
    body: JSON.stringify(payload),
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function getWards() {
  return api<Ward[]>("/wards", { method: "GET" });
}

export async function getBeds(wardId: string) {
  return api<BedGridResponse>(`/wards/${wardId}/beds`, { method: "GET" });
}

export async function getActiveAdmissions() {
  return api<Admission[]>("/admissions?status=admitted", { method: "GET" });
}

export async function getDischarges() {
  return api<Discharge[]>("/admissions/discharges", { method: "GET" });
}

// ---------------- HD-13: CLINICAL DISPOSITIONS ----------------

export interface ClinicalDisposition {
  id: string;
  facility_id: string;
  patient_id: string;
  visit_id: string;
  encounter_id?: string | null;
  disposition_type: "admit" | "discharge" | "transfer" | "follow_up";
  priority: "routine" | "urgent" | "emergency";
  recommended_ward_id?: string | null;
  recommended_department_id?: string | null;
  reason?: string | null;
  status: "pending" | "admitted" | "discharged" | "transferred" | "cancelled";
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PendingAdmissionItem {
  disposition_id: string;
  patient_id: string;
  patient_name: string;
  patient_uhid: string;
  patient_sex?: string | null;
  patient_age?: number | null;
  visit_id: string;
  visit_number: string;
  encounter_id?: string | null;
  priority: "routine" | "urgent" | "emergency";
  recommended_ward_id?: string | null;
  recommended_ward_name?: string | null;
  recommended_department_id?: string | null;
  recommended_department_name?: string | null;
  reason?: string | null;
  doctor_id?: string | null;
  doctor_name?: string | null;
  created_at: string;
}

export interface PendingDischargeItem {
  admission_id: string;
  patient_id: string;
  patient_name: string;
  patient_uhid: string;
  ward_id: string;
  ward_name: string;
  bed_id: string;
  bed_number: string;
  admitted_at: string;
  recommended_by_id?: string | null;
  recommended_by_name?: string | null;
  reason?: string | null;
  created_at: string;
}

export async function createClinicalDisposition(data: {
  patient_id: string;
  visit_id: string;
  encounter_id?: string | null;
  disposition_type: "admit" | "discharge" | "transfer" | "follow_up";
  priority?: "routine" | "urgent" | "emergency";
  recommended_ward_id?: string | null;
  recommended_department_id?: string | null;
  reason?: string | null;
  notes?: string | null;
}) {
  return api<ClinicalDisposition>("/admissions/dispositions", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function getPendingAdmissions() {
  return api<PendingAdmissionItem[]>("/admissions/to-admit", { method: "GET" });
}

export async function getPendingDischarges() {
  return api<PendingDischargeItem[]>("/admissions/to-discharge", { method: "GET" });
}

export async function updateClinicalDisposition(
  id: string,
  data: { status?: string; notes?: string }
) {
  return api<ClinicalDisposition>(`/admissions/dispositions/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

// ---------------- HD-16: ADMISSION CHECKLIST ----------------

export interface AdmissionChecklistTask {
  id: string;
  admission_id: string;
  task_code: string;
  title: string;
  category: string;
  is_mandatory: boolean;
  status: "pending" | "completed" | "skipped";
  completed_at?: string | null;
  completed_by?: string | null;
  completed_by_name?: string | null;
  skipped_reason?: string | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export async function getAdmissionChecklist(admissionId: string) {
  return api<AdmissionChecklistTask[]>(`/admissions/${admissionId}/checklist`, { method: "GET" });
}

export async function updateAdmissionChecklistTask(
  admissionId: string,
  taskId: string,
  data: {
    status: "pending" | "completed" | "skipped";
    skipped_reason?: string | null;
    notes?: string | null;
  }
) {
  return api<AdmissionChecklistTask>(`/admissions/${admissionId}/checklist/${taskId}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

// ---------------- HD-15: ADMISSION CHART ----------------

export interface AdmissionChart {
  admission_id: string;
  patient: {
    id: string;
    full_name: string;
    uhid: string;
    sex?: string | null;
    dob?: string | null;
    age_years?: number | null;
    mobile?: string | null;
  };
  admission: {
    id: string;
    admitted_at: string | null;
    status: string;
    ward_id: string;
    ward_name: string;
    bed_id: string;
    bed_number: string;
    reason?: string | null;
  };
  vitals: Array<{
    id: string;
    measured_at: string | null;
    temp_c?: number | null;
    pulse_bpm?: number | null;
    resp_rate?: number | null;
    bp_systolic?: number | null;
    bp_diastolic?: number | null;
    spo2_pct?: number | null;
    pain_score?: number | null;
  }>;
  allergies: Array<{
    id: string;
    allergen_type: string;
    substance_text: string;
    severity: string;
    reaction?: string | null;
    is_blocking: boolean;
  }>;
  diagnoses: Array<{
    id: string;
    icd_code: string;
    icd_version: string;
    diagnosis_text: string;
    diagnosis_type: string;
    is_primary: boolean;
  }>;
  orders: Array<{
    id: string;
    order_number: string;
    order_type: string;
    priority: string;
    status: string;
    ordered_at: string | null;
  }>;
  medications: Array<{
    id: string;
    medicine_name: string;
    dosage?: string | null;
    frequency?: string | null;
    duration_days?: number | null;
    route?: string | null;
    status: string;
    instructions?: string | null;
  }>;
  checklist_summary: {
    total: number;
    completed: number;
    skipped: number;
    pending: number;
    percent_complete: number;
  };
}

export async function getAdmissionChart(admissionId: string) {
  return api<AdmissionChart>(`/admissions/${admissionId}/chart`, { method: "GET" });
}
