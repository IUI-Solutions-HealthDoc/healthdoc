"use client";

import { useLocale } from "@/lib/i18n";

export interface PatientIdentity {
  patient_name?: string | null;
  patient_uhid?: string | null;
  patient_age_years?: number | null;
  patient_sex?: string | null;
}

/**
 * Name over UHID · age · sex: what a wristband check compares. Worklists that
 * showed no patient, or an internal id, left the bench unable to confirm whose
 * sample or scan it was (QA 10-12 Oct 2026). A missing patient is shown as a
 * warning, never as a blank.
 */
export function PatientIdentityCell({ row }: { row: PatientIdentity }) {
  const { t } = useLocale();
  if (!row.patient_name) {
    return <span className="text-danger">{t("patient.identityUnavailable")}</span>;
  }
  const age = row.patient_age_years == null ? t("patient.ageUnknown") : `${row.patient_age_years} y`;
  return (
    <>
      <span className="font-medium">{row.patient_name}</span>
      <span className="block text-xs text-muted-foreground">
        {[row.patient_uhid, age, row.patient_sex].filter(Boolean).join(" · ")}
      </span>
    </>
  );
}
