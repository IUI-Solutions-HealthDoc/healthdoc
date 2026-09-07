/**
 * Invoices. Retired from fixtures (P1.1).
 *
 * MANUAL LINE EDITING WAS REMOVED, NOT LEFT UNIMPLEMENTED.
 *
 * The fixture exposed updateInvoiceDraft, addInvoiceItem, updateInvoiceItem and
 * removeInvoiceItem. No endpoint backs any of them, and after review the
 * decision is that none should: charges are aggregated onto the draft by
 * `POST /billing/visits/{visit_id}/invoice/build` from what the lab, radiology
 * and pharmacy modules actually recorded. A clerk typing a line by hand would
 * be billing for work no department logged.
 *
 * Issuing then freezes the amounts — `trg_invoices_freeze` blocks changes to
 * everything but status once the invoice leaves 'draft' — and the documented
 * correction path is cancel-and-reissue, never an edit. So the editor screen
 * was not an unfinished feature; it was a feature that contradicts the schema.
 *
 * If that is ever revisited, it needs endpoints AND a decision about what
 * happens to the accrual guard in `_already_billed_reference_ids`, which exists
 * to stop the same lab item being billed twice.
 */
import { api } from "@/lib/api";
import { DEFAULT_CURRENCY, type Money } from "../lib/money";
import type {
  InvoiceListFilters,
  PaymentWithRefunds,
  InvoiceWithItems,
  Paginated,
} from "../types";

/**
 * Wire money -> view money.
 *
 * The API sends a bare decimal string ("500.00") — see lib/api.ts: "Money
 * always arrives as a string. Never parseFloat it." The billing UI models money
 * as { amount, currency }, which the fixture produced and the server never has.
 *
 * Adapted here, at the boundary, rather than by retyping every billing
 * component: invoices carry no currency column server-side at all, so the
 * currency is the facility's and is filled in once, in one place. If the schema
 * ever gains a per-invoice currency, this is the only line that changes.
 */
function money(wire: string): Money {
  return { amount: wire, currency: DEFAULT_CURRENCY };
}

/** The wire shape of GET /billing/invoices rows. */
interface InvoiceListRow {
  id: string;
  invoice_number: string;
  visit_id: string;
  patient_id: string;
  patient_full_name: string;
  patient_identifier: string;
  status: InvoiceWithItems["status"];
  gross_amount: string;
  net_amount: string;
  scheme_code: string | null;
  row_version: number;
  created_at: string;
}

/** The wire shape of GET /billing/invoices/{id} — lines, receipts and balance. */
export interface InvoiceDetail extends InvoiceListRow {
  facility_id: string;
  discount_amount: string;
  scheme_adjustment: string;
  lines: InvoiceWithItems["items"];
  /** Receipts with their reversals nested — refunds used to be write-only. */
  payments: PaymentWithRefunds[];
  total_paid: string;
  total_refunded: string;
  balance_due: string;
}

function toInvoiceWithItems(detail: InvoiceDetail): InvoiceWithItems {
  return {
    id: detail.id,
    invoice_number: detail.invoice_number,
    visit_id: detail.visit_id,
    patient_id: detail.patient_id,
    facility_id: detail.facility_id,
    status: detail.status,
    gross_amount: money(detail.gross_amount),
    discount_amount: money(detail.discount_amount),
    scheme_adjustment: money(detail.scheme_adjustment),
    net_amount: money(detail.net_amount),
    scheme_code: detail.scheme_code,
    sensitivity: "critical",
    row_version: detail.row_version,
    created_at: detail.created_at,
    updated_at: detail.created_at,
    items: detail.lines,
    payments: detail.payments,
    patient: {
      uhid: detail.patient_identifier,
      full_name: detail.patient_full_name,
    },
  };
}

/**
 * GET /billing/invoices — facility-scoped, server-side.
 *
 * Search, status and paging are applied server-side, including the total.
 */
export async function listInvoices(
  filters: InvoiceListFilters = {},
): Promise<Paginated<InvoiceWithItems>> {
  const params = new URLSearchParams();
  params.set("page", String(filters.page ?? 1));
  params.set("page_size", String(Math.min(filters.page_size ?? 20, 100)));
  if (filters.status && filters.status !== "all") params.set("status", filters.status);
  if (filters.query?.trim()) params.set("q", filters.query.trim());

  const page = await api<{
    items: InvoiceListRow[];
    page: number;
    page_size: number;
    total: number;
  }>(`/billing/invoices?${params.toString()}`);

  return {
    page: page.page,
    page_size: page.page_size,
    total: page.total,
    // List rows carry no lines or payments — the endpoint does not join them
    // per row, deliberately. Open one to get them.
    items: page.items.map((r) => ({
      ...toInvoiceWithItems({
        ...r,
        facility_id: "",
        discount_amount: "0",
        scheme_adjustment: "0",
        lines: [],
        payments: [],
        total_paid: "0",
        total_refunded: "0",
        balance_due: r.net_amount,
      }),
    })),
  };
}

/** GET /billing/invoices/{id} — the invoice with its lines, receipts and balance. */
export async function getInvoice(invoiceId: string): Promise<InvoiceWithItems> {
  const detail = await api<InvoiceDetail>(`/billing/invoices/${invoiceId}`);
  return toInvoiceWithItems(detail);
}

/** The raw detail, when the caller needs balance_due / total_paid as well. */
export function getInvoiceDetail(invoiceId: string): Promise<InvoiceDetail> {
  return api<InvoiceDetail>(`/billing/invoices/${invoiceId}`);
}

/**
 * POST /billing/invoices/{id}/issue — makes a draft payable and freezes it.
 *
 * If-Match carries the row_version read from the invoice, and the server
 * requires it. Departments append charge lines to a draft as work completes, so
 * a stale client would otherwise freeze an invoice that is missing a line added
 * since it loaded — unbillable revenue, and not amendable afterwards.
 */
export async function issueInvoice(
  invoiceId: string,
  rowVersion: number,
): Promise<InvoiceWithItems> {
  const issued = await api<InvoiceListRow>(`/billing/invoices/${invoiceId}/issue`, {
    method: "POST",
    ifMatch: rowVersion,
    idempotencyKey: null, // the row_version check is the concurrency guard
  });
  return getInvoice(issued.id);
}
