import { translate } from "@/lib/i18n";
export const ENTRY_TYPES = [
  { get label() { return translate("nurse.msg.oralIntake"); }, value: "intake_oral" },
  { get label() { return translate("nurse.msg.ivIntakeIncludesBloodFluidsGiven"); }, value: "intake_iv" },
  { get label() { return translate("nurse.msg.urineOutput"); }, value: "output_urine" },
  { get label() { return translate("nurse.msg.drainOutputIncludesTubeVomitType"); }, value: "output_drain" },
  { get label() { return translate("nurse.msg.otherOutputEGStool"); }, value: "output_other" },
] as const;

export const DEFAULT_VALUES = {
  admission_id: "",
  entry_type: "intake_oral",
  recorded_at: "",
  volume_ml: undefined,
  notes: "",
} as const;