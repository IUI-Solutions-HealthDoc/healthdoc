"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { getInvoiceBalance, listPayments } from "../api";
import { balanceDue, paidTotal } from "../lib/calculations";
import { moneyZero } from "../lib/money";
import type { InvoiceBalance, PaymentWithRefunds } from "../types";

const emptyBalance = (): InvoiceBalance => ({
  net_amount: moneyZero(),
  paid_total: moneyZero(),
  refunded_total: moneyZero(),
  balance_due: moneyZero(),
});

export function useInvoicePayments(invoiceId: string | null) {
  const [payments, setPayments] = useState<PaymentWithRefunds[]>([]);
  const [balance, setBalance] = useState<InvoiceBalance>(emptyBalance);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!invoiceId) {
      setPayments([]);
      setBalance(emptyBalance());
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [rows, bal] = await Promise.all([
        listPayments(invoiceId),
        getInvoiceBalance(invoiceId),
      ]);
      setPayments(rows);
      setBalance(bal);
    } catch (reason) {
      setPayments([]);
      setBalance(emptyBalance());
      setError(reason instanceof Error ? reason.message : "Failed to load payment history");
    } finally {
      setLoading(false);
    }
  }, [invoiceId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const derived = useMemo(() => {
    const flatRefunds = payments.flatMap((p) => p.refunds);
    return {
      paid_total: paidTotal(payments),
      balance_due: balanceDue(balance.net_amount, payments, flatRefunds),
    };
  }, [payments, balance.net_amount]);

  return {
    payments,
    loading,
    error,
    balance,
    paid_total: balance.paid_total ?? derived.paid_total,
    balance_due: balance.balance_due ?? derived.balance_due,
    refunded_total: balance.refunded_total,
    refresh,
  };
}
