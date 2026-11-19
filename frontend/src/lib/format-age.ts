import { translate } from "@/lib/i18n";
/**
 * An age as people read it on a clinical screen.
 *
 * A missing age is "Age unknown", never 0: "0 yrs" reads as a newborn, and
 * age drives dosing and reference ranges (QA 10 Oct 2026: an unknown age
 * showed "?y" on the dashboard and "0 yrs" in the consultation header). A
 * recorded 0 is a real infant and stays "0 yrs".
 */
export const AGE_UNKNOWN = "Age unknown";

export function formatAge(age: number | null | undefined, unit = "yrs"): string {
  return age === null || age === undefined || Number.isNaN(age) ? AGE_UNKNOWN : `${age} ${unit}`;
}

/** "34 yrs · Male", or "Age unknown · Male". */
export function formatAgeSex(age: number | null | undefined, sex: string | null | undefined): string {
  const s = sex ? sex[0].toUpperCase() + sex.slice(1) : "";
  return s ? `${formatAge(age)} · ${s}` : formatAge(age);
}

/** The compact "34y/M" of a card, "?/M" never: "Age unknown/M". */
export function formatAgeSexShort(age: number | null | undefined, sex: string | null | undefined): string {
  const s = sex ? sex[0].toUpperCase() : "";
  const a = age === null || age === undefined ? AGE_UNKNOWN : `${age}y`;
  return s ? `${a}/${s}` : a;
}

/**
 * A schedule age in days as people say it: "At birth", "6 weeks",
 * "9 months", "10 years". The catalogue showed 270, 480 and 3650 days
 * (QA 17 Oct 2026). EPI ages under six months are given in weeks.
 */
export function formatScheduleAge(days: number | null | undefined): string {
  if (days === null || days === undefined || !Number.isFinite(days)) return "—";
  if (days <= 0) return translate("common.msg.atBirth");
  if (days < 182 && days % 7 === 0) return `${days / 7} weeks`;
  if (days < 730) {
    const months = Math.round(days / 30.4);
    return `${months} month${months === 1 ? "" : "s"}`;
  }
  const years = Math.round(days / 365.25);
  return `${years} years`;
}

/** "left_upper_arm" → "Left upper arm": stored codes are not display text. */
export function humanizeCode(value: string | null | undefined): string {
  if (!value) return "—";
  if (!/[_]/.test(value) && value !== value.toLowerCase()) return value;
  const words = value.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}
