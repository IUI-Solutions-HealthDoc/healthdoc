"use client";

import { useCallback, useEffect, useState } from "react";

import { listDataAccessLogs } from "../api";
import type { AccessChannel, DataAccessFilters, DataAccessLog } from "../types";

export function useDataAccessLogs(
  initial: DataAccessFilters = { access_channel: "all" },
) {
  const [filters, setFilters] = useState<DataAccessFilters>(initial);
  const [rows, setRows] = useState<DataAccessLog[]>([]);
  /** Rows in the loaded page with no patient_id, so not facility-attributable.
   *  Surfaced rather than dropped — see the endpoint's docstring. */
  const [unattributed, setUnattributed] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await listDataAccessLogs(filters);
      setRows(response.items);
      setUnattributed(response.unattributed_in_page);
    } catch (reason) {
      setRows([]);
      setUnattributed(0);
      setError(reason instanceof Error ? reason.message : "Failed to load data access logs");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return {
    rows,
    unattributed,
    loading,
    error,
    filters,
    setQuery: (query: string) => setFilters((f) => ({ ...f, query })),
    setAccessChannel: (access_channel: AccessChannel | "all") =>
      setFilters((f) => ({ ...f, access_channel })),
    refresh,
  };
}
