"use client";

import { useCallback, useMemo, useState } from "react";

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
      setIdempotencyKey(newIdempotencyKey());
      toast.success(t("doctor.toast.vitalsRecorded"));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("doctor.toast.recordVitalsFailed"));
    } finally {
      setSaving(false);
    }
  }, [anyEntered, encounter, form, idempotencyKey, t]);

  return { form, setField, bmi, whr, anyEntered, saving, record };
}
