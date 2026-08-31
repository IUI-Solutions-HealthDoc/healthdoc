"use client";

import { useCallback, useEffect, useState } from "react";

import { listFileAccessLogs } from "../api";
import type { FileAccessAction, FileAccessFilters, FileAccessLog } from "../types";

export function useFileAccessLogs(initial: FileAccessFilters = { action: "all" }) {
  const [filters, setFilters] = useState<FileAccessFilters>(initial);
  const [rows, setRows] = useState<FileAccessLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRows(await listFileAccessLogs(filters));
    } catch (reason) {
      setRows([]);
      setError(reason instanceof Error ? reason.message : "Failed to load file access logs");
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
    setAction: (action: FileAccessAction | "all") => setFilters((f) => ({ ...f, action })),
    refresh,
  };
}
