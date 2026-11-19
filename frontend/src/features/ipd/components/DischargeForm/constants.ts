import { DischargeType } from "./validation";
import { translate } from "@/lib/i18n";

export const DISCHARGE_TYPE_LABELS: Record<DischargeType, string> = {
  get discharged() { return translate("ipd.msg.dischargedRoutine"); },
  dama: "DAMA (Discharge Against Medical Advice)",
  get deceased() { return translate("nurse.msg.deceased"); },
  get absconded() { return translate("nurse.msg.absconded"); },
  get transferred() { return translate("ipd.msg.transferredToAnotherFacility"); },
};

export const MODULE_LABELS: Record<string, string> = {
  get pharmacy() { return translate("doctor.orderType.pharmacy"); },
  get billing() { return translate("nav.billing"); },
  get nursing() { return translate("ipd.msg.nursing"); },
  lab: "Lab",
  get radiology() { return translate("sidebar.radiology"); },
  get patient() { return translate("common.patient"); },
};

export const DEFAULT_VALUES = {
  admission_id: "",
  discharged_at: "",
  discharge_type: "discharged" as const,
  discharge_summary: "",
  follow_up_date: "",
  // `undefined`, not "". The schema is `z.guid().optional()`, and an
  // empty string is neither a UUID nor absent — so this default failed
  // validation on every submit, for every discharge type. Nothing renders an
  // input for destination_facility_id, so the error had nowhere to appear:
  // the Preview Discharge button simply did nothing, and no patient could be
  // discharged at all.
  destination_facility_id: undefined as string | undefined,
  destination_facility_name: "",
};