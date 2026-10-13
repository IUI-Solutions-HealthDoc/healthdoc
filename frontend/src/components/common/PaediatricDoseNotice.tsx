"use client";

/**
 * A child on a prescribing or dispensing screen. HealthDoc has no clinically
 * approved paediatric dosing table yet, so it cannot check a dose; it can and
 * must say that the patient is a child (QA 12 Oct 2026: an adult 500 mg
 * paracetamol tablet TDS went to a 3-year-old, 14 kg, with no warning).
 * Unknown age is called out too, because it hides the same risk.
 */
export const PAEDIATRIC_AGE_YEARS = 12;

export function PaediatricDoseNotice({ ageYears }: { ageYears: number | null | undefined }) {
  if (ageYears === null || ageYears === undefined) {
    return (
      <p role="alert" className="rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
        Age unknown: confirm the patient&apos;s age and weight before choosing a dose.
      </p>
    );
  }
  if (ageYears >= PAEDIATRIC_AGE_YEARS) return null;
  return (
    <p role="alert" className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm font-medium text-red-900">
      Child, {ageYears} {ageYears === 1 ? "year" : "years"}: check every dose and form against the child&apos;s weight.
      HealthDoc does not check paediatric doses automatically.
    </p>
  );
}
