import { z } from "zod";

/** Plain calendar dates only: no UTC conversion of a clinician's date input. */
export function externalResultSchema(today: string) {
  return z.object({
    provider_name: z.string().trim().max(500, "Use at most 500 characters.").transform((v) => v || null),
    summary: z.string().trim().min(1, "Enter the outside result summary.").max(10000, "Use at most 10,000 characters."),
    observed_on: z.string().refine((v) => !v || (
      /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(v)) &&
      new Date(v).toISOString().slice(0, 10) === v && v <= today
    ), "Enter a valid date that is not in the future.").transform((v) => v || null),
  });
}
