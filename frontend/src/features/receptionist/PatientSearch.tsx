"use client";

import { useState } from "react";
import { Printer, Scan, Check } from "lucide-react";

import { PatientAvatar } from "@/components/ui";
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
import { PatientCardModal, type PatientCardData } from "./PatientCardModal";

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
  const [cardPatient, setCardPatient] = useState<PatientCardData | null>(null);
  /** Pagination, from PR #412. The screen previously fetched page 1 only and
   *  showed "N matches" while displaying at most 20 — so a receptionist
   *  searching a common surname was told there were 43 matches and shown
   *  nothing beyond the first 20, with no way to reach the rest. */
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 20;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleQuickScan(exactIdentifier: string) {
    const norm = exactIdentifier.trim().toUpperCase();
    if (!norm) return;
    setCriteria({ ...EMPTY, uhid: norm });
    setBusy(true);
    setError(null);
    try {
      const response = await searchPatients({ uhid: norm }, 1, PAGE_SIZE);
      setResults(response.items);
      setTotal(response.total);
      setPage(1);
    } catch (reason) {
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
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 p-3.5 rounded-lg border border-primary/20 bg-primary/5">
          <div className="flex items-center gap-2 text-primary">
            <Scan size={20} />
            <span className="text-sm font-semibold">Scan Barcode / Exact Identifier</span>
          </div>
          <div className="flex-1 flex gap-2">
            <input
              type="text"
              className="flex-1 rounded-md border border-border bg-card px-3 py-1.5 font-mono text-sm uppercase placeholder:normal-case placeholder:font-sans"
              placeholder="Scan barcode or paste UHID / THID (e.g. IN-RJ-JPR001-2026-000001-4)..."
              value={criteria.uhid ?? ""}
              onChange={(e) => set("uhid", e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  void handleQuickScan(criteria.uhid ?? "");
                }
              }}
            />
            <button
              type="button"
              onClick={() => void handleQuickScan(criteria.uhid ?? "")}
              disabled={!criteria.uhid?.trim() || busy}
              className="rounded-md bg-primary px-3.5 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
            >
              Scan & Find
            </button>
          </div>
        </div>

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
            <span className="text-muted-foreground">UHID / THID</span>
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

      {results && results.length > 0 && (() => {
        const exactMatch =
          results.length === 1 && isIdentityMatch(results[0].matched_on) ? results[0] : null;

        return (
          <div className="space-y-4">
            {exactMatch && (
              <div className="surface-card border-2 border-emerald-500/40 bg-emerald-50/30 p-5 shadow-sm dark:bg-emerald-950/20">
                <div className="flex items-center justify-between border-b border-emerald-200/60 pb-3 dark:border-emerald-800/40">
                  <div className="flex items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-600 text-white">
                      <Check size={14} />
                    </span>
                    <h3 className="font-semibold text-emerald-900 dark:text-emerald-200">
                      Exact Identity Match Found
                    </h3>
                  </div>
                  <MatchBadge matchedOn={exactMatch.matched_on} score={exactMatch.match_score} />
                </div>

                {exactMatch.matched_on === "merged_identifier" && (
                  <div className="mt-3 rounded bg-blue-50 p-2.5 text-xs text-blue-800 border border-blue-200">
                    <strong>Notice:</strong> This patient card was merged from previous identifier{" "}
                    <span className="font-mono font-semibold">{exactMatch.merged_from_uhid}</span>. Displaying the active canonical record.
                  </div>
                )}

                {exactMatch.thid && !exactMatch.uhid && (
                  <div className="mt-3 rounded bg-amber-50 p-2.5 text-xs text-amber-800 border border-amber-200">
                    <strong>Provisional Emergency Record (THID):</strong> This patient has a temporary emergency identifier.
                  </div>
                )}

                <div className="mt-4 flex flex-wrap items-center justify-between gap-4">
                  <div className="flex items-center gap-3.5">
                    <PatientAvatar patientId={exactMatch.id} name={exactMatch.full_name} size="md" />
                    <div>
                      <p className="font-bold text-foreground text-base">{exactMatch.full_name}</p>
                      <p className="font-mono text-sm text-muted-foreground font-semibold">
                        {exactMatch.uhid ?? exactMatch.thid}
                      </p>
                      <p className="text-xs text-muted-foreground capitalize">
                        {exactMatch.sex}
                        {exactMatch.age_years !== null ? ` · ${exactMatch.age_years}y` : ""}
                        {exactMatch.dob ? ` (DOB: ${exactMatch.dob})` : ""}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() =>
                        setCardPatient({
                          id: exactMatch.id,
                          full_name: exactMatch.full_name,
                          uhid: exactMatch.uhid,
                          thid: exactMatch.thid,
                          sex: exactMatch.sex,
                          age_years: exactMatch.age_years,
                          dob: exactMatch.dob,
                        })
                      }
                      className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3.5 py-1.5 text-sm font-medium hover:bg-muted"
                    >
                      <Printer size={15} />
                      Print Card
                    </button>
                    {onSelect && (
                      <button
                        type="button"
                        onClick={() => onSelect(exactMatch)}
                        className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700"
                      >
                        {selectLabel}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )}

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
                    <th className="px-4 py-3 text-left">UHID / THID</th>
                    <th className="px-4 py-3 text-left">Name</th>
                    <th className="px-4 py-3 text-left">Sex / Age</th>
                    <th className="px-4 py-3 text-left">Mobile</th>
                    <th className="px-4 py-3 text-left">Matched on</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((patient) => (
                    <tr key={patient.id} className="border-b border-border last:border-none">
                      <td className="px-4 py-3 font-mono text-sm">
                        {patient.uhid ?? patient.thid ?? "—"}
                      </td>
                      <td className="px-4 py-3 font-medium">
                        <div className="flex items-center gap-2.5">
                          <PatientAvatar patientId={patient.id} name={patient.full_name} size="sm" />
                          <span>{patient.full_name}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-sm">
                        {patient.sex}
                        {patient.age_years !== null ? ` · ${patient.age_years}y` : ""}
                        {patient.dob ? ` (DOB: ${patient.dob})` : ""}
                      </td>
                      {/* Masked by the server. The full number is not needed to
                          identify someone at a counter. */}
                      <td className="px-4 py-3 text-sm">{patient.mobile_masked ?? "—"}</td>
                      <td className="px-4 py-3">
                        <MatchBadge matchedOn={patient.matched_on} score={patient.match_score} />
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="inline-flex items-center justify-end gap-2">
                          <button
                            type="button"
                            onClick={() =>
                              setCardPatient({
                                id: patient.id,
                                full_name: patient.full_name,
                                uhid: patient.uhid,
                                thid: patient.thid,
                                sex: patient.sex,
                                age_years: patient.age_years,
                                dob: patient.dob,
                              })
                            }
                            className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
                            title="Print patient card"
                          >
                            <Printer size={13} />
                            Card
                          </button>
                          {onSelect && (
                            <button
                              type="button"
                              onClick={() => onSelect(patient)}
                              className="text-sm font-medium text-primary underline hover:text-primary/80"
                            >
                              {selectLabel}
                            </button>
                          )}
                        </div>
                      </td>
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
          </div>
        );
      })()}

      {cardPatient && (
        <PatientCardModal
          open={Boolean(cardPatient)}
          onClose={() => setCardPatient(null)}
          patient={cardPatient}
        />
      )}
    </section>
  );
}

export default PatientSearch;

