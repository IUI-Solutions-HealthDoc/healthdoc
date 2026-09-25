"use client";

import { useEffect, useState } from "react";

import { listQueue } from "../api";
import type { EncounterContext, QueueToken } from "../types";

/**
 * The patient the doctor is currently consulting, from their own queue.
 *
 * Replaces `mockEncounterContext` (P1.1), which was a fixed fictional patient.
 * Every order and prescription raised from the standalone /doctor/orders and
 * /doctor/prescriptions pages would have been filed against that same invented
 * visit — the mock did not just supply display text, it supplied the
 * `visit_id` and `patient_id` the writes are attached to.
 *
 * There is no id in either route's path, so "which patient" has to come from
 * somewhere. It comes from the doctor's own worklist: the token currently
 * `in_service` is, by definition, the consultation they are in.
 *
 * Returns null when no token is in service. The screens must render an empty
 * state rather than fall back to anything — a prescribing screen that guesses
 * its patient is the failure this replaces, not a milder version of it.
 */
export function useEncounterContext(): {
  context: EncounterContext | null;
  loading: boolean;
  error: string | null;
} {
  const [context, setContext] = useState<EncounterContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);

    listQueue()
      .then((tokens: QueueToken[]) => {
        if (cancelled) return;
        // in_service is the one being seen now. `called` is next up but not yet
        // in the room, and charting against it would attribute an order to a
        // patient who has not been examined.
        const active = tokens.find((t) => t.status === "in_service") ?? null;
        setContext(active ? toContext(active) : null);
        // toContext returns null for a token missing provider or department —
        // see below.
        setError(null);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setContext(null);
        setError(e instanceof Error ? e.message : "Could not load your queue");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return { context, loading, error };
}

/**
 * A worklist row only forms a context if it carries the provider and
 * department. Those are optional on QueueToken (a plain queue row has no
 * provider join) and required on EncounterContext, so a token without them
 * cannot be charted against. Returns null rather than substituting placeholder
 * strings — an order attributed to "" is worse than an order refused.
 */
function toContext(token: QueueToken): EncounterContext | null {
  if (!token.provider_user_id || !token.provider_name || !token.department) {
    return null;
  }
  return {
    visit_id: token.visit_id,
    patient_id: token.patient_id,
    patient_name: token.full_name,
    uhid: token.uhid,
    age_years: token.age_years,
    sex: token.sex,
    provider_user_id: token.provider_user_id,
    provider_name: token.provider_name,
    department: token.department,
    department_hi: token.department_hi ?? null,
    token_display: token.token_display,
  };
}
