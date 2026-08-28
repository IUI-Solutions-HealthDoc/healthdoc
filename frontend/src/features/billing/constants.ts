// FACILITY_* re-exported MOCK_FACILITY_*. Receipts now take the facility
// name from GET /users/me — a receipt naming the wrong hospital is a
// document a patient keeps. Removed (P1.1); never send a facility from the
// browser.
//
import type {
  ChargeCategory,
  InvoiceStatus,
  PaymentMode,
  PaymentStatus,
  SchemeOptionCode,
} from "./types";
export const RECEIPT_PREFIX = "RCP";
export const REFUND_PREFIX = "RFD";

export const CHARGE_CATEGORY_LABELS: Record<ChargeCategory, string> = {
  registration: "Registration",
  consultation: "Consultation",
  lab: "Lab",
  radiology: "Radiology",
  pharmacy: "Pharmacy",
  procedure: "Procedure",
  ipd_stay: "IPD Stay",
  blood: "Blood Bank",
  other: "Other",
};

export const INVOICE_STATUS_LABELS: Record<InvoiceStatus, string> = {
  draft: "Draft",
  issued: "Issued",
  partially_paid: "Partially Paid",
  paid: "Paid",
  waived: "Waived",
  cancelled: "Cancelled",
};

export const PAYMENT_MODE_LABELS: Record<PaymentMode, string> = {
  cash: "Cash",
  upi: "UPI",
  card: "Card",
  netbanking: "Net banking",
};

export const PAYMENT_STATUS_LABELS: Record<PaymentStatus, string> = {
  success: "Success",
  reversed: "Reversed",
};

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
