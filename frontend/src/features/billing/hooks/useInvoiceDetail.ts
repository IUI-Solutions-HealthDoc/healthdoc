"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getInvoice } from "../api";
import type { InvoiceWithItems } from "../types";

type Snapshot = {
  invoiceId: string | null;
  invoice: InvoiceWithItems | null;
  loading: boolean;
  error: string | null;
};

export function useInvoiceDetail(invoiceId: string | null) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const generation = useRef(0);
  const activeId = useRef(invoiceId);

  const setInvoice = useCallback((invoice: InvoiceWithItems | null) => {
    if (activeId.current !== invoiceId) return;
    // A mutation's read-back supersedes GETs started before it. Never let an
    // older balance/status arrive later and roll the displayed invoice back.
    generation.current += 1;
    const mismatch = invoice !== null && invoice.id !== invoiceId;
    setSnapshot({ invoiceId, invoice: mismatch ? null : invoice, loading: false,
      error: mismatch ? "The response does not match the selected invoice. Retry loading the invoice." : null });
  }, [invoiceId]);

  const refresh = useCallback(async () => {
    if (activeId.current !== invoiceId) return;
    const request = ++generation.current;
    if (!invoiceId) {
      setSnapshot(null);
      return;
    }
    setSnapshot({ invoiceId, invoice: null, loading: true, error: null });
    try {
      const row = await getInvoice(invoiceId);
      if (generation.current === request) setInvoice(row);
    } catch (e) {
      if (generation.current === request) {
        setSnapshot({ invoiceId, invoice: null, loading: false,
          error: e instanceof Error ? e.message : "Failed to load invoice" });
      }
    }
  }, [invoiceId, setInvoice]);

  useEffect(() => {
    activeId.current = invoiceId;
    void refresh();
    return () => { generation.current += 1; activeId.current = null; };
  }, [invoiceId, refresh]);

  // Hide the old identity during render, not one effect after the selection.
  const current = snapshot?.invoiceId === invoiceId ? snapshot : null;
  return { invoice: current?.invoice ?? null, setInvoice,
    loading: Boolean(invoiceId) && (current?.loading ?? true),
    error: current?.error ?? null, refresh };
}
