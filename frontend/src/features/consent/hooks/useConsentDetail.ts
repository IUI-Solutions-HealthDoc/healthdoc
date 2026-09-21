"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { getConsent } from "../api";
import type { ConsentRecord } from "../types";

/**
 * One consent record.
 *
 * Takes the patient id as well: the endpoint is
 * GET /consent/patients/{patient_id}/records/{consent_id} — consent_records has
 * no facility_id of its own and is scoped through the patient, so the patient
 * is part of the address rather than a convenience.
 */
export function useConsentDetail(patientId: string | null, id: string | null) {
  const [record, setRecord] = useState<ConsentRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const contextRef = useRef({ patientId, id });
  if (contextRef.current.patientId !== patientId || contextRef.current.id !== id) contextRef.current = { patientId, id };
  const context = contextRef.current;
  const requestRef = useRef(0);

  const [prevId, setPrevId] = useState(id);
  const [prevPatientId, setPrevPatientId] = useState(patientId);

  // Synchronously reset record during render when id or patientId changes
  // so the previous record never flashes while fetching the new one.
  if (id !== prevId || patientId !== prevPatientId) {
    setPrevId(id);
    setPrevPatientId(patientId);
    setRecord(null);
    setError(null);
  }

  const load = useCallback(async () => {
    if (contextRef.current !== context) return;
    const request = ++requestRef.current;
    const current = context.id;
    if (!current || !patientId) {
      setRecord(null);
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const row = await getConsent(patientId, current);
      if (contextRef.current === context && requestRef.current === request) setRecord(row);
    } catch (reason) {
      if (contextRef.current === context && requestRef.current === request) {
        setRecord(null);
        setError(reason instanceof Error ? reason.message : "Failed to load consent details");
      }
    } finally {
      if (contextRef.current === context && requestRef.current === request) setLoading(false);
    }
  }, [patientId, context]);

  useEffect(() => {
    void load();
  }, [id, patientId, load]);

  return { record: id === prevId && patientId === prevPatientId ? record : null, loading, error, refresh: load };
}
