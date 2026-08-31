"use client";

import { useState } from "react";

import { ApiError } from "@/lib/api";

import { searchPatients } from "./api";
import {
  MATCH_LABELS,
  isIdentityMatch,
  type PatientSearchRequest,
  type PatientSearchResult,
} from "./types";
import {
  isValidAbhaInput,
  isValidPatientName,
  isValidUhidInput,
  normaliseIndianMobileInput,
} from "./patientValidation";

type Props = {
  /** Rendered on each row when present — used by registration to offer a merge. */
  onSelect?: (patient: PatientSearchResult) => void;
  selectLabel?: string;
};

const EMPTY: PatientSearchRequest = {
  full_name: "",
  dob: "",
  mobile: "",
  uhid: "",
  abha_number: "",
};

function MatchBadge({ matchedOn, score }: { matchedOn: string; score: number }) {
  const identity = isIdentityMatch(matchedOn);
  return (
    <span
      title={`Match score ${score.toFixed(2)}`}
      className={`rounded-full px-2 py-1 text-xs font-medium ${
        identity ? "bg-success-muted text-success" : "bg-warning-muted text-warning"
      }`}
    >
      {MATCH_LABELS[matchedOn] ?? matchedOn}
    </span>
  );
}

export function PatientSearch({ onSelect, selectLabel = "Select" }: Props) {
  const [criteria, setCriteria] = useState<PatientSearchRequest>(EMPTY);
  const [results, setResults] = useState<PatientSearchResult[] | null>(null);
  const [total, setTotal] = useState(0);
  /** Pagination, from PR #412. The screen previously fetched page 1 only and
   *  showed "N matches" while displaying at most 20 — so a receptionist
   *  searching a common surname was told there were 43 matches and shown
   *  nothing beyond the first 20, with no way to reach the rest. */
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const hasCriterion = Boolean(
    criteria.full_name?.trim() ||
      criteria.mobile?.trim() ||
      criteria.uhid?.trim() ||
      criteria.abha_number?.trim(),
  );
  const mobileInvalid = Boolean(
    criteria.mobile?.trim() && !normaliseIndianMobileInput(criteria.mobile),
  );
  const abhaInvalid = Boolean(
    criteria.abha_number?.trim() && !isValidAbhaInput(criteria.abha_number),
  );
  const uhidInvalid = Boolean(criteria.uhid?.trim() && !isValidUhidInput(criteria.uhid));
  const nameInvalid = Boolean(criteria.full_name?.trim() && !isValidPatientName(criteria.full_name));
  const nameNeedsDob = Boolean(criteria.full_name?.trim() && !criteria.dob);
  const formInvalid = mobileInvalid || abhaInvalid || uhidInvalid || nameInvalid || nameNeedsDob;
  const inputClass = (invalid: boolean) =>
    `w-full rounded-md border px-3 py-2 ${invalid ? "border-danger" : "border-border"}`;

  function set(field: keyof PatientSearchRequest, value: string) {
    setCriteria((current) => ({ ...current, [field]: value }));
  }

  async function search(nextPage: number) {
    if (!hasCriterion || formInvalid) {
      setError(
        nameNeedsDob
          ? "Date of birth is required for a name search."
          : "Correct the highlighted search fields before searching.",
      );
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const trimmed = Object.fromEntries(
        Object.entries(criteria)
          .map(([key, value]) => [key, typeof value === "string" ? value.trim() : value])
          .filter(([, value]) => value !== "" && value !== undefined),
      );
      const response = await searchPatients(trimmed, nextPage, PAGE_SIZE);
      setResults(response.items);
      setTotal(response.total);
      setPage(nextPage);
    } catch (reason) {
      // A disabled module reads as a permission failure otherwise, and a
      // receptionist told "search failed" will retry rather than escalate.
      // From PR #412.
      setError(
        reason instanceof ApiError
          ? reason.isModuleDisabled
            ? "Patient search is not enabled at this facility."
            : reason.message
          : "Patient search failed",
      );
      setResults(null);
    } finally {
      setBusy(false);
    }
  }

  function run(event: React.FormEvent) {
    event.preventDefault();
    void search(1);
  }

  return (
    <section className="space-y-6">
      <form onSubmit={run} className="surface-card space-y-4 p-6">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Name</span>
            <input
              className={inputClass(nameInvalid)}
              aria-invalid={nameInvalid}
              value={criteria.full_name ?? ""}
              onChange={(e) => set("full_name", e.target.value)}
              autoComplete="off"
            />
          </label>

          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Date of birth</span>
            <input
              type="date"
              className={inputClass(nameNeedsDob)}
              aria-invalid={nameNeedsDob}
              value={criteria.dob ?? ""}
              max={new Date().toISOString().slice(0, 10)}
              onChange={(e) => set("dob", e.target.value)}
              required={Boolean(criteria.full_name?.trim())}
            />
          </label>

          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Mobile</span>
            <input
              className={inputClass(mobileInvalid)}
              aria-invalid={mobileInvalid}
              value={criteria.mobile ?? ""}
              onChange={(e) => set("mobile", e.target.value)}
              inputMode="tel"
              maxLength={18}
              placeholder="10 digits or +91"
              autoComplete="off"
            />
          </label>

          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">UHID</span>
            <input
              className={inputClass(uhidInvalid)}
              aria-invalid={uhidInvalid}
              value={criteria.uhid ?? ""}
              onChange={(e) => set("uhid", e.target.value)}
              autoComplete="off"
              placeholder="IN-DL-DEV001-2026-000001-4"
            />
          </label>

          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">ABHA number</span>
            <input
              className={inputClass(abhaInvalid)}
              aria-invalid={abhaInvalid}
              value={criteria.abha_number ?? ""}
              onChange={(e) => set("abha_number", e.target.value)}
              inputMode="numeric"
              maxLength={20}
              autoComplete="off"
            />
          </label>
        </div>

        {/* Aadhaar is a valid search criterion server-side and is deliberately
            not offered here. Typing one to find a patient puts it on a shared
            reception screen for a lookup that name or mobile already answers. */}

        <div className="flex items-center gap-3">
          <button
            type="submit"
          disabled={!hasCriterion || formInvalid || busy}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy ? "Searching…" : "Search"}
          </button>
          <button
            type="button"
            onClick={() => {
              setCriteria(EMPTY);
              setResults(null);
              setError(null);
              setPage(1);
            }}
            className="text-sm underline"
          >
            Clear
          </button>
          {!hasCriterion && (
            <span className="text-sm text-muted-foreground">
              Enter at least one criterion.
            </span>
          )}
          {nameNeedsDob ? (
            <span className="text-sm text-danger">Date of birth is required with name.</span>
          ) : formInvalid ? (
            <span className="text-sm text-danger">Check the highlighted field formats.</span>
          ) : null}
        </div>
      </form>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      {results && results.length === 0 && (
        <div className="surface-card p-6">
          <p className="text-sm text-muted-foreground">
            No patient matches those details. Register a new patient only after
            searching by mobile and by name — a duplicate chart is far harder to
            undo than a second search.
          </p>
        </div>
      )}

      {results && results.length > 0 && (
        <div className="surface-card overflow-hidden">
          <div className="border-b border-border px-6 py-4">
            <h2 className="text-lg font-semibold">
              {total} match{total === 1 ? "" : "es"}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Identity matches are exact. A name and date-of-birth match is a
              likeness, not proof — confirm before you attach a visit to it.
            </p>
          </div>

          <table className="min-w-full border-collapse">
            <thead className="bg-muted">
              <tr>
                <th className="px-4 py-3 text-left">UHID</th>
                <th className="px-4 py-3 text-left">Name</th>
                <th className="px-4 py-3 text-left">Sex / Age</th>
                <th className="px-4 py-3 text-left">Mobile</th>
                <th className="px-4 py-3 text-left">Matched on</th>
                {onSelect && <th className="px-4 py-3" />}
              </tr>
            </thead>
            <tbody>
              {results.map((patient) => (
                <tr key={patient.id} className="border-b border-border last:border-none">
                  <td className="px-4 py-3 font-mono text-sm">
                    {patient.uhid ?? "—"}
                  </td>
                  <td className="px-4 py-3 font-medium">{patient.full_name}</td>
                  <td className="px-4 py-3 text-sm">
                    {patient.sex}
                    {patient.age_years !== null ? ` · ${patient.age_years}y` : ""}
                  </td>
                  {/* Masked by the server. The full number is not needed to
                      identify someone at a counter. */}
                  <td className="px-4 py-3 text-sm">{patient.mobile_masked ?? "—"}</td>
                  <td className="px-4 py-3">
                    <MatchBadge matchedOn={patient.matched_on} score={patient.match_score} />
                  </td>
                  {onSelect && (
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        onClick={() => onSelect(patient)}
                        className="text-sm underline"
                      >
                        {selectLabel}
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>

          {total > PAGE_SIZE && (
            <div className="flex items-center justify-center gap-3 border-t border-border py-3">
              <button
                type="button"
                className="rounded-md border border-border px-3 py-1 text-sm disabled:opacity-50"
                disabled={busy || page <= 1}
                onClick={() => void search(page - 1)}
              >
                Previous
              </button>
              <span className="text-xs text-muted-foreground">
                Page {page} of {Math.max(1, Math.ceil(total / PAGE_SIZE))}
              </span>
              <button
                type="button"
                className="rounded-md border border-border px-3 py-1 text-sm disabled:opacity-50"
                disabled={busy || page >= Math.ceil(total / PAGE_SIZE)}
                onClick={() => void search(page + 1)}
              >
                Next
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export default PatientSearch;
