/**
 * Equipment register. Mutations carry an Idempotency-Key: a status change
 * retried on a flaky ward connection must record one event, not two.
 */
import { api } from "@/lib/api";

export const EQUIPMENT_CATEGORIES = [
  "imaging", "laboratory", "life_support", "monitoring", "surgical", "sterilisation", "power", "cold_chain", "other",
] as const;
export type EquipmentCategory = (typeof EQUIPMENT_CATEGORIES)[number];
export type EquipmentStatus = "working" | "down" | "maintenance" | "retired";

export interface EquipmentItem {
  id: string;
  name: string;
  category: EquipmentCategory;
  location: string | null;
  asset_tag: string | null;
  is_critical: boolean;
  status: EquipmentStatus;
  status_since: string;
  status_reason: string | null;
}

export interface EquipmentEvent {
  from_status: EquipmentStatus | null;
  to_status: EquipmentStatus;
  reason: string | null;
  changed_by: string;
  changed_at: string;
}

export function listEquipment(): Promise<EquipmentItem[]> {
  return api<EquipmentItem[]>("/equipment");
}

export function registerEquipment(
  payload: { name: string; category: EquipmentCategory; location: string | null; asset_tag: string | null; is_critical: boolean },
  idempotencyKey: string,
): Promise<EquipmentItem> {
  return api<EquipmentItem>("/equipment", { method: "POST", idempotencyKey, body: JSON.stringify(payload) });
}

export function changeEquipmentStatus(
  id: string,
  payload: { status: EquipmentStatus; reason: string | null },
  idempotencyKey: string,
): Promise<EquipmentItem> {
  return api<EquipmentItem>(`/equipment/${id}/status`, { method: "POST", idempotencyKey, body: JSON.stringify(payload) });
}

export function equipmentHistory(id: string): Promise<EquipmentEvent[]> {
  return api<EquipmentEvent[]>(`/equipment/${id}/history`);
}
