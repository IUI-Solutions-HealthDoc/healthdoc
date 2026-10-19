import { z } from "zod";
import { translate } from "@/lib/i18n";

export const addVitalsSchema = z
  .object({
    patient_id: z.string().trim().min(1, { error: () => translate("nurse.msg.patientIsRequired") }),
    encounter_id: z.string().optional(),
    admission_id: z.string().optional(),

    measured_at: z.string().min(1),

    height_cm: z.number().positive({ error: () => translate("nurse.msg.heightMustBeGreaterThan0") }).optional(),
    weight_kg: z.number().positive({ error: () => translate("nurse.msg.weightMustBeGreaterThan0") }).optional(),
    waist_cm: z.number().positive().optional(),
    hip_cm: z.number().positive().optional(),

    temp_c: z
      .number()
      .min(30, { error: () => translate("nurse.msg.temperatureMustBeAtLeast30") })
      .max(45, { error: () => translate("nurse.msg.temperatureCannotExceed45C") })
      .optional(),

    pulse_bpm: z
      .number()
      .int()
      .min(30, { error: () => translate("nurse.msg.pulseMustBeAtLeast30") })
      .max(220, { error: () => translate("nurse.msg.pulseCannotExceed220Bpm") })
      .optional(),

    resp_rate: z
      .number()
      .int()
      .min(5, { error: () => translate("nurse.msg.respiratoryRateMustBeAtLeast") })
      .max(60, { error: () => translate("nurse.msg.respiratoryRateCannotExceed60") })
      .optional(),

    bp_systolic: z
      .number()
      .int()
      .min(50, { error: () => translate("nurse.msg.systolicBpMustBeAtLeast") })
      .max(250, { error: () => translate("nurse.msg.systolicBpCannotExceed250") })
      .optional(),

    bp_diastolic: z
      .number()
      .int()
      .min(30, { error: () => translate("nurse.msg.diastolicBpMustBeAtLeast") })
      .max(150, { error: () => translate("nurse.msg.diastolicBpCannotExceed150") })
      .optional(),

    spo2_pct: z
      .number()
      .min(50, "SpO₂ must be at least 50%")
      .max(100, "SpO₂ cannot exceed 100%")
      .optional(),

    pain_score: z
      .number()
      .int()
      .min(0, { error: () => translate("nurse.msg.painScoreMustBeBetween0") })
      .max(10, { error: () => translate("nurse.msg.painScoreMustBeBetween0") })
      .optional(),
  })
  .refine((data) => !!data.encounter_id || !!data.admission_id, {
    error: () => translate("nurse.msg.vitalsMustBeLinkedToEither"),
    path: ["admission_id"],
  });

export type AddVitalsSchema = z.infer<typeof addVitalsSchema>;
