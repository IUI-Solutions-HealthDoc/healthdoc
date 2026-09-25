"use client";

import Link from "next/link";
import { useEffect, useState, useCallback, useMemo } from "react";

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
import { PageHeading } from "@/components/common/PageHeading";
import { ApiError, formatDateTime } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

const initial: EmergencyPatientInput = {
  full_name: "",
  sex: "unknown",
  age_years: 0,
  mobile: "",
};

export default function Page() {
  const { t } = useLocale();
  const acuityStyles = useMemo(
    (): Record<EmergencyAcuity, { label: string; badge: string; border: string }> => ({
      resuscitation: {
        label: t("emergency.acuityBadgeP1"),
        badge: "bg-red-600 text-white font-bold",
        border: "border-l-4 border-red-600",
      },
      emergent: {
        label: t("emergency.acuityBadgeP2"),
        badge: "bg-orange-500 text-white font-bold",
        border: "border-l-4 border-orange-500",
      },
      urgent: {
        label: t("emergency.acuityBadgeP3"),
        badge: "bg-amber-400 text-slate-900 font-semibold",
        border: "border-l-4 border-amber-400",
      },
      non_urgent: {
        label: t("emergency.acuityBadgeP4"),
        badge: "bg-emerald-600 text-white font-medium",
        border: "border-l-4 border-emerald-600",
      },
    }),
    [t],
  );

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
      setError(err instanceof ApiError ? err.message : t("emergency.errLoadBoard"));
    } finally {
      setBoardLoading(false);
    }
  }, [t]);

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
      setError(reason instanceof ApiError ? reason.message : t("emergency.errRegistrationFailed"));
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
      setError(reason instanceof ApiError ? reason.message : t("emergency.errCreateVisit"));
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
      setError(t("emergency.errChiefComplaintRequired"));
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
      setError(err instanceof ApiError ? err.message : t("emergency.errSaveTriage"));
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
      setError(t("emergency.errRetriageMinChars"));
      return;
    }

    setRetriageSubmitting(true);
    setError(null);
    try {
      await reTriageEmergencyPatient(retriageTarget.id, retriageAcuity, retriageReason.trim());
      setRetriageModalOpen(false);
      void loadBoardData();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("emergency.errRetriage"));
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
      setError(err instanceof ApiError ? err.message : t("emergency.errMarkSeen"));
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
      setError(err instanceof ApiError ? err.message : t("emergency.errDisposition"));
    } finally {
      setDispositionSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Header & Tabs */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <PageHeading titleKey="emergency.title" titleClassName="text-2xl font-bold tracking-tight" />

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
            {t("emergency.tabBoard")}
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
            {t("emergency.tabRegistration")}
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
            <span className="text-xs text-muted-foreground uppercase font-semibold">{t("emergency.metricActiveCensus")}</span>
            <div className="mt-1 text-2xl font-bold text-foreground">{metrics.active_census}</div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {t("emergency.metricWaitingInTx", { waiting: metrics.waiting_count, inTx: metrics.in_treatment_count })}
            </div>
          </div>

          <div className="surface-card p-4 rounded-lg border border-border">
            <span className="text-xs text-muted-foreground uppercase font-semibold">{t("emergency.metricHighAcuity")}</span>
            <div className="mt-1 text-2xl font-bold text-danger">
              {metrics.resuscitation_count + metrics.emergent_count}
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">
              {t("emergency.metricP1P2", { p1: metrics.resuscitation_count, p2: metrics.emergent_count })}
            </div>
          </div>

          <div className="surface-card p-4 rounded-lg border border-border">
            <span className="text-xs text-muted-foreground uppercase font-semibold">{t("emergency.metricDoorToClinician")}</span>
            <div className="mt-1 text-2xl font-bold text-foreground">
              {metrics.avg_door_to_clinician_minutes !== null
                ? `${metrics.avg_door_to_clinician_minutes}m`
                : "—"}
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">{t("emergency.metricFacilityAverage")}</div>
          </div>

          <div className="surface-card p-4 rounded-lg border border-border">
            <span className="text-xs text-muted-foreground uppercase font-semibold">{t("emergency.metricLwbsRate")}</span>
            <div className="mt-1 text-2xl font-bold text-foreground">
              {metrics.active_census + metrics.lwbs_count > 0
                ? ((metrics.lwbs_count / (metrics.active_census + metrics.lwbs_count)) * 100).toFixed(1)
                : "0.0"}%
            </div>
            <div className="text-xs text-muted-foreground mt-0.5">{t("emergency.metricLwbsCount", { count: metrics.lwbs_count })}</div>
          </div>
        </div>
      )}

      {/* Tab 1: Active Triage Board */}
      {activeTab === "board" && (
        <section className="space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold">{t("emergency.boardTitle")}</h2>
              <p className="text-xs text-muted-foreground">{t("emergency.boardSubtitle")}</p>
            </div>
            <button
              type="button"
              onClick={() => void loadBoardData()}
              disabled={boardLoading}
              className="text-xs text-primary underline hover:text-primary/80"
            >
              {boardLoading ? t("emergency.refreshingBoard") : t("emergency.refreshBoard")}
            </button>
          </div>

          {triages.length === 0 ? (
            <div className="surface-card p-8 text-center text-sm text-muted-foreground">
              {boardLoading ? t("emergency.loadingBoard") : t("emergency.boardEmpty")}
            </div>
          ) : (
            <div className="surface-card overflow-hidden rounded-lg border border-border">
              <div className="overflow-x-auto">
                <table className="min-w-full border-collapse text-sm">
                  <thead className="bg-muted">
                    <tr>
                      <th className="px-4 py-3 text-left">{t("emergency.colAcuity")}</th>
                      <th className="px-4 py-3 text-left">{t("emergency.colPatientComplaint")}</th>
                      <th className="px-4 py-3 text-left">{t("emergency.colBayClinician")}</th>
                      <th className="px-4 py-3 text-left">{t("emergency.colStatus")}</th>
                      <th className="px-4 py-3 text-left">{t("emergency.colDoorToClinician")}</th>
                      <th className="px-4 py-3 text-right">{t("emergency.colActions")}</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {triages.map((tr) => {
                      const acuityInfo = acuityStyles[tr.acuity_level] ?? acuityStyles.urgent;
                      return (
                        <tr key={tr.id} className={`hover:bg-muted/20 transition-colors ${acuityInfo.border}`}>
                          <td className="px-4 py-3">
                            <span className={`inline-block rounded-full px-2.5 py-1 text-xs ${acuityInfo.badge}`}>
                              {tr.acuity_level.toUpperCase()}
                            </span>
                            <div className="text-[10px] text-muted-foreground mt-1">
                              {t("emergency.triagedAt", { time: formatDateTime(tr.triaged_at) })}
                            </div>
                          </td>

                          <td className="px-4 py-3">
                            <div className="font-semibold text-foreground">{tr.chief_complaint}</div>
                            {tr.triage_notes && (
                              <p className="text-xs text-muted-foreground mt-0.5 max-w-sm">{tr.triage_notes}</p>
                            )}
                            <div className="text-[11px] text-muted-foreground mt-1 font-mono">
                              Patient: {tr.patient_id.slice(0, 8)}… · Visit: {tr.visit_id.slice(0, 8)}…
                            </div>
                          </td>

                          <td className="px-4 py-3">
                            <div className="font-medium">
                              {t("emergency.bay", { bay: tr.assigned_bay || t("common.unassigned") })}
                            </div>
                            <div className="text-xs text-muted-foreground mt-0.5">
                              {tr.assigned_doctor_id
                                ? `Doctor: ${tr.assigned_doctor_id.slice(0, 8)}…`
                                : t("emergency.noDoctorAssigned")}
                            </div>
                          </td>

                          <td className="px-4 py-3">
                            <span className="capitalize rounded bg-muted px-2 py-0.5 text-xs font-medium">
                              {tr.status.replace("_", " ")}
                            </span>
                            {tr.disposition && (
                              <div className="text-xs font-semibold text-primary mt-1 capitalize">
                                Disp: {tr.disposition}
                              </div>
                            )}
                          </td>

                          <td className="px-4 py-3">
                            {tr.clinician_seen_at ? (
                              <span className="inline-flex items-center gap-1 text-emerald-600 font-medium text-xs">
                                {t("emergency.seenIn", { minutes: tr.door_to_clinician_minutes ?? 0 })}
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 text-amber-600 font-medium text-xs">
                                {t("emergency.waitingForClinician")}
                              </span>
                            )}
                          </td>

                          <td className="px-4 py-3 text-right">
                            <div className="flex items-center justify-end gap-2 flex-wrap">
                              {!tr.clinician_seen_at && tr.status === "waiting" && (
                                <button
                                  type="button"
                                  onClick={() => void handleMarkSeen(tr)}
                                  className="rounded bg-emerald-600 text-white px-2 py-1 text-xs font-medium hover:bg-emerald-700"
                                >
                                  {t("emergency.markSeen")}
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={() => handleOpenRetriage(tr)}
                                className="rounded border border-border bg-background px-2 py-1 text-xs font-medium hover:bg-muted"
                              >
                                {t("emergency.reTriage")}
                              </button>
                              <button
                                type="button"
                                onClick={() => handleOpenDisposition(tr)}
                                className="rounded border border-border bg-background px-2 py-1 text-xs font-medium hover:bg-muted"
                              >
                                {t("emergency.disposition")}
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
            <h2 className="text-xl font-semibold">{t("emergency.registrationTitle")}</h2>
            <p className="mt-1 text-sm text-muted-foreground">{t("emergency.registrationSubtitle")}</p>
          </div>

          {created ? (
            <section className="surface-card border border-success p-6 space-y-4" aria-live="polite">
              <div>
                <p className="text-sm text-muted-foreground">{t("emergency.thidIssued")}</p>
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
                  <p className="font-semibold text-success">
                    {t("emergency.visitActive", { visitNumber: createdVisit.visit_number })}
                  </p>
                  <p className="text-xs text-muted-foreground">{t("emergency.readyForTriage")}</p>
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
                      {t("emergency.goToBoard")}
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
                    {visitBusy ? t("emergency.startingVisit") : t("emergency.startVisit")}
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
                  {t("emergency.registerAnother")}
                </button>
              </div>
            </section>
          ) : (
            <form onSubmit={submitRegistration} className="surface-card space-y-5 p-6">
              <label className="block space-y-1 text-sm">
                <span className="text-muted-foreground">{t("emergency.nameOptional")}</span>
                <input
                  className="w-full rounded-md border border-border px-3 py-2 text-foreground bg-background"
                  value={form.full_name ?? ""}
                  onChange={(event) => setForm((current) => ({ ...current, full_name: event.target.value }))}
                />
              </label>
              <div className="grid gap-4 sm:grid-cols-2">
                <label className="block space-y-1 text-sm">
                  <span className="text-muted-foreground">{t("field.sex")}</span>
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
                    <option value="unknown">{t("emergency.sexUnknown")}</option>
                    <option value="female">{t("emergency.sexFemale")}</option>
                    <option value="male">{t("emergency.sexMale")}</option>
                    <option value="other">{t("emergency.sexOther")}</option>
                  </select>
                </label>
                <label className="block space-y-1 text-sm">
                  <span className="text-muted-foreground">{t("emergency.estimatedAge")}</span>
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
                <span className="text-muted-foreground">{t("emergency.mobileOptional")}</span>
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
                {busy ? t("emergency.issuingThid") : t("emergency.registerThid")}
              </button>
            </form>
          )}

          <section className="space-y-4 pt-4 border-t border-border">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold">{t("emergency.arrivalsTitle")}</h3>
                <p className="text-xs text-muted-foreground">{t("emergency.arrivalsSubtitle")}</p>
              </div>
              <button
                type="button"
                onClick={() => void loadWorklist()}
                disabled={worklistLoading}
                className="text-xs text-primary underline hover:text-primary/80"
              >
                {worklistLoading ? t("emergency.refreshingArrivals") : t("emergency.refreshArrivals")}
              </button>
            </div>

            {worklist.length === 0 ? (
              <div className="surface-card p-6 text-center text-sm text-muted-foreground">
                {worklistLoading ? t("emergency.loadingArrivals") : t("emergency.noArrivals")}
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
                        {t("emergency.triagePatient")}
                      </button>
                      <Link
                        href={`/doctor/consultation?visit_id=${item.visit_id}`}
                        className="rounded-md bg-primary text-white px-3 py-1.5 text-xs font-medium hover:bg-primary/90"
                      >
                        {t("emergency.consultation")}
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
                <h3 className="text-lg font-semibold">{t("emergency.triageModalTitle")}</h3>
                <p className="text-xs text-muted-foreground">
                  {triageTargetArrival.full_name} ({triageTargetArrival.thid ?? triageTargetArrival.uhid ?? "Arrival"})
                </p>
              </div>
              <button type="button" onClick={() => setTriageModalOpen(false)} className="text-muted-foreground hover:text-foreground">✕</button>
            </div>

            <form onSubmit={handleSubmitTriage} className="space-y-4 text-sm">
              <label className="block space-y-1">
                <span className="font-medium text-foreground">{t("emergency.acuityLevel")}</span>
                <select
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                  value={triageAcuity}
                  onChange={(e) => setTriageAcuity(e.target.value as EmergencyAcuity)}
                >
                  <option value="resuscitation">{t("emergency.acuityP1")}</option>
                  <option value="emergent">{t("emergency.acuityP2")}</option>
                  <option value="urgent">{t("emergency.acuityP3")}</option>
                  <option value="non_urgent">{t("emergency.acuityP4")}</option>
                </select>
              </label>

              <label className="block space-y-1">
                <span className="font-medium text-foreground">{t("emergency.chiefComplaint")}</span>
                <input
                  type="text"
                  required
                  placeholder={t("emergency.placeholderChiefComplaint")}
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                  value={triageComplaint}
                  onChange={(e) => setTriageComplaint(e.target.value)}
                />
              </label>

              <div className="grid grid-cols-2 gap-4">
                <label className="block space-y-1">
                  <span className="font-medium text-foreground">{t("emergency.assignedBay")}</span>
                  <input
                    type="text"
                    placeholder={t("emergency.placeholderBay")}
                    className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                    value={triageBay}
                    onChange={(e) => setTriageBay(e.target.value)}
                  />
                </label>
              </div>

              <label className="block space-y-1">
                <span className="font-medium text-foreground">{t("emergency.triageNotesOptional")}</span>
                <textarea
                  rows={3}
                  placeholder={t("emergency.placeholderTriageNotes")}
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
                  {t("common.cancel")}
                </button>
                <button
                  type="submit"
                  disabled={triageSubmitting}
                  className="rounded-md bg-primary px-4 py-2 text-white hover:bg-primary/90 disabled:opacity-50"
                >
                  {triageSubmitting ? t("emergency.savingTriage") : t("emergency.saveTriage")}
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
                <h3 className="text-lg font-semibold">{t("emergency.retriageTitle")}</h3>
                <p className="text-xs text-muted-foreground">
                  {t("emergency.currentAcuity")}{" "}
                  <span className="font-semibold uppercase">{retriageTarget.acuity_level}</span>
                </p>
              </div>
              <button type="button" onClick={() => setRetriageModalOpen(false)} className="text-muted-foreground hover:text-foreground">✕</button>
            </div>

            <form onSubmit={handleSubmitRetriage} className="space-y-4 text-sm">
              <label className="block space-y-1">
                <span className="font-medium text-foreground">{t("emergency.newAcuityLevel")}</span>
                <select
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                  value={retriageAcuity}
                  onChange={(e) => setRetriageAcuity(e.target.value as EmergencyAcuity)}
                >
                  <option value="resuscitation">{t("emergency.acuityP1")}</option>
                  <option value="emergent">{t("emergency.acuityP2")}</option>
                  <option value="urgent">{t("emergency.acuityP3")}</option>
                  <option value="non_urgent">{t("emergency.acuityP4")}</option>
                </select>
              </label>

              <label className="block space-y-1">
                <span className="font-medium text-danger">{t("emergency.retriageJustification")}</span>
                <textarea
                  rows={3}
                  required
                  minLength={10}
                  placeholder={t("emergency.placeholderRetriageJustification")}
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                  value={retriageReason}
                  onChange={(e) => setRetriageReason(e.target.value)}
                />
                <span className="text-[11px] text-muted-foreground">
                  {t("emergency.retriageMinChars", { count: retriageReason.length })}
                </span>
              </label>

              <div className="flex justify-end gap-3 pt-3 border-t border-border">
                <button
                  type="button"
                  onClick={() => setRetriageModalOpen(false)}
                  className="rounded-md border border-border px-4 py-2 hover:bg-muted"
                >
                  {t("common.cancel")}
                </button>
                <button
                  type="submit"
                  disabled={retriageSubmitting}
                  className="rounded-md bg-primary px-4 py-2 text-white hover:bg-primary/90 disabled:opacity-50"
                >
                  {retriageSubmitting ? t("emergency.updatingAcuity") : t("emergency.confirmRetriage")}
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
                <h3 className="text-lg font-semibold">{t("emergency.dispositionModalTitle")}</h3>
                <p className="text-xs text-muted-foreground">{t("emergency.dispositionModalSubtitle")}</p>
              </div>
              <button type="button" onClick={() => setDispositionModalOpen(false)} className="text-muted-foreground hover:text-foreground">✕</button>
            </div>

            <form onSubmit={handleSubmitDisposition} className="space-y-4 text-sm">
              <label className="block space-y-1">
                <span className="font-medium text-foreground">{t("emergency.dispositionDecision")}</span>
                <select
                  className="w-full rounded-md border border-border bg-background px-3 py-2 text-foreground"
                  value={dispositionType}
                  onChange={(e) => setDispositionType(e.target.value as EmergencyDisposition)}
                >
                  <option value="discharge">{t("emergency.dispDischargeHome")}</option>
                  <option value="admit">{t("emergency.dispAdmit")}</option>
                  <option value="transfer">{t("emergency.dispTransfer")}</option>
                  <option value="lwbs">{t("emergency.dispLwbs")}</option>
                </select>
              </label>

              <label className="block space-y-1">
                <span className="font-medium text-foreground">{t("emergency.dispositionNotes")}</span>
                <textarea
                  rows={3}
                  placeholder={t("emergency.placeholderDispositionNotes")}
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
                  {t("common.cancel")}
                </button>
                <button
                  type="submit"
                  disabled={dispositionSubmitting}
                  className="rounded-md bg-primary px-4 py-2 text-white hover:bg-primary/90 disabled:opacity-50"
                >
                  {dispositionSubmitting ? t("emergency.recording") : t("emergency.finalizeDisposition")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
