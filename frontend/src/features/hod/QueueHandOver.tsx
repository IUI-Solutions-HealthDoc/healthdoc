"use client";

/**
 * Hand a doctor's waiting patients to a colleague in the same department and
 * close the doctor's queue. Two steps on purpose: choosing the covering doctor
 * shows exactly what will happen ("move 6 patients and close this queue")
 * before anything moves.
 */
import { useState } from "react";

import { ApiError } from "@/lib/api";
import { useLocale } from "@/lib/i18n";

import { handOverQueue } from "./api";
import type { HodQueueSummary } from "./types";

export function QueueHandOver({
  queue,
  others,
  onDone,
}: {
  queue: HodQueueSummary;
  others: HodQueueSummary[];
  onDone: () => void;
}) {
  const { t } = useLocale();
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const candidates = others.filter((other) => other.is_open && other.queue_id !== queue.queue_id);

  if (!queue.is_open || queue.waiting_count === 0 || candidates.length === 0) return null;

  async function submit() {
    if (!target || busy) return;
    setBusy(true);
    setError(null);
    try {
      await handOverQueue(queue.queue_id, target);
      setTarget("");
      onDone();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : t("hod.handOverFailed"));
    } finally {
      setBusy(false);
    }
  }

  const chosen = candidates.find((candidate) => candidate.queue_id === target);
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      <label className="text-xs text-muted-foreground">
        {t("hod.coverWith")}{" "}
        <select
          value={target}
          onChange={(event) => setTarget(event.target.value)}
          className="ml-1 rounded-md border border-border px-2 py-1 text-xs"
        >
          <option value="">{t("hod.chooseDoctor")}</option>
          {candidates.map((candidate) => (
            <option key={candidate.queue_id} value={candidate.queue_id}>
              {candidate.doctor_name ?? t("common.unassigned")} ({candidate.waiting_count})
            </option>
          ))}
        </select>
      </label>
      {chosen ? (
        <button
          type="button"
          disabled={busy}
          onClick={() => void submit()}
          className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
        >
          {t("hod.handOverConfirm", {
            count: queue.waiting_count,
            doctor: chosen.doctor_name ?? t("common.unassigned"),
          })}
        </button>
      ) : null}
      {error ? (
        <p className="w-full text-xs text-danger" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
