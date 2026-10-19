import type { Shift } from "./types";
import { translate } from "@/lib/i18n";

export const SHIFTS: readonly Shift[] = ["morning", "evening", "night"] as const;

export const INCIDENT_STATUS_LABELS: Record<string, string> = {
  get reported() { return translate("nurse.msg.reported"); },
  get under_review() { return translate("nurse.msg.underReview"); },
  get action_taken() { return translate("nurse.msg.actionTaken"); },
  get closed() { return translate("nurse.msg.closed"); },
};
