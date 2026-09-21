"use client";

import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Droplet,
  FileCheck,
  Search,
  TestTube,
  X,
} from "lucide-react";
import { crossmatchBlood, issueBloodUnit } from "../api";
import { formatBloodGroup, type BloodCrossmatch, type BloodUnit } from "../types";
import { api } from "@/lib/api";
import { useClinicalWrite } from "@/lib/useClinicalWrite";

interface BloodCrossmatchModalProps {
  isOpen: boolean;
  onClose: () => void;
  unit: BloodUnit | null;
  onSuccess: () => void;
}

export function BloodCrossmatchModal({
  isOpen,
  onClose,
  unit,
  onSuccess,
}: BloodCrossmatchModalProps) {
  const [patientSearch, setPatientSearch] = useState("");
  const [selectedPatient, setSelectedPatient] = useState<{
    id: string;
    uhid: string;
    full_name: string;
  } | null>(null);

  const [compatibility, setCompatibility] = useState<"compatible" | "incompatible" | "">("");
  const [notes, setNotes] = useState("");
  const [issueDirectly, setIssueDirectly] = useState(false);
  const [issuedToWard, setIssuedToWard] = useState("");

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [completedSlip, setCompletedSlip] = useState<string | null>(null);
  const searchSequence = useRef(0);
  const mounted = useRef(true);
  const matchWrite = useClinicalWrite();
  const issueWrite = useClinicalWrite();
  const savedMatch = useRef<BloodCrossmatch | null>(null);
  const [matchSaved, setMatchSaved] = useState(false);
  const uncertain = matchWrite.retryPending || issueWrite.retryPending;
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; searchSequence.current += 1; };
  }, []);

  const clearRecipient = () => {
    if (isSubmitting || uncertain || savedMatch.current) return;
    searchSequence.current += 1;
    setSelectedPatient(null);
    setCompatibility("");
    setIssueDirectly(false);
    setNotes("");
    setIssuedToWard("");
    setError(null);
  };

  if (!isOpen || !unit) return null;

  const handlePatientSearch = async () => {
    if (!patientSearch.trim()) return;
    const request = ++searchSequence.current;
    setError(null);
    try {
      const isDigits = /^\d+$/.test(patientSearch.trim());
      const body = isDigits
        ? { mobile: patientSearch.trim(), page: 1, page_size: 5 }
        : { uhid: patientSearch.trim(), page: 1, page_size: 5 };
      const res = await api<{
        items: Array<{
          id: string;
          uhid: string;
          full_name?: string;
          first_name?: string;
          last_name?: string;
        }>;
      }>("/patients/search", {
        method: "POST",
        idempotencyKey: null,
        body: JSON.stringify(body),
      });
      if (!mounted.current || request !== searchSequence.current) return;
      if (res?.items?.length === 1) {
        const p = res.items[0];
        setSelectedPatient({
          id: p.id,
          uhid: p.uhid,
          full_name: p.full_name || `${p.first_name || ""} ${p.last_name || ""}`.trim() || "Patient",
        });
      } else {
        setError("Enter an exact UHID. Search must return exactly one patient.");
      }
    } catch (err: unknown) {
      if (!mounted.current || request !== searchSequence.current) return;
      setError(err instanceof Error ? err.message : "Search failed.");
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isSubmitting || !mounted.current) return;
    setError(null);

    if (!selectedPatient || !compatibility) {
      setError("Select the patient and explicitly record the compatibility result.");
      return;
    }

    try {
      setIsSubmitting(true);
      const xm = savedMatch.current ?? await matchWrite.run({
        patient_id: selectedPatient.id,
        unit_id: unit.id,
        compatibility_result: compatibility,
        notes: notes.trim() || null,
      }, async (payload, key) => {
        const result = await crossmatchBlood(payload, key);
        if (result.patient_id !== payload.patient_id || result.unit_id !== payload.unit_id)
          throw new Error("Crossmatch did not match the selected patient and unit.");
        return result;
      });
      if (!mounted.current) return;
      if (xm.patient_id !== selectedPatient.id || xm.unit_id !== unit.id)
        throw new Error("The saved crossmatch belongs to a different patient or unit.");
      savedMatch.current = xm;
      setMatchSaved(true);

      if (compatibility === "compatible" && issueDirectly) {
        const issued = await issueWrite.run({
          crossmatch_id: xm.id,
          notes: [issuedToWard.trim() && `Destination: ${issuedToWard.trim()}`, notes.trim()].filter(Boolean).join("\n") || null,
        }, async (payload, key) => {
          const result = await issueBloodUnit(payload, key);
          if (!result.issued_at || result.id !== xm.id)
            throw new Error("Issue was not confirmed by the server.");
          return result;
        });
        if (!mounted.current) return;
        setCompletedSlip(issued.id);
      } else {
        onSuccess();
        onClose();
      }
    } catch (err: unknown) {
      if (mounted.current) setError(err instanceof Error ? err.message : "Crossmatch / Issue failed.");
    } finally {
      if (mounted.current) setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="w-full max-w-lg rounded-2xl border border-border bg-card p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
        <div className="flex items-center justify-between pb-4 border-b border-border">
          <div className="flex items-center gap-2">
            <TestTube className="h-5 w-5 text-primary" />
            <div>
              <h3 className="text-lg font-bold text-card-foreground">Major/Minor Crossmatch</h3>
              <p className="text-xs text-muted-foreground">Compatibility testing & controlled issue</p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={isSubmitting || uncertain}
            aria-label="Close crossmatch"
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {completedSlip ? (
          <div className="mt-6 text-center space-y-4 p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
            <CheckCircle2 className="h-12 w-12 mx-auto text-emerald-500" />
            <div>
              <h4 className="font-bold text-base text-foreground">Blood Unit Issued Successfully</h4>
              <p className="text-xs text-muted-foreground mt-1">Controlled release authorized to {issuedToWard}</p>
              <div className="mt-3 inline-block rounded-lg bg-background px-4 py-2 border border-border">
                <span className="text-xs text-muted-foreground block font-medium">Crossmatch Record ID</span>
                <span className="font-mono text-sm font-black text-primary">{completedSlip}</span>
              </div>
            </div>
            <button
              onClick={() => {
                onSuccess();
                onClose();
              }}
              className="w-full rounded-xl bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              Done
            </button>
          </div>
        ) : (
          <>
            {/* Unit Details Preview */}
            <div className="mt-4 flex items-center justify-between p-3 rounded-xl bg-muted/40 border border-border text-xs">
              <div className="flex items-center gap-2">
                <Droplet className="h-4 w-4 text-rose-500" />
                <div>
                  <span className="font-mono font-bold text-foreground">
                    {unit.bag_number || unit.unit_number || unit.id.slice(0, 8).toUpperCase()}
                  </span>
                  <span className="text-muted-foreground ml-2 capitalize">
                    {(unit.component_type || "Component not recorded").replace(/_/g, " ")} ({unit.volume_ml} mL)
                  </span>
                </div>
              </div>
              <span className="font-black px-2 py-0.5 rounded-full bg-rose-500/10 text-rose-600 dark:text-rose-400">
                {formatBloodGroup(unit.blood_group, unit.rh_factor)}
              </span>
            </div>

            {error && (
              <div className="mt-4 flex items-center gap-2 rounded-lg bg-destructive/10 p-3 text-sm text-destructive border border-destructive/20">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            <form onSubmit={handleSubmit} className="mt-4">
              <fieldset disabled={isSubmitting || uncertain || matchSaved} className="space-y-4">
              {/* Patient Selection */}
              <div>
                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                  Recipient Patient *
                </label>
                {selectedPatient ? (
                  <div className="flex items-center justify-between p-2.5 rounded-lg border border-primary/40 bg-primary/5 text-xs">
                    <div>
                      <span className="font-bold text-foreground">{selectedPatient.full_name}</span>
                      <span className="text-muted-foreground font-mono ml-2">UHID: {selectedPatient.uhid}</span>
                    </div>
                    <button
                      type="button"
                      onClick={clearRecipient}
                      className="text-xs text-primary underline font-medium"
                    >
                      Change
                    </button>
                  </div>
                ) : (
                  <div className="flex gap-2">
                    <input
                      type="text"
                      placeholder="Enter exact Patient UHID or Mobile..."
                      value={patientSearch}
                      onChange={(e) => { searchSequence.current += 1; setPatientSearch(e.target.value); }}
                      className="w-full rounded-lg border border-input bg-background px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-primary"
                    />
                    <button
                      type="button"
                      onClick={handlePatientSearch}
                      aria-label="Search patient"
                      className="rounded-lg bg-secondary px-3 py-2 text-xs font-semibold text-secondary-foreground hover:bg-secondary/80 transition-colors shrink-0"
                    >
                      <Search className="h-3.5 w-3.5" />
                    </button>
                  </div>
                )}
              </div>

              {/* Compatibility Result */}
              <div>
                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                  Crossmatch Lab Compatibility Result *
                </label>
                <div className="grid grid-cols-2 gap-3">
                  <label
                    className={`cursor-pointer flex items-center justify-center gap-2 p-3 rounded-xl border text-xs font-semibold transition-all ${
                      compatibility === "compatible"
                        ? "border-emerald-500 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-1 ring-emerald-500"
                        : "border-border text-muted-foreground hover:border-border/80"
                    }`}
                  >
                    <input
                      type="radio"
                      name="compat"
                      value="compatible"
                      checked={compatibility === "compatible"}
                      onChange={() => setCompatibility("compatible")}
                      className="sr-only"
                    />
                    <CheckCircle2 className="h-4 w-4" />
                    Compatible (No Agglutination)
                  </label>

                  <label
                    className={`cursor-pointer flex items-center justify-center gap-2 p-3 rounded-xl border text-xs font-semibold transition-all ${
                      compatibility === "incompatible"
                        ? "border-destructive bg-destructive/10 text-destructive ring-1 ring-destructive"
                        : "border-border text-muted-foreground hover:border-border/80"
                    }`}
                  >
                    <input
                      type="radio"
                      name="compat"
                      value="incompatible"
                      checked={compatibility === "incompatible"}
                      onChange={() => setCompatibility("incompatible")}
                      className="sr-only"
                    />
                    <AlertTriangle className="h-4 w-4" />
                    Incompatible (Agglutinated)
                  </label>
                </div>
              </div>

              {/* Immediate Issue Option */}
              {compatibility === "compatible" && (
                <div className="p-3 rounded-xl border border-border bg-muted/20 space-y-2 text-xs">
                  <label className="flex items-center gap-2 cursor-pointer font-semibold text-foreground">
                    <input
                      type="checkbox"
                      checked={issueDirectly}
                      onChange={(e) => setIssueDirectly(e.target.checked)}
                      className="rounded border-input text-primary focus:ring-primary"
                    />
                    <span>Issue directly to recipient ward now</span>
                  </label>

                  {issueDirectly && (
                    <div className="pt-2">
                      <label className="block text-[11px] text-muted-foreground font-medium mb-1">
                        Destination (saved in issue notes) *
                      </label>
                      <input
                        type="text"
                        value={issuedToWard}
                        onChange={(e) => setIssuedToWard(e.target.value)}
                        placeholder="e.g. ICU Bed 4, OT-2, Emergency Resus"
                        className="w-full rounded-lg border border-input bg-background px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-primary"
                        required
                      />
                    </div>
                  )}
                </div>
              )}

              {/* Notes */}
              <div>
                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">
                  Lab Technician Observations
                </label>
                <textarea
                  rows={2}
                  placeholder="Saline phase, Albumin phase, Coomb's AHG test notes..."
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  className="w-full rounded-lg border border-input bg-background px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-primary"
                />
              </div>

              </fieldset>
              {matchSaved && !completedSlip && <p role="status" className="mt-3 text-xs">Crossmatch recorded. Any further retry applies only to issuing this same crossmatch.</p>}
              <div className="flex items-center justify-end gap-3 pt-4 border-t border-border">
                <button
                  type="button"
                  onClick={onClose}
                  disabled={isSubmitting || uncertain}
                  className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-muted transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting || !selectedPatient || !compatibility}
                  className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
                >
                  <FileCheck className="h-4 w-4" />
                  {isSubmitting
                    ? "Saving..."
                    : uncertain ? "Retry unchanged save"
                    : matchSaved ? "Retry issue"
                    : issueDirectly
                    ? "Crossmatch & Issue"
                    : "Save Crossmatch Result"}
                </button>
              </div>
            </form>
          </>
        )}
      </div>
    </div>
  );
}
