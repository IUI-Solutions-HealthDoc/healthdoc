"use client";

import { useCallback, useEffect, useState } from "react";

import { listQueue } from "../api";
import type { QueueToken } from "../types";
import { translate } from "@/lib/i18n";

export function useDoctorQueue() {
  const [patients, setPatients] = useState<QueueToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<QueueToken | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPatients(await listQueue());
    } catch (e) {
      setError(e instanceof Error ? e.message : translate("doctor.msg.failedToLoadQueue"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { patients, loading, error, refresh, selected, select: setSelected };
}
