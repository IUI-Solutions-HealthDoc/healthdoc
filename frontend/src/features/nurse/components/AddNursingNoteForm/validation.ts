import { z } from "zod";
import { translate } from "@/lib/i18n";

export const addNursingNoteSchema = z.object({
  encounter_id: z.string().min(1),
  patient_id: z.string().min(1),

  category: z.string().min(1),

  priority: z.string().min(1),

  note: z
    .string()
    .min(10, { error: () => translate("nurse.msg.noteMustContainAtLeast10") })
    .max(1000),
});

export type AddNursingNoteSchema = z.infer<typeof addNursingNoteSchema>;
