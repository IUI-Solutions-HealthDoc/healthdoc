"use client";

import { useCallback, useEffect, useState } from "react";

import { toast } from "@/components/ui/toast";
import { ApiError, formatDateTime, newIdempotencyKey } from "@/lib/api";
import {
  createQueue,
  listQueueOpeningOptions,
  listQueueTokens,
  listQueues,
  updateTokenPriority,
} from "@/features/receptionist/api";
import type {
  QueueOpeningOptions,
  QueueSummary,
  QueueTokenList,
  TokenPriorityUpdate,
} from "@/features/receptionist/types";

/**
 * Reception's view of today's queues (#171).
 *
 * Distinct from /queue-display, which is the public wall board: this one is
 * authenticated, shows every queue rather than one department, and is what a
 * receptionist answers "how long is the wait for Dr X" from.
 */
export default function Page() {
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

  const load = useCallback(async () => {
    try {
      const [rows, options] = await Promise.all([
        listQueues(),
        listQueueOpeningOptions(),
      ]);
      setQueues(rows);
      setOpeningOptions(options);
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
      setError(reason instanceof ApiError ? reason.message : "Could not load queues");
    }
  }, []);

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
          setError(reason instanceof ApiError ? reason.message : "Could not load tokens");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

  const handleCreateQueue = async () => {
    const option = openingOptions?.items.find((item) => item.roster_id === optionId);
    if (!option || !openingOptions) {
      setError("Select an available rostered clinic before opening a queue.");
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
      toast.success("Queue opened", `${option.staff_name} · ${option.department_name}`);
      setCreateKey(newIdempotencyKey());
      setDisplayLabel("");
      setShowOpenQueue(false);
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not open queue");
    } finally {
      setCreating(false);
    }
  };

  const handlePriorityUpdate = async () => {
    if (!priorityTokenId || !selected) return;
    if (priorityReason.trim().length < 10) {
      setError("Priority change reason must be at least 10 characters.");
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
      toast.success("Priority updated", "The queue order now reflects the new priority.");
      await load();
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not update token priority");
    } finally {
      setUpdatingPriority(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Today&apos;s queues</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Waiting counts for every open clinic.
          </p>
        </div>
        {/* Manual refresh, not a poll. The live board is /queue-display, which
            is push-based; polling here would add load for a screen someone
            looks at when a patient asks, not continuously. */}
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setShowOpenQueue((shown) => !shown)}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white"
          >
            {showOpenQueue ? "Close form" : "Open queue"}
          </button>
          <button type="button" onClick={() => void load()} className="text-sm underline">
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      {showOpenQueue && (
        <section className="surface-card space-y-4 p-5" aria-labelledby="open-queue-title">
          <div>
            <h2 id="open-queue-title" className="text-lg font-semibold">Open today&apos;s queue</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Available doctors come from today&apos;s HOD-approved roster.
            </p>
          </div>
          {openingOptions && openingOptions.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No available roster entries remain for {openingOptions.service_date}. The department
              HOD can add one from Department dashboard → Department roster; a development database
              seed is not required.
            </p>
          ) : (
            <div className="grid gap-4 md:grid-cols-[2fr_1fr_auto] md:items-end">
              <label className="space-y-1 text-sm">
                <span className="text-muted-foreground">Rostered clinic</span>
                <select
                  className="w-full rounded-md border border-border bg-background px-3 py-2"
                  value={optionId}
                  onChange={(event) => setOptionId(event.target.value)}
                >
                  {openingOptions?.items.map((option) => (
                    <option key={option.roster_id} value={option.roster_id}>
                      {option.staff_name} · {option.department_name} · {option.shift}
                      {option.room_number ? ` · Room ${option.room_number}` : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-sm">
                <span className="text-muted-foreground">Display label (optional)</span>
                <input
                  maxLength={50}
                  className="w-full rounded-md border border-border px-3 py-2"
                  value={displayLabel}
                  onChange={(event) => setDisplayLabel(event.target.value)}
                  placeholder="e.g. General OPD"
                />
              </label>
              <button
                type="button"
                disabled={creating || !optionId}
                onClick={() => void handleCreateQueue()}
                className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              >
                {creating ? "Opening…" : "Open"}
              </button>
            </div>
          )}
        </section>
      )}

      {queues !== null && queues.length === 0 && (
        <div className="surface-card p-6">
          <p className="text-sm text-muted-foreground">
            No open queues today.
          </p>
        </div>
      )}

      {queues && queues.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {queues.map((q) => (
            <button
              key={q.id}
              type="button"
              onClick={() => setSelected(q.id)}
              className={`surface-card p-4 text-left transition-all hover:shadow-md ${
                selected === q.id ? "ring-2 ring-primary" : ""
              }`}
            >
              <p className="text-base font-semibold">{q.doctor_name ?? "Doctor"}</p>
              <p className="text-sm text-muted-foreground">
                {q.room_number ? `Room ${q.room_number}` : "Room not assigned"}
              </p>
              <div className="mt-3 flex items-baseline gap-4">
                <span className="text-3xl font-bold tabular-nums">{q.waiting_count}</span>
                <span className="text-sm text-muted-foreground">waiting</span>
              </div>
              <p className="mt-1 text-sm">
                Now serving:{" "}
                <span className="font-mono">{q.now_serving ?? "—"}</span>
              </p>
            </button>
          ))}
        </div>
      )}

      {tokens && (
        <div className="surface-card overflow-hidden">
          <div className="border-b border-border px-6 py-4">
            <h2 className="text-lg font-semibold">
              {tokens.waiting_count} waiting · now serving{" "}
              <span className="font-mono">{tokens.now_serving ?? "—"}</span>
            </h2>
          </div>
          <table className="min-w-full border-collapse">
            <thead className="bg-muted">
              <tr>
                <th className="px-4 py-3 text-left">Token</th>
                <th className="px-4 py-3 text-left">Patient</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left">Priority</th>
                <th className="px-4 py-3 text-left">Issued</th>
                <th className="px-4 py-3 text-left">Action</th>
              </tr>
            </thead>
            <tbody>
              {tokens.items.map((t) => (
                <tr key={t.id} className="border-b border-border last:border-none">
                  <td className="px-4 py-3 font-mono">{t.token_display}</td>
                  <td className="px-4 py-3 text-sm">
                    <span className="block font-medium">{t.patient_name ?? "Patient unavailable"}</span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {t.patient_identifier ?? "No identifier"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm">{t.status.replaceAll("_", " ")}</td>
                  <td className="px-4 py-3 text-sm">{t.priority.replaceAll("_", " ")}</td>
                  <td className="px-4 py-3 text-sm">{formatDateTime(t.created_at)}</td>
                  <td className="px-4 py-3 text-sm">
                    {t.status === "waiting" && t.priority === "normal" ? (
                      <button
                        type="button"
                        className="font-medium underline"
                        onClick={() => {
                          setPriorityTokenId(t.id);
                          setPriority("senior_citizen");
                          setPriorityReason("");
                        }}
                      >
                        Change priority
                      </button>
                    ) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {priorityTokenId ? (
        <section className="surface-card space-y-4 p-5" aria-labelledby="priority-title">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 id="priority-title" className="text-lg font-semibold">Change queue priority</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Reception can record senior-citizen, pregnancy, or follow-up priority. Emergency escalation remains a clinical decision.
              </p>
            </div>
            <button type="button" className="text-sm underline" onClick={() => setPriorityTokenId(null)}>
              Cancel
            </button>
          </div>
          <div className="grid gap-4 md:grid-cols-[1fr_2fr_auto] md:items-end">
            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">Priority *</span>
              <select
                value={priority}
                onChange={(event) => setPriority(event.target.value as TokenPriorityUpdate["priority"])}
                className="w-full rounded-md border border-border bg-background px-3 py-2"
              >
                <option value="senior_citizen">Senior citizen</option>
                <option value="pregnant">Pregnant patient</option>
                <option value="follow_up_recall">Follow-up recall</option>
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">Reason *</span>
              <input
                required
                minLength={10}
                maxLength={250}
                value={priorityReason}
                onChange={(event) => setPriorityReason(event.target.value)}
                className={`w-full rounded-md border px-3 py-2 ${
                  priorityReason && priorityReason.trim().length < 10 ? "border-danger" : "border-border"
                }`}
                placeholder="Record why the priority applies"
              />
            </label>
            <button
              type="button"
              disabled={updatingPriority || priorityReason.trim().length < 10}
              onClick={() => void handlePriorityUpdate()}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {updatingPriority ? "Updating…" : "Update"}
            </button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
