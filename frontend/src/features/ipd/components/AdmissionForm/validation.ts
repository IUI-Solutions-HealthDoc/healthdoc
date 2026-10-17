import { z } from "zod";

export const addAdmissionSchema = z.object({
  visit_id: z.guid("Choose the patient to admit"),
  ward_id: z.guid("Select a ward"),
  bed_id: z.guid("Select a bed"),
  admitted_at: z.string().min(1, "Enter the admission date and time"),
  reason: z.string().optional(),
});

export type AddAdmissionSchema = z.infer<typeof addAdmissionSchema>;