"use client";

import { useState } from "react";

import { PatientSearch } from "@/features/receptionist/PatientSearch";
import { RegistrationForm } from "@/features/receptionist/RegistrationForm";
import { StartVisit } from "@/features/receptionist/StartVisit";
import type { PatientSearchResult } from "@/features/receptionist/types";

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

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Register patient</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Check whether this patient already has a record before creating one.
        </p>
      </div>

      <section className="space-y-4">
        <h2 className="text-lg font-medium">1. Search for an existing record</h2>
        <PatientSearch
          selectLabel="Use this patient"
          onSelect={(patient) => {
            setSelected(patient);
            setConfirmedNew(false);
          }}
        />
        {selected ? (
          <div className="space-y-4">
            <div className="surface-card flex flex-wrap items-center justify-between gap-3 border border-success/30 bg-success-muted p-4">
              <div>
                <p className="font-medium">Using existing patient record</p>
                <p className="text-sm text-muted-foreground">
                  {selected.full_name} · {selected.uhid ?? "UHID pending"}
                </p>
              </div>
              <button type="button" className="text-sm underline" onClick={() => setSelected(null)}>
                Choose another patient
              </button>
            </div>
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
        <h2 className="text-lg font-medium">2. Register a new patient</h2>

        {!confirmedNew && !selected ? (
          <div className="surface-card space-y-3 p-6">
            <p className="text-sm text-muted-foreground">
              Only continue if the search above returned no match for this
              person.
            </p>
            <button
              type="button"
              onClick={() => setConfirmedNew(true)}
              className="rounded-md border border-border px-4 py-2 text-sm font-medium"
            >
              No existing record — register new
            </button>
          </div>
        ) : confirmedNew ? (
          <RegistrationForm />
        ) : null}
      </section>
    </div>
  );
}
