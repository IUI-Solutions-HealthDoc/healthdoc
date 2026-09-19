"use client";

import Link from "next/link";
import { useEffect, useState, useCallback } from "react";

import {
  createEmergencyVisit,
  listEmergencyWorklist,
  registerEmergencyPatient,
  listEmergencyTriages,
  getEmergencyMetrics,
  createEmergencyTriage,
  reTriageEmergencyPatient,
  updateEmergencyTriage,
  type EmergencyPatient,
  type EmergencyPatientInput,
  type EmergencyVisitResult,
  type EmergencyWorklistItem,
  type EmergencyTriageOut,
  type EmergencyMetricsOut,
  type EmergencyAcuity,
  type EmergencyTriageStatus,
  type EmergencyDisposition,
} from "@/features/emergency/api";
import { ApiError, formatDateTime } from "@/lib/api";

const initial: EmergencyPatientInput = {
  full_name: "",
  sex: "unknown",
  age_years: 0,
  mobile: "",
};

const ACUITY_STYLES: Record<EmergencyAcuity, { label: string; badge: string; border: string }> = {
  resuscitation: {
    label: "P1 Resuscitation (Immediate)",
    badge: "bg-red-600 text-white font-bold",
    border: "border-l-4 border-red-600",
  },
  emergent: {
    label: "P2 Emergent (<15m)",
    badge: "bg-orange-500 text-white font-bold",
    border: "border-l-4 border-orange-500",
  },
  urgent: {
    label: "P3 Urgent (<60m)",
    badge: "bg-amber-400 text-slate-900 font-semibold",
    border: "border-l-4 border-amber-400",
  },
  non_urgent: {
    label: "P4 Non-urgent (Routine)",
    badge: "bg-emerald-600 text-white font-medium",
    border: "border-l-4 border-emerald-600",
  },
};

export default function Page() {
  const [activeTab, setActiveTab] = useState<"board" | "registration">("board");

  // Registration states
  const [form, setForm] = useState<EmergencyPatientInput>(initial);
  const [created, setCreated] = useState<EmergencyPatient | null>(null);
  const [createdVisit, setCreatedVisit] = useState<EmergencyVisitResult | null>(null);
  const [worklist, setWorklist] = useState<EmergencyWorklistItem[]>([]);
  const [worklistLoading, setWorklistLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [visitBusy, setVisitBusy] = useState(false);

  // Triage board & Metrics states (HD-18)
  const [triages, setTriages] = useState<EmergencyTriageOut[]>([]);
  const [metrics, setMetrics] = useState<EmergencyMetricsOut | null>(null);
  const [boardLoading, setBoardLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Triage Creation Modal
  const [triageModalOpen, setTriageModalOpen] = useState(false);
  const [triageTargetArrival, setTriageTargetArrival] = useState<EmergencyWorklistItem | null>(null);
  const [triageAcuity, setTriageAcuity] = useState<EmergencyAcuity>("urgent");
  const [triageComplaint, setTriageComplaint] = useState("");
  const [triageNotes, setTriageNotes] = useState("");
  const [triageBay, setTriageBay] = useState("");
  const [triageSubmitting, setTriageSubmitting] = useState(false);

  // Re-triage Modal
  const [retriageModalOpen, setRetriageModalOpen] = useState(false);
  const [retriageTarget, setRetriageTarget] = useState<EmergencyTriageOut | null>(null);
  const [retriageAcuity, setRetriageAcuity] = useState<EmergencyAcuity>("urgent");
  const [retriageReason, setRetriageReason] = useState("");
  const [retriageSubmitting, setRetriageSubmitting] = useState(false);

  // Disposition Modal
  const [dispositionModalOpen, setDispositionModalOpen] = useState(false);
  const [dispositionTarget, setDispositionTarget] = useState<EmergencyTriageOut | null>(null);
  const [dispositionType, setDispositionType] = useState<EmergencyDisposition>("discharge");
  const [dispositionNotes, setDispositionNotes] = useState("");
  const [dispositionSubmitting, setDispositionSubmitting] = useState(false);

  const loadBoardData = useCallback(async () => {
    setBoardLoading(true);
    try {
      const [triageRows, metricsData] = await Promise.all([
        listEmergencyTriages(),
        getEmergencyMetrics(),
      ]);
      setTriages(triageRows);
      setMetrics(metricsData);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load triage board");
    } finally {
      setBoardLoading(false);
    }
  }, []);

  async function loadWorklist() {
    setWorklistLoading(true);
    try {
      const items = await listEmergencyWorklist();
      setWorklist(items);
    } catch {
      // Non-blocking
    } finally {
      setWorklistLoading(false);
    }
  }

  useEffect(() => {
    void loadBoardData();
    void loadWorklist();
  }, [loadBoardData]);

  async function submitRegistration(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setCreatedVisit(null);
    try {
      const patient = await registerEmergencyPatient({
        ...form,
        full_name: form.full_name?.trim() || undefined,
        mobile: form.mobile?.trim() || undefined,
      });
      setCreated(patient);
      setForm(initial);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Emergency registration failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleStartEmergencyVisit() {
    if (!created) return;
    setVisitBusy(true);
    setError(null);
    try {
      const v = await createEmergencyVisit(created.id);
      setCreatedVisit(v);
      void loadWorklist();
      void loadBoardData();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Failed to create emergency visit");
    } finally {
      setVisitBusy(false);
    }
  }

  function handleOpenTriage(arrival: EmergencyWorklistItem) {
    setTriageTargetArrival(arrival);
    setTriageAcuity("urgent");
    setTriageComplaint("");
    setTriageNotes("");
    setTriageBay("");
    setTriageModalOpen(true);
  }

  async function handleSubmitTriage(e: React.FormEvent) {
    e.preventDefault();
    if (!triageTargetArrival) return;
    if (!triageComplaint.trim()) {
      setError("Chief complaint is required for triage.");
      return;
    }

    setTriageSubmitting(true);
    setError(null);
    try {
      await createEmergencyTriage({
        patient_id: triageTargetArrival.patient_id,
        visit_id: triageTargetArrival.visit_id,
        acuity_level: triageAcuity,
        chief_complaint: triageComplaint.trim(),
        triage_notes: triageNotes.trim() || null,
        assigned_bay: triageBay.trim() || null,
      });
      setTriageModalOpen(false);
      void loadBoardData();
      void loadWorklist();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to save triage assessment");
    } finally {
      setTriageSubmitting(false);
    }
  }

  function handleOpenRetriage(triage: EmergencyTriageOut) {
    setRetriageTarget(triage);
    setRetriageAcuity(triage.acuity_level);
    setRetriageReason("");
    setRetriageModalOpen(true);
  }

  async function handleSubmitRetriage(e: React.FormEvent) {
    e.preventDefault();
    if (!retriageTarget) return;
    if (!retriageReason.trim() || retriageReason.trim().length < 10) {
      setError("Re-triage justification must be at least 10 characters.");
      return;
    }

    setRetriageSubmitting(true);
    setError(null);
    try {
      await reTriageEmergencyPatient(retriageTarget.id, retriageAcuity, retriageReason.trim());
      setRetriageModalOpen(false);
      void loadBoardData();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to re-triage patient");
    } finally {
      setRetriageSubmitting(false);
    }
  }

  async function handleMarkSeen(triage: EmergencyTriageOut) {
    try {
      await updateEmergencyTriage(triage.id, {
        status: "in_treatment",
        clinician_seen_at: new Date().toISOString(),
      });
      void loadBoardData();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to record clinician seen timestamp");
    }
  }

  function handleOpenDisposition(triage: EmergencyTriageOut) {
    setDispositionTarget(triage);
    setDispositionType("discharge");
    setDispositionNotes("");
    setDispositionModalOpen(true);
  }

  async function handleSubmitDisposition(e: React.FormEvent) {
    e.preventDefault();
    if (!dispositionTarget) return;

    setDispositionSubmitting(true);
    setError(null);
    try {
      const statusMap: Record<EmergencyDisposition, EmergencyTriageStatus> = {
        admit: "admitted",
        discharge: "discharged",
        lwbs: "lwbs",
        transfer: "discharged",
      };
      await updateEmergencyTriage(dispositionTarget.id, {
        status: statusMap[dispositionType],
        disposition: dispositionType,
        disposition_notes: dispositionNotes.trim() || null,
      });
      setDispositionModalOpen(false);
      void loadBoardData();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to record disposition");
    } finally {
      setDispositionSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Header & Tabs */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Emergency registration & arrivals</h1>
          <p className="text-sm text-muted-foreground">
            Acuity Triage Tracking Board, Door-to-Clinician Intervals, and Fast-Track THID Registration.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setActiveTab("board")}
            className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === "board"
                ? "bg-primary text-white shadow-sm"
                : "bg-muted text-foreground hover:bg-muted/80"
            }`}
          >
            Triage Tracking Board
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("registration")}
            className={`rounded-md px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === "registration"
                ? "bg-primary text-white shadow-sm"
                : "bg-muted text-foreground hover:bg-muted/80"
            }`}
          >
            Emergency registration
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="rounded-md bg-danger/10 border border-danger/30 p-3 text-sm text-danger">
          {error}
        </div>
      )}

      {/* KPI Metrics Banner (HD-18) */}
      {metrics && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="surface-card p-4 rounded-lg border border-border">
            <span className="text-xs text-muted-foreground uppercase font-semibold">Active Census</span>
            <div className="mt-1 text-2xl font-bold text-foreground">{metrics.active_census}</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              Waiting: {metrics.waiting_count} · In Tx: {metrics.in_treatment_count}
            </div>
          </div>

          <div className="surface-card p-4 rounded-lg border border-border">
            <span className="text-xs text-muted-foreground uppercase font-semibold">High Acuity (P1/P2)</span>
            <div className="mt-1 text-2xl font-bold text-danger">
              {metrics.resuscitation_count + metrics.emergent_count}
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">
              P1: {metrics.resuscitation_count} · P2: {metrics.emergent_count}
            </div>
          </div>

          <div className="surface-card p-4 rounded-lg border border-border">
            <span className="text-xs text-muted-foreground uppercase font-semibold">Door-to-Clinician</span>
            <div className="mt-1 text-2xl font-bold text-foreground">
              {metrics.avg_door_to_clinician_minutes !== null
                ? `${metrics.avg_door_to_clinician_minutes}m`
                : "—"}
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">Facility average</div>
          </div>

          <div className="surface-card p-4 rounded-lg border border-border">
            <span className="text-xs text-muted-foreground uppercase font-semibold">LWBS Rate</span>
            <div className="mt-1 text-2xl font-bold text-foreground">
              {metrics.active_census + metrics.lwbs_count > 0
                ? ((metrics.lwbs_count / (metrics.active_census + metrics.lwbs_count)) * 100).toFixed(1)
                : "0.0"}%
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">{metrics.lwbs_count} left without being seen</div>
          </div>
        </div>
      )}

      {/* Tab 1: Active Triage Board */}
      {activeTab === "board" && (
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">Active Triage Board</h2>
              <p className="text-xs text-muted-foreground">
                Live patient acuity status, bay allocations, and clinical intervals.
              </p>
            </div>
            <button
              type="button"
              onClick={() => void loadBoardData()}
              disabled={boardLoading}
              className="text-xs text-primary underline hover:text-primary/80"
            >
              {boardLoading ? "Refreshing board…" : "Refresh board"}
            </button>
          </div>

          {triages.length === 0 ? (
            <div className="surface-card p-8 text-center text-sm text-muted-foreground">
              {boardLoading ? "Loading triage board…" : "No active triaged patients in the Emergency Department."}
            </div>
          ) : (
            <div className="surface-card overflow-hidden rounded-lg border border-border">
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-sm">
                  <thead className="bg-muted">
                    <tr>
                      <th className="px-4 py-3 text-left">Acuity</th>
                      <th className="px-4 py-3 text-left">Patient & Complaint</th>
                      <th className="px-4 py-3 text-left">Bay / Clinician</th>
                      <th className="px-4 py-3 text-left">Status</th>
                      <th className="px-4 py-3 text-left">Door-to-Clinician</th>
                      <th className="px-4 py-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {triages.map((t) => {
                      const acuityInfo = ACUITY_STYLES[t.acuity_level] ?? ACUITY_STYLES.urgent;
                      return (
                        <tr key={t.id} className={`hover:bg-muted/20 transition-colors ${acuityInfo.border}`}>
                          <td className="px-4 py-3">
                            <span className={`inline-block rounded-full px-2.5 py-1 text-xs ${acuityInfo.badge}`}>
                              {t.acuity_level.toUpperCase()}
                            </span>
                            <div className="text-[10px] text-muted-foreground mt-1">
                              Triaged {formatDateTime(t.triaged_at)}
                            </div>
                          </td>

                          <td className="px-4 py-3">
                            <div className="font-semibold text-foreground">
                              {t.chief_complaint}
                            </div>
                            {t.triage_notes && (
                              <p className="text-xs text-muted-foreground mt-0.5 max-w-sm">
                                {t.triage_notes}
                              </p>
                            )}
                            <div className="text-[11px] text-muted-foreground mt-1 font-mono">
                              Patient: {t.patient_id.slice(0, 8)}… · Visit: {t.visit_id.slice(0, 8)}…
                            </div>
                          </td>

                          <td className="px-4 py-3">
                            <div className="font-medium">
                              Bay: {t.assigned_bay || "Unassigned"}
                            </div>
                            <div className="text-xs text-muted-foreground mt-0.5">
                              {t.assigned_doctor_id ? `Doctor: ${t.assigned_doctor_id.slice(0, 8)}…` : "No doctor assigned"}
                            </div>
                          </td>

                          <td className="px-4 py-3">
                            <span className="capitalize rounded bg-muted px-2 py-0.5 text-xs font-medium">
                              {t.status.replace("_", " ")}
                            </span>
                            {t.disposition && (
                              <div className="text-xs font-semibold text-primary mt-1 capitalize">
                                Disp: {t.disposition}
                              </div>
                            )}
                          </td>

                          <td className="px-4 py-3">
                            {t.clinician_seen_at ? (
                              <span className="inline-flex items-center gap-1 text-emerald-600 font-medium text-xs">
                                ✓ Seen in {t.door_to_clinician_minutes ?? 0}m
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-amber-600 font-medium text-xs">
                                ⏱ Waiting for clinician
                              </span>
                            )}
                          </td>

                          <td className="px-4 py-3 text-right">
                            <div className="flex items-center justify-end gap-2 flex-wrap">
                              {!t.clinician_seen_at && t.status === "waiting" && (
                                <button
                                  type="button"
                                  onClick={() => void handleMarkSeen(t)}
                                  className="rounded bg-emerald-600 text-white px-2 py-1 text-xs font-medium hover:bg-emerald-700"
                                >
                                  Mark Seen
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={() => handleOpenRetriage(t)}
                                className="rounded border border-border bg-background px-2 py-1 text-xs font-medium hover:bg-muted"
                              >
                                Re-Triage
                              </button>
                              <button
                                type="button"
                                onClick={() => handleOpenDisposition(t)}
                                className="rounded border border-border bg-background px-2 py-1 text-xs font-medium hover:bg-muted"
                              >
                                Disposition
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      )}

      {/* Tab 2: Fast-track Registration & Arrivals */}
      {activeTab === "registration" && (
        <div className="mx-auto max-w-3xl space-y-8">
          <div>
            <h2 className="text-xl font-semibold">Emergency Registration & Fast-Track THID</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Issue a temporary hospital identity (THID) immediately for unscheduled arrivals.
            </p>
          </div>

          {created ? (
            <section className="surface-card border border-success p-6 space-y-4" aria-live="polite">
              <div>
                <p className="text-sm text-muted-foreground">Temporary identity issued</p>
                <p className="mt-1 font-mono text-2xl font-semibold text-primary">{created.thid}</p>
                <p className="mt-1 font-medium">
                  {created.full_name} · estimated age {created.age_years} · {created.sex}
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  Patient ID <span className="font-mono">{created.id}</span>
                </p>
              </div>

              {createdVisit ? (
                <div className="rounded-md border border-success/30 bg-success-muted p-4 space-y-2">
                  <p className="font-semibold text-success">Emergency visit {createdVisit.visit_number} active</p>
                  <p className="text-xs text-muted-foreground">
                    Patient is registered and ready for triage and emergency consultation.
                  </p>
                  <div className="pt-2 flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() => {
                        setActiveTab("board");
                        void loadWorklist();
                        void loadBoardData();
                      }}
                      className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90"
                    >
                      Go to Triage Board
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex flex-wrap items-center gap-3 pt-2">
                  <button
                    type="button"
                    onClick={() => void handleStartEmergencyVisit()}
                    disabled={visitBusy}
                    className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 disabled:opacity-50"
                  >
                    {visitBusy ? "Starting emergency visit…" : "Start Emergency Visit"}
                  </button>
                </div>
              )}

              <div className="pt-2">
                <button
                  type="button"
                  className="text-xs text-muted-foreground underline hover:text-foreground"
                  onClick={() => {
                    setCreated(null);
                    setCreatedVisit(null);
                  }}
                >
                  Register another patient
                </button>
              </div>
            </section>
          ) : (
            <form onSubmit={submitRegistration} className="surface-card space-y-5 p-6">
              <label className="block space-y-1 text-sm">
                <span className="text-muted-foreground">Name (leave blank if unknown)</span>
                <input
                  className="w-full rounded-md border border-border px-3 py-2 text-foreground bg-background"
                  value={form.full_name ?? ""}
                  onChange={(event) => setForm((current) => ({ ...current, full_name: event.target.value }))}
                />
              </label>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block space-y-1 text-sm">
                  <span className="text-muted-foreground">Sex</span>
                  <select
                    className="w-full rounded-md border border-border px-3 py-2 text-foreground bg-background"
                    value={form.sex}
                    onChange={(event) =>
                      setForm((current) => ({
                        ...current,
                        sex: event.target.value as EmergencyPatientInput["sex"],
                      }))
                    }
                  >
                    <option value="unknown">Unknown</option>
                    <option value="female">Female</option>
                    <option value="male">Male</option>
                    <option value="other">Other</option>
                  </select>
                </label>
                <label className="block space-y-1 text-sm">
                  <span className="text-muted-foreground">Estimated age (years)</span>
                  <input
                    type="number"
                    min="0"
                    max="150"
                    required
                    className="w-full rounded-md border border-border px-3 py-2 text-foreground bg-background"
                    value={form.age_years}
                    onChange={(event) =>
                      setForm((current) => ({ ...current, age_years: Number(event.target.value) }))
                    }
                  />
                </label>
              </div>
              <label className="block space-y-1 text-sm">
                <span className="text-muted-foreground">Mobile (optional)</span>
                <input
                  type="tel"
                  className="w-full rounded-md border border-border px-3 py-2 text-foreground bg-background"
                  value={form.mobile ?? ""}
                  onChange={(event) => setForm((current) => ({ ...current, mobile: event.target.value }))}
                />
              </label>
              <button
                type="submit"
                disabled={busy}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                {busy ? "Issuing THID…" : "Register and issue THID"}
              </button>
            </form>
          )}

          <section className="space-y-4 pt-4 border-t border-border">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold">Active Emergency Arrivals</h3>
                <p className="text-xs text-muted-foreground">
                  Un-triaged or active emergency visits awaiting clinical action
                </p>
              </div>
              <button
                type="button"
                onClick={() => void loadWorklist()}
                disabled={worklistLoading}
                className="text-xs text-primary underline hover:text-primary/80"
              >
                {worklistLoading ? "Refreshing…" : "Refresh arrivals"}
              </button>
            </div>

            {worklist.length === 0 ? (
              <div className="surface-card p-6 text-center text-sm text-muted-foreground">
                {worklistLoading ? "Loading arrivals…" : "No active emergency arrivals."}
              </div>
            ) : (
              <div className="surface-card overflow-hidden divide-y divide-border">
                {worklist.map((item) => (
                  <div key={item.visit_id} className="p-4 flex flex-wrap items-center justify-between gap-3 hover:bg-muted/30">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-sm font-semibold text-primary">
                          {item.thid ?? item.uhid ?? "Unknown"}
                        </span>
                        <span className="font-medium text-sm">{item.full_name}</span>
                        <span className="text-xs text-muted-foreground">
                          · {item.age_years ?? "?"}y/{item.sex[0]?.toUpperCase()}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        Visit {item.visit_number} · Arrived {new Date(item.arrival_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => handleOpenTriage(item)}
                        className="rounded-md bg-amber-600 text-white px-3 py-1.5 text-xs font-medium hover:bg-amber-700"
                      >
                        Triage Patient
                      </button>
                      <Link
                        href={`/doctor/consultation?visit_id=${item.visit_id}`}
                        className="rounded-md bg-primary text-white px-3 py-1.5 text-xs font-medium hover:bg-primary/90"
                      >
                        Consultation
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      )}

      {/* Triage Assessment Modal (HD-18) */}
      {triageModalOpen && triageTargetArrival && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true">
          <div className="surface-card w-full max-w-lg rounded-lg border border-border bg-card p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div>
                <h3 className="text-lg font-semibold">Triage Patient Assessment</h3>
                <p className="text-xs text-muted-foreground">
                  {triageTargetArrival.full_name} ({triageTargetArrival.thid ?? triageTargetArrival.uhid ?? "Arrival"})
                </p>
              </div>
              <button type="button" onClick={() => setTriageModalOpen(false)} className="text-muted-foreground hover:text-foreground">✕</button>
            </div>

            <form onSubmit={handleSubmitTriage} className="space-y-4 text-sm">
              <label className="block space-y-1">
                <span className="font-medium text-foreground">Acuity Level</span>
                <select
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                  value={triageAcuity}
                  onChange={(e) => setTriageAcuity(e.target.value as EmergencyAcuity)}
                >
                  <option value="resuscitation">Priority 1 — Resuscitation (Immediate life threat)</option>
                  <option value="emergent">Priority 2 — Emergent (Care within 15 mins)</option>
                  <option value="urgent">Priority 3 — Urgent (Care within 60 mins)</option>
                  <option value="non_urgent">Priority 4 — Non-urgent (Routine)</option>
                </select>
              </label>

              <label className="block space-y-1">
                <span className="font-medium text-foreground">Chief Complaint (Required)</span>
                <input
                  type="text"
                  required
                  placeholder="e.g. Severe chest pain, dyspnea, acute head trauma"
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                  value={triageComplaint}
                  onChange={(e) => setTriageComplaint(e.target.value)}
                />
              </label>

              <div className="grid grid-cols-2 gap-4">
                <label className="block space-y-1">
                  <span className="font-medium text-foreground">Assigned Bay</span>
                  <input
                    type="text"
                    placeholder="e.g. Resus-1, Bay 3"
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                    value={triageBay}
                    onChange={(e) => setTriageBay(e.target.value)}
                  />
                </label>
              </div>

              <label className="block space-y-1">
                <span className="font-medium text-foreground">Triage Notes (Optional)</span>
                <textarea
                  rows={3}
                  placeholder="Primary survey findings, initial vitals, airway/breathing status..."
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                  value={triageNotes}
                  onChange={(e) => setTriageNotes(e.target.value)}
                />
              </label>

              <div className="flex justify-end gap-3 pt-3 border-t border-border">
                <button
                  type="button"
                  onClick={() => setTriageModalOpen(false)}
                  className="rounded-md border border-border px-4 py-2 hover:bg-muted"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={triageSubmitting}
                  className="rounded-md bg-primary px-4 py-2 text-white hover:bg-primary/90 disabled:opacity-50"
                >
                  {triageSubmitting ? "Saving Triage…" : "Save Triage Assessment"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Re-Triage Modal (HD-18) */}
      {retriageModalOpen && retriageTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true">
          <div className="surface-card w-full max-w-lg rounded-lg border border-border bg-card p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div>
                <h3 className="text-lg font-semibold">Re-Triage Patient</h3>
                <p className="text-xs text-muted-foreground">
                  Current Acuity: <span className="font-semibold uppercase">{retriageTarget.acuity_level}</span>
                </p>
              </div>
              <button type="button" onClick={() => setRetriageModalOpen(false)} className="text-muted-foreground hover:text-foreground">✕</button>
            </div>

            <form onSubmit={handleSubmitRetriage} className="space-y-4 text-sm">
              <label className="block space-y-1">
                <span className="font-medium text-foreground">New Acuity Level</span>
                <select
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                  value={retriageAcuity}
                  onChange={(e) => setRetriageAcuity(e.target.value as EmergencyAcuity)}
                >
                  <option value="resuscitation">Priority 1 — Resuscitation (Immediate)</option>
                  <option value="emergent">Priority 2 — Emergent (&lt;15 mins)</option>
                  <option value="urgent">Priority 3 — Urgent (&lt;60 mins)</option>
                  <option value="non_urgent">Priority 4 — Non-urgent (Routine)</option>
                </select>
              </label>

              <label className="block space-y-1">
                <span className="font-medium text-danger">
                  Clinical Justification for Acuity Change (Required, min 10 chars)
                </span>
                <textarea
                  rows={3}
                  required
                  minLength={10}
                  placeholder="Document physiological deterioration, improvement, altered vitals, or changing clinical signs..."
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                  value={retriageReason}
                  onChange={(e) => setRetriageReason(e.target.value)}
                />
                <span className="text-[11px] text-muted-foreground">
                  {retriageReason.length}/10 minimum characters
                </span>
              </label>

              <div className="flex justify-end gap-3 pt-3 border-t border-border">
                <button
                  type="button"
                  onClick={() => setRetriageModalOpen(false)}
                  className="rounded-md border border-border px-4 py-2 hover:bg-muted"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={retriageSubmitting}
                  className="rounded-md bg-primary px-4 py-2 text-white hover:bg-primary/90 disabled:opacity-50"
                >
                  {retriageSubmitting ? "Updating Acuity…" : "Confirm Re-Triage"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Disposition Modal (HD-18) */}
      {dispositionModalOpen && dispositionTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm" role="dialog" aria-modal="true">
          <div className="surface-card w-full max-w-lg rounded-lg border border-border bg-card p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div>
                <h3 className="text-lg font-semibold">Emergency Disposition</h3>
                <p className="text-xs text-muted-foreground">Final outcome and transfer of care</p>
              </div>
              <button type="button" onClick={() => setDispositionModalOpen(false)} className="text-muted-foreground hover:text-foreground">✕</button>
            </div>

            <form onSubmit={handleSubmitDisposition} className="space-y-4 text-sm">
              <label className="block space-y-1">
                <span className="font-medium text-foreground">Disposition Decision</span>
                <select
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                  value={dispositionType}
                  onChange={(e) => setDispositionType(e.target.value as EmergencyDisposition)}
                >
                  <option value="discharge">Discharge Home</option>
                  <option value="admit">Admit to Inpatient Ward / ICU</option>
                  <option value="transfer">Transfer to Higher Center</option>
                  <option value="lwbs">Left Without Being Seen (LWBS)</option>
                </select>
              </label>

              <label className="block space-y-1">
                <span className="font-medium text-foreground">Disposition Notes</span>
                <textarea
                  rows={3}
                  placeholder="Clinical condition upon departure, destination ward, discharge instructions, or transfer details..."
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                  value={dispositionNotes}
                  onChange={(e) => setDispositionNotes(e.target.value)}
                />
              </label>

              <div className="flex justify-end gap-3 pt-3 border-t border-border">
                <button
                  type="button"
                  onClick={() => setDispositionModalOpen(false)}
                  className="rounded-md border border-border px-4 py-2 hover:bg-muted"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={dispositionSubmitting}
                  className="rounded-md bg-primary px-4 py-2 text-white hover:bg-primary/90 disabled:opacity-50"
                >
                  {dispositionSubmitting ? "Recording…" : "Finalize Disposition"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
