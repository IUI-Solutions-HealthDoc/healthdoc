import { z } from "zod";

export const addIntakeOutputSchema = z.object({
  admission_id: z.guid(),
  recorded_at: z
    .string()
    .min(1, "Recorded time is required")
    .refine((val) => !isNaN(Date.parse(val)), "Enter a valid date and time")
    .transform((val) => new Date(val).toISOString()),

  entry_type: z.enum([
    "intake_oral",
    "intake_iv",
    "output_urine",
    "output_drain",
    "output_other",
  ]),

  volume_ml: z
    .number()
    .int("Volume must be a whole number (mL)")
    .positive("Volume must be greater than 0"),

  notes: z.string().max(500).optional(),
});

export type AddIntakeOutputSchema = z.infer<typeof addIntakeOutputSchema>;