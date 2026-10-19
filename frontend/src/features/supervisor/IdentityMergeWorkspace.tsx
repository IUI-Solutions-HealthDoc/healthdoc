"use client";

import { useState, type FormEvent } from "react";

import {
  approveThidPromotion,
  requestThidPromotion,
  unmergeThidPromotion,
  type PromotionLog,
} from "@/features/emergency/api";
import { PageHeading } from "@/components/common/PageHeading";
import { ApiError } from "@/lib/api";
import { useLocale, type MessageKey } from "@/lib/i18n";

type Tab = "request" | "approve" | "unmerge";

function errorMessage(reason: unknown): string {
  if (reason instanceof ApiError) {
    const code =
      reason.payload &&
      typeof reason.payload === "object" &&
      "code" in reason.payload
        ? String((reason.payload as { code?: string }).code)
        : undefined;
    if (code === "self_approval_not_allowed") {
      return "Maker–checker: the supervisor who requested cannot also approve.";
    }
    if (code === "self_unmerge_not_allowed") {
      return "Maker–checker: the supervisor who approved cannot also unmerge.";
    }
    if (code === "patient_not_thid") {
      return "This patient is not on the THID path — only temporary emergency charts can be promoted.";
    }
    if (code === "promotion_already_pending") {
      return "A promotion is already pending for this patient.";
    }
    if (code === "patient_not_found") {
      return "No THID patient with that ID exists in this facility.";
    }
    if (code === "merge_log_not_found") {
      return "No identity merge with that ID exists in this facility.";
    }
    if (code === "not_pending") {
      return "This identity merge is no longer pending approval.";
    }
    if (code === "not_approved") {
      return "Only an approved identity merge can be unmerged.";
    }
    if (code === "patient_already_promoted" || code === "patient_already_has_uhid") {
      return "This patient already has a permanent UHID.";
    }
    if (reason.code === 422) {
      return "Check that the patient or merge-log ID is a valid UUID.";
    }
    return reason.message;
  }
  return "Request failed";
}

function ResultCard({ log }: { log: PromotionLog }) {
  const { t } = useLocale();
  return (
    <div className="surface-card space-y-2 border border-success p-4" aria-live="polite">
      <p className="text-sm text-muted-foreground">{t("supervisor.ui.mergeLog")}</p>
      <p className="break-all font-mono text-sm font-semibold">{log.id}</p>
      <p className="text-sm">{t("bloodBank.inventory.filterStatus")}{" "}<span className="font-medium">{log.status}</span>
      </p>
      <p className="text-xs text-muted-foreground">{t("common.patient")}{" "}<span className="font-mono">{log.source_patient_id}</span>
      </p>
      {log.status === "pending" ? (
        <p className="text-sm text-muted-foreground">{t("supervisor.ui.handThisMergeLogIdTo")}</p>
      ) : null}
      {log.status === "approved" ? (
        <p className="text-sm text-muted-foreground">{t("supervisor.ui.uhidAssignedAThirdSupervisorNot")}</p>
      ) : null}
    </div>
  );
}

export function IdentityMergeWorkspace() {
  const { t } = useLocale();
  const [tab, setTab] = useState<Tab>("request");
  const [patientId, setPatientId] = useState("");
  const [mergeLogId, setMergeLogId] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastLog, setLastLog] = useState<PromotionLog | null>(null);

  function resetFeedback() {
    setError(null);
    setLastLog(null);
  }

  async function onRequest(event: FormEvent) {
    event.preventDefault();
    const id = patientId.trim();
    if (!id) return;
    setBusy(true);
    resetFeedback();
    try {
      const log = await requestThidPromotion(id, reason);
      setLastLog(log);
    } catch (reasonCaught) {
      setError(errorMessage(reasonCaught));
    } finally {
      setBusy(false);
    }
  }

  async function onApprove(event: FormEvent) {
    event.preventDefault();
    const id = mergeLogId.trim();
    if (!id) return;
    setBusy(true);
    resetFeedback();
    try {
      setLastLog(await approveThidPromotion(id));
    } catch (reasonCaught) {
      setError(errorMessage(reasonCaught));
    } finally {
      setBusy(false);
    }
  }

  async function onUnmerge(event: FormEvent) {
    event.preventDefault();
    const id = mergeLogId.trim();
    const explanation = reason.trim();
    if (!id || !explanation) return;
    if (!window.confirm("Unmerge this identity promotion and clear its assigned UHID?")) return;
    setBusy(true);
    resetFeedback();
    try {
      setLastLog(await unmergeThidPromotion(id, explanation));
    } catch (reasonCaught) {
      setError(errorMessage(reasonCaught));
    } finally {
      setBusy(false);
    }
  }

  const tabs: { id: Tab; labelKey: MessageKey }[] = [
    { id: "request", labelKey: "supervisor.merge.step.request" },
    { id: "approve", labelKey: "supervisor.merge.step.approve" },
    { id: "unmerge", labelKey: "supervisor.merge.step.unmerge" },
  ];

  return (
    <div className="mx-auto max-w-3xl space-y-6 p-6">
      <PageHeading titleKey="supervisor.mergesTitle" titleClassName="text-3xl font-semibold" />

      <nav className="flex flex-wrap gap-2" aria-label={t("supervisor.ui.identityMergeSteps")}>
        {tabs.map((item) => (
          <button
            key={item.id}
            type="button"
            aria-pressed={tab === item.id}
            className={`rounded-md px-3 py-2 text-sm font-medium ${
              tab === item.id
                ? "bg-primary text-primary-foreground"
                : "border border-border"
            }`}
            onClick={() => {
              setTab(item.id);
              resetFeedback();
            }}
          >
            {t(item.labelKey)}
          </button>
        ))}
      </nav>

      {error ? (
        <p role="alert" className="rounded-md bg-danger-muted p-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      {lastLog ? <ResultCard log={lastLog} /> : null}

      {tab === "request" ? (
        <form onSubmit={onRequest} className="surface-card space-y-4 p-6">
          <h2 className="text-lg font-medium">{t("supervisor.merge.requestTitle")}</h2>
          <p className="text-sm text-muted-foreground">{t("supervisor.ui.pasteThePatientIdFromEmergency")}</p>
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">{t("supervisor.merge.patientId")}</span>
            <input
              className="w-full rounded-md border border-border px-3 py-2 font-mono text-sm"
              value={patientId}
              onChange={(e) => setPatientId(e.target.value)}
              required
              autoComplete="off"
            />
          </label>
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">{t("supervisor.merge.reasonOptional")}</span>
            <input
              className="w-full rounded-md border border-border px-3 py-2"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <button
            type="submit"
            disabled={busy || !patientId.trim()}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {busy ? t("supervisor.merge.requesting") : t("supervisor.merge.requestButton")}
          </button>
        </form>
      ) : null}

      {tab === "approve" ? (
        <form onSubmit={onApprove} className="surface-card space-y-4 p-6">
          <h2 className="text-lg font-medium">{t("supervisor.merge.approveTitle")}</h2>
          <p className="text-sm text-muted-foreground">{t("supervisor.ui.mustBeADifferentSupervisorFrom")}</p>
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">{t("supervisor.merge.mergeLogId")}</span>
            <input
              className="w-full rounded-md border border-border px-3 py-2 font-mono text-sm"
              value={mergeLogId}
              onChange={(e) => setMergeLogId(e.target.value)}
              required
              autoComplete="off"
            />
          </label>
          <button
            type="submit"
            disabled={busy || !mergeLogId.trim()}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {busy ? t("supervisor.merge.approving") : t("supervisor.merge.approveButton")}
          </button>
        </form>
      ) : null}

      {tab === "unmerge" ? (
        <form onSubmit={onUnmerge} className="surface-card space-y-4 p-6">
          <h2 className="text-lg font-medium">{t("supervisor.merge.unmergeTitle")}</h2>
          <p className="text-sm text-muted-foreground">{t("supervisor.ui.clearsTheUhidAndReturnsThe")}</p>
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">{t("supervisor.merge.mergeLogId")}</span>
            <input
              className="w-full rounded-md border border-border px-3 py-2 font-mono text-sm"
              value={mergeLogId}
              onChange={(e) => setMergeLogId(e.target.value)}
              required
              autoComplete="off"
            />
          </label>
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">{t("supervisor.merge.unmergeReason")}</span>
            <input
              className="w-full rounded-md border border-border px-3 py-2"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required
            />
          </label>
          <button
            type="submit"
            disabled={busy || !mergeLogId.trim() || !reason.trim()}
            className="rounded-md bg-danger px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy ? t("supervisor.merge.unmerging") : t("supervisor.merge.unmergeButton")}
          </button>
        </form>
      ) : null}
    </div>
  );
}
