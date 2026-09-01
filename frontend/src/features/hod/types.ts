/**
 * Head-of-department dashboard.
 *
 * These shapes are transcribed from app/queue/schemas.py, not inferred from the
 * OpenAPI spec: every hod-dashboard handler is annotated `-> dict` with no
 * response_model, so the spec describes them as untyped objects. The schema
 * classes are the real contract — HodDashboardOverviewOut, DepartmentWorkloadOut,
 * EmergencyEscalationOut, PendingApprovalOut, PendingLabOrderOut.
 *
 * Numbers that are counts arrive as JSON numbers. `quantity_requested` is a
 * Decimal server-side and therefore a STRING on the wire — the same rule as
 * money everywhere else in this codebase. Do not parseFloat it for display.
 */

export interface HodQueueSummary {
  queue_id: string;
  doctor_user_id: string;
  doctor_name: string | null;
  room_id: string | null;
  is_open: boolean;
  waiting_count: number;
  now_serving: string | null;
}

export interface HodRosterSummary {
  roster_id: string;
  staff_user_id: string;
  shift: string;
  room_id: string | null;
  is_available: boolean;
}

export type RosterShift = "morning" | "evening" | "night";

export interface RosterEntry {
  id: string;
  staff_user_id: string;
  department_id: string;
  room_id: string | null;
  shift: RosterShift;
  roster_date: string;
  is_available: boolean;
}

export interface RosterCandidate {
  staff_user_id: string;
  staff_name: string;
  designation: string | null;
}

export interface RosterRoom {
  id: string;
  department_id: string;
  room_number: string;
  is_active: boolean;
}

export interface CreateRosterEntry {
  staff_user_id: string;
  department_id: string;
  room_id: string | null;
  shift: RosterShift;
  roster_date: string;
}

export interface HodOverview {
  department_id: string;
  date: string;
  queues: HodQueueSummary[];
  roster: HodRosterSummary[];
}

export interface DepartmentWorkload {
  department_id: string;
  date: string;
  total_waiting: number;
  queues_open: number;
  queues_closed: number;
  completed_today: number;
}

export interface EmergencyEscalation {
  token_id: string;
  token_display: string;
  status: string;
  doctor_name: string | null;
  created_at: string;
}

export interface PendingLabOrder {
  lab_order_item_id: string;
  accession_number: string;
  test_name: string;
  status: string;
  /** Null when the test has no published turnaround estimate. */
  estimated_minutes: number | null;
  created_at: string;
}

export interface PendingApprovalItem {
  item_id: string;
  item_name: string | null;
  /** Decimal server-side, so a string on the wire. */
  quantity_requested: string;
}

/**
 * An indent awaiting this HOD's approval.
 *
 * The same rows the inventory screen shows under Indents. Surfaced here too
 * because approval is a departmental budget decision and the HOD's own screen
 * is where they would look for it — not the storekeeper's.
 */
export interface PendingApproval {
  indent_id: string;
  department_id: string;
  created_at: string;
  items: PendingApprovalItem[];
}
