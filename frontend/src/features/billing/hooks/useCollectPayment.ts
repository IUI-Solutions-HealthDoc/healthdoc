"use client";

import { useCallback, useState } from "react";

import { collectPayment, getInvoice } from "../api";
import { getActionableErrorMessage } from "../lib/errors";
import { toast } from "@/components/ui/toast";
import type { CollectPaymentInput, InvoiceWithItems, Payment } from "../types";
import { translate } from "@/lib/i18n";

export function useCollectPayment(
  invoiceId: string | null,
  onSaved?: (invoice: InvoiceWithItems, payment: Payment) => void,
) {
  const [busy, setBusy] = useState(false);

  const submit = useCallback(
    async (body: CollectPaymentInput) => {
      if (!invoiceId) return;
      setBusy(true);
      try {
        // The endpoint returns the receipt alone; the fixture returned
        // { payment, invoice }. Re-read the invoice rather than reconstructing
        // it — status and balance move server-side when a payment lands
        // (issued -> partially_paid -> paid) and the client must not guess
        // which.
        const payment = await collectPayment(invoiceId, body);
        const invoice = await getInvoice(invoiceId);
        toast.success(translate("billing.msg.paymentCollected"), payment.receipt_number);
        onSaved?.(invoice, payment);
        return { payment, invoice };
      } catch (e) {
        toast.error(getActionableErrorMessage(e, translate("billing.collect.paymentFailed")));
        throw e;
      } finally {
        setBusy(false);
      }
    },
    [invoiceId, onSaved],
  );

  return { submit, busy };
}
