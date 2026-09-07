"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { listInvoices } from "../api";
import type { InvoiceListFilters, InvoiceStatus, InvoiceWithItems } from "../types";

export function useInvoices(initial: InvoiceListFilters = { status: "all" }) {
  const [filters, setFilters] = useState<InvoiceListFilters>(initial);
  const [invoices, setInvoices] = useState<InvoiceWithItems[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const requestSequence = useRef(0);
  const invalidateRequests = useCallback(() => { requestSequence.current++; }, []);

  const refresh = useCallback(async () => {
    const sequence = ++requestSequence.current;
    setLoading(true);
    setError(null);
    try {
      const { items, total } = await listInvoices(filters);
      if (sequence !== requestSequence.current) return;
      setInvoices(items);
      setTotal(total);
    } catch (e) {
      if (sequence !== requestSequence.current) return;
      setInvoices([]);
      setTotal(0);
      setError(e instanceof Error ? e.message : "Failed to load invoices");
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    const timer = setTimeout(() => void refresh(), 200);
    return () => { clearTimeout(timer); invalidateRequests(); };
  }, [refresh, invalidateRequests]);

  const setQuery = (query: string) => setFilters((f) => ({ ...f, query, page: 1 }));
  const setStatus = (status: InvoiceStatus | "all") =>
    setFilters((f) => ({ ...f, status, page: 1 }));
  const setPage = (page: number) => setFilters((f) => ({ ...f, page }));

  return {
    invoices,
    loading,
    error,
    filters,
    total,
    setPage,
    setQuery,
    setStatus,
    refresh,
  };
}
