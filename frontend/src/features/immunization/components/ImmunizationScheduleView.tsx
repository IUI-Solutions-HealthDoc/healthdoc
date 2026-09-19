"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Award,
  CheckCircle2,
  Clock,
  Plus,
  RefreshCw,
  ShieldAlert,
  Syringe,
} from "lucide-react";
import { fetchPatientSchedule } from "../api";
import type { PatientImmunizationSchedule } from "../types";

interface ImmunizationScheduleViewProps {
  patientId: string;
  patientName?: string;
  uhid?: string;
  onOpenRecordModal: () => void;
  onOpenCertificateModal: () => void;
  refreshTrigger?: number;
}

export function ImmunizationScheduleView({
  patientId,
  patientName,
  uhid,
  onOpenRecordModal,
  onOpenCertificateModal,
  refreshTrigger = 0,
}: ImmunizationScheduleViewProps) {
  const [schedule, setSchedule] = useState<PatientImmunizationSchedule | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"history" | "due" | "overdue">("history");

  const loadSchedule = useCallback(async () => {
    if (!patientId) return;
    try {
      setLoading(true);
      setError(null);
      const data = await fetchPatientSchedule(patientId);
      setSchedule(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load immunization schedule.");
    } finally {
      setLoading(false);
    }
  }, [patientId]);

  useEffect(() => {
    loadSchedule();
  }, [loadSchedule, refreshTrigger]);

  if (loading) {
    return (
      <div className="flex items-center justify-center p-12 text-muted-foreground">
        <RefreshCw className="h-6 w-6 animate-spin mr-2" />
        <span>Loading immunization schedule...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-6 text-destructive flex items-center justify-between">
        <div>
          <h4 className="font-semibold text-sm">Error Loading Immunization Data</h4>
          <p className="text-xs mt-1">{error}</p>
        </div>
        <button
          onClick={loadSchedule}
          className="rounded-lg bg-destructive px-3 py-1.5 text-xs font-semibold text-destructive-foreground hover:bg-destructive/90 transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  const recordCount = schedule?.records.length || 0;
  const dueCount = schedule?.due_vaccines.length || 0;
  const overdueCount = schedule?.overdue_vaccines.length || 0;

  return (
    <div className="space-y-6">
      {/* Top action header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-card border border-border p-5 rounded-2xl shadow-sm">
        <div>
          <div className="flex items-center gap-2">
            <Syringe className="h-5 w-5 text-primary" />
            <h2 className="text-lg font-bold text-foreground">
              {patientName ? `${patientName}'s Immunization Profile` : "Patient Immunization Schedule"}
            </h2>
          </div>
          {uhid && <p className="text-xs text-muted-foreground mt-0.5 font-mono">UHID: {uhid}</p>}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={onOpenCertificateModal}
            className="flex items-center gap-1.5 rounded-xl border border-border bg-background px-3.5 py-2 text-xs font-semibold text-foreground hover:bg-muted transition-colors shadow-sm"
          >
            <Award className="h-4 w-4 text-amber-500" />
            View Certificate
          </button>
          <button
            onClick={onOpenRecordModal}
            className="flex items-center gap-1.5 rounded-xl bg-primary px-3.5 py-2 text-xs font-semibold text-primary-foreground hover:bg-primary/90 transition-colors shadow-sm"
          >
            <Plus className="h-4 w-4" />
            Record Dose
          </button>
        </div>
      </div>

      {/* KPI status cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div
          onClick={() => setActiveTab("history")}
          className={`cursor-pointer rounded-2xl border p-4 transition-all ${
            activeTab === "history"
              ? "border-primary bg-primary/5 ring-1 ring-primary"
              : "border-border bg-card hover:border-border/80"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Administered Doses
            </span>
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          </div>
          <div className="mt-2 text-2xl font-black text-foreground">{recordCount}</div>
          <p className="text-[11px] text-muted-foreground mt-1">Verified vaccinations on record</p>
        </div>

        <div
          onClick={() => setActiveTab("due")}
          className={`cursor-pointer rounded-2xl border p-4 transition-all ${
            activeTab === "due"
              ? "border-amber-500 bg-amber-500/5 ring-1 ring-amber-500"
              : "border-border bg-card hover:border-border/80"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Due Next
            </span>
            <Clock className="h-4 w-4 text-amber-500" />
          </div>
          <div className="mt-2 text-2xl font-black text-foreground">{dueCount}</div>
          <p className="text-[11px] text-muted-foreground mt-1">Recommended per national schedule</p>
        </div>

        <div
          onClick={() => setActiveTab("overdue")}
          className={`cursor-pointer rounded-2xl border p-4 transition-all ${
            activeTab === "overdue"
              ? "border-destructive bg-destructive/5 ring-1 ring-destructive"
              : "border-border bg-card hover:border-border/80"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
              Overdue Doses
            </span>
            <ShieldAlert className="h-4 w-4 text-destructive" />
          </div>
          <div className="mt-2 text-2xl font-black text-foreground">{overdueCount}</div>
          <p className="text-[11px] text-muted-foreground mt-1">Lapsed milestone vaccines</p>
        </div>
      </div>

      {/* Tab Panels */}
      <div className="rounded-2xl border border-border bg-card overflow-hidden shadow-sm">
        <div className="flex items-center border-b border-border px-4 pt-3 bg-muted/20">
          <button
            onClick={() => setActiveTab("history")}
            className={`pb-3 px-3 text-xs font-semibold border-b-2 transition-colors ${
              activeTab === "history"
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            Administration History ({recordCount})
          </button>
          <button
            onClick={() => setActiveTab("due")}
            className={`pb-3 px-3 text-xs font-semibold border-b-2 transition-colors ${
              activeTab === "due"
                ? "border-amber-500 text-amber-500"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            Due Vaccines ({dueCount})
          </button>
          <button
            onClick={() => setActiveTab("overdue")}
            className={`pb-3 px-3 text-xs font-semibold border-b-2 transition-colors ${
              activeTab === "overdue"
                ? "border-destructive text-destructive"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            Overdue ({overdueCount})
          </button>
        </div>

        {/* Tab 1: History */}
        {activeTab === "history" && (
          <div className="p-4">
            {recordCount === 0 ? (
              <div className="text-center py-12 text-muted-foreground text-xs">
                <Syringe className="h-8 w-8 mx-auto mb-2 opacity-40" />
                No vaccines recorded yet for this patient. Click &quot;Record Dose&quot; to log an administration.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-muted/50 text-muted-foreground font-semibold">
                    <tr>
                      <th className="p-3 rounded-l-lg">Vaccine</th>
                      <th className="p-3">Dose #</th>
                      <th className="p-3">Administered</th>
                      <th className="p-3">Batch / Lot</th>
                      <th className="p-3">Route / Site</th>
                      <th className="p-3">Adverse Reaction</th>
                      <th className="p-3 rounded-r-lg">Expiry</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {schedule?.records.map((rec) => (
                      <tr key={rec.id} className="hover:bg-muted/30">
                        <td className="p-3 font-semibold text-foreground">
                          {rec.vaccine_name || "Vaccine"}
                          {rec.vaccine_code && (
                            <span className="ml-1 text-[10px] text-muted-foreground font-mono">
                              ({rec.vaccine_code})
                            </span>
                          )}
                        </td>
                        <td className="p-3">
                          <span className="inline-flex items-center rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-semibold text-primary">
                            Dose {rec.dose_number}
                          </span>
                        </td>
                        <td className="p-3 font-mono">{rec.administered_date}</td>
                        <td className="p-3 font-mono font-medium">{rec.batch_number}</td>
                        <td className="p-3 text-muted-foreground">
                          {rec.route || "—"} {rec.site ? `• ${rec.site}` : ""}
                        </td>
                        <td className="p-3 text-muted-foreground">
                          {rec.adverse_reaction ? (
                            <span className="inline-flex items-center gap-1 text-destructive font-medium">
                              <AlertTriangle className="h-3 w-3" />
                              {rec.adverse_reaction}
                            </span>
                          ) : (
                            "None recorded"
                          )}
                        </td>
                        <td className="p-3 font-mono text-muted-foreground">{rec.expiry_date || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        {/* Tab 2: Due Vaccines */}
        {activeTab === "due" && (
          <div className="p-4">
            {dueCount === 0 ? (
              <div className="text-center py-12 text-muted-foreground text-xs">
                <CheckCircle2 className="h-8 w-8 mx-auto mb-2 text-emerald-500 opacity-60" />
                All scheduled vaccines for the patient&apos;s current age milestone have been administered.
              </div>
            ) : (
              <div className="space-y-3">
                {schedule?.due_vaccines.map((v) => (
                  <div
                    key={v.vaccine_id}
                    className="flex items-center justify-between p-3.5 rounded-xl border border-border bg-background hover:border-primary/40 transition-colors"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-sm text-foreground">{v.vaccine_name}</span>
                        <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground">
                          {v.vaccine_code}
                        </span>
                        <span className="rounded-full bg-amber-500/10 px-2 py-0.5 text-[10px] font-semibold text-amber-600 dark:text-amber-400">
                          Due Dose {v.dose_number}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">
                        Recommended milestone: {v.due_at_months} months • Route: {v.route}
                      </p>
                    </div>
                    <button
                      onClick={onOpenRecordModal}
                      className="rounded-lg bg-primary/10 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary hover:text-primary-foreground transition-colors"
                    >
                      Administer
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tab 3: Overdue */}
        {activeTab === "overdue" && (
          <div className="p-4">
            {overdueCount === 0 ? (
              <div className="text-center py-12 text-muted-foreground text-xs">
                <CheckCircle2 className="h-8 w-8 mx-auto mb-2 text-emerald-500 opacity-60" />
                No overdue vaccines. All schedule deadlines are up to date!
              </div>
            ) : (
              <div className="space-y-3">
                {schedule?.overdue_vaccines.map((v) => (
                  <div
                    key={v.vaccine_id}
                    className="flex items-center justify-between p-3.5 rounded-xl border border-destructive/30 bg-destructive/5 hover:border-destructive/60 transition-colors"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-sm text-foreground">{v.vaccine_name}</span>
                        <span className="rounded bg-destructive/20 px-1.5 py-0.5 text-[10px] font-mono text-destructive">
                          {v.vaccine_code}
                        </span>
                        <span className="rounded-full bg-destructive/10 px-2 py-0.5 text-[10px] font-semibold text-destructive">
                          Overdue • Dose {v.dose_number}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground mt-1">
                        Required milestone was {v.due_at_months} months • Route: {v.route}
                      </p>
                    </div>
                    <button
                      onClick={onOpenRecordModal}
                      className="rounded-lg bg-destructive px-3 py-1.5 text-xs font-semibold text-destructive-foreground hover:bg-destructive/90 transition-colors"
                    >
                      Catch-up Now
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
