/**
 * Nurse / IPD nursing DTOs — aligned with schema vitals (0023), eMAR (0043),
 * order check-off (0045), clinical_incidents (0046), handover (0023).
 */

export type Shift = "morning" | "evening" | "night";

export type IntakeOutputEntryType =
  | "intake_oral"
  | "intake_iv"
  | "output_urine"
  | "output_drain"
  | "output_other";

export type NursingTaskPriority = "routine" | "urgent" | "stat";

export type NursingTaskStatus =
  | "placed"
  | "accepted"
  | "in_progress"
  | "completed"
  | "cancelled";

export type ClinicalIncidentType =
  | "medication_error"
  | "patient_fall"
  | "pressure_injury"
  | "wrong_patient"
  | "wrong_site"
  | "equipment_failure"
  | "needlestick"
  | "transfusion_reaction"
  | "hospital_acquired_infection"
  | "near_miss"
  | "other";

export type ClinicalIncidentSeverity =
  | "no_harm"
  | "minor"
  | "moderate"
  | "severe"
  | "death";

export type ClinicalIncidentStatus =
  | "reported"
  | "under_review"
  | "action_taken"
  | "closed";

export type Vitals = {
  id: string;
  patient_id: string;
  encounter_id: string | null;
  admission_id: string | null;
  measured_at: string;
  temp_c: number | null;
  pulse_bpm: number | null;
  resp_rate: number | null;
  bp_systolic: number | null;
  bp_diastolic: number | null;
  spo2_pct: number | null;
  pain_score: number | null;
  bmi: number | null;
  whr: number | null;
};

export type NursingHandoverNote = {
  id: string;
  admission_id: string;
  shift: Shift;
  situation: string | null;
  background: string | null;
  assessment: string | null;
  recommendation: string | null;
  handed_over_to: string;
  created_by?: string;
  created_at?: string;
};

export type IntakeOutputRecord = {
  id: string;
  admission_id: string;
  recorded_at: string;
  entry_type: IntakeOutputEntryType;
  volume_ml: number;
  notes: string | null;
  created_by?: string;
  created_at?: string;
};

export type FluidBalance = {
  admission_id: string;
  total_intake_ml: number;
  total_output_ml: number;
  net_ml: number;
};

export type NursingTask = {
  id: string;
  patient_id: string;
  encounter_id: string | null;
  order_type: string;
  priority: NursingTaskPriority;
  status: NursingTaskStatus;
  ordered_at: string;
  accepted_at: string | null;
  accepted_by: string | null;
  completed_at: string | null;
  completed_by: string | null;
  completion_note: string | null;
  order_number?: string | null;
  patient_name?: string | null;
  patient_uhid?: string | null;
  patient_age_years?: number | null;
  patient_sex?: string | null;
};

export type ClinicalIncident = {
  id: string;
  facility_id: string;
  department_id: string | null;
  ward_id: string | null;
  patient_id: string | null;
  admission_id: string | null;
  incident_type: string;
  severity: string;
  status: string;
  occurred_at: string;
  reported_at: string;
  description: string;
  immediate_action: string;
  reported_by: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  root_cause: string | null;
  corrective_action: string | null;
};

export type ReportIncidentPayload = {
  incident_type: string;
  severity: string;
  occurred_at: string;
  description: string;
  immediate_action: string;
  patient_id?: string | null;
  admission_id?: string | null;
  department_id?: string | null;
  ward_id?: string | null;
  reported_at?: string | null;
};

export type AdmissionTransferResult = {
  id: string;
  visit_id: string;
  patient_id: string;
  ward_id: string;
  bed_id: string;
  admitted_at: string;
  reason: string | null;
  status: string;
};

export type HandoverRecipientOption = {
  value: string;
  label: string;
};
