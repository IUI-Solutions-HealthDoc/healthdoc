"use client";

import { useEffect, useState } from "react";

import { getEncounterForVisit } from "../api";
import type { ActiveEncounter, EncounterContext } from "../types";
import { translate } from "@/lib/i18n";

/** Resolve the server-owned encounter used by standalone clinical screens. */
export function usePersistedEncounter(context: EncounterContext): {
  encounter: ActiveEncounter | null;
  loading: boolean;
  error: string | null;
} {
  const [encounter, setEncounter] = useState<ActiveEncounter | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    void getEncounterForVisit(context.visit_id, context.patient_id)
      .then((row) => {
        if (cancelled) return;
        setEncounter(row);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        setEncounter(null);
        setError(cause instanceof Error ? cause.message : translate("doctor.msg.couldNotLoadTheEncounter"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [context.patient_id, context.visit_id]);

  return { encounter, loading, error };
}
