"use client";

import { useState } from "react";

import { PageHeading } from "@/components/common/PageHeading";
import { PatientSearch } from "@/features/receptionist/PatientSearch";
import { AbhaIdentityPanel } from "@/features/receptionist/AbhaIdentityPanel";
import { RegistrationForm } from "@/features/receptionist/RegistrationForm";
import { StartVisit } from "@/features/receptionist/StartVisit";
import type { PatientSearchResult } from "@/features/receptionist/types";
import { useLocale } from "@/lib/i18n";

/**
 * Registration (#170).
 *
 * Search first, register second — in that order on the page, deliberately.
 * Registration is the step that creates duplicates, and a duplicate chart takes
 * a supervisor-approved merge to undo. Putting the search above the form makes
 * the cheap check the default rather than a discipline.
 */
export default function Page() {
  const [confirmedNew, setConfirmedNew] = useState(false);
  const [selected, setSelected] = useState<PatientSearchResult | null>(null);
  const { t } = useLocale();

  return (
    <div className="space-y-8">
      <PageHeading
        titleKey="receptionist.registrationTitle"
        subtitleKey="receptionist.registrationSubtitle"
      />

      <section className="space-y-4">
        <h2 className="text-lg font-medium">{t("patient.searchExistingSection")}</h2>
        <PatientSearch
          selectLabel={t("common.useThisPatient")}
          onSelect={(patient) => {
            setSelected(patient);
            setConfirmedNew(false);
          }}
        />
        {selected ? (
          <div className="space-y-4">
            <div className="surface-card flex flex-wrap items-center justify-between gap-3 border border-success/30 bg-success-muted p-4">
              <div>
                <p className="font-medium">{t("patient.usingExisting")}</p>
                <p className="text-sm text-muted-foreground">
                  {selected.full_name} · {selected.uhid ?? t("patient.uhidPending")}
                </p>
              </div>
              <button type="button" className="text-sm underline" onClick={() => setSelected(null)}>
                {t("patient.chooseAnother")}
              </button>
            </div>
            <AbhaIdentityPanel patient={selected} />
            <StartVisit
              patient={{
                id: selected.id,
                full_name: selected.full_name,
                uhid: selected.uhid,
                thid: null,
              }}
            />
          </div>
        ) : null}
      </section>

      <section className="space-y-4">
        <h2 className="text-lg font-medium">{t("patient.registerNewSection")}</h2>

        {!confirmedNew && !selected ? (
          <div className="surface-card space-y-3 p-6">
            <p className="text-sm text-muted-foreground">
              {t("patient.registerOnlyIfNoMatch")}
            </p>
            <button
              type="button"
              onClick={() => setConfirmedNew(true)}
              className="rounded-md border border-border px-4 py-2 text-sm font-medium"
            >
              {t("receptionist.registerNew")}
            </button>
          </div>
        ) : confirmedNew ? (
          <RegistrationForm />
        ) : null}
      </section>
    </div>
  );
}
