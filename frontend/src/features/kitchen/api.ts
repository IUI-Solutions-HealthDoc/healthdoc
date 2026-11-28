/**
 * Kitchen and diet. Mutations carry an Idempotency-Key: a meal record retried
 * on a flaky ward connection must record one meal, not two.
 */
import { api } from "@/lib/api";

export const DIET_TYPES = [
  "normal", "soft", "liquid", "clear_liquid", "diabetic", "renal", "low_salt", "low_fat",
  "high_protein", "semi_solid", "tube_feed", "npo", "other",
] as const;
export type DietType = (typeof DIET_TYPES)[number];

export const MEALS = ["early_morning", "breakfast", "mid_morning", "lunch", "evening_snack", "dinner", "bedtime"] as const;
export type Meal = (typeof MEALS)[number];

export const MEAL_STATUSES = ["served", "refused", "not_served"] as const;
export type MealStatus = (typeof MEAL_STATUSES)[number];

export interface DietOrder {
  id: string;
  admission_id: string;
  diet_type: DietType;
  instructions: string | null;
  food_allergies: string | null;
  status: "active" | "stopped";
  starts_at: string;
  stopped_at: string | null;
  stop_reason: string | null;
}

export interface MealRecord {
  id: string;
  admission_id: string;
  diet_order_id: string | null;
  service_date: string;
  meal: Meal;
  status: MealStatus;
  notes: string | null;
  recorded_at: string;
}

export interface BoardRow {
  admission_id: string;
  ward_id: string;
  ward_name: string;
  bed_number: string;
  patient_name: string | null;
  uhid: string | null;
  diet: DietOrder | null;
  meals: MealRecord[];
}

export interface KitchenBoard {
  service_date: string;
  meals: Meal[];
  rows: BoardRow[];
}

export function getKitchenBoard(date: string, wardId: string | null): Promise<KitchenBoard> {
  const params = new URLSearchParams({ date });
  if (wardId) params.set("ward_id", wardId);
  return api<KitchenBoard>(`/dietary/board?${params.toString()}`);
}

export function orderDiet(
  payload: { admission_id: string; diet_type: DietType; instructions: string | null; food_allergies: string | null },
  idempotencyKey: string,
): Promise<DietOrder> {
  return api<DietOrder>("/dietary/orders", { method: "POST", idempotencyKey, body: JSON.stringify(payload) });
}

export function stopDiet(orderId: string, reason: string, idempotencyKey: string): Promise<DietOrder> {
  return api<DietOrder>(`/dietary/orders/${orderId}/stop`, { method: "POST", idempotencyKey, body: JSON.stringify({ reason }) });
}

export function recordMeal(
  payload: { admission_id: string; service_date: string; meal: Meal; status: MealStatus; notes: string | null },
  idempotencyKey: string,
): Promise<MealRecord> {
  return api<MealRecord>("/dietary/meals", { method: "POST", idempotencyKey, body: JSON.stringify(payload) });
}
