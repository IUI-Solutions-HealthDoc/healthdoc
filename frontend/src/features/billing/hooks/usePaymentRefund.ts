"use client";

import { useCallback, useState } from "react";

import { createRefund } from "../api";
import { toast } from "@/components/ui/toast";
import type { CreateRefundInput, Refund } from "../types";
import { translate } from "@/lib/i18n";

export function usePaymentRefund(
  paymentId: string | null,
  /** The refund alone. The caller re-reads the invoice — the balance moves
   *  server-side and must not be reconstructed client-side. */
  onSaved?: (refund: Refund) => void,
) {
  const [busy, setBusy] = useState(false);

  const submit = useCallback(
    async (body: CreateRefundInput) => {
      if (!paymentId) return;
      setBusy(true);
      try {
        // The endpoint returns the refund alone. The fixture returned
        // { refund, payment, invoice }; the balance moves server-side, so the
        // caller re-reads rather than being handed a reconstructed invoice.
        const refund = await createRefund(paymentId, body);
        toast.success(translate("billing.msg.paymentReversed"), refund.refund_number);
        onSaved?.(refund);
        return refund;
      } catch (e) {
        toast.error(e instanceof Error ? e.message : translate("billing.msg.reversalFailed"));
        throw e;
      } finally {
        setBusy(false);
      }
    },
    [onSaved, paymentId],
  );

  return { submit, busy };
}
