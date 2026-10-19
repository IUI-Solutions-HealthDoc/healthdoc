import type {
  DiagnosisType,
  EncounterType,
  FrequencyCode,
  OrderPriority,
  OrderType,
  Modality,
  ProcedureSetting,
  RouteCode,
  SampleType,
  QueuePriority,
} from "./types";
import { translate } from "@/lib/i18n";

/**
 * break_glass_grants.justification — the schema annotates it "≥20 chars,
 * mandatory", but as a comment, not a CHECK constraint. Enforced here so the
 * form matches intent; the server must enforce it too (raised with B7).
 */
export const BREAK_GLASS_JUSTIFICATION_MIN = 20;

/**
 * Minimum characters to override a non-anaphylaxis allergy.
 * Mirrors backend allergies/service.OVERRIDE_REASON_MIN_CHARS.
 * Anaphylaxis has no override at any length.
 */
export const ALLERGY_OVERRIDE_REASON_MIN = 20;

/** Schema priority sort (high → low) — QueuePriority docstring in enums.py. */
export const QUEUE_PRIORITY_RANK: Record<QueuePriority, number> = {
  emergency: 0,
  doctor_recall: 1,
  admin_override: 2,
  senior_citizen: 3,
  pregnant: 4,
  follow_up_recall: 5,
  normal: 6,
};

export const ENCOUNTER_TYPE_OPTIONS: { value: EncounterType; label: string }[] = [
  { value: "consultation", get label() { return translate("monitor.kind.consultation"); } },
  { value: "follow_up", label: "Follow-up" },
  { value: "emergency", get label() { return translate("role.emergency"); } },
  { value: "ward_round", get label() { return translate("doctor.encounterType.ward_round"); } },
];

export const DIAGNOSIS_TYPE_OPTIONS: { value: DiagnosisType; label: string }[] = [
  { value: "provisional", get label() { return translate("doctor.diagnosisType.provisional"); } },
  { value: "final", get label() { return translate("doctor.diagnosisType.final"); } },
  { value: "differential", get label() { return translate("doctor.diagnosisType.differential"); } },
];

export const ORDER_TYPE_OPTIONS: { value: OrderType; label: string }[] = [
  { value: "lab", label: "Lab" },
  { value: "radiology", get label() { return translate("sidebar.radiology"); } },
  { value: "procedure", get label() { return translate("doctor.orderType.procedure"); } },
];

/** lab_order_items.sample_type — NOT NULL, so the form must collect it. */
export const SAMPLE_TYPE_OPTIONS: { value: SampleType; label: string }[] = [
  { value: "blood", get label() { return translate("doctor.orderType.blood"); } },
  { value: "serum", get label() { return translate("doctor.sampleType.serum"); } },
  { value: "plasma", get label() { return translate("doctor.sampleType.plasma"); } },
  { value: "urine", get label() { return translate("mch.urine"); } },
  { value: "stool", get label() { return translate("doctor.sampleType.stool"); } },
  { value: "swab", get label() { return translate("doctor.sampleType.swab"); } },
  { value: "tissue", get label() { return translate("doctor.sampleType.tissue"); } },
];

/** radiology_order_items.modality — NOT NULL. */
export const MODALITY_OPTIONS: { value: Modality; label: string }[] = [
  { value: "xray", label: "X-Ray" },
  { value: "ct", label: "CT" },
  { value: "mri", label: "MRI" },
  { value: "usg", get label() { return translate("doctor.modality.usg"); } },
  { value: "mammo", get label() { return translate("doctor.modality.mammo"); } },
];

/** Non-theatre procedures. OT procedures require scheduling context first. */
export const PROCEDURE_SETTING_OPTIONS: { value: ProcedureSetting; label: string }[] = [
  { value: "opd_minor", get label() { return translate("doctor.procedureSetting.opd_minor"); } },
  { value: "bedside", get label() { return translate("doctor.procedureSetting.bedside"); } },
  { value: "emergency", get label() { return translate("role.emergency"); } },
];

export const ORDER_PRIORITY_OPTIONS: { value: OrderPriority; label: string }[] = [
  { value: "routine", label: "Routine" },
  { value: "urgent", label: "Urgent" },
  { value: "stat", label: "STAT" },
];

export const PRIORITY_META: Record<
  QueuePriority,
  { label: string; variant: "default" | "secondary" | "destructive" | "outline" } | null
> = {
  normal: null,
  senior_citizen: { get label() { return translate("doctor.msg.senior"); }, variant: "secondary" },
  pregnant: { get label() { return translate("doctor.msg.pregnant"); }, variant: "secondary" },
  emergency: { get label() { return translate("role.emergency"); }, variant: "destructive" },
  doctor_recall: { get label() { return translate("doctor.msg.recall"); }, variant: "outline" },
  follow_up_recall: { label: "Follow-up", variant: "outline" },
  admin_override: { get label() { return translate("receptionist.priority"); }, variant: "outline" },
};

// --- Prescription vocabularies (prescription_items) ---

/** Frequency codes with expansions. SOS = as needed (PRN); STAT = immediately, once. */
export const FREQUENCY_OPTIONS: { value: FrequencyCode; label: string }[] = [
  { value: "OD", get label() { return translate("doctor.msg.odOnceDaily"); } },
  { value: "BD", get label() { return translate("doctor.msg.bdTwiceDaily"); } },
  { value: "TDS", get label() { return translate("doctor.msg.tdsThriceDaily"); } },
  { value: "QID", get label() { return translate("doctor.msg.qidFourTimesDaily"); } },
  { value: "HS", get label() { return translate("doctor.msg.hsAtBedtime"); } },
  { value: "STAT", label: "STAT — immediately, once" },
  { value: "SOS", get label() { return translate("doctor.msg.sosAsNeededPrn"); } },
];

/** Frequencies that don't take a fixed duration (single or as-needed dosing). */
export const FREQUENCIES_WITHOUT_DURATION: FrequencyCode[] = ["SOS", "STAT"];

export const ROUTE_OPTIONS: { value: RouteCode; label: string }[] = [
  { value: "oral", get label() { return translate("nurse.ui.oral"); } },
  { value: "iv", get label() { return translate("nurse.ui.intravenousIv"); } },
  { value: "im", get label() { return translate("nurse.ui.intramuscularIm"); } },
  { value: "sc", get label() { return translate("nurse.ui.subcutaneousSc"); } },
  { value: "topical", get label() { return translate("nurse.ui.topical"); } },
  { value: "inhaled", get label() { return translate("doctor.msg.inhaled"); } },
  { value: "sublingual", get label() { return translate("nurse.ui.sublingual"); } },
  { value: "rectal", get label() { return translate("nurse.ui.rectal"); } },
  { value: "ophthalmic", get label() { return translate("doctor.msg.ophthalmic"); } },
];
