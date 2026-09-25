// FACILITY_* re-exported MOCK_FACILITY_*. Receipts now take the facility
// name from GET /users/me — a receipt naming the wrong hospital is a
// document a patient keeps. Removed (P1.1); never send a facility from the
// browser.
//
import type { SchemeOptionCode } from "./types";
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
    description: "Patient pays net amount in full (stored as null; MIS shows self_pay)",
  },
  {
    code: "PMJAY",
    label: "PM-JAY (Ayushman Bharat)",
    scheme_code: "PMJAY",
    description: "Ayushman Bharat — scheme adjustment applied",
  },
  {
    code: "OTHER",
    label: "Other scheme",
    scheme_code: "OTHER",
    description: "Corporate / state / other coverage",
  },
];
