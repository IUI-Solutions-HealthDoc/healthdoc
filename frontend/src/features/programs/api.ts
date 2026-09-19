import { api } from "@/lib/api";
import type {
  CareProgram,
  EnrolPatientInput,
  ExitEnrolmentInput,
  ProgramEnrolment,
  ProgramTimeline,
  ProgramVisit,
  RecordProgramVisitInput,
} from "./types";

export async function listCarePrograms(): Promise<CareProgram[]> {
  return api<CareProgram[]>("/programs");
}

export async function listEnrolments(filters?: {
  program_code?: string;
  patient_id?: string;
  status?: string;
}): Promise<ProgramEnrolment[]> {
  const params = new URLSearchParams();
  if (filters?.program_code) params.set("program_code", filters.program_code);
  if (filters?.patient_id) params.set("patient_id", filters.patient_id);
  if (filters?.status) params.set("status", filters.status);
  return api<ProgramEnrolment[]>(`/programs/enrolments?${params.toString()}`);
}

export async function enrolPatient(body: EnrolPatientInput): Promise<ProgramEnrolment> {
  return api<ProgramEnrolment>("/programs/enrolments", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getEnrolmentTimeline(enrolmentId: string): Promise<ProgramTimeline> {
  return api<ProgramTimeline>(`/programs/enrolments/${enrolmentId}`);
}

export async function exitEnrolment(
  enrolmentId: string,
  body: ExitEnrolmentInput,
): Promise<ProgramEnrolment> {
  return api<ProgramEnrolment>(`/programs/enrolments/${enrolmentId}/exit`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function recordProgramVisit(
  enrolmentId: string,
  body: RecordProgramVisitInput,
): Promise<ProgramVisit> {
  return api<ProgramVisit>(`/programs/enrolments/${enrolmentId}/visits`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
