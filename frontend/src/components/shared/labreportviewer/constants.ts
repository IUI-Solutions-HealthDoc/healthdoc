import { translate } from "@/lib/i18n";
// reportviewer/constants.ts

export const REPORT_STATUS = {
  get DRAFT() { return translate("billing.invoiceStatus.draft"); },
  get IN_PROGRESS() { return translate("common.msg.inProgress"); },
  get VERIFIED() { return translate("consent.verified"); },
  get FINAL() { return translate("doctor.diagnosisType.final"); },
  get CANCELLED() { return translate("appointment.status.cancelled"); },
} as const;

export const REPORT_STATUS_COLORS = {
  DRAFT: "bg-gray-100 text-gray-700",
  IN_PROGRESS: "bg-yellow-100 text-yellow-700",
  VERIFIED: "bg-blue-100 text-blue-700",
  FINAL: "bg-green-100 text-green-700",
  CANCELLED: "bg-red-100 text-red-700",
} as const;

export const RESULT_FLAG_COLORS = {
  NORMAL: "text-green-600",
  HIGH: "text-red-600 font-semibold",
  LOW: "text-orange-600 font-semibold",
  CRITICAL: "text-red-800 font-bold",
  PANIC: "text-purple-700 font-bold",
} as const;

export const GENDER_LABELS = {
  get Male() { return translate("mch.sex.male"); },
  get Female() { return translate("mch.sex.female"); },
  Other: "Other",
} as const;

export const DATE_FORMAT = "dd MMM yyyy";

export const DATETIME_FORMAT = "dd MMM, hh:mm a";

export const DEFAULT_REPORT_TITLE = "Laboratory Investigation Report";

export const EMPTY_VALUE = "--";