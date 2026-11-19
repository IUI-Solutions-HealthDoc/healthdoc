import { translate } from "@/lib/i18n";
/** Keyed by the API's field names — see VitalsTimeline.types.ts. */
export const VITAL_LABELS = {
  get temp_c() { return translate("nurse.vitalsTemp"); },
  get pulse_bpm() { return translate("doctor.vitalPulse"); },
  get resp_rate() { return translate("common.msg.respiratoryRate"); },
  bp_systolic: "BP systolic",
  bp_diastolic: "BP diastolic",
  spo2_pct: "SpO₂",
  get pain_score() { return translate("doctor.vitalPainScore"); },
} as const;