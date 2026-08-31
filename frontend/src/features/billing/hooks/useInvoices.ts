"use client";

import { useCallback, useEffect, useState } from "react";

import { listInvoices } from "../api";
import type { InvoiceListFilters, InvoiceStatus, InvoiceWithItems } from "../types";

export function useInvoices(initial: InvoiceListFilters = { status: "all" }) {
  const [filters, setFilters] = useState<InvoiceListFilters>(initial);
  const [invoices, setInvoices] = useState<InvoiceWithItems[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { items } = await listInvoices(filters);
      setInvoices(items);
    } catch (e) {
      setInvoices([]);
      setError(e instanceof Error ? e.message : "Failed to load invoices");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const setQuery = (query: string) => setFilters((f) => ({ ...f, query }));
  const setStatus = (status: InvoiceStatus | "all") =>
    setFilters((f) => ({ ...f, status }));

  return {
    invoices,
    loading,
    error,
    filters,
    setQuery,
    setStatus,
    refresh,
  };
}
