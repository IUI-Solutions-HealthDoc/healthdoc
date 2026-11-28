"use client";

/**
 * Housekeeping: open cleaning tasks, urgent first then oldest first. A bed
 * turnover arrives on its own when a patient is discharged or transferred;
 * marking it done (linen changed, mattress and surfaces disinfected) returns
 * the bed to the vacant pool. Linen stripped during the clean can be sent to
 * the laundry from the same form.
 */
import { useCallback, useEffect, useState } from "react";

import { ApiError, formatDateTime, newIdempotencyKey } from "@/lib/api";
import { useLocale } from "@/lib/i18n";
import { useAuth } from "@/providers/auth-provider";
import { getWardLocations, type WardLocation } from "@/lib/wardLocations";

import {
  MANUAL_TASK_TYPES,
  cancelTask,
  completeTask,
  listTasks,
  raiseTask,
  startTask,
  type HousekeepingTask,
  type Priority,
  type TaskStatus,
  type TaskType,
} from "./api";

const STATUS_BADGE: Record<TaskStatus, string> = {
  pending: "bg-amber-100 text-amber-900",
  in_progress: "bg-sky-100 text-sky-900",
  done: "bg-emerald-100 text-emerald-800",
  cancelled: "bg-slate-100 text-slate-600",
};

/** The linen a bed usually gives up; other items go through the Laundry screen. */
const BED_LINEN = ["bed_sheet", "draw_sheet", "pillow_cover", "blanket"] as const;

export function HousekeepingBoard() {
  const { t } = useLocale();
  const [state, setState] = useState<"open" | "closed">("open");
  const [tasks, setTasks] = useState<HousekeepingTask[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setTasks(await listTasks(state));
      setError(null);
    } catch (reason) {
      setTasks(null);
      setError(reason instanceof ApiError ? reason.message : t("housekeeping.errLoad"));
    }
  }, [state, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const beds = tasks?.filter((task) => task.task_type === "bed_turnover").length ?? 0;

  return (
    <div className="space-y-5 p-6">
      <div>
        <h1 className="text-xl font-semibold">{t("housekeeping.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("housekeeping.intro")}</p>
      </div>
      <RaiseForm onSaved={() => void load()} />
      <div className="flex gap-2 text-sm">
        <button type="button" onClick={() => setState("open")}
          className={`rounded-md px-3 py-1 ${state === "open" ? "bg-primary text-white" : "border border-border"}`}>{t("housekeeping.openTab")}</button>
        <button type="button" onClick={() => setState("closed")}
          className={`rounded-md px-3 py-1 ${state === "closed" ? "bg-primary text-white" : "border border-border"}`}>{t("housekeeping.closedTab")}</button>
      </div>
      {error ? <p className="text-sm text-danger" role="alert">{error}</p> : null}
      {tasks === null && !error ? <p className="text-sm text-muted-foreground">{t("common.loading")}</p> : null}
      {tasks && state === "open" ? <p className="text-sm">{t("housekeeping.summary", { total: tasks.length, beds })}</p> : null}
      {tasks && tasks.length === 0 ? <p className="text-sm text-muted-foreground">{t("housekeeping.empty")}</p> : null}
      {tasks && tasks.length ? (
        <ul className="space-y-2">
          {tasks.map((task) => <TaskRow key={task.id} task={task} onChanged={() => void load()} />)}
        </ul>
      ) : null}
    </div>
  );
}

function RaiseForm({ onSaved }: { onSaved: () => void }) {
  const { t } = useLocale();
  const [wards, setWards] = useState<WardLocation[]>([]);
  const [wardId, setWardId] = useState("");
  const [bedId, setBedId] = useState("");
  const [taskType, setTaskType] = useState<TaskType>("routine_clean");
  const [priority, setPriority] = useState<Priority>("routine");
  const [notes, setNotes] = useState("");
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getWardLocations().then(setWards).catch(() => setWards([]));
  }, []);

  const beds = wards.find((ward) => ward.ward_id === wardId)?.beds ?? [];

  const needsNotes = taskType === "other";

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!wardId || busy || (needsNotes && !notes.trim())) return;
    setBusy(true);
    setError(null);
    try {
      await raiseTask({ ward_id: wardId, bed_id: bedId || null, task_type: taskType, priority, notes: notes.trim() || null }, key);
      setNotes("");
      setBedId("");
      setKey(newIdempotencyKey());
      onSaved();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t("housekeeping.errSave"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="grid gap-3 rounded border border-border p-4 text-sm md:grid-cols-6">
      <p className="font-medium md:col-span-6">{t("housekeeping.raiseTitle")}</p>
      <label>
        <span className="text-muted-foreground">{t("housekeeping.ward")}</span>
        <select value={wardId} onChange={(e) => { setWardId(e.target.value); setBedId(""); }} className="mt-1 w-full rounded-md border border-border px-2 py-1.5">
          <option value="">—</option>
          {wards.map((ward) => <option key={ward.ward_id} value={ward.ward_id}>{ward.ward_name}</option>)}
        </select>
      </label>
      <label>
        <span className="text-muted-foreground">{t("housekeeping.bed")}</span>
        <select value={bedId} onChange={(e) => setBedId(e.target.value)} disabled={!wardId}
          className="mt-1 w-full rounded-md border border-border px-2 py-1.5">
          <option value="">{t("housekeeping.wholeWard")}</option>
          {beds.map((bed) => <option key={bed.bed_id} value={bed.bed_id}>{bed.bed_number}</option>)}
        </select>
      </label>
      <label>
        <span className="text-muted-foreground">{t("housekeeping.taskType")}</span>
        <select value={taskType} onChange={(e) => setTaskType(e.target.value as TaskType)} className="mt-1 w-full rounded-md border border-border px-2 py-1.5">
          {MANUAL_TASK_TYPES.map((type) => (
            <option key={type} value={type}>{t(`housekeeping.type.${type}` as "housekeeping.type.other")}</option>
          ))}
        </select>
      </label>
      <label>
        <span className="text-muted-foreground">{t("housekeeping.priority")}</span>
        <select value={priority} onChange={(e) => setPriority(e.target.value as Priority)} className="mt-1 w-full rounded-md border border-border px-2 py-1.5">
          <option value="routine">{t("housekeeping.priority.routine")}</option>
          <option value="urgent">{t("housekeeping.priority.urgent")}</option>
        </select>
      </label>
      <label className="md:col-span-2">
        <span className="text-muted-foreground">{t("housekeeping.notes")}</span>
        <input value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={500}
          className="mt-1 w-full rounded-md border border-border px-2 py-1.5" />
      </label>
      <div className="md:col-span-6">
        <button type="submit" disabled={!wardId || busy || (needsNotes && !notes.trim())}
          className="rounded-md bg-primary px-3 py-1.5 font-medium text-white disabled:opacity-50">
          {t("housekeeping.raise")}
        </button>
      </div>
      {error ? <p className="text-sm text-danger md:col-span-6" role="alert">{error}</p> : null}
    </form>
  );
}

function TaskRow({ task, onChanged }: { task: HousekeepingTask; onChanged: () => void }) {
  const { t } = useLocale();
  const { user } = useAuth();
  // Cancel is nurse/admin/supervisor on the server; HOD can do everything else.
  const canCancel = ["nurse", "admin", "supervisor"].includes(user?.role ?? "");
  const isOpen = task.status === "pending" || task.status === "in_progress";
  const strict = task.task_type === "bed_turnover" || task.task_type === "terminal_clean";
  const [mode, setMode] = useState<"" | "complete" | "cancel">("");
  const [cleaner, setCleaner] = useState(task.assigned_to_name ?? "");
  const [checks, setChecks] = useState({ linen_changed: false, mattress_disinfected: false, surfaces_disinfected: false, waste_removed: false });
  const [linen, setLinen] = useState<Partial<Record<(typeof BED_LINEN)[number], string>>>({});
  const [linenInfected, setLinenInfected] = useState(false);
  const [notes, setNotes] = useState("");
  const [reason, setReason] = useState("");
  const [key, setKey] = useState(newIdempotencyKey);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const linenItems = BED_LINEN.map((item_type) => ({ item_type, quantity: Number((linen[item_type] ?? "").trim() || "0") }))
    .filter((line) => line.quantity !== 0);
  const linenValid = linenItems.every((line) => Number.isInteger(line.quantity) && line.quantity > 0);
  const ready = !strict || (checks.linen_changed && checks.mattress_disinfected && checks.surfaces_disinfected);

  async function run(action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await action();
      setKey(newIdempotencyKey());
      setMode("");
      onChanged();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t("housekeeping.errSave"));
    } finally {
      setBusy(false);
    }
  }

  const checkLabels: [keyof typeof checks, string][] = [
    ["linen_changed", t("housekeeping.linenChanged")],
    ["mattress_disinfected", t("housekeeping.mattressDisinfected")],
    ["surfaces_disinfected", t("housekeeping.surfacesDisinfected")],
    ["waste_removed", t("housekeeping.wasteRemoved")],
  ];

  return (
    <li className={`rounded border p-3 text-sm ${task.priority === "urgent" && isOpen ? "border-amber-400" : "border-border"}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">
            {task.ward_name}{task.bed_number ? ` · ${t("housekeeping.bedLabel", { bed: task.bed_number })}` : ""}
          </p>
          <p className="text-xs text-muted-foreground">
            {t(`housekeeping.type.${task.task_type}` as "housekeeping.type.other")} · {t(`housekeeping.source.${task.source}` as "housekeeping.source.manual")}
            {" · "}{t("housekeeping.requested", { when: formatDateTime(task.requested_at) })}
          </p>
          {task.notes ? <p className="mt-1 whitespace-pre-line text-xs">{task.notes}</p> : null}
          {task.assigned_to_name ? <p className="text-xs">{t("housekeeping.cleanedBy", { name: task.assigned_to_name })}</p> : null}
          {task.status === "done" && task.completed_at ? (
            <p className="text-xs text-muted-foreground">
              {t("housekeeping.done", { when: formatDateTime(task.completed_at) })}
              {task.linen_batch_id ? ` · ${t("housekeeping.sentToLaundry")}` : ""}
            </p>
          ) : null}
          {task.status === "cancelled" && task.cancel_reason ? (
            <p className="text-xs text-muted-foreground">{t("housekeeping.cancelledBecause", { reason: task.cancel_reason })}</p>
          ) : null}
        </div>
        <div className="flex flex-col items-end gap-1">
          <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_BADGE[task.status]}`}>
            {t(`housekeeping.status.${task.status}` as "housekeeping.status.pending")}
          </span>
          {task.priority === "urgent" ? <span className="text-xs font-medium text-amber-800">{t("housekeeping.priority.urgent")}</span> : null}
        </div>
      </div>
      {isOpen ? (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input value={cleaner} onChange={(e) => setCleaner(e.target.value)} maxLength={120} placeholder={t("housekeeping.cleaner")}
            className="rounded-md border border-border px-2 py-1 text-xs" />
          {task.status === "pending" ? (
            <button type="button" disabled={busy} onClick={() => void run(() => startTask(task.id, cleaner.trim() || null, key))}
              className="rounded-md border border-border px-3 py-1 text-xs disabled:opacity-50">{t("housekeeping.start")}</button>
          ) : null}
          <button type="button" onClick={() => setMode(mode === "complete" ? "" : "complete")}
            className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-white">{t("housekeeping.complete")}</button>
          {canCancel ? (
            <button type="button" onClick={() => setMode(mode === "cancel" ? "" : "cancel")} className="text-xs underline">
              {t("housekeeping.cancel")}
            </button>
          ) : null}
        </div>
      ) : null}
      {isOpen && mode === "complete" ? (
        <div className="mt-2 space-y-2 rounded border border-border p-3 text-xs">
          {strict ? <p className="text-muted-foreground">{t("housekeeping.turnoverRule")}</p> : null}
          <div className="flex flex-wrap gap-3">
            {checkLabels.map(([field, label]) => (
              <label key={field} className="flex items-center gap-1.5">
                <input type="checkbox" checked={checks[field]} onChange={(e) => setChecks((c) => ({ ...c, [field]: e.target.checked }))} />
                {label}
              </label>
            ))}
          </div>
          <p className="font-medium">{t("housekeeping.sendLinen")}</p>
          <div className="flex flex-wrap gap-2">
            {BED_LINEN.map((item) => (
              <label key={item} className="flex items-center gap-1">
                {t(`laundry.item.${item}` as "laundry.item.other")}
                <input inputMode="numeric" value={linen[item] ?? ""} onChange={(e) => setLinen((l) => ({ ...l, [item]: e.target.value }))}
                  className="w-14 rounded-md border border-border px-1 py-0.5" />
              </label>
            ))}
            <label className="flex items-center gap-1.5">
              <input type="checkbox" checked={linenInfected} onChange={(e) => setLinenInfected(e.target.checked)} />
              {t("housekeeping.linenInfected")}
            </label>
          </div>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={500} placeholder={t("housekeeping.notes")}
            className="w-full rounded-md border border-border px-2 py-1" />
          <button type="button" disabled={busy || !ready || !linenValid}
            onClick={() => void run(() => completeTask(task.id, {
              assigned_to_name: cleaner.trim() || null, ...checks, notes: notes.trim() || null,
              linen_items: linenItems, linen_infected: linenInfected,
            }, key))}
            className="rounded-md bg-primary px-3 py-1 font-medium text-white disabled:opacity-50">{t("common.save")}</button>
        </div>
      ) : null}
      {isOpen && mode === "cancel" ? (
        <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
          <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} placeholder={t("housekeeping.cancelReason")}
            className="min-w-64 flex-1 rounded-md border border-border px-2 py-1" />
          <button type="button" disabled={busy || !reason.trim()} onClick={() => void run(() => cancelTask(task.id, reason.trim(), key))}
            className="rounded-md border border-border px-3 py-1 disabled:opacity-50">{t("housekeeping.confirmCancel")}</button>
        </div>
      ) : null}
      {error ? <p className="mt-1 text-xs text-danger" role="alert">{error}</p> : null}
    </li>
  );
}
