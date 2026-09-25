"use client";

import { StatusChip } from "@/components/ui/StatusChip";
import { useLocale } from "@/lib/i18n";
import { invoiceStatusLabel } from "../lib/labels";
import type { InvoiceStatus } from "../types";

export function InvoiceStatusChip({ status }: { status: InvoiceStatus }) {
  const { t } = useLocale();
  return <StatusChip status={status} label={invoiceStatusLabel(t, status)} />;
}
