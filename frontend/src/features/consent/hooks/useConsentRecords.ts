"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { listConsentRecords } from "../api";
import type { ConsentListFilters, ConsentRecord, ConsentStatus } from "../types";

export function useConsentRecords(initial: ConsentListFilters = { status: "all" }) {
  const [filters, setFilters] = useState<ConsentListFilters>(initial);
  const [rows, setRows] = useState<ConsentRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const activeReqRef = useRef(0);
  const [prevPatientId, setPrevPatientId] = useState(initial.patient_id);

  // Synchronously clear rows and increment request counter during render when
  // patient_id changes so Patient A's rows never flash on Patient B's initial frame.
  if (initial.patient_id !== prevPatientId) {
    setPrevPatientId(initial.patient_id);
    setRows([]);
    setError(null);
    setLoading(true);
    activeReqRef.current += 1;
    setFilters((current) => ({ ...current, patient_id: initial.patient_id }));
  }

  const refresh = useCallback(async () => {
    const reqId = ++activeReqRef.current;
    const targetPatientId = filters.patient_id;
    setLoading(true);
    setError(null);
    try {
      const data = await listConsentRecords(filters);
      if (reqId === activeReqRef.current && filters.patient_id === targetPatientId) {
        setRows(data);
      }
    } catch (e) {
      if (reqId === activeReqRef.current && filters.patient_id === targetPatientId) {
        setRows([]);
        setError(e instanceof Error ? e.message : "Failed to load consents");
      }
    } finally {
      if (reqId === activeReqRef.current && filters.patient_id === targetPatientId) {
        setLoading(false);
      }
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
