"use client";

import { useCallback, useEffect, useState } from "react";

import { listKpis } from "../api";
import type { KpiPeriod, KpiSnapshot } from "../types";

export function useKpis(initialPeriod: KpiPeriod = "7d") {
  const [period, setPeriod] = useState<KpiPeriod>(initialPeriod);
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [items, setItems] = useState<KpiSnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (period === "custom" && (!customFrom || !customTo)) return;
    if (period === "custom" && customFrom > customTo) {
      setError("The From date must be on or before the To date.");
      setItems([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await listKpis(period, customFrom || undefined, customTo || undefined);
      setItems(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load KPIs");
    } finally {
      setLoading(false);
    }
  }, [period, customFrom, customTo]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return {
    items,
    loading,
    error,
    period,
    setPeriod,
    customFrom,
    customTo,
    setCustomFrom,
    setCustomTo,
    refresh,
  };
}
