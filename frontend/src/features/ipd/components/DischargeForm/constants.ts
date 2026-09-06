import { DischargeType } from "./validation";

export const DISCHARGE_TYPE_LABELS: Record<DischargeType, string> = {
  discharged: "Discharged (Routine)",
  dama: "DAMA (Discharge Against Medical Advice)",
  deceased: "Deceased",
  absconded: "Absconded",
  transferred: "Transferred to Another Facility",
};

export const MODULE_LABELS: Record<string, string> = {
  pharmacy: "Pharmacy",
  billing: "Billing",
  nursing: "Nursing",
  lab: "Lab",
  radiology: "Radiology",
  patient: "Patient",
};

export const DEFAULT_VALUES = {
  admission_id: "",
  discharged_at: "",
  discharge_type: "discharged" as const,
  discharge_summary: "",
  follow_up_date: "",
  // `undefined`, not "". The schema is `z.string().uuid().optional()`, and an
  // empty string is neither a UUID nor absent — so this default failed
  // validation on every submit, for every discharge type. Nothing renders an
  // input for destination_facility_id, so the error had nowhere to appear:
  // the Preview Discharge button simply did nothing, and no patient could be
  // discharged at all.
  destination_facility_id: undefined as string | undefined,
  destination_facility_name: "",
};