"use client";

import { useCallback, useEffect, useState } from "react";

import { toast } from "@/components/ui/toast";
import { ApiError, formatDateTime, newIdempotencyKey } from "@/lib/api";
import {
  createQueue,
  getStaleVisits,
  issueToken,
  listQueueOpeningOptions,
  listQueueTokens,
  listQueues,
  listVisitsWithoutTokens,
  reconcileStaleVisits,
  updateTokenPriority,
} from "@/features/receptionist/api";
import type {
  QueueOpeningOptions,
  QueueSummary,
  QueueTokenList,
  StaleVisitsReconcileResult,
  StaleVisitsReport,
  TokenPriorityUpdate,
  VisitWithoutToken,
} from "@/features/receptionist/types";
import { ScanShareDeskModal } from "@/features/receptionist/ScanShareDeskModal";
import { PageHeading } from "@/components/common/PageHeading";
import { useLocale, type MessageKey } from "@/lib/i18n";

const QUEUE_PRIORITIES = ["normal", "senior_citizen", "pregnant", "follow_up_recall"] as const;


/**
 * Reception's view of today's queues (#171).
 *
 * Distinct from /queue-display, which is the public wall board: this one is
 * authenticated, shows every queue rather than one department, and is what a
 * receptionist answers "how long is the wait for Dr X" from.
 */
export default function Page() {
  const { t, localizeField } = useLocale();
  const priorityLabel = useCallback(
    (code: string) => {
      if ((QUEUE_PRIORITIES as readonly string[]).includes(code)) {
        return t(`priority.${code}` as MessageKey);
      }
      return code.replaceAll("_", " ");
    },
    [t],
  );
  const [queues, setQueues] = useState<QueueSummary[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [tokens, setTokens] = useState<QueueTokenList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [openingOptions, setOpeningOptions] = useState<QueueOpeningOptions | null>(null);
  const [optionId, setOptionId] = useState("");
  const [displayLabel, setDisplayLabel] = useState("");
  const [showOpenQueue, setShowOpenQueue] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createKey, setCreateKey] = useState(() => newIdempotencyKey());
  const [priorityTokenId, setPriorityTokenId] = useState<string | null>(null);
  const [priority, setPriority] = useState<TokenPriorityUpdate["priority"]>("senior_citizen");
  const [priorityReason, setPriorityReason] = useState("");
  const [updatingPriority, setUpdatingPriority] = useState(false);
  const [unassignedVisits, setUnassignedVisits] = useState<VisitWithoutToken[] | null>(null);
  const [showUnassignedVisits, setShowUnassignedVisits] = useState(false);
  const [assigningVisit, setAssigningVisit] = useState<VisitWithoutToken | null>(null);
  const [assignQueueId, setAssignQueueId] = useState("");
  const [assignPriority, setAssignPriority] = useState("normal");
  const [assigningBusy, setAssigningBusy] = useState(false);

  // HD-12: Stale visits state
  const [staleReport, setStaleReport] = useState<StaleVisitsReport | null>(null);
  const [showStaleVisits, setShowStaleVisits] = useState(false);
  const [reconciling, setReconciling] = useState(false);

  // HD-36: ABDM Scan & Share modal state
  const [showScanShareModal, setShowScanShareModal] = useState(false);
  const [reconcileResult, setReconcileResult] = useState<StaleVisitsReconcileResult | null>(null);

  const load = useCallback(async () => {
    try {
      const [rows, options, unassigned, stale] = await Promise.all([
        listQueues(),
        listQueueOpeningOptions(),
        listVisitsWithoutTokens().catch(() => [] as VisitWithoutToken[]),
        getStaleVisits().catch(() => null),
      ]);
      setQueues(rows);
      setOpeningOptions(options);
      setUnassignedVisits(unassigned);
      setStaleReport(stale);
      setOptionId((current) =>
        options.items.some((option) => option.roster_id === current)
          ? current
          : (options.items[0]?.roster_id ?? ""),
      );
      setSelected((current) =>
        rows.some((queue) => queue.id === current) ? current : (rows[0]?.id ?? null),
      );
      setError(null);
    } catch (reason) {
      setQueues(null);
      setOpeningOptions(null);
      setSelected(null);
      setTokens(null);
      setError(reason instanceof ApiError ? reason.message : t("receptionist.errLoadQueues"));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setTokens(null);
    listQueueTokens(selected)
      .then((list) => {
        if (!cancelled) setTokens(list);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof ApiError ? reason.message : t("receptionist.errLoadTokens"));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selected, t]);

  const handleCreateQueue = async () => {
    const option = openingOptions?.items.find((item) => item.roster_id === optionId);
    if (!option || !openingOptions) {
      setError(t("receptionist.errSelectRosterBeforeOpen"));
      return;
    }
    setCreating(true);
    setError(null);
    try {
      await createQueue(
        {
          department_id: option.department_id,
          doctor_user_id: option.staff_user_id,
          room_id: option.room_id,
          display_label: displayLabel.trim() || null,
          service_date: openingOptions.service_date,
        },
        createKey,
      );
      toast.success(
        t("receptionist.queueOpened"),
        `${option.staff_name} · ${localizeField(option.department_name, option.department_name_hi)}`,
      );
      setCreateKey(newIdempotencyKey());
      setDisplayLabel("");
      setShowOpenQueue(false);
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("receptionist.errOpenQueue"));
    } finally {
      setCreating(false);
    }
  };

  const handlePriorityUpdate = async () => {
    if (!priorityTokenId || !selected) return;
    if (priorityReason.trim().length < 10) {
      setError(t("receptionist.errPriorityReasonMinLength"));
      return;
    }

    setUpdatingPriority(true);
    setError(null);
    try {
      await updateTokenPriority(priorityTokenId, {
        priority,
        reason: priorityReason.trim(),
      });
      const refreshed = await listQueueTokens(selected);
      setTokens(refreshed);
      setPriorityTokenId(null);
      setPriorityReason("");
      toast.success(t("receptionist.toastPriorityUpdatedTitle"), t("receptionist.toastPriorityUpdatedBody"));
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("receptionist.errUpdateTokenPriority"));
    } finally {
      setUpdatingPriority(false);
    }
  };

  const handleIssueTokenForVisit = async () => {
    if (!assigningVisit || !assignQueueId) return;
    setAssigningBusy(true);
    setError(null);
    try {
      const issued = await issueToken(
        {
          queue_id: assignQueueId,
          visit_id: assigningVisit.visit_id,
          priority: assignPriority,
        },
        newIdempotencyKey(),
      );
      toast.success(
        t("receptionist.issueToken"),
        t("receptionist.toastTokenIssued", {
          token: issued.token_display,
          name: assigningVisit.patient_name,
        }),
      );
      setAssigningVisit(null);
      await load();
      if (selected) {
        const refreshed = await listQueueTokens(selected);
        setTokens(refreshed);
      }
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("receptionist.errIssueToken"));
    } finally {
      setAssigningBusy(false);
    }
  };

  const handleReconcileAllStale = async () => {
    if (
      !window.confirm(t("receptionist.reconcileConfirmMessage"))
    ) {
      return;
    }
    setReconciling(true);
    setError(null);
    try {
      const res = await reconcileStaleVisits();
      setReconcileResult(res);
      toast.success(
        t("receptionist.toastStaleReconciledTitle"),
        t("receptionist.toastStaleReconciledBody", {
          reconciled: res.reconciled_count,
          skipped: res.skipped_count,
        }),
      );
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("receptionist.errReconcileStale"));
    } finally {
      setReconciling(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHeading
          titleKey="receptionist.queueTitle"
          subtitleKey="receptionist.queueSubtitle"
        />
        {/* Manual refresh, not a poll. The live board is /queue-display, which
            is push-based; polling here would add load for a screen someone
            looks at when a patient asks, not continuously. */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setShowStaleVisits((shown) => !shown)}
            className={`relative rounded-md border px-3 py-2 text-sm font-medium transition ${
              showStaleVisits
                ? "border-rose-500 bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300"
                : "border-border bg-card text-foreground hover:bg-muted"
            }`}
          >
            {t("receptionist.staleVisits")}
            {staleReport && staleReport.total_stale_count > 0 ? (
              <span className="ml-2 rounded-full bg-rose-600 px-1.5 py-0.5 text-[11px] font-bold text-white">
                {staleReport.total_stale_count}
              </span>
            ) : null}
          </button>
          <button
            type="button"
            onClick={() => setShowUnassignedVisits((shown) => !shown)}
            className={`relative rounded-md border px-3 py-2 text-sm font-medium transition ${
              showUnassignedVisits
                ? "border-primary bg-primary/10 text-primary"
                : "border-border bg-card text-foreground hover:bg-muted"
            }`}
          >
            {t("receptionist.visitsAwaitingToken")}
            {unassignedVisits && unassignedVisits.length > 0 ? (
              <span className="ml-2 rounded-full bg-amber-500 px-1.5 py-0.5 text-[11px] font-bold text-white">
                {unassignedVisits.length}
              </span>
            ) : null}
          </button>
          <button
            type="button"
            onClick={() => setShowScanShareModal(true)}
            className="rounded-md border border-primary/40 bg-primary/10 px-3.5 py-2 text-sm font-semibold text-primary hover:bg-primary/20"
          >
            {t("receptionist.abdmScanShare")}
          </button>
          <button
            type="button"
            onClick={() => setShowOpenQueue((shown) => !shown)}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white"
          >
            {showOpenQueue ? t("common.close") : t("receptionist.openQueue")}
          </button>
          <button type="button" onClick={() => void load()} className="text-sm underline">
            {t("common.refresh")}
          </button>
        </div>
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      {showUnassignedVisits && (
        <section className="surface-card space-y-4 p-5" aria-labelledby="unassigned-visits-title">
          <div className="flex items-center justify-between">
            <div>
              <h2 id="unassigned-visits-title" className="text-lg font-semibold">
                {t("receptionist.visitsAwaitingHeading", { count: unassignedVisits?.length ?? 0 })}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {t("receptionist.visitsAwaitingHint")}
              </p>
            </div>
          </div>

          {unassignedVisits && unassignedVisits.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("receptionist.noVisitsAwaiting")}</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse">
                <thead className="bg-muted/40 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2.5 text-left">{t("receptionist.visitNumber")}</th>
                    <th className="px-4 py-2.5 text-left">{t("common.patient")}</th>
                    <th className="px-4 py-2.5 text-left">{t("receptionist.department")}</th>
                    <th className="px-4 py-2.5 text-left">{t("receptionist.visitDate")}</th>
                    <th className="px-4 py-2.5 text-right">{t("receptionist.action")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border text-sm">
                  {unassignedVisits?.map((v) => (
                    <tr key={v.visit_id} className="hover:bg-muted/20 transition-colors">
                      <td className="px-4 py-3 font-mono font-bold text-primary">{v.visit_number}</td>
                      <td className="px-4 py-3">
                        <span className="block font-medium text-foreground">{v.patient_name}</span>
                        <span className="font-mono text-xs text-muted-foreground">{v.uhid ?? v.thid ?? t("receptionist.noUhid")}</span>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{localizeField(v.department_name ?? t("receptionist.generalClinic"), v.department_name_hi)}</td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">{formatDateTime(v.visit_date)}</td>
                      <td className="px-4 py-3 text-right">
                        <button
                          type="button"
                          onClick={() => {
                            setAssigningVisit(v);
                            setAssignQueueId(queues?.[0]?.id ?? "");
                            setAssignPriority("normal");
                          }}
                          className="rounded-md bg-primary px-3 py-1 text-xs font-semibold text-white shadow-xs hover:bg-primary/90 transition"
                        >
                          {t("receptionist.issueToken")}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {assigningVisit && (
            <div className="rounded-lg border border-primary/30 bg-primary/5 p-4 space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-foreground">
                  {t("receptionist.issueTokenHeading", {
                    name: assigningVisit.patient_name,
                    visit: assigningVisit.visit_number,
                  })}
                </h3>
                <button
                  type="button"
                  onClick={() => setAssigningVisit(null)}
                  className="text-xs text-muted-foreground underline"
                >
                  {t("common.cancel")}
                </button>
              </div>
              {queues && queues.length === 0 ? (
                <p className="text-xs text-danger">{t("receptionist.noOpenQueuesFirst")}</p>
              ) : (
                <div className="grid gap-3 sm:grid-cols-[2fr_1fr_auto] sm:items-end">
                  <label className="space-y-1 text-xs">
                    <span className="text-muted-foreground">{t("receptionist.selectClinicDoctor")} *</span>
                    <select
                      value={assignQueueId}
                      onChange={(e) => setAssignQueueId(e.target.value)}
                      className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm"
                    >
                      {queues?.map((q) => (
                        <option key={q.id} value={q.id}>
                          {q.doctor_name ?? t("common.doctor")}{" "}
                          {q.room_number ? `· ${t("receptionist.room", { number: q.room_number })}` : ""} (
                          {t("receptionist.queueOptionWaiting", { waiting: q.waiting_count })})
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="space-y-1 text-xs">
                    <span className="text-muted-foreground">{t("receptionist.priority")}</span>
                    <select
                      value={assignPriority}
                      onChange={(e) => setAssignPriority(e.target.value)}
                      className="w-full rounded-md border border-border bg-background px-3 py-1.5 text-sm"
                    >
                      {QUEUE_PRIORITIES.map((value) => (
                        <option key={value} value={value}>
                          {priorityLabel(value)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    disabled={assigningBusy || !assignQueueId}
                    onClick={() => void handleIssueTokenForVisit()}
                    className="rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                  >
                    {assigningBusy ? t("receptionist.issuing") : t("receptionist.confirmToken")}
                  </button>
                </div>
              )}
            </div>
          )}
        </section>
      )}

      {showStaleVisits && (
        <section className="surface-card space-y-4 p-5" aria-labelledby="stale-visits-title">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h2 id="stale-visits-title" className="text-lg font-semibold text-foreground">
                {t("receptionist.staleReviewTitle", { count: staleReport?.total_stale_count ?? 0 })}
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {t("receptionist.staleReviewDescription", {
                  cutoff: staleReport?.cutoff_date ?? t("common.today"),
                })}
              </p>
            </div>
            {staleReport && staleReport.total_stale_count > 0 && (
              <button
                type="button"
                disabled={reconciling}
                onClick={() => void handleReconcileAllStale()}
                className="rounded-md bg-rose-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-rose-700 disabled:opacity-50"
              >
                {reconciling ? t("receptionist.reconciling") : t("receptionist.reconcileAllButton", { count: staleReport.total_stale_count })}
              </button>
            )}
          </div>

          {reconcileResult && (
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
              <span className="font-semibold">{t("receptionist.reconciliationCompleted")}</span>{" "}
              {t("receptionist.reconcileSummary", {
                reconciled: reconcileResult.reconciled_count,
                skipped: reconcileResult.skipped_count,
              })}
            </div>
          )}

          {staleReport && staleReport.candidates.length === 0 ? (
            <div className="rounded-lg border border-border bg-muted/20 p-6 text-center text-sm text-muted-foreground">
              {t("receptionist.staleVisitsEmpty")}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse">
                <thead className="bg-muted/40 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="px-4 py-2.5 text-left">{t("receptionist.visitNumber")}</th>
                    <th className="px-4 py-2.5 text-left">{t("common.patient")}</th>
                    <th className="px-4 py-2.5 text-left">{t("receptionist.department")}</th>
                    <th className="px-4 py-2.5 text-left">{t("receptionist.visitDate")}</th>
                    <th className="px-4 py-2.5 text-left">{t("common.status")}</th>
                    <th className="px-4 py-2.5 text-left">{t("receptionist.queueToken")}</th>
                    <th className="px-4 py-2.5 text-left">{t("receptionist.encounters")}</th>
                    <th className="px-4 py-2.5 text-right">{t("receptionist.recommended")}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border text-sm">
                  {staleReport?.candidates.map((c) => (
                    <tr key={c.visit_id} className="hover:bg-muted/20 transition-colors">
                      <td className="px-4 py-3 font-mono font-bold text-primary">{c.visit_number}</td>
                      <td className="px-4 py-3">
                        <span className="block font-medium text-foreground">{c.patient_name}</span>
                        <span className="font-mono text-xs text-muted-foreground">{c.patient_uhid}</span>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{localizeField(c.department_name ?? t("receptionist.generalClinic"), c.department_name_hi)}</td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">{formatDateTime(c.visit_date)}</td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex rounded px-2 py-0.5 text-xs font-medium ${
                          c.current_status === "registered"
                            ? "bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300"
                            : "bg-blue-100 text-blue-800 dark:bg-blue-950/50 dark:text-blue-300"
                        }`}>
                          {c.current_status}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">
                        {c.live_token_display ? (
                          <span className="text-amber-600 dark:text-amber-400">
                            {c.live_token_display} ({c.live_token_status})
                          </span>
                        ) : (
                          <span className="text-muted-foreground">{t("receptionist.none")}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs">
                        {c.has_active_encounter ? (
                          <span className="text-rose-600 font-medium">{t("receptionist.inProgressNote")}</span>
                        ) : (
                          <span className="text-muted-foreground">{t("receptionist.encounterNotesCount", { count: c.encounter_count })}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right text-xs font-medium">
                        <span className="rounded bg-muted px-2 py-1 text-foreground">
                          {c.recommended_visit_action === "mark_lwbs" ? t("receptionist.setLwbs") : t("common.close")}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {showOpenQueue && (
        <section className="surface-card space-y-4 p-5" aria-labelledby="open-queue-title">
          <div>
            <h2 id="open-queue-title" className="text-lg font-semibold">{t("receptionist.openTodaysQueue")}</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("receptionist.rosterFromHodHint")}
            </p>
          </div>
          {openingOptions && openingOptions.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {t("receptionist.noRosterForDate", { date: openingOptions.service_date })}
            </p>
          ) : (
            <div className="grid gap-4 md:grid-cols-[2fr_1fr_auto] md:items-end">
              <label className="space-y-1 text-sm">
                <span className="text-muted-foreground">{t("receptionist.rosteredClinic")}</span>
                <select
                  className="w-full rounded-md border border-border bg-background px-3 py-2"
                  value={optionId}
                  onChange={(event) => setOptionId(event.target.value)}
                >
                  {openingOptions?.items.map((option) => (
                    <option key={option.roster_id} value={option.roster_id}>
                      {option.staff_name} · {localizeField(option.department_name, option.department_name_hi)} · {option.shift}
                      {option.room_number ? ` · ${t("receptionist.room", { number: option.room_number })}` : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-sm">
                <span className="text-muted-foreground">{t("receptionist.displayLabelOptional")}</span>
                <input
                  maxLength={50}
                  className="w-full rounded-md border border-border px-3 py-2"
                  value={displayLabel}
                  onChange={(event) => setDisplayLabel(event.target.value)}
                  placeholder={t("receptionist.displayLabelExample")}
                />
              </label>
              <button
                type="button"
                disabled={creating || !optionId}
                onClick={() => void handleCreateQueue()}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                {creating ? t("common.loading") : t("common.open")}
              </button>
            </div>
          )}
        </section>
      )}

      {queues !== null && queues.length === 0 && (
        <div className="surface-card p-6">
          <p className="text-sm text-muted-foreground">
            {t("receptionist.noOpenQueues")}
          </p>
        </div>
      )}

      {queues && queues.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {queues.map((q) => {
            const isSelected = selected === q.id;
            return (
              <button
                key={q.id}
                type="button"
                onClick={() => setSelected(q.id)}
                className={`group relative rounded-xl border p-5 text-left transition-all duration-200 ${
                  isSelected
                    ? "border-primary bg-primary/5 shadow-md ring-2 ring-primary/20"
                    : "border-border/80 bg-card hover:border-border hover:shadow-sm"
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-base font-bold text-foreground group-hover:text-primary transition-colors">
                      {q.doctor_name ?? t("receptionist.generalClinic")}
                    </p>
                    <p className="mt-0.5 text-xs font-medium text-muted-foreground">
                      {q.room_number ? t("receptionist.room", { number: q.room_number }) : t("receptionist.roomNotAssigned")}
                    </p>
                  </div>
                  {isSelected && (
                    <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-bold text-primary">
                      {t("receptionist.queueBadgeActive")}
                    </span>
                  )}
                </div>

                <div className="mt-4 flex items-center justify-between border-t border-border/50 pt-3">
                  <div>
                    <span className="text-3xl font-extrabold tabular-nums tracking-tight text-foreground">
                      {q.waiting_count}
                    </span>
                    <span className="ml-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                      {t("receptionist.waitingShort")}
                    </span>
                  </div>
                  <div className="text-right">
                    <span className="block text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">
                      {t("receptionist.nowServingLabel")}
                    </span>
                    <span className="inline-block rounded bg-primary/10 px-2 py-0.5 font-mono text-sm font-bold text-primary">
                      {q.now_serving ?? "—"}
                    </span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}

      {tokens && (
        <div className="surface-card overflow-hidden shadow-sm">
          <div className="flex flex-wrap items-center justify-between border-b border-border bg-muted/20 px-6 py-4">
            <h2 className="text-base font-bold text-foreground">
              {t("receptionist.queueRosterHeading", { count: tokens.waiting_count })}
            </h2>
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-muted-foreground">{t("receptionist.currentCounter")}</span>
              <span className="rounded bg-primary px-2.5 py-1 font-mono text-xs font-bold text-primary-foreground shadow-xs">
                {tokens.now_serving ?? "—"}
              </span>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse">
              <thead className="table-sticky-header">
                <tr>
                  <th className="px-5 py-3.5 text-left">{t("receptionist.token")}</th>
                  <th className="px-5 py-3.5 text-left">{t("receptionist.patientIdentifier")}</th>
                  <th className="px-5 py-3.5 text-left">{t("common.status")}</th>
                  <th className="px-5 py-3.5 text-left">{t("receptionist.priority")}</th>
                  <th className="px-5 py-3.5 text-left">{t("receptionist.issuedTime")}</th>
                  <th className="px-5 py-3.5 text-right">{t("receptionist.action")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {tokens.items.map((tokenRow) => {
                  const isSenior = tokenRow.priority === "senior_citizen";
                  const isEmergency = tokenRow.priority === "emergency";
                  return (
                    <tr key={tokenRow.id} className="table-row-hover transition-colors">
                      <td className="px-5 py-3.5 font-mono text-sm font-bold text-primary">
                        <span className="rounded bg-primary/10 px-2 py-1">
                          {tokenRow.token_display}
                        </span>
                      </td>
                      <td className="px-5 py-3.5 text-sm">
                        <span className="block font-semibold text-foreground">
                          {tokenRow.patient_name ?? t("receptionist.patientUnavailable")}
                        </span>
                        <span className="font-mono text-xs text-muted-foreground">
                          {tokenRow.patient_identifier ?? t("receptionist.noIdentifier")}
                        </span>
                      </td>
                      <td className="px-5 py-3.5 text-xs">
                        <span className="inline-flex items-center rounded-full px-2.5 py-0.5 font-semibold capitalize bg-muted text-muted-foreground">
                          {tokenRow.status.replaceAll("_", " ")}
                        </span>
                      </td>
                      <td className="px-5 py-3.5 text-xs">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 font-semibold capitalize ${
                            isEmergency
                              ? "bg-red-100 text-red-800 dark:bg-red-950/40 dark:text-red-300"
                              : isSenior
                                ? "bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-300"
                                : "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300"
                          }`}
                        >
                          {priorityLabel(tokenRow.priority)}
                        </span>
                      </td>
                      <td className="px-5 py-3.5 text-xs text-muted-foreground">
                        {formatDateTime(tokenRow.created_at)}
                      </td>
                      <td className="px-5 py-3.5 text-right text-xs">
                        {tokenRow.status === "waiting" && tokenRow.priority === "normal" ? (
                          <button
                            type="button"
                            className="rounded border border-border bg-card px-2.5 py-1 font-medium text-foreground shadow-xs hover:bg-muted transition"
                            onClick={() => {
                              setPriorityTokenId(tokenRow.id);
                              setPriority("senior_citizen");
                              setPriorityReason("");
                            }}
                          >
                            {t("receptionist.escalatePriority")}
                          </button>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {priorityTokenId ? (
        <section className="surface-card space-y-4 p-5" aria-labelledby="priority-title">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 id="priority-title" className="text-lg font-semibold">{t("receptionist.changeQueuePriority")}</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                {t("receptionist.priorityEscalationHint")}
              </p>
            </div>
            <button type="button" className="text-sm underline" onClick={() => setPriorityTokenId(null)}>
              {t("common.cancel")}
            </button>
          </div>
          <div className="grid gap-4 md:grid-cols-[1fr_2fr_auto] md:items-end">
            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">{t("receptionist.priorityRequired")}</span>
              <select
                value={priority}
                onChange={(event) => setPriority(event.target.value as TokenPriorityUpdate["priority"])}
                className="w-full rounded-md border border-border bg-background px-3 py-2"
              >
                {(["senior_citizen", "pregnant", "follow_up_recall"] as const).map((value) => (
                  <option key={value} value={value}>
                    {priorityLabel(value)}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">{t("receptionist.reasonRequired")}</span>
              <input
                required
                minLength={10}
                maxLength={250}
                value={priorityReason}
                onChange={(event) => setPriorityReason(event.target.value)}
                className={`w-full rounded-md border px-3 py-2 ${
                  priorityReason && priorityReason.trim().length < 10 ? "border-danger" : "border-border"
                }`}
                placeholder={t("receptionist.priorityReasonPlaceholder")}
              />
            </label>
            <button
              type="button"
              disabled={updatingPriority || priorityReason.trim().length < 10}
              onClick={() => void handlePriorityUpdate()}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {updatingPriority ? t("common.loading") : t("common.save")}
            </button>
          </div>
        </section>
      ) : null}
      {/* HD-36: ABDM Scan & Share Reception Desk Modal */}
      <ScanShareDeskModal
        isOpen={showScanShareModal}
        onClose={() => setShowScanShareModal(false)}
      />
    </div>
  );
}
