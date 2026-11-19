// FACILITY_* re-exported MOCK_FACILITY_*. Receipts now take the facility
// name from GET /users/me — a receipt naming the wrong hospital is a
// document a patient keeps. Removed (P1.1); never send a facility from the
// browser.
//
import type { SchemeOptionCode } from "./types";
import { translate } from "@/lib/i18n";
export const RECEIPT_PREFIX = "RCP";
export const REFUND_PREFIX = "RFD";

export const SCHEME_OPTIONS: {
  code: SchemeOptionCode;
  label: string;
  scheme_code: string | null;
  description: string;
}[] = [
  {
    code: "self_pay",
    label: "Self-pay / Cash",
    scheme_code: null,
    get description() { return translate("billing.msg.patientPaysNetAmountInFull"); },
  },
  {
    code: "PMJAY",
    label: "PM-JAY (Ayushman Bharat)",
    scheme_code: "PMJAY",
    get description() { return translate("billing.msg.ayushmanBharatSchemeAdjustmentApplied"); },
  },
  {
    code: "OTHER",
    get label() { return translate("billing.msg.otherScheme"); },
    scheme_code: "OTHER",
    get description() { return translate("billing.msg.corporateStateOtherCoverage"); },
  },
];
