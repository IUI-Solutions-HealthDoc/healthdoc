"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { listDataAccessLogs } from "../api";
import type { DataAccessLog } from "../types";

export function useDataAccessLogs(consentId: string | null) {
  const [rows, setRows] = useState<DataAccessLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const contextRef = useRef({ consentId });
  if (contextRef.current.consentId !== consentId) contextRef.current = { consentId };
  const context = contextRef.current;
  const [loadedContext, setLoadedContext] = useState(context);
  const sequence = useRef(0);

  const refresh = useCallback(async () => {
    if (contextRef.current !== context) return;
    const request = ++sequence.current;
    const isCurrent = () => contextRef.current === context && sequence.current === request;
    setLoadedContext(context);
    setRows([]);
    if (!consentId) {
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await listDataAccessLogs({ consent_id: consentId });
      if (isCurrent()) setRows(result);
    } catch (reason) {
      if (!isCurrent()) return;
      setRows([]);
      setError(reason instanceof Error ? reason.message : "Failed to load access history");
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [consentId, context]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return {
    rows: loadedContext === context ? rows : [],
    loading: loadedContext !== context || loading,
    error: loadedContext === context ? error : null,
    refresh,
  };
}
