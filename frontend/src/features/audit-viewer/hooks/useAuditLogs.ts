"use client";

import { useCallback, useEffect, useState } from "react";

import { listAuditLogs } from "../api";
import type { AuditLog, AuditLogFilters } from "../types";

export function useAuditLogs(initial: AuditLogFilters = { action: "all", resource_type: "all" }) {
  const [filters, setFilters] = useState<AuditLogFilters>(initial);
  const [rows, setRows] = useState<AuditLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (filters.from && filters.to && filters.from > filters.to) {
      setRows([]);
      setError("The From date must be on or before the To date.");
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setRows((await listAuditLogs(filters)).items);
    } catch (e) {
      setRows([]);
      setError(e instanceof Error ? e.message : "Failed to load audit logs");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return {
    rows,
    loading,
    error,
    filters,
    setQuery: (query: string) => setFilters((f) => ({ ...f, query })),
    setAction: (action: string) => setFilters((f) => ({ ...f, action })),
    setResourceType: (resource_type: string) => setFilters((f) => ({ ...f, resource_type })),
    setFrom: (from: string) => setFilters((f) => ({ ...f, from: from || undefined })),
    setTo: (to: string) => setFilters((f) => ({ ...f, to: to || undefined })),
    refresh,
  };
}
