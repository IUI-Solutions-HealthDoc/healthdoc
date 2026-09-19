/** Operating Theatre (OT) types aligned with backend ot schemas (HD-27). */

export type OtCaseStatus = "scheduled" | "in_progress" | "completed" | "cancelled";

export type WhoSafetyChecklist = {
  sign_in: boolean;
  time_out: boolean;
  sign_out: boolean;
  confirmed_by_role?: string;
  notes?: string;
  verified_at?: string;
  verified_by_user_id?: string;
};

export type OtSchedule = {
  id: string;
  facility_id: string;
  patient_id: string;
  patient_name?: string | null;
  patient_uhid?: string | null;
  visit_id: string;
  theatre_number: string;
  scheduled_start: string;
  scheduled_end: string;
  procedure_name: string;
  status: OtCaseStatus;
  admission_id?: string | null;
  pre_op_checklist?: WhoSafetyChecklist | null;
  cancel_reason?: string | null;
  surgical_safety_confirmed: boolean;
  created_at: string;
};

export type OtRecord = {
  id: string;
  ot_schedule_id: string;
  started_at?: string | null;
  ended_at?: string | null;
  surgeon_user_id: string;
  anesthetist_user_id?: string | null;
  notes?: string | null;
  pre_op_diagnosis?: string | null;
  post_op_diagnosis?: string | null;
  procedure_performed?: string | null;
  anesthesia_type?: string | null;
  scrub_nurse?: string | null;
  circulating_nurse?: string | null;
  implants_used?: unknown;
  sponge_needle_count_correct?: boolean | null;
  specimens_sent?: unknown;
  complications?: string | null;
  recovery_status?: string | null;
  created_at: string;
};

export type OtScheduleDetail = OtSchedule & {
  record?: OtRecord | null;
};

export type CreateOtScheduleInput = {
  patient_id: string;
  visit_id: string;
  theatre_number: string;
  scheduled_start: string;
  scheduled_end: string;
  procedure_name: string;
  admission_id?: string | null;
  pre_op_checklist?: Record<string, unknown> | null;
};

export type UpdateWhoChecklistInput = {
  sign_in_confirmed: boolean;
  time_out_confirmed: boolean;
  sign_out_confirmed: boolean;
  confirmed_by_role?: string;
  notes?: string;
};

export type CompleteOtCaseInput = {
  started_at: string;
  ended_at?: string | null;
  surgeon_user_id: string;
  anesthetist_user_id?: string | null;
  notes?: string;
  pre_op_diagnosis?: string;
  post_op_diagnosis?: string;
  procedure_performed?: string;
  anesthesia_type?: string;
  scrub_nurse?: string;
  circulating_nurse?: string;
  implants_used?: unknown;
  sponge_needle_count_correct: boolean;
  specimens_sent?: unknown;
  complications?: string;
  recovery_status?: string;
};
