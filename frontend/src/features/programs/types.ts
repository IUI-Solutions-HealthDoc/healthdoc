/** Longitudinal care programs & condition registry types (HD-28). */

export type CareProgram = {
  id: string;
  program_code: string;
  program_name: string;
  category: string;
  description?: string | null;
  is_active: boolean;
};

export type ProgramEnrolment = {
  id: string;
  facility_id: string;
  patient_id: string;
  patient_name?: string | null;
  patient_uhid?: string | null;
  program_code: string;
  program_name: string;
  enrolment_date: string;
  status: "active" | "exited" | "completed";
  exit_date?: string | null;
  exit_reason?: string | null;
  target_outcomes?: Record<string, unknown> | null;
  enrolled_by: string;
  created_at: string;
};

export type ProgramVisit = {
  id: string;
  enrolment_id: string;
  scheduled_date: string;
  completed_date?: string | null;
  status: "scheduled" | "completed" | "missed";
  metrics?: Record<string, unknown> | null;
  clinical_summary?: string | null;
  conducted_by?: string | null;
  created_at: string;
};

export type ProgramTimeline = {
  enrolment: ProgramEnrolment;
  visits: ProgramVisit[];
};

export type EnrolPatientInput = {
  patient_id: string;
  program_code: string;
  enrolment_date?: string;
  target_outcomes?: Record<string, unknown>;
};

export type ExitEnrolmentInput = {
  exit_date: string;
  exit_reason: string;
};

export type RecordProgramVisitInput = {
  scheduled_date: string;
  completed_date?: string;
  metrics?: Record<string, unknown>;
  clinical_summary?: string;
};
