import { ApiError, api } from "@/lib/api";
import { StaleWriteError } from "../types";
import type {
  ActiveEncounter,
  CreateDiagnosisInput,
  CreateEncounterInput,
  EncounterType,
  IcdConcept,
  NoteStatus,
  UpdateEncounterInput,
  VitalsInput,
} from "../types";

interface EncounterResponse {
  id: string;
  visit_id: string;
  provider_user_id: string;
  encounter_type?: string | null;
  chief_complaint?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  subjective?: string | null;
  objective?: string | null;
  assessment?: string | null;
  plan?: string | null;
  note_status: string;
  row_version: number;
}

interface IcdSearchResponse {
  items: IcdConcept[];
  source: string;
}

function toEncounter(row: EncounterResponse, patientId: string): ActiveEncounter {
  return {
    id: row.id,
    visit_id: row.visit_id,
    patient_id: patientId,
    provider_user_id: row.provider_user_id,
    encounter_type: row.encounter_type as EncounterType | undefined,
    chief_complaint: row.chief_complaint ?? undefined,
    started_at: row.started_at ?? new Date().toISOString(),
    ended_at: row.ended_at ?? undefined,
    subjective: row.subjective ?? undefined,
    objective: row.objective ?? undefined,
    assessment: row.assessment ?? undefined,
    plan: row.plan ?? undefined,
    note_status: row.note_status as NoteStatus,
    row_version: row.row_version,
  };
}

/** Latest persisted encounter for this visit; null means the consultation is not saved yet. */
export async function getEncounterForVisit(
  visitId: string,
  patientId: string,
): Promise<ActiveEncounter | null> {
  try {
    const row = await api<EncounterResponse>(`/encounters/by-visit/${visitId}`);
    return toEncounter(row, patientId);
  } catch (error) {
    if (error instanceof ApiError && error.code === 404) return null;
    throw error;
  }
}

/** POST /encounters. The server owns the id and all authorship fields. */
export async function createEncounter(
  body: CreateEncounterInput,
  patientId: string,
  idempotencyKey: string,
): Promise<ActiveEncounter> {
  const row = await api<EncounterResponse>("/encounters", {
    method: "POST",
    body: JSON.stringify(body),
    idempotencyKey,
  });
  return toEncounter(row, patientId);
}

/** PATCH /encounters/{id}; If-Match prevents one clinician overwriting another. */
export async function updateEncounter(
  encounter: ActiveEncounter,
  patch: UpdateEncounterInput,
): Promise<ActiveEncounter> {
  try {
    const row = await api<EncounterResponse>(`/encounters/${encounter.id}`, {
      method: "PATCH",
      body: JSON.stringify(patch),
      ifMatch: encounter.row_version,
    });
    return toEncounter(row, encounter.patient_id);
  } catch (error) {
    if (error instanceof ApiError && error.isStaleWrite) {
      const payload = error.payload as { current?: EncounterResponse };
      const current = payload.current;
      throw new StaleWriteError(current?.row_version ?? encounter.row_version ?? 1, {
        encounter_type: current?.encounter_type as EncounterType | undefined,
        chief_complaint: current?.chief_complaint ?? undefined,
        subjective: current?.subjective ?? undefined,
        objective: current?.objective ?? undefined,
        assessment: current?.assessment ?? undefined,
        plan: current?.plan ?? undefined,
        note_status: current?.note_status as NoteStatus | undefined,
      });
    }
    throw error;
  }
}

export async function completeEncounter(
  encounter: ActiveEncounter,
  endedAt: string,
): Promise<ActiveEncounter> {
  return updateEncounter(encounter, { ended_at: endedAt });
}

/** POST /nursing/vitals; recorded_by is derived from the access token. */
export async function saveVitals(input: VitalsInput, idempotencyKey: string): Promise<void> {
  await api("/nursing/vitals", {
    method: "POST",
    body: JSON.stringify(input),
    idempotencyKey,
  });
}

/** GET /diagnoses/icd-search; WHO ICD-11 degrades to the local ICD catalogue. */
export async function searchIcd(query: string): Promise<IcdConcept[]> {
  const q = query.trim();
  if (!q) return [];
  const response = await api<IcdSearchResponse>(
    `/diagnoses/icd-search?q=${encodeURIComponent(q)}`,
  );
  return response.items;
}

/** POST one diagnosis under the persisted encounter. */
export async function saveDiagnosis(
  row: CreateDiagnosisInput,
  idempotencyKey: string,
): Promise<void> {
  await api(`/encounters/${row.encounter_id}/diagnoses`, {
    method: "POST",
    body: JSON.stringify(row),
    idempotencyKey,
  });
}

export async function listDiagnoses(
  encounterId: string,
): Promise<Array<CreateDiagnosisInput & { id: string }>> {
  return api<Array<CreateDiagnosisInput & { id: string }>>(
    `/encounters/${encounterId}/diagnoses`,
  );
}

export interface TerminologyConcept {
  code: string;
  display: string;
  system: "icd10" | "icd11" | "snomed";
  system_name: string;
  system_uri: string;
  category?: string | null;
}

export interface TerminologySearchResponse {
  items: TerminologyConcept[];
  system: string;
  total: number;
}

export async function searchTerminology(
  query: string,
  system: "all" | "icd10" | "icd11" | "snomed" = "all",
): Promise<TerminologyConcept[]> {
  const q = query.trim();
  if (!q) return [];
  const response = await api<TerminologySearchResponse>(
    `/terminology/search?q=${encodeURIComponent(q)}&system=${encodeURIComponent(system)}`,
  );
  return response.items;
}

export interface SpecialtyTemplateField {
  name: string;
  label: string;
  type: "text" | "number" | "select" | "multiselect" | "textarea" | "date";
  required?: boolean;
  options?: Array<{ label: string; value: string }>;
  unit?: string;
  help_text?: string;
}

export interface SpecialtyTemplate {
  specialty_type: "pediatric" | "cardiology" | "obstetrics";
  title: string;
  description: string;
  fields: SpecialtyTemplateField[];
}

export interface SpecialtyAssessmentRecord {
  id: string;
  encounter_id: string;
  patient_id: string;
  specialty_type: string;
  clinical_data: Record<string, unknown>;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export async function getSpecialtyTemplates(): Promise<SpecialtyTemplate[]> {
  return api<SpecialtyTemplate[]>("/clinical/specialty-templates");
}

export async function getEncounterSpecialty(
  encounterId: string,
): Promise<SpecialtyAssessmentRecord | null> {
  try {
    return await api<SpecialtyAssessmentRecord>(`/clinical/encounters/${encounterId}/specialty`);
  } catch {
    return null;
  }
}

export async function saveEncounterSpecialty(
  encounterId: string,
  specialtyType: string,
  clinicalData: Record<string, unknown>,
): Promise<SpecialtyAssessmentRecord> {
  return api<SpecialtyAssessmentRecord>(`/clinical/encounters/${encounterId}/specialty`, {
    method: "POST",
    body: JSON.stringify({
      specialty_type: specialtyType,
      clinical_data: clinicalData,
    }),
  });
}

