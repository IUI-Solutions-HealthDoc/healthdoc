import { api, newIdempotencyKey } from "@/lib/api";

import type { AddVitalsSchema } from "@/features/nurse/components/AddVitalsForm/validation";
import type { AddPatientMovementSchema } from "@/components/AddPatientMovementForm/validation";
import type { AddHandoverSchema } from "@/features/nurse/components/AddHandoverForm/validation";
import type { AddIntakeOutputSchema } from "@/features/nurse/components/AddIntakeOutputForm/validation";
import type { AddProcedureAssistanceSchema } from "@/features/nurse/components/AddProcedureAssistanceForm/validation";
import type { AddNursingNoteSchema } from "@/features/nurse/components/AddNursingNoteForm/validation";
import type { VitalRecord } from "@/components/VitalsTimeline/VitalsTimeline.types";
import type { MedicationRecord } from "@/components/tables/EMARTable/EMARTable.types";
import type { DischargeSummary } from "@/features/ipd/api/ipd";
import type {
  AdmissionTransferResult,
  ClinicalIncident,
  FluidBalance,
  IntakeOutputRecord,
  NursingTask,
  ReportIncidentPayload,
  Vitals,
} from "../types";

export type {
  AdmissionTransferResult,
  ClinicalIncident,
  FluidBalance,
  IntakeOutputRecord,
  NursingHandoverNote,
  NursingTask,
  ReportIncidentPayload,
  Vitals,
} from "../types";

export class UnsupportedWorkflowError extends Error {
  constructor(workflow: string) {
    super(`${workflow} is not available yet.`);
    this.name = "UnsupportedWorkflowError";
  }
}

export async function getNursingTasks(patientId?: string) {
  if (patientId) {
    return api<NursingTask[]>(
      `/nursing/tasks?patient_id=${encodeURIComponent(patientId)}`,
    );
  }
  return api<NursingTask[]>("/nursing/tasks");
}

export async function getPatientVitals(patientId: string) {
  return api<VitalRecord[]>(`/nursing/patients/${patientId}/vitals`);
}

export async function getAdmissionFluidBalance(admissionId: string) {
  return api<FluidBalance>(`/nursing/admissions/${admissionId}/fluid-balance`);
}

export async function getAdmissionMedicationAdministrations(admissionId: string) {
  return api<MedicationRecord[]>(
    `/nursing/admissions/${admissionId}/medication-administrations`,
  );
}

export async function getAdmissionHandoverNotes(admissionId: string) {
  void admissionId;
  // Table exists (0023) but no published FastAPI read route yet.
  throw new UnsupportedWorkflowError("Handover notes list");
}

export async function getAdmissionSummary(admissionId: string) {
  return api<DischargeSummary>(`/admissions/${admissionId}/discharge-summary`);
}

export async function listIncidents(filters?: {
  patientId?: string;
  status?: string;
}) {
  const params = new URLSearchParams();
  if (filters?.patientId) params.set("patient_id", filters.patientId);
  if (filters?.status) params.set("status", filters.status);
  const qs = params.toString();
  return api<ClinicalIncident[]>(
    qs ? `/nursing/incidents?${qs}` : "/nursing/incidents",
  );
}

export async function acceptNursingTask(orderId: string) {
  return api<NursingTask>(`/nursing/tasks/${orderId}/accept`, {
    method: "POST",
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function completeNursingTask(orderId: string, note?: string) {
  return api<NursingTask>(`/nursing/tasks/${orderId}/complete`, {
    method: "POST",
    body: JSON.stringify({ note: note ?? null }),
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function addVitals(data: AddVitalsSchema) {
  return api<Vitals>("/nursing/vitals", {
    method: "POST",
    body: JSON.stringify(data),
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function addHandover(data: AddHandoverSchema) {
  void data;
  // Table exists (0023) but no published FastAPI write route yet.
  throw new UnsupportedWorkflowError("Handover note entry");
}

export async function reportIncident(data: ReportIncidentPayload) {
  return api<ClinicalIncident>("/nursing/incidents", {
    method: "POST",
    body: JSON.stringify(data),
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function addIntakeOutput(data: AddIntakeOutputSchema) {
  return api<IntakeOutputRecord>("/nursing/intake-output", {
    method: "POST",
    body: JSON.stringify(data),
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function addPatientMovement(data: AddPatientMovementSchema) {
  return api<AdmissionTransferResult>(
    `/admissions/${data.admission_id}/transfer`,
    {
      method: "POST",
      body: JSON.stringify({
        to_ward_id: data.to_ward_id,
        to_bed_id: data.to_bed_id,
        reason: data.reason ?? null,
      }),
      idempotencyKey: newIdempotencyKey(),
    },
  );
}

export async function addProcedureAssistance(data: AddProcedureAssistanceSchema) {
  void data;
  throw new UnsupportedWorkflowError("Procedure assistance entry");
}

export async function addNursingNote(data: AddNursingNoteSchema) {
  void data;
  throw new UnsupportedWorkflowError("Nursing note entry");
}
