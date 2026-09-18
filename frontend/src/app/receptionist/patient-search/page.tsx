"use client";

import { useState } from "react";
import { Printer } from "lucide-react";

import { PatientSearch } from "@/features/receptionist/PatientSearch";
import { StartVisit } from "@/features/receptionist/StartVisit";
import { PatientCardModal } from "@/features/receptionist/PatientCardModal";
import type { PatientSearchResult } from "@/features/receptionist/types";

export default function Page() {
  const [selected, setSelected] = useState<PatientSearchResult | null>(null);
  const [showCard, setShowCard] = useState(false);

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
                {selected.full_name} · {selected.uhid ?? selected.thid ?? "UHID pending"}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setShowCard(true)}
                className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-xs font-semibold hover:bg-muted"
              >
                <Printer size={14} />
                Print Card
              </button>
              <button type="button" className="text-sm underline" onClick={() => setSelected(null)}>
                Change patient
              </button>
            </div>
          </div>
          <StartVisit
            patient={{
              id: selected.id,
              full_name: selected.full_name,
              uhid: selected.uhid,
              thid: selected.thid ?? null,
            }}
          />

          {showCard && (
            <PatientCardModal
              open={showCard}
              onClose={() => setShowCard(false)}
              patient={{
                id: selected.id,
                full_name: selected.full_name,
                uhid: selected.uhid,
                thid: selected.thid,
                sex: selected.sex,
                age_years: selected.age_years,
                dob: selected.dob,
              }}
            />
          )}
        </div>
      ) : null}
    </div>
  );
}
