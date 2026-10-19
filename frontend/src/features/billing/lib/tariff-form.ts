import { z } from "zod";
import { translate } from "@/lib/i18n";

const noControl = (value: string) => [...value].every((character) => character.charCodeAt(0) >= 32 && character.charCodeAt(0) !== 127);
const code = z.string().trim().min(1, { error: () => translate("billing.msg.enterAChargeCode") }).max(30, { error: () => translate("billing.msg.useAtMost30Characters") })
  .refine(noControl, { error: () => translate("billing.msg.controlCharactersAreNotAllowed") });

export const tariffFormSchema = z.object({
  charge_code: code,
  description: z.string().trim().min(1, { error: () => translate("billing.msg.enterADescription") }).refine(noControl, { error: () => translate("billing.msg.controlCharactersAreNotAllowed") }),
  description_hi: z
    .string()
    .trim()
    .max(200)
    .refine(noControl, { error: () => translate("billing.msg.controlCharactersAreNotAllowed") })
    .optional()
    .transform((value) => (value && value.length > 0 ? value : null)),
  charge_category: z.enum(["registration", "consultation", "lab", "radiology", "pharmacy", "procedure", "ipd_stay", "blood", "other"]),
  // Numeric(12,2): validate and normalize strings without binary float rounding.
  unit_price: z.string().trim().regex(/^\d{1,10}(\.\d{1,2})?$/, { error: () => translate("billing.msg.enterANonNegativePriceWith") })
    .transform((value) => {
      const [whole, fraction = ""] = value.split(".");
      return `${whole.replace(/^0+(?=\d)/, "")}.${fraction.padEnd(2, "0")}`;
    }),
  effective_from: z.string().refine((value) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const date = new Date(`${value}T00:00:00Z`);
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
  }, { error: () => translate("billing.msg.enterAValidEffectiveDate") }),
  scheme_code: z.string().trim().max(30, { error: () => translate("billing.msg.useAtMost30Characters") })
    .refine(noControl, { error: () => translate("billing.msg.controlCharactersAreNotAllowed") }).transform((value) => value || null),
});
