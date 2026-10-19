import { translate } from "@/lib/i18n";
export const SETTINGS = [
  { label: "OPD Minor Procedure", value: "opd_minor" },
  { get label() { return translate("doctor.procedureSetting.bedside"); }, value: "bedside" },
  { get label() { return translate("role.emergency"); }, value: "emergency" },
  { get label() { return translate("nurse.msg.operationTheatre"); }, value: "ot" },
] as const;

export const DEFAULT_VALUES = {
  encounter_id: "",
  patient_id: "",
  procedure_name: "",
  procedure_code: "",
  code_system: "",
  setting: "bedside",
  ot_schedule_id: "",
  performed_by: "",
  assisted_by: "",
  started_at: "",
  ended_at: "",
  outcome: "",
  complications: "",
} as const;