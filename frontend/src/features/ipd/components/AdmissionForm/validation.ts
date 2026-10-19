import { z } from "zod";
import { translate } from "@/lib/i18n";

export const addAdmissionSchema = z.object({
  visit_id: z.guid({ error: () => translate("ipd.msg.chooseThePatientToAdmit") }),
  ward_id: z.guid({ error: () => translate("ipd.msg.selectAWard") }),
  bed_id: z.guid({ error: () => translate("ipd.msg.selectABed") }),
  admitted_at: z.string().min(1, { error: () => translate("ipd.msg.enterTheAdmissionDateAndTime") }),
  reason: z.string().optional(),
});

export type AddAdmissionSchema = z.infer<typeof addAdmissionSchema>;