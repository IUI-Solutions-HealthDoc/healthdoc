import { api } from "@/lib/api";
import type {
  ImmunizationCertificate,
  ImmunizationRecord,
  ImmunizationRecordCreate,
  PatientImmunizationSchedule,
  Vaccine,
} from "./types";

export function fetchVaccineCatalogue(): Promise<Vaccine[]> {
  return api<Vaccine[]>("/immunization/catalogue");
}

export function fetchPatientSchedule(patientId: string): Promise<PatientImmunizationSchedule> {
  return api<PatientImmunizationSchedule>(`/immunization/patients/${patientId}`);
}

export function recordImmunization(payload: ImmunizationRecordCreate, idempotencyKey: string): Promise<ImmunizationRecord> {
  return api<ImmunizationRecord>("/immunization/records", {
    method: "POST",
    idempotencyKey,
    body: JSON.stringify(payload),
  });
}

export function fetchImmunizationCertificate(patientId: string): Promise<ImmunizationCertificate> {
  return api<ImmunizationCertificate>(`/immunization/patients/${patientId}/certificate`);
}
