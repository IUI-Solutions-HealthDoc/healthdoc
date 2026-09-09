import { z } from "zod";

const noControl = (value: string) => [...value].every((character) => character.charCodeAt(0) >= 32 && character.charCodeAt(0) !== 127);
const code = z.string().trim().min(1, "Enter a charge code.").max(30, "Use at most 30 characters.")
  .refine(noControl, "Control characters are not allowed.");

export const tariffFormSchema = z.object({
  charge_code: code,
  description: z.string().trim().min(1, "Enter a description.").refine(noControl, "Control characters are not allowed."),
  charge_category: z.enum(["registration", "consultation", "lab", "radiology", "pharmacy", "procedure", "ipd_stay", "blood", "other"]),
  // Numeric(12,2): validate and normalize strings without binary float rounding.
  unit_price: z.string().trim().regex(/^\d{1,10}(\.\d{1,2})?$/, "Enter a non-negative price with up to 10 whole digits and 2 decimals.")
    .transform((value) => {
      const [whole, fraction = ""] = value.split(".");
      return `${whole.replace(/^0+(?=\d)/, "")}.${fraction.padEnd(2, "0")}`;
    }),
  effective_from: z.string().refine((value) => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const date = new Date(`${value}T00:00:00Z`);
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
  }, "Enter a valid effective date."),
  scheme_code: z.string().trim().max(30, "Use at most 30 characters.")
    .refine(noControl, "Control characters are not allowed.").transform((value) => value || null),
});
