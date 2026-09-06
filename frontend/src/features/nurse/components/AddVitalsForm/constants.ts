/** `datetime-local` wants local wall-clock, not the UTC that toISOString gives. */
export function nowForDateTimeLocal(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16);
}

export const DEFAULT_VALUES = {
  patient_id: "",
  // Callers override this with nowForDateTimeLocal() when they build or reset
  // the form. It is NOT defaulted here: this object is module-level, so a call
  // at this line would freeze the timestamp at page load and a ward dashboard
  // left open for a shift would stamp every observation with the same time.
  measured_at: "",
  encounter_id: undefined,
  admission_id: undefined,
  height_cm: undefined,
  weight_kg: undefined,
  waist_cm: undefined,
  hip_cm: undefined,
  temp_c: undefined,
  pulse_bpm: undefined,
  resp_rate: undefined,
  bp_systolic: undefined,
  bp_diastolic: undefined,
  spo2_pct: undefined,
  pain_score: undefined,
};

export const PAIN_SCORE_OPTIONS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
