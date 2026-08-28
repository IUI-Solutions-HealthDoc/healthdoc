/** Billing DTOs aligned to BE billing schemas + migration 0014/0033 (§4.2 money as string). */

import type { Money } from "./lib/money";

export type { Money };

export type InvoiceStatus =
  | "draft"
  | "issued"
  | "partially_paid"
  | "paid"
  | "waived"
  | "cancelled";

export type ChargeCategory =
  | "registration"
  | "consultation"
  | "lab"
  | "radiology"
  | "pharmacy"
  | "procedure"
  | "ipd_stay"
  | "blood"
  | "other";

export type PaymentMode = "cash" | "upi" | "card" | "netbanking";
export type PaymentStatus = "success" | "reversed";

/**
 * UI selector codes. Stored `invoices.scheme_code` is null for self-pay
 * (BE MIS labels that as "self_pay") or "PMJAY" / other scheme strings.
 */
export type SchemeOptionCode = "self_pay" | "PMJAY" | "OTHER";

/** Migration 0033 — effective-dated tariff row (never UPDATEd; revise = new row). */
export type ChargeMaster = {
  id: string;
  facility_id: string;
  charge_code: string;
  description: string;
  charge_category: ChargeCategory;
  unit_price: Money;
  /** null = general tariff; "PMJAY" etc. = scheme rate */
  scheme_code: string | null;
  effective_from: string;
  effective_to: string | null;
  is_active: boolean;
  created_by: string;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
};

export type Invoice = {
  id: string;
  invoice_number: string;
  visit_id: string;
  patient_id: string;
  facility_id: string;
  status: InvoiceStatus;
  gross_amount: Money;
  discount_amount: Money;
  scheme_adjustment: Money;
  net_amount: Money;
  scheme_code: string | null;
  sensitivity: "critical";
  /**
   * Optimistic concurrency (0035). Required by POST /invoices/{id}/issue as an
   * If-Match: departments append charge lines to a draft as work completes, so
   * a stale client would freeze an invoice missing a line added since it
   * loaded. The fixture omitted this field entirely.
   */
  row_version: number;
  created_at: string;
  updated_at: string;
};

export type InvoiceItem = {
  id: string;
  invoice_id: string;
  charge_category: ChargeCategory;
  /** Source table, e.g. lab_order_items — required for accrual anti-double-bill */
  reference_type: string | null;
  reference_id: string | null;
  /** Pins exact tariff row used at accrual (0033) */
  charge_master_id: string | null;
  description: string;
  quantity: number;
  unit_price: Money;
  amount: Money;
};

/** Visit type enum (lowercase) — schema visits.visit_type. */
export type VisitType = "opd" | "ipd" | "emergency" | "day_care";

export type PatientSex = "male" | "female" | "other" | "unknown";

export type InvoiceWithItems = Invoice & {
  items: InvoiceItem[];
  payments?: Payment[];
  /** Read context from patients / visits — not invoice columns. */
  patient?: {
    uhid: string;
    full_name: string;
    age_years?: number;
    sex?: PatientSex;
  };
  visit?: { visit_type: VisitType };
};

export type Paginated<T> = {
  items: T[];
  page: number;
  page_size: number;
  total: number;
};

export type Payment = {
  id: string;
  invoice_id: string;
  receipt_number: string;
  amount: Money;
  currency: string;
  mode: PaymentMode;
  status: PaymentStatus;
  /** Write-path / audit actor — not on PaymentOut; kept for receipt print */
  collected_by: string;
  collected_at: string;
  sensitivity: "critical";
};

export type Refund = {
  id: string;
  payment_id: string;
  refund_number: string;
  amount: Money;
  reason: string;
  approved_by: string;
  refunded_at: string;
};

/** POST /billing/invoices/{id}/payments — requires Idempotency-Key header on wire. */
export type CollectPaymentInput = {
  amount: Money | number;
  mode: PaymentMode;
  currency?: string;
  collected_at?: string | null;
};

/** POST /billing/payments/{id}/refunds — requires Idempotency-Key header on wire. */
export type CreateRefundInput = {
  amount: Money | number;
  reason: string;
};

export type PaymentWithRefunds = Payment & {
  refunds: Refund[];
};

export type InvoiceListFilters = {
  query?: string;
  status?: InvoiceStatus | "all";
  page?: number;
  page_size?: number;
};

export type AddInvoiceItemInput = {
  charge_category: ChargeCategory;
  description: string;
  quantity: number;
  unit_price: Money | number;
  reference_type?: string | null;
  reference_id?: string | null;
  charge_master_id?: string | null;
};

export type UpdateInvoiceDraftInput = {
  scheme_code?: string | null;
  discount_amount?: Money | number;
  scheme_adjustment?: Money | number;
  status?: InvoiceStatus;
};

export type InvoiceBalance = {
  net_amount: Money;
  paid_total: Money;
  refunded_total: Money;
  balance_due: Money;
};

/** GET /billing/visits/{visit_id}/invoice/preview — ChargeLine */
export type ChargeLine = {
  charge_category: ChargeCategory;
  reference_type: string;
  reference_id: string;
  description: string;
  quantity: number;
  unit_price: Money;
  amount: Money;
  priced: boolean;
  pricing_note: string | null;
  charge_master_id?: string | null;
};

export type InvoicePreviewResponse = {
  visit_id: string;
  patient_id: string | null;
  invoice_id: string | null;
  invoice_status: string | null;
  already_billed_count: number;
  new_charge_lines: ChargeLine[];
  unpriced_count: number;
  projected_new_charges_total: Money;
  projected_gross_amount: Money;
};

export type InvoiceBuildRequest = {
  dry_run?: boolean;
};

export type InvoiceBuildResponse = {
  visit_id: string;
  invoice_id: string;
  invoice_number: string;
  status: string;
  lines_added: number;
  lines_skipped_unpriced: number;
  gross_amount: Money;
  net_amount: Money;
};

/** GET /billing/visits/{visit_id}/pmjay-eligibility */
export type PMJAYEligibilityResponse = {
  patient_id: string;
  visit_id: string;
  scheme_code: "PMJAY";
  eligibility_status: "eligible" | "not_eligible" | "not_determined";
  reason: string;
  is_stub: boolean;
};

/** GET /billing/mis/daily-revenue */
export type DailyRevenuePoint = {
  day: string;
  payment_count: number;
  gross_collected: Money;
  refunded: Money;
  net_revenue: Money;
};

export type DailyRevenueResponse = {
  facility_id: string;
  date_from: string;
  date_to: string;
  points: DailyRevenuePoint[];
  total_net_revenue: Money;
};

/** GET /billing/mis/pending-invoices */
export type PendingInvoiceLine = {
  invoice_id: string;
  invoice_number: string;
  visit_id: string;
  patient_id: string;
  status: string;
  net_amount: Money;
  paid_amount: Money;
  balance_due: Money;
  created_at: string;
  days_pending: number;
};

export type PendingInvoicesResponse = {
  facility_id: string;
  as_of: string;
  count: number;
  total_balance_due: Money;
  items: PendingInvoiceLine[];
};

/** GET /billing/mis/scheme-breakdown */
export type SchemeBreakdownLine = {
  /** "self_pay" when invoices.scheme_code is NULL */
  scheme_code: string;
  invoice_count: number;
  net_billed: Money;
  scheme_adjustment_total: Money;
  collected_total: Money;
};

export type SchemeBreakdownResponse = {
  facility_id: string;
  date_from: string;
  date_to: string;
  lines: SchemeBreakdownLine[];
  grand_total_net_billed: Money;
};

export type MisDateRange = {
  date_from?: string;
  date_to?: string;
};
