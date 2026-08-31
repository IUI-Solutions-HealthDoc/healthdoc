"use client";

import { useCallback, useEffect, useState } from "react";

import { listDataAccessLogs } from "../api";
import type { DataAccessLog } from "../types";

export function useDataAccessLogs(consentId: string | null) {
  const [rows, setRows] = useState<DataAccessLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!consentId) {
      setRows([]);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      setRows(await listDataAccessLogs({ consent_id: consentId }));
    } catch (reason) {
      setRows([]);
      setError(reason instanceof Error ? reason.message : "Failed to load access history");
    } finally {
      setLoading(false);
    }
  }, [consentId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { rows, loading, error, refresh };
}
