/**
 * Payments and refunds. Retired from fixtures (P1.1).
 *
 * There is no GET /billing/payments. There does not need to be: a payment is
 * only ever read in the context of its invoice, and GET /billing/invoices/{id}
 * already returns the receipts and the balance alongside the lines. Adding a
 * standalone list would mean a second implementation of the balance
 * arithmetic, and the number on screen is the one a patient is asked to settle.
 */
import { api, newIdempotencyKey } from "@/lib/api";
import { DEFAULT_CURRENCY } from "../lib/money";
import type {
  CollectPaymentInput,
  CreateRefundInput,
  InvoiceBalance,
  Payment,
  PaymentWithRefunds,
  Refund,
} from "../types";
import { getInvoiceDetail } from "./invoices";

/** Receipts against one invoice, each with its reversals, from the invoice read. */
export async function listPayments(invoiceId: string): Promise<PaymentWithRefunds[]> {
  const detail = await getInvoiceDetail(invoiceId);
  return detail.payments;
}

/** One receipt. Narrowed from the invoice rather than fetched by id — there is
 *  no by-id endpoint, and a payment outside its invoice has no useful meaning. */
export async function getPayment(
  invoiceId: string,
  paymentId: string,
): Promise<PaymentWithRefunds | null> {
  const payments = await listPayments(invoiceId);
  return payments.find((p) => p.id === paymentId) ?? null;
}

/**
 * What is still owed.
 *
 * Server-computed: `balance_due = net_amount - (successful payments - refunds)`,
 * from the same helper `record_payment` uses to decide whether the invoice is
 * now partially_paid or paid. Deliberately not recomputed here — two versions
 * of that arithmetic would eventually disagree.
 */
export async function getInvoiceBalance(invoiceId: string): Promise<InvoiceBalance> {
  const detail = await getInvoiceDetail(invoiceId);
  const money = (wire: string) => ({ amount: wire, currency: DEFAULT_CURRENCY });
  return {
    net_amount: money(detail.net_amount),
    paid_total: money(detail.total_paid),
    refunded_total: money(detail.total_refunded),
    balance_due: money(detail.balance_due),
  };
}

/**
 * POST /billing/invoices/{id}/payments.
 *
 * Idempotency-Key is mandatory server-side (§4A.1) and generated per attempt:
 * a retried request replays the stored receipt instead of taking the money
 * twice. The invoice must be `issued` or `partially_paid` — a draft is refused
 * 409, because payment against a still-editable invoice defeats the freeze.
 */
export function collectPayment(
  invoiceId: string,
  input: CollectPaymentInput,
): Promise<Payment> {
  return api<Payment>(`/billing/invoices/${invoiceId}/payments`, {
    method: "POST",
    body: JSON.stringify(input),
    idempotencyKey: newIdempotencyKey(),
  });
}

/**
 * POST /billing/payments/{payment_id}/refunds — supervisor/admin only.
 *
 * Refunds are a reversal ledger, not an edit: the payment row stays exactly as
 * recorded and a refund row is added against it. That is why there is no
 * payment update endpoint anywhere.
 */
export function createRefund(
  paymentId: string,
  input: CreateRefundInput,
): Promise<Refund> {
  return api<Refund>(`/billing/payments/${paymentId}/refunds`, {
    method: "POST",
    body: JSON.stringify(input),
    idempotencyKey: newIdempotencyKey(),
  });
}
