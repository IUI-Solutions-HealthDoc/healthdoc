/** Laundry batches. Mutations carry an Idempotency-Key. */
import { api } from "@/lib/api";

export const LINEN_ITEM_TYPES = [
  "bed_sheet", "draw_sheet", "pillow_cover", "blanket", "patient_gown", "towel", "curtain", "ot_linen", "other",
] as const;
export type LinenItemType = (typeof LINEN_ITEM_TYPES)[number];
export type BatchStatus = "collected" | "washing" | "ready" | "returned";
export const NEXT_STATUS: Partial<Record<BatchStatus, BatchStatus>> = { collected: "washing", washing: "ready", ready: "returned" };

export interface LinenLine {
  item_type: LinenItemType;
  quantity: number;
  returned_quantity: number | null;
  condemned_quantity: number;
  missing_quantity: number | null;
}

export interface LinenBatch {
  id: string;
  ward_id: string | null;
  ward_name: string | null;
  bed_number: string | null;
  source: string | null;
  is_infected: boolean;
  status: BatchStatus;
  notes: string | null;
  collected_at: string;
  returned_at: string | null;
  items: LinenLine[];
}

export function listBatches(openOnly: boolean): Promise<LinenBatch[]> {
  return api<LinenBatch[]>(openOnly ? "/laundry/batches?open_only=true" : "/laundry/batches?status=returned");
}

export function collectLinen(
  payload: {
    ward_id: string | null; source: string | null; is_infected: boolean; notes: string | null;
    items: { item_type: LinenItemType; quantity: number }[];
  },
  idempotencyKey: string,
): Promise<LinenBatch> {
  return api<LinenBatch>("/laundry/batches", { method: "POST", idempotencyKey, body: JSON.stringify(payload) });
}

export function advanceBatch(
  id: string,
  payload: { status: BatchStatus; notes?: string | null; counts?: { item_type: LinenItemType; returned: number; condemned: number }[] },
  idempotencyKey: string,
): Promise<LinenBatch> {
  return api<LinenBatch>(`/laundry/batches/${id}/status`, { method: "POST", idempotencyKey, body: JSON.stringify(payload) });
}
