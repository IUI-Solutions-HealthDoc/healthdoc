import { z } from "zod";
import { translate } from "@/lib/i18n";

export const addPatientMovementSchema = z.object({
  admission_id: z.string().min(1),
  to_ward_id: z.string().min(1, { error: () => translate("common.msg.selectADestinationWard") }),
  to_bed_id: z.string().min(1, { error: () => translate("common.msg.selectADestinationBed") }),
  reason: z.string().optional(),
});

export type AddPatientMovementSchema = z.infer<typeof addPatientMovementSchema>;
