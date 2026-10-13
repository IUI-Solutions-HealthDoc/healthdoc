import { z } from "zod";

export const addProcedureAssistanceSchema = z.object({
  encounter_id: z.string().min(1),
  patient_id: z.string().min(1),

  procedure_name: z.string().min(2),

  procedure_code: z.string().optional(),
  code_system: z.string().optional(),

  setting: z.enum(["opd_minor", "bedside", "emergency", "ot"]),

  ot_schedule_id: z.string().optional(),

  performed_by: z.guid(),
  assisted_by: z.guid().optional(),

  started_at: z.string().min(1),
  ended_at: z.string().optional(),

  outcome: z.string().optional(),
  complications: z.string().optional(),
});

export type AddProcedureAssistanceSchema = z.infer<
  typeof addProcedureAssistanceSchema
>;