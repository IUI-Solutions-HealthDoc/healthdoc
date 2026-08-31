"use client";

import { useCallback, useEffect, useState } from "react";

import { listConsentRecords } from "../api";
import type { ConsentListFilters, ConsentRecord, ConsentStatus } from "../types";

export function useConsentRecords(initial: ConsentListFilters = { status: "all" }) {
  const [filters, setFilters] = useState<ConsentListFilters>(initial);
  const [rows, setRows] = useState<ConsentRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // The dashboard starts with no patient and supplies one after the shared
  // patient picker resolves. useState(initial) reads `initial` only once, so
  // without this sync the hook kept patient_id=undefined forever and rendered
  // an honest-looking empty ledger without making the records request at all.
  useEffect(() => {
    setFilters((current) =>
      current.patient_id === initial.patient_id
        ? current
        : { ...current, patient_id: initial.patient_id },
    );
  }, [initial.patient_id]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRows(await listConsentRecords(filters));
    } catch (e) {
      setRows([]);
      setError(e instanceof Error ? e.message : "Failed to load consents");
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
    setStatus: (status: ConsentStatus | "all") => setFilters((f) => ({ ...f, status })),
    refresh,
  };
}
