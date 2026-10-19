import { z } from "zod";
import { translate } from "@/lib/i18n";

/** Plain calendar dates only: no UTC conversion of a clinician's date input. */
export function externalResultSchema(today: string) {
  return z.object({
    provider_name: z.string().trim().max(500, { error: () => translate("doctor.msg.useAtMost500Characters") }).transform((v) => v || null),
    summary: z.string().trim().min(1, { error: () => translate("doctor.msg.enterTheOutsideResultSummary") }).max(10000, { error: () => translate("doctor.msg.useAtMost10000Characters") }),
    observed_on: z.string().refine((v) => !v || (
      /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(v)) &&
      new Date(v).toISOString().slice(0, 10) === v && v <= today
    ), { error: () => translate("doctor.msg.enterAValidDateThatIs") }).transform((v) => v || null),
  });
}
