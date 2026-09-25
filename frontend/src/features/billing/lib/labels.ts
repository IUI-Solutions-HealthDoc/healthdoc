import type { MessageKey } from "@/lib/i18n";
import type { ChargeCategory, InvoiceStatus, PaymentMode, PaymentStatus } from "../types";

export type BillingTranslate = (
  key: MessageKey,
  vars?: Record<string, string | number>,
) => string;

export const CHARGE_CATEGORY_KEYS: Record<ChargeCategory, MessageKey> = {
  registration: "billing.category.registration",
  consultation: "billing.category.consultation",
  lab: "billing.category.lab",
  radiology: "billing.category.radiology",
  pharmacy: "billing.category.pharmacy",
  procedure: "billing.category.procedure",
  ipd_stay: "billing.category.ipd_stay",
  blood: "billing.category.blood",
  other: "billing.category.other",
};

export const CHARGE_CATEGORIES = Object.keys(CHARGE_CATEGORY_KEYS) as ChargeCategory[];

export const PAYMENT_MODE_KEYS: Record<PaymentMode, MessageKey> = {
  cash: "billing.paymentMode.cash",
  upi: "billing.paymentMode.upi",
  card: "billing.paymentMode.card",
  netbanking: "billing.paymentMode.netbanking",
};

export const PAYMENT_MODES = Object.keys(PAYMENT_MODE_KEYS) as PaymentMode[];

export const INVOICE_STATUS_KEYS: Record<InvoiceStatus, MessageKey> = {
  draft: "billing.invoiceStatus.draft",
  issued: "billing.invoiceStatus.issued",
  partially_paid: "billing.invoiceStatus.partially_paid",
  paid: "billing.invoiceStatus.paid",
  waived: "billing.invoiceStatus.waived",
  cancelled: "billing.invoiceStatus.cancelled",
};

export const PAYMENT_STATUS_KEYS: Record<PaymentStatus, MessageKey> = {
  success: "billing.paymentStatus.success",
  reversed: "billing.paymentStatus.reversed",
};

export function chargeCategoryLabel(t: BillingTranslate, category: ChargeCategory): string {
  return t(CHARGE_CATEGORY_KEYS[category]);
}

export function paymentModeLabel(t: BillingTranslate, mode: PaymentMode): string {
  return t(PAYMENT_MODE_KEYS[mode]);
}

export function invoiceStatusLabel(t: BillingTranslate, status: InvoiceStatus): string {
  return t(INVOICE_STATUS_KEYS[status]);
}

export function paymentStatusLabel(t: BillingTranslate, status: PaymentStatus): string {
  return t(PAYMENT_STATUS_KEYS[status]);
}
