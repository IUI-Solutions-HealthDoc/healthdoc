"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getInvoiceDetail } from "../api";
import { DEFAULT_CURRENCY, moneyZero } from "../lib/money";
import type { InvoiceBalance, PaymentWithRefunds } from "../types";

const emptyBalance = (): InvoiceBalance => ({
  net_amount: moneyZero(),
  paid_total: moneyZero(),
  refunded_total: moneyZero(),
  balance_due: moneyZero(),
});

type Snapshot = {
  scope: string;
  payments: PaymentWithRefunds[];
  balance: InvoiceBalance;
  loading: boolean;
  error: string | null;
};

export function useInvoicePayments(invoiceId: string | null, revision = 0) {
  const scope = `${invoiceId ?? "none"}:${revision}`;
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const generation = useRef(0);

  const refresh = useCallback(async () => {
    const request = ++generation.current;
    if (!invoiceId) { setSnapshot(null); return; }
    const initial = { scope, payments: [], balance: emptyBalance(), loading: true, error: null };
    setSnapshot(initial);
    try {
      // One response owns both receipts and their balance. Two independent
      // reads could straddle a payment/refund and disagree with each other.
      const detail = await getInvoiceDetail(invoiceId);
      if (generation.current !== request) return;
      const money = (amount: string) => ({ amount, currency: DEFAULT_CURRENCY });
      setSnapshot({ scope, payments: detail.payments, loading: false, error: null, balance: {
        net_amount: money(detail.net_amount), paid_total: money(detail.total_paid),
        refunded_total: money(detail.total_refunded), balance_due: money(detail.balance_due),
      } });
    } catch (reason) {
      if (generation.current === request) setSnapshot({ ...initial, loading: false,
        error: reason instanceof Error ? reason.message : "Failed to load payment history" });
    }
  }, [invoiceId, scope]);

  useEffect(() => {
    void refresh();
    return () => { generation.current += 1; };
  }, [refresh]);

  // Invalidate during render, before the effect: the old ₹50 balance must
  // not authorize a payment against a newly built ₹463.27 invoice.
  const current = snapshot?.scope === scope ? snapshot : null;
  const balance = current?.balance ?? emptyBalance();

  return {
    payments: current?.payments ?? [],
    loading: Boolean(invoiceId) && (current?.loading ?? true),
    error: current?.error ?? null,
    balance,
    paid_total: balance.paid_total,
    balance_due: balance.balance_due,
    refunded_total: balance.refunded_total,
    refresh,
  };
}
