/**
 * Mirrors backend/app/pharmacy/schemas.py. Wire names, no mapping layer.
 *
 * Decimal fields arrive as strings over JSON. They are typed `string` here and
 * must stay that way — `parseFloat` on a quantity or an MRP loses paise, and a
 * dispense is a billable, auditable event.
 */

/** GET /pharmacy/queue */
export interface PrescriptionQueueItem {
  prescription_id: string;
  patient_id: string;
  patient_full_name: string;
  uhid: string | null;
  thid: string | null;
  visit_id: string | null;
  encounter_id: string;
  prescribed_at: string;
  item_count: number;
  /** null means nothing has been dispensed against this prescription yet. */
  dispense_status: string | null;
}

export interface PrescriptionQueueResponse {
  items: PrescriptionQueueItem[];
  page: number;
  page_size: number;
  total: number;
}

/** GET /pharmacy/medicines/search */
export interface BatchAvailability {
  batch_id: string;
  batch_number: string;
  expiry_date: string;
  quantity: string;
  stock_location_id: string;
  issue_rate_mrp: string | null;
}

export interface MedicineSearchResult {
  item_id: string;
  name: string;
  generic_name: string | null;
  strength: string | null;
  form: string | null;
  is_controlled_drug: boolean;
  total_available_quantity: string;
  /**
   * FEFO order — earliest expiry first — decided by the server, and the reason
   * the first batch is the one to pick. Do not re-sort this list in the UI: a
   * different order on screen from the order the server considers correct is
   * how expired stock gets dispensed.
   */
  batches: BatchAvailability[];
}

export interface MedicineSearchResponse {
  items: MedicineSearchResult[];
}

/** GET /orders/prescriptions/{prescription_id} */
export interface PrescriptionItem {
  id: string;
  prescription_id: string;
  medicine_item_id: string | null;
  medicine_name: string;
  dosage: string | null;
  frequency: string | null;
  duration_days: number | null;
  route: string | null;
  instructions: string | null;
  status: string;
  allergy_override_reason: string | null;
  allergy_override_by: string | null;
}

export interface PrescriptionDetail {
  id: string;
  encounter_id: string;
  facility_id: string;
  patient_id: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
  items: PrescriptionItem[];
  interaction_warnings: string[];
}

export interface DispenseItemInput {
  prescription_item_id: string;
  quantity_dispensed: string;
  batch_id?: string;
  substitute_item_id?: string;
  substitute_reason?: string;
  allergy_override_reason?: string;
  interaction_override_reason?: string;
}

export interface DispenseInput {
  prescription_id: string;
  items: DispenseItemInput[];
  allow_partial: boolean;
}

export interface BatchAllocation {
  batch_id: string;
  batch_number: string;
  quantity_from_batch: string;
  expiry_date: string;
}

export interface DispenseItemResult {
  item_row_ids: string[];
  prescription_item_id: string;
  quantity_prescribed: string | null;
  quantity_dispensed: string;
  is_substitute: boolean;
  substitute_item_id: string | null;
  substitute_reason: string | null;
  is_partial: boolean;
  approval_status: "not_required" | "pending" | "approved" | "rejected";
  batches: BatchAllocation[];
}

export interface DispenseResult {
  id: string;
  prescription_id: string;
  visit_id: string | null;
  status: string;
  dispensed_by: string;
  version: number;
  is_current: boolean;
  created_at: string;
  items: DispenseItemResult[];
}

export interface PendingSubstitution {
  item_id: string;
  dispense_id: string;
  prescription_id: string;
  prescription_item_id: string;
  patient_id: string;
  patient_full_name: string;
  uhid: string | null;
  prescribed_medicine_name: string;
  substitute_item_id: string;
  substitute_medicine_name: string;
  substitute_strength: string | null;
  substitute_form: string | null;
  quantity_requested: string;
  substitute_reason: string;
  requested_at: string;
}

export interface PendingSubstitutionResponse {
  items: PendingSubstitution[];
  total: number;
}

/** GET /pharmacy/expiry-tracker?threshold_days=30 */
export interface ExpiringBatch {
  batch_id: string;
  item_id: string;
  item_name: string;
  batch_number: string;
  expiry_date: string;
  days_to_expiry: number;
  quantity: string;
  stock_location_id: string;
  stock_location_name: string;
}

export interface ExpiryTrackerResponse {
  items: ExpiringBatch[];
  threshold_days: number;
}

export interface ReorderAlertItem {
  item_id: string;
  item_name: string;
  reorder_level: string;
  current_stock: string;
}

export interface ReorderAlertsResponse {
  items: ReorderAlertItem[];
}

/**
 * The 30/60/90 buckets #212 asks for.
 *
 * Already-expired stock is split out rather than folded into "30 days": a batch
 * that expired yesterday is not a warning, it is stock that must not leave the
 * counter, and putting it in the same bucket as one expiring next month hides
 * exactly the row a pharmacist has to act on first.
 */
export type ExpiryBucket = "expired" | "30" | "60" | "90";

export function bucketFor(daysToExpiry: number): ExpiryBucket {
  if (daysToExpiry < 0) return "expired";
  if (daysToExpiry <= 30) return "30";
  if (daysToExpiry <= 60) return "60";
  return "90";
}

export const BUCKET_LABELS: Record<ExpiryBucket, string> = {
  expired: "Expired — do not dispense",
  "30": "Within 30 days",
  "60": "31–60 days",
  "90": "61–90 days",
};

/** HD-24: Medicine Stock Returns */
export interface PharmacyReturn {
  id: string;
  facility_id: string;
  patient_id: string;
  dispense_id: string | null;
  item_id: string;
  batch_id: string | null;
  quantity: string;
  return_reason: string;
  disposition: "resalable" | "quarantine" | "damaged" | "expired";
  status: string;
  returned_by: string;
  created_at: string;
  item_name?: string | null;
  batch_number?: string | null;
}

export interface PharmacyReturnListResponse {
  items: PharmacyReturn[];
  total: number;
}

export interface PharmacyReturnCreateInput {
  patient_id: string;
  dispense_id?: string | null;
  item_id: string;
  batch_id?: string | null;
  quantity: number | string;
  return_reason: string;
  disposition: "resalable" | "quarantine" | "damaged" | "expired";
}

