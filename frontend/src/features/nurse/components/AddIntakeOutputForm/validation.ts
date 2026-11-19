import { z } from "zod";
import { translate } from "@/lib/i18n";

export const addIntakeOutputSchema = z.object({
  admission_id: z.guid(),
  recorded_at: z
    .string()
    .min(1, { error: () => translate("nurse.msg.recordedTimeIsRequired") })
    .refine((val) => !isNaN(Date.parse(val)), { error: () => translate("nurse.msg.enterAValidDateAndTime") })
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
    .int({ error: () => translate("nurse.msg.volumeMustBeAWholeNumber") })
    .positive({ error: () => translate("nurse.msg.volumeMustBeGreaterThan0") }),

  notes: z.string().max(500).optional(),
});

export type AddIntakeOutputSchema = z.infer<typeof addIntakeOutputSchema>;