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
