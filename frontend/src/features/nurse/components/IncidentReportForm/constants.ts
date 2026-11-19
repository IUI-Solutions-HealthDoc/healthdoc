import { IncidentType, IncidentSeverity } from "./IncidentReportForm.types";
import { translate } from "@/lib/i18n";

export const INCIDENT_TYPES: { value: IncidentType; label: string }[] = [
  { value: "medication_error", get label() { return translate("nurse.msg.medicationError"); } },
  { value: "patient_fall", get label() { return translate("nurse.msg.patientFall"); } },
  { value: "pressure_injury", get label() { return translate("nurse.msg.pressureInjury"); } },
  { value: "wrong_patient", get label() { return translate("nurse.msg.wrongPatient"); } },
  { value: "wrong_site", get label() { return translate("nurse.msg.wrongSite"); } },
  { value: "equipment_failure", get label() { return translate("nurse.msg.equipmentFailure"); } },
  { value: "needlestick", get label() { return translate("nurse.msg.needlestick"); } },
  { value: "transfusion_reaction", get label() { return translate("nurse.msg.transfusionReaction"); } },
  { value: "hospital_acquired_infection", label: "Hospital-Acquired Infection" },
  { value: "near_miss", get label() { return translate("nurse.msg.nearMissDidNotReachPatient"); } },
  { value: "other", label: "Other" },
];

// Harm that actually REACHED the patient. near_miss is NOT a severity —
// it's a type (above), for events that never reached the patient.
export const SEVERITIES: { value: IncidentSeverity; label: string }[] = [
  { value: "no_harm", get label() { return translate("nurse.msg.noHarm"); } },
  { value: "minor", get label() { return translate("nurse.msg.minor"); } },
  { value: "moderate", get label() { return translate("nurse.msg.moderate"); } },
  { value: "severe", get label() { return translate("nurse.msg.severe"); } },
  { value: "death", get label() { return translate("nurse.msg.death"); } },
];
