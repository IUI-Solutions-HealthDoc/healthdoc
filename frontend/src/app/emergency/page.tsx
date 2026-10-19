"use client";

import { formatAgeSexShort } from "@/lib/format-age";
import Link from "next/link";
import { useEffect, useState, useCallback, useMemo, useRef } from "react";

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
import { toast } from "@/components/ui/toast";
import { ApiError, formatDateTime, newIdempotencyKey } from "@/lib/api";
import { canRoleAccessPath } from "@/lib/auth/routes";
import { useLocale } from "@/lib/i18n";
import { useUserRole } from "@/providers/auth-provider";

/**
 * Age starts empty, not 0: a desk that pressed Register without touching the
 * form saved "estimated age 0", which then read "0 yrs" up to the IPD chart
 * (QA 16 Oct 2026). Acuity and disposition likewise start unchosen.
 */
interface RegistrationDraft {
  full_name: string;
  sex: EmergencyPatientInput["sex"];
  age: string;
  mobile: string;
}

const initial: RegistrationDraft = { full_name: "", sex: "unknown", age: "", mobile: "" };

const MOBILE_RE = /^[6-9]\d{9}$/;

function draftErrors(draft: RegistrationDraft): { age?: true; mobile?: true } {
  const errors: { age?: true; mobile?: true } = {};
  const age = draft.age.trim();
  if (!/^\d{1,3}$/.test(age) || Number(age) > 150) errors.age = true;
  const mobile = draft.mobile.replace(/[\s-]/g, "");
  if (mobile && !MOBILE_RE.test(mobile.replace(/^(\+?91)/, ""))) errors.mobile = true;
  return errors;
}

/** "Unknown (TH-…)" already carries the THID; do not print it twice. */
function nameWithIdentifier(name: string, identifier: string | null | undefined): string {
  if (!identifier || name.includes(identifier)) return name;
  return `${name} (${identifier})`;
}

const FIELD = "w-full rounded-md border px-3 py-2 text-foreground bg-background";
const fieldClass = (invalid: boolean) =>
  `${FIELD} ${invalid ? "border-danger ring-2 ring-danger/30" : "border-border"}`;

function DialogError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div role="alert" className="rounded-md border border-danger/30 bg-danger/10 p-3 text-sm text-danger">
      {message}
    </div>
  );
}

export default function Page() {
  const { t } = useLocale();
  const role = useUserRole();
  const canConsult = canRoleAccessPath(role, "/doctor/consultation");
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

  const statusLabel = (status: EmergencyTriageStatus): string =>
    t(
      ({
        waiting: "emergency.statusWaiting",
        in_treatment: "emergency.statusInTreatment",
        admitted: "emergency.statusAdmitted",
        discharged: "emergency.statusDischarged",
        lwbs: "emergency.statusLwbs",
      } as const)[status] ?? "emergency.statusWaiting",
    );

  const [activeTab, setActiveTab] = useState<"board" | "registration">("board");

  // Registration states
  const [form, setForm] = useState<RegistrationDraft>(initial);
  const [showFormErrors, setShowFormErrors] = useState(false);
  const formErrors = draftErrors(form);
  const [created, setCreated] = useState<EmergencyPatient | null>(null);
  const [createdVisit, setCreatedVisit] = useState<EmergencyVisitResult | null>(null);
  const [worklist, setWorklist] = useState<EmergencyWorklistItem[]>([]);
  const [worklistLoading, setWorklistLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [visitBusy, setVisitBusy] = useState(false);
  // A resend of the same unchanged form keeps its key so the server replays
  // the THID it already issued; any edit is a different registration.
  const registrationAttempt = useRef<{ fingerprint: string; key: string } | null>(null);
  const registrationInFlight = useRef(false);

  // Triage board & Metrics states (HD-18)
  const [triages, setTriages] = useState<EmergencyTriageOut[]>([]);
  const [metrics, setMetrics] = useState<EmergencyMetricsOut | null>(null);
  const [boardLoading, setBoardLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Triage Creation Modal
  const [triageModalOpen, setTriageModalOpen] = useState(false);
  const [triageTargetArrival, setTriageTargetArrival] = useState<EmergencyWorklistItem | null>(null);
  const [triageAcuity, setTriageAcuity] = useState<EmergencyAcuity | "">("");
  const [triageError, setTriageError] = useState<string | null>(null);
  const [triageComplaint, setTriageComplaint] = useState("");
  const [triageNotes, setTriageNotes] = useState("");
  const [triageBay, setTriageBay] = useState("");
  const [triageSubmitting, setTriageSubmitting] = useState(false);

  // Re-triage Modal
  const [retriageModalOpen, setRetriageModalOpen] = useState(false);
  const [retriageTarget, setRetriageTarget] = useState<EmergencyTriageOut | null>(null);
  const [retriageAcuity, setRetriageAcuity] = useState<EmergencyAcuity | "">("");
  const [retriageError, setRetriageError] = useState<string | null>(null);
  const [retriageReason, setRetriageReason] = useState("");
  const [retriageSubmitting, setRetriageSubmitting] = useState(false);

  // Disposition Modal
  const [dispositionModalOpen, setDispositionModalOpen] = useState(false);
  const [dispositionTarget, setDispositionTarget] = useState<EmergencyTriageOut | null>(null);
  const [dispositionType, setDispositionType] = useState<EmergencyDisposition | "">("");
  const [dispositionConfirmed, setDispositionConfirmed] = useState(false);
  const [dispositionError, setDispositionError] = useState<string | null>(null);
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
    if (registrationInFlight.current) return;
    if (Object.keys(draftErrors(form)).length) {
      setShowFormErrors(true);
      return;
    }
    const payload: EmergencyPatientInput = {
      sex: form.sex,
      age_years: Number(form.age.trim()),
      full_name: form.full_name.trim() || undefined,
      mobile: form.mobile.replace(/[\s-]/g, "") || undefined,
    };
    const fingerprint = JSON.stringify(payload);
    if (registrationAttempt.current?.fingerprint !== fingerprint) {
      registrationAttempt.current = { fingerprint, key: newIdempotencyKey() };
    }
    registrationInFlight.current = true;
    setBusy(true);
    setError(null);
    setCreatedVisit(null);
    try {
      const patient = await registerEmergencyPatient(payload, registrationAttempt.current.key);
      registrationAttempt.current = null;
      setCreated(patient);
      setForm(initial);
      setShowFormErrors(false);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("emergency.errRegistrationFailed"));
    } finally {
      registrationInFlight.current = false;
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
    setTriageAcuity("");
    setTriageError(null);
    setError(null);
    setTriageComplaint("");
    setTriageNotes("");
    setTriageBay("");
    setTriageModalOpen(true);
  }

  async function handleSubmitTriage(e: React.FormEvent) {
    e.preventDefault();
    if (!triageTargetArrival) return;
    if (!triageAcuity) {
      setTriageError(t("emergency.errAcuityRequired"));
      return;
    }
    if (!triageComplaint.trim()) {
      setTriageError(t("emergency.errChiefComplaintRequired"));
      return;
    }

    setTriageSubmitting(true);
    setTriageError(null);
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
      toast.success(t("emergency.toastTriageSaved", { name: triageTargetArrival.full_name }));
      void loadBoardData();
      void loadWorklist();
    } catch (err) {
      setTriageError(err instanceof ApiError ? err.message : t("emergency.errSaveTriage"));
    } finally {
      setTriageSubmitting(false);
    }
  }

  function handleOpenRetriage(triage: EmergencyTriageOut) {
    setRetriageTarget(triage);
    // Opening on the current level made Confirm send "no change", which the
    // server refuses; the current level is not offered at all.
    setRetriageAcuity("");
    setRetriageReason("");
    setRetriageError(null);
    setError(null);
    setRetriageModalOpen(true);
  }

  async function handleSubmitRetriage(e: React.FormEvent) {
    e.preventDefault();
    if (!retriageTarget) return;
    if (!retriageAcuity) {
      setRetriageError(t("emergency.errAcuityRequired"));
      return;
    }
    if (retriageReason.trim().length < 10) {
      setRetriageError(t("emergency.errRetriageMinChars"));
      return;
    }

    setRetriageSubmitting(true);
    setRetriageError(null);
    try {
      await reTriageEmergencyPatient(retriageTarget.id, retriageAcuity, retriageReason.trim());
      setRetriageModalOpen(false);
      toast.success(t("emergency.toastRetriaged", { name: retriageTarget.patient_name ?? "" }));
      void loadBoardData();
    } catch (err) {
      setRetriageError(err instanceof ApiError ? err.message : t("emergency.errRetriage"));
    } finally {
      setRetriageSubmitting(false);
    }
  }

  async function handleMarkSeen(triage: EmergencyTriageOut) {
    try {
      // The server stamps the time; a client clock is not the record.
      await updateEmergencyTriage(triage.id, { clinician_seen: true });
      toast.success(t("emergency.toastSeen", { name: triage.patient_name ?? "" }));
      void loadBoardData();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("emergency.errMarkSeen"));
    }
  }

  function handleOpenDisposition(triage: EmergencyTriageOut) {
    setDispositionTarget(triage);
    setDispositionType("");
    setDispositionConfirmed(false);
    setDispositionError(null);
    setError(null);
    setDispositionNotes("");
    setDispositionModalOpen(true);
  }

  async function handleSubmitDisposition(e: React.FormEvent) {
    e.preventDefault();
    if (!dispositionTarget) return;
    if (!dispositionType) {
      setDispositionError(t("emergency.errDispositionRequired"));
      return;
    }
    const highAcuity = dispositionTarget.acuity_level === "resuscitation" || dispositionTarget.acuity_level === "emergent";
    if (dispositionType === "discharge" && highAcuity && !dispositionConfirmed) {
      setDispositionError(t("emergency.errConfirmHighAcuity"));
      return;
    }

    setDispositionSubmitting(true);
    setDispositionError(null);
    try {
      await updateEmergencyTriage(dispositionTarget.id, {
        disposition: dispositionType,
        disposition_notes: dispositionNotes.trim() || null,
        confirm_high_acuity_discharge: dispositionType === "discharge" && highAcuity ? dispositionConfirmed : undefined,
      });
      setDispositionModalOpen(false);
      const name = dispositionTarget.patient_name ?? "";
      toast.success(
        dispositionType === "admit"
          ? t("emergency.toastAdmitQueued", { name })
          : t("emergency.toastDisposition", { name }),
      );
      void loadBoardData();
      void loadWorklist();
    } catch (err) {
      setDispositionError(err instanceof ApiError ? err.message : t("emergency.errDisposition"));
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
            {(metrics.awaiting_triage_count ?? 0) > 0 && (
              <div className="text-xs font-medium text-amber-700 mt-0.5">
                {t("emergency.awaitingTriage", { count: metrics.awaiting_triage_count ?? 0 })}
              </div>
            )}
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
                              {acuityInfo.label}
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
                            <div className="text-[11px] text-muted-foreground mt-1">
                              <span className="font-medium text-foreground">
                                {nameWithIdentifier(tr.patient_name ?? "", tr.patient_identifier)}
                              </span>
                              {" · "}
                              {formatAgeSexShort(tr.patient_age_years ?? null, tr.patient_sex ?? "unknown")}
                              {tr.visit_number ? ` · ${tr.visit_number}` : ""}
                              {tr.arrived_at ? ` · ${t("emergency.arrivedAt", { time: formatDateTime(tr.arrived_at) })}` : ""}
                            </div>
                          </td>

                          <td className="px-4 py-3">
                            <div className="font-medium">
                              {t("emergency.bay", { bay: tr.assigned_bay || t("common.unassigned") })}
                            </div>
                            <div className="text-xs text-muted-foreground mt-0.5">
                              {tr.doctor_name
                                ? t("emergency.seenBy", { name: tr.doctor_name })
                                : t("emergency.noDoctorAssigned")}
                            </div>
                          </td>

                          <td className="px-4 py-3">
                            <span className="rounded bg-muted px-2 py-0.5 text-xs font-medium">
                              {statusLabel(tr.status)}
                            </span>
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
                  {nameWithIdentifier(created.full_name, created.thid)} · {formatAgeSexShort(created.age_years, created.sex)}
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
            <form onSubmit={submitRegistration} noValidate className="surface-card space-y-5 p-6">
              <label className="block space-y-1 text-sm">
                <span className="text-muted-foreground">{t("emergency.nameOptional")}</span>
                <input
                  className="w-full rounded-md border border-border px-3 py-2 text-foreground bg-background"
                  value={form.full_name}
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
                    type="text"
                    inputMode="numeric"
                    aria-invalid={showFormErrors && formErrors.age ? true : undefined}
                    aria-describedby={showFormErrors && formErrors.age ? "ed-age-error" : undefined}
                    className={fieldClass(Boolean(showFormErrors && formErrors.age))}
                    value={form.age}
                    onChange={(event) =>
                      setForm((current) => ({ ...current, age: event.target.value.replace(/[^\d]/g, "").slice(0, 3) }))
                    }
                  />
                  {showFormErrors && formErrors.age && (
                    <span id="ed-age-error" className="block text-xs text-danger">{t("emergency.errAgeRequired")}</span>
                  )}
                </label>
              </div>
              <label className="block space-y-1 text-sm">
                <span className="text-muted-foreground">{t("emergency.mobileOptional")}</span>
                <input
                  type="tel"
                  inputMode="numeric"
                  aria-invalid={showFormErrors && formErrors.mobile ? true : undefined}
                  aria-describedby={showFormErrors && formErrors.mobile ? "ed-mobile-error" : undefined}
                  className={fieldClass(Boolean(showFormErrors && formErrors.mobile))}
                  value={form.mobile}
                  onChange={(event) => setForm((current) => ({ ...current, mobile: event.target.value }))}
                />
                {showFormErrors && formErrors.mobile && (
                  <span id="ed-mobile-error" className="block text-xs text-danger">{t("emergency.errMobileInvalid")}</span>
                )}
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
                          {item.thid ?? item.uhid ?? t("mch.sex.unknown")}
                        </span>
                        <span className="font-medium text-sm">{item.full_name}</span>
                        <span className="text-xs text-muted-foreground">
                          · {formatAgeSexShort(item.age_years, item.sex)}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground mt-0.5">{t("emergency.ui.visitVisitNumberArrivedValue", { visit_number: item.visit_number, value: new Date(item.arrival_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) })}</p>
                    </div>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => handleOpenTriage(item)}
                        className="rounded-md bg-amber-600 text-white px-3 py-1.5 text-xs font-medium hover:bg-amber-700"
                      >
                        {t("emergency.triagePatient")}
                      </button>
                      {canConsult ? (
                        <Link
                          href={`/doctor/consultation?visit_id=${item.visit_id}`}
                          className="rounded-md bg-primary text-white px-3 py-1.5 text-xs font-medium hover:bg-primary/90"
                        >
                          {t("emergency.consultation")}
                        </Link>
                      ) : (
                        <span className="max-w-[16rem] text-[11px] text-muted-foreground">{t("emergency.consultByDoctor")}</span>
                      )}
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
                  {nameWithIdentifier(triageTargetArrival.full_name, triageTargetArrival.thid ?? triageTargetArrival.uhid)}
                </p>
              </div>
              <button type="button" onClick={() => setTriageModalOpen(false)} className="text-muted-foreground hover:text-foreground">✕</button>
            </div>

            <form onSubmit={handleSubmitTriage} noValidate className="space-y-4 text-sm">
              <DialogError message={triageError} />
              <label className="block space-y-1">
                <span className="font-medium text-foreground">{t("emergency.acuityLevel")}</span>
                <select
                  className={fieldClass(Boolean(triageError && !triageAcuity))}
                  aria-invalid={triageError && !triageAcuity ? true : undefined}
                  value={triageAcuity}
                  onChange={(e) => setTriageAcuity(e.target.value as EmergencyAcuity)}
                >
                  <option value="" disabled>{t("emergency.chooseAcuity")}</option>
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
                  maxLength={500}
                  placeholder={t("emergency.placeholderChiefComplaint")}
                  aria-invalid={triageError && triageAcuity && !triageComplaint.trim() ? true : undefined}
                  className={fieldClass(Boolean(triageError && triageAcuity && !triageComplaint.trim()))}
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
                  <span className="font-semibold">{(acuityStyles[retriageTarget.acuity_level] ?? acuityStyles.urgent).label}</span>
                </p>
              </div>
              <button type="button" onClick={() => setRetriageModalOpen(false)} className="text-muted-foreground hover:text-foreground">✕</button>
            </div>

            <form onSubmit={handleSubmitRetriage} noValidate className="space-y-4 text-sm">
              <DialogError message={retriageError} />
              <label className="block space-y-1">
                <span className="font-medium text-foreground">{t("emergency.newAcuityLevel")}</span>
                <select
                  className={fieldClass(Boolean(retriageError && !retriageAcuity))}
                  aria-invalid={retriageError && !retriageAcuity ? true : undefined}
                  value={retriageAcuity}
                  onChange={(e) => setRetriageAcuity(e.target.value as EmergencyAcuity)}
                >
                  <option value="" disabled>{t("emergency.chooseAcuity")}</option>
                  {(["resuscitation", "emergent", "urgent", "non_urgent"] as const)
                    .filter((level) => level !== retriageTarget.acuity_level)
                    .map((level) => (
                      <option key={level} value={level}>
                        {t(({ resuscitation: "emergency.acuityP1", emergent: "emergency.acuityP2", urgent: "emergency.acuityP3", non_urgent: "emergency.acuityP4" } as const)[level])}
                      </option>
                    ))}
                </select>
              </label>

              <label className="block space-y-1">
                <span className="font-medium text-foreground">{t("emergency.retriageJustification")}</span>
                <textarea
                  rows={3}
                  required
                  placeholder={t("emergency.placeholderRetriageJustification")}
                  aria-invalid={retriageError && retriageAcuity && retriageReason.trim().length < 10 ? true : undefined}
                  className={fieldClass(Boolean(retriageError && retriageAcuity && retriageReason.trim().length < 10))}
                  value={retriageReason}
                  onChange={(e) => setRetriageReason(e.target.value)}
                />
                <span className={`text-[11px] ${retriageReason.trim().length >= 10 ? "text-emerald-700" : "text-muted-foreground"}`}>
                  {t("emergency.retriageMinChars", { count: retriageReason.trim().length })}
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

            <form onSubmit={handleSubmitDisposition} noValidate className="space-y-4 text-sm">
              <DialogError message={dispositionError} />
              <p className="text-xs text-muted-foreground">
                {nameWithIdentifier(dispositionTarget.patient_name ?? "", dispositionTarget.patient_identifier)} ·{" "}
                {(acuityStyles[dispositionTarget.acuity_level] ?? acuityStyles.urgent).label}
              </p>
              <label className="block space-y-1">
                <span className="font-medium text-foreground">{t("emergency.dispositionDecision")}</span>
                <select
                  className={fieldClass(Boolean(dispositionError && !dispositionType))}
                  aria-invalid={dispositionError && !dispositionType ? true : undefined}
                  value={dispositionType}
                  onChange={(e) => {
                    setDispositionType(e.target.value as EmergencyDisposition);
                    setDispositionConfirmed(false);
                  }}
                >
                  <option value="" disabled>{t("emergency.chooseDisposition")}</option>
                  <option value="discharge">{t("emergency.dispDischargeHome")}</option>
                  {dispositionTarget.clinician_seen_at && <option value="admit">{t("emergency.dispAdmit")}</option>}
                  <option value="transfer">{t("emergency.dispTransfer")}</option>
                  {!dispositionTarget.clinician_seen_at && <option value="lwbs">{t("emergency.dispLwbs")}</option>}
                </select>
                <span className="block text-[11px] text-muted-foreground">{t("emergency.admitAfterSeenHint")}</span>
              </label>
              {dispositionType === "discharge" &&
                (dispositionTarget.acuity_level === "resuscitation" || dispositionTarget.acuity_level === "emergent") && (
                  <label className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger/5 p-3">
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={dispositionConfirmed}
                      onChange={(e) => setDispositionConfirmed(e.target.checked)}
                    />
                    <span className="text-sm text-danger">{t("emergency.confirmHighAcuityDischarge")}</span>
                  </label>
                )}

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
