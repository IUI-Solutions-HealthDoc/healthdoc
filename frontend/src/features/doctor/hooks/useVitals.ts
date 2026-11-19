"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import type { VitalRecord } from "@/components/VitalsTimeline/VitalsTimeline.types";
import { getPatientVitals } from "@/features/nurse/api/nursing";

import { toast } from "@/components/ui/toast";
import { newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { saveVitals } from "../api";
import { computeBmi, computeWhr } from "../lib/formatters";
import type { ActiveEncounter, VitalsInput } from "../types";

export interface VitalsForm {
  temp_c: string;
  pulse_bpm: string;
  resp_rate: string;
  bp_systolic: string;
  bp_diastolic: string;
  spo2_pct: string;
  height_cm: string;
  weight_kg: string;
  waist_cm: string;
  hip_cm: string;
  pain_score: string;
}

const EMPTY: VitalsForm = {
  temp_c: "",
  pulse_bpm: "",
  resp_rate: "",
  bp_systolic: "",
  bp_diastolic: "",
  spo2_pct: "",
  height_cm: "",
  weight_kg: "",
  waist_cm: "",
  hip_cm: "",
  pain_score: "",
};

/**
 * The server's accepted ranges (nursing/schemas.py VitalsCreate), checked
 * before sending so the field itself is marked: 4567 °C or a pulse of 456789
 * reached the server and came back as an unhighlighted generic error
 * (QA 17 Oct 2026).
 */
export const VITAL_RANGES: Record<keyof VitalsForm, [number, number]> = {
  temp_c: [20, 45],
  pulse_bpm: [0, 350],
  resp_rate: [0, 120],
  spo2_pct: [0, 100],
  bp_systolic: [0, 350],
  bp_diastolic: [0, 250],
  pain_score: [0, 10],
  height_cm: [0, 300],
  weight_kg: [0, 700],
  waist_cm: [0, 300],
  hip_cm: [0, 300],
};

export function vitalErrors(form: VitalsForm): Partial<Record<keyof VitalsForm, string>> {
  const errors: Partial<Record<keyof VitalsForm, string>> = {};
  for (const key of Object.keys(VITAL_RANGES) as (keyof VitalsForm)[]) {
    const raw = form[key].trim();
    if (!raw) continue;
    const value = Number(raw);
    const [low, high] = VITAL_RANGES[key];
    if (!Number.isFinite(value) || value < low || value > high) errors[key] = `${low}–${high}`;
  }
  const sys = Number(form.bp_systolic), dia = Number(form.bp_diastolic);
  if (form.bp_systolic.trim() && form.bp_diastolic.trim() && !errors.bp_systolic && !errors.bp_diastolic && dia >= sys) {
    errors.bp_diastolic = "< systolic";
  }
  return errors;
}

function num(v: string): number | undefined {
  if (v.trim() === "") return undefined;
  const n = Number(v);
  return Number.isFinite(n) ? n : undefined;
}

export function useVitals(encounter: ActiveEncounter) {
  const { t } = useLocale();
  const [form, setForm] = useState<VitalsForm>(EMPTY);
  const [saving, setSaving] = useState(false);
  const [idempotencyKey, setIdempotencyKey] = useState(() => newIdempotencyKey());
  // What has been recorded: the form clears after a save, so without this the
  // saved values were shown nowhere (QA 12 Oct 2026).
  const [history, setHistory] = useState<VitalRecord[] | null>(null);
  const [historyFailed, setHistoryFailed] = useState(false);
  const [tried, setTried] = useState(false);
  const errors = useMemo(() => vitalErrors(form), [form]);

  const loadHistory = useCallback(async () => {
    try {
      const rows = await getPatientVitals(encounter.patient_id);
      setHistory([...rows].sort((a, b) => b.measured_at.localeCompare(a.measured_at)));
      setHistoryFailed(false);
    } catch {
      setHistoryFailed(true);
    }
  }, [encounter.patient_id]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const setField = useCallback(
    (field: keyof VitalsForm, value: string) => setForm((f) => ({ ...f, [field]: value })),
    [],
  );

  const bmi = useMemo(() => computeBmi(num(form.height_cm), num(form.weight_kg)), [form.height_cm, form.weight_kg]);
  const whr = useMemo(() => computeWhr(num(form.waist_cm), num(form.hip_cm)), [form.waist_cm, form.hip_cm]);
  const anyEntered = useMemo(() => Object.values(form).some((v) => v.trim() !== ""), [form]);

  const record = useCallback(async () => {
    if (!anyEntered) {
      toast.error(t("doctor.toast.enterOneVital"));
      return;
    }
    if (Object.keys(vitalErrors(form)).length) {
      setTried(true);
      toast.error(t("doctor.toast.vitalsOutOfRange"));
      return;
    }
    setSaving(true);
    // bmi/whr omitted — server computes them on write (never client-supplied).
    const input: VitalsInput = {
      patient_id: encounter.patient_id,
      encounter_id: encounter.id,
      measured_at: new Date().toISOString(),
      temp_c: num(form.temp_c),
      pulse_bpm: num(form.pulse_bpm),
      resp_rate: num(form.resp_rate),
      bp_systolic: num(form.bp_systolic),
      bp_diastolic: num(form.bp_diastolic),
      spo2_pct: num(form.spo2_pct),
      height_cm: num(form.height_cm),
      weight_kg: num(form.weight_kg),
      waist_cm: num(form.waist_cm),
      hip_cm: num(form.hip_cm),
      pain_score: num(form.pain_score),
    };
    try {
      await saveVitals(input, idempotencyKey);
      setForm(EMPTY);
      setTried(false);
      setIdempotencyKey(newIdempotencyKey());
      toast.success(t("doctor.toast.vitalsRecorded"));
      void loadHistory();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("doctor.toast.recordVitalsFailed"));
    } finally {
      setSaving(false);
    }
  }, [anyEntered, encounter, form, idempotencyKey, t, loadHistory]);

  // Out-of-range fields are marked as soon as they are typed, not only after Record.
  return { form, setField, bmi, whr, anyEntered, saving, record, history, historyFailed, errors, tried };
}
