"use client";

import { StatusChip } from "@/components/ui/StatusChip";
import { useLocale } from "@/lib/i18n";
import { paymentStatusLabel } from "../lib/labels";
import type { PaymentStatus } from "../types";

export function PaymentStatusChip({ status }: { status: PaymentStatus }) {
  const { t } = useLocale();
  return <StatusChip status={status} label={paymentStatusLabel(t, status)} />;
}
