import type { AddNursingNoteSchema } from "./validation";
import { translate } from "@/lib/i18n";

export const DEFAULT_VALUES: AddNursingNoteSchema = {
  encounter_id: "",
  patient_id: "",
  get category() { return translate("billing.tariff.schemeGeneral"); },
  get priority() { return translate("mch.mode.normal"); },
  note: "",
};

export const NOTE_CATEGORIES = [
  "General",
  "Medication",
  "Vitals",
  "Procedure",
  "Observation",
];

export const PRIORITIES = ["Low", "Normal", "High", "Critical"] as const;
