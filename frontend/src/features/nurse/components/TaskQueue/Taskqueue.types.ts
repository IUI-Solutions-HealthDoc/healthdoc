export type OrderType = "lab" | "radiology" | "pharmacy" | "procedure" | "blood" | string;
export type OrderPriority = "routine" | "urgent" | "stat";

export type OrderStatus =
  | "placed"
  | "accepted"
  | "in_progress"
  | "completed"
  | "cancelled";

export interface Order {
  id: string;
  order_number?: string;
  encounter_id: string | null;
  patient_id: string;
  order_type: OrderType;
  priority: OrderPriority;
  status: OrderStatus;
  ordered_at: string;
  /** 0045 — when the ward took ownership (null until accept/complete). */
  accepted_at?: string | null;
  accepted_by?: string | null;
  /** 0045 — check-off evidence. */
  completed_at?: string | null;
  completed_by?: string | null;
  completion_note?: string | null;

  // Joined display field — not a column on `orders` (comes from
  // patients.full_name).
  patient_name?: string | null;
  patient_uhid?: string | null;
  patient_age_years?: number | null;
  patient_sex?: string | null;
}

export interface TaskQueueProps {
  orders: Order[];
  onAccept?: (orderId: string) => void | Promise<void>;
  onCheckOff: (orderId: string) => void | Promise<void>;
}
