"use client";

import { useState } from "react";

import { PatientSearch } from "@/features/receptionist/PatientSearch";
import { StartVisit } from "@/features/receptionist/StartVisit";
import type { PatientSearchResult } from "@/features/receptionist/types";

export default function Page() {
  const [selected, setSelected] = useState<PatientSearchResult | null>(null);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Patient search</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Search before registering. A duplicate chart splits a patient&apos;s
          history across two records and takes a supervisor-approved merge to
          undo.
        </p>
      </div>

      <PatientSearch onSelect={setSelected} selectLabel="Start visit" />

      {selected ? (
        <div className="space-y-4">
          <div className="surface-card flex flex-wrap items-center justify-between gap-3 border border-success/30 bg-success-muted p-4">
            <div>
              <p className="font-medium">Selected patient</p>
              <p className="text-sm text-muted-foreground">
                {selected.full_name} · {selected.uhid ?? "UHID pending"}
              </p>
            </div>
            <button type="button" className="text-sm underline" onClick={() => setSelected(null)}>
              Change patient
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
    </div>
  );
}
