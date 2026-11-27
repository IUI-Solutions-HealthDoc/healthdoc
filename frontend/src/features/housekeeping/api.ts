/** Housekeeping tasks. Mutations carry an Idempotency-Key. */
import { api } from "@/lib/api";

import type { LinenItemType } from "@/features/laundry/api";

export const TASK_TYPES = ["bed_turnover", "terminal_clean", "routine_clean", "spill", "linen_change", "other"] as const;
export type TaskType = (typeof TASK_TYPES)[number];
/** What staff may raise by hand; turnovers come from discharge and transfer. */
export const MANUAL_TASK_TYPES = TASK_TYPES.filter((type) => type !== "bed_turnover");
export type Priority = "routine" | "urgent";
export type TaskStatus = "pending" | "in_progress" | "done" | "cancelled";

export interface HousekeepingTask {
  id: string;
  ward_id: string;
  ward_name: string | null;
  bed_id: string | null;
  bed_number: string | null;
  task_type: TaskType;
  priority: Priority;
  source: "discharge" | "transfer" | "manual";
  status: TaskStatus;
  notes: string | null;
  requested_at: string;
  assigned_to_name: string | null;
  started_at: string | null;
  completed_at: string | null;
  linen_changed: boolean;
  mattress_disinfected: boolean;
  surfaces_disinfected: boolean;
  waste_removed: boolean;
  linen_batch_id: string | null;
  cancel_reason: string | null;
}

export interface CompletePayload {
  assigned_to_name: string | null;
  linen_changed: boolean;
  mattress_disinfected: boolean;
  surfaces_disinfected: boolean;
  waste_removed: boolean;
  notes: string | null;
  linen_items: { item_type: LinenItemType; quantity: number }[];
  linen_infected: boolean;
}

export function listTasks(state: "open" | "closed"): Promise<HousekeepingTask[]> {
  return api<HousekeepingTask[]>(`/housekeeping/tasks?state=${state}`);
}

export function raiseTask(
  payload: { ward_id: string; bed_id: string | null; task_type: TaskType; priority: Priority; notes: string | null },
  idempotencyKey: string,
): Promise<HousekeepingTask> {
  return api<HousekeepingTask>("/housekeeping/tasks", { method: "POST", idempotencyKey, body: JSON.stringify(payload) });
}

export function startTask(id: string, assignedToName: string | null, idempotencyKey: string): Promise<HousekeepingTask> {
  return api<HousekeepingTask>(`/housekeeping/tasks/${id}/start`, {
    method: "POST", idempotencyKey, body: JSON.stringify({ assigned_to_name: assignedToName }),
  });
}

export function completeTask(id: string, payload: CompletePayload, idempotencyKey: string): Promise<HousekeepingTask> {
  return api<HousekeepingTask>(`/housekeeping/tasks/${id}/complete`, { method: "POST", idempotencyKey, body: JSON.stringify(payload) });
}

export function cancelTask(id: string, reason: string, idempotencyKey: string): Promise<HousekeepingTask> {
  return api<HousekeepingTask>(`/housekeeping/tasks/${id}/cancel`, { method: "POST", idempotencyKey, body: JSON.stringify({ reason }) });
}
