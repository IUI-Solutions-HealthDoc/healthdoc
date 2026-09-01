/**
 * Head-of-department dashboard reads.
 *
 * All five are gated `require_roles("hod", "admin")` and scoped to the caller's
 * FACILITY, not their department — the department comes from the path. That is
 * why the screen takes its department from `/users/me` rather than a picker:
 * with a picker, the head of Medicine could read Surgery's workload and pending
 * approvals simply by choosing it.
 *
 * `overview_date` and `workload_date` are REQUIRED query parameters with no
 * server default. Omitting them is a 422, not a "today" — so the caller decides
 * which day it is, deliberately, because "today" at a facility is its own
 * business date and not the browser's.
 */
import { api } from "@/lib/api";

import type {
  DepartmentWorkload,
  CreateRosterEntry,
  EmergencyEscalation,
  HodOverview,
  PendingApproval,
  PendingLabOrder,
  RosterCandidate,
  RosterEntry,
  RosterRoom,
} from "./types";

/** Queues and roster for one department on one day. */
export function getOverview(departmentId: string, date: string): Promise<HodOverview> {
  return api<HodOverview>(
    `/queue/hod-dashboard/${departmentId}?overview_date=${encodeURIComponent(date)}`,
  );
}

/** Counts for the same day: waiting, queues open/closed, completed. */
export function getWorkload(departmentId: string, date: string): Promise<DepartmentWorkload> {
  return api<DepartmentWorkload>(
    `/queue/hod-dashboard/${departmentId}/workload?workload_date=${encodeURIComponent(date)}`,
  );
}

/**
 * Tokens escalated to emergency priority.
 *
 * No date parameter — an escalation is live or it is not, and a department head
 * looking at this wants what is happening now, not what happened on a chosen
 * day.
 */
export async function listEscalations(departmentId: string): Promise<EmergencyEscalation[]> {
  const response = await api<{ items: EmergencyEscalation[] }>(
    `/queue/hod-dashboard/${departmentId}/emergency-escalations`,
  );
  return response.items;
}

/** Lab work ordered by this department and not yet resulted. */
export async function listPendingLabOrders(departmentId: string): Promise<PendingLabOrder[]> {
  const response = await api<{ items: PendingLabOrder[] }>(
    `/queue/hod-dashboard/${departmentId}/pending-lab-orders`,
  );
  return response.items;
}

/** Indents from this department awaiting the HOD's approval. */
export async function listPendingApprovals(departmentId: string): Promise<PendingApproval[]> {
  const response = await api<{ items: PendingApproval[] }>(
    `/queue/hod-dashboard/${departmentId}/pending-approvals`,
  );
  return response.items;
}

/** Minimal active staff list for the caller's own department. */
export async function listRosterCandidates(
  departmentId: string,
): Promise<RosterCandidate[]> {
  const response = await api<{ items: RosterCandidate[] }>(
    `/queue/roster-candidates?department_id=${encodeURIComponent(departmentId)}`,
  );
  return response.items;
}

/** Active rooms in this department; room assignment on a roster is optional. */
export async function listRosterRooms(departmentId: string): Promise<RosterRoom[]> {
  const response = await api<{
    items: RosterRoom[];
    page: number;
    page_size: number;
    total: number;
  }>(
    `/departments/rooms?department_id=${encodeURIComponent(departmentId)}&is_active=true&page=1&page_size=100`,
  );
  return response.items;
}

export async function listRoster(
  departmentId: string,
  rosterDate: string,
): Promise<RosterEntry[]> {
  const response = await api<{ items: RosterEntry[] }>(
    `/queue/rosters?department_id=${encodeURIComponent(departmentId)}&roster_date=${encodeURIComponent(rosterDate)}`,
  );
  return response.items;
}

export function createRosterEntry(
  payload: CreateRosterEntry,
  idempotencyKey: string,
): Promise<RosterEntry> {
  return api<RosterEntry>("/queue/rosters", {
    method: "POST",
    idempotencyKey,
    body: JSON.stringify(payload),
  });
}

export function setRosterAvailability(
  rosterId: string,
  isAvailable: boolean,
): Promise<RosterEntry> {
  return api<RosterEntry>(`/queue/rosters/${rosterId}/availability`, {
    method: "PATCH",
    body: JSON.stringify({ is_available: isAvailable }),
  });
}
