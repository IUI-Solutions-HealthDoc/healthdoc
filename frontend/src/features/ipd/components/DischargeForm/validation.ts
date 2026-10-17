import { z } from "zod";

export const DISCHARGE_TYPES = [
  "discharged",
  "dama",
  "deceased",
  "absconded",
  "transferred",
] as const;

export const addDischargeSchema = z
  .object({
    admission_id: z.guid("Admission ID must be a UUID"),
    discharged_at: z.string().min(1, "Enter the discharge date and time"),
    discharge_type: z.enum(DISCHARGE_TYPES),
    discharge_summary: z.string().min(1, "Discharge summary is required"),
    // Normalised on the way out, in dischargePatient — see the note there.
    follow_up_date: z.string().optional(),
    // Backend: DischargeRequest.destination_facility_id / destination_facility_name.
    // Required (either one) only when discharge_type === "transferred" —
    // mirrors ck_discharges_transfer_destination.
    destination_facility_id: z.guid().optional(),
    destination_facility_name: z.string().trim().optional(),
    // Set after the server reports open mandatory checklist items and the
    // ward confirms discharging anyway.
    acknowledge_incomplete_checklist: z.boolean().optional(),
  })
  .refine(
    (data) => !data.follow_up_date || !data.discharged_at || data.follow_up_date.slice(0, 10) >= data.discharged_at.slice(0, 10),
    { message: "The follow-up date must be on or after the discharge date", path: ["follow_up_date"] },
  )
  .refine(
    (data) =>
      data.discharge_type !== "transferred" ||
      !!data.destination_facility_id ||
      !!data.destination_facility_name?.length,
    {
      message:
        "Destination facility (ID or name) is required for a transferred discharge",
      path: ["destination_facility_name"],
    },
  );

export type AddDischargeSchema = z.infer<typeof addDischargeSchema>;
export type DischargeType = (typeof DISCHARGE_TYPES)[number];