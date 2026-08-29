/**
 * Procurement: goods receipt, department indents, stock adjustments.
 *
 * These live under /pharmacy on the wire even though the screen is "Inventory"
 * — the whole procurement workflow is owned by the pharmacy module, and
 * app/inventory/ holds only the item/batch/ledger models. Named for the screen
 * here and mapped to the real paths in api.ts, rather than renaming the routes.
 *
 * Money and quantities arrive as decimal STRINGS. Never parseFloat them for
 * display; a stock quantity that has been through a float is a quantity you
 * cannot reconcile against the ledger.
 */

export type GrnStatus = "draft" | "received" | "verified" | "cancelled";
/**
 * Taken from ck_indents_status, not inferred from the workflow. An indent
 * starts 'requested'; there is no 'pending' state here even though adjustments
 * have one. Two workflows in the same module using different vocabulary for
 * "not yet decided" is exactly the kind of thing worth reading rather than
 * assuming.
 */
export type IndentStatus = "requested" | "approved" | "rejected" | "issued";
export type AdjustmentStatus = "pending" | "approved" | "rejected";

export interface Supplier {
  id: string;
  name: string;
  contact_info: string | null;
  is_active: boolean;
}

export interface StockLocation {
  id: string;
  name: string;
  location_type:
    | "central"
    | "pharmacy"
    | "lab"
    | "radiology"
    | "ward"
    | "emergency"
    | "ot";
  department_id: string | null;
}

export interface GrnItem {
  id: string;
  item_id: string;
  batch_number: string | null;
  expiry_date: string | null;
  quantity: string;
  unit_price: string | null;
}

export interface Grn {
  id: string;
  supplier_id: string;
  invoice_number: string | null;
  received_date: string;
  status: GrnStatus;
  items: GrnItem[];
}

export interface GrnItemDraft {
  item_id: string;
  /** Display-only; the wire carries item_id. Kept so the table can name a row. */
  item_name: string;
  batch_number: string;
  expiry_date: string;
  quantity: string;
  unit_price: string;
}

export interface CreateGrnInput {
  supplier_id: string;
  purchase_order_id?: string | null;
  invoice_number: string | null;
  received_date: string;
  items: Array<{
    item_id: string;
    batch_number: string | null;
    expiry_date: string | null;
    quantity: string;
    unit_price: string | null;
  }>;
}

export interface IndentItem {
  id: string;
  item_id: string;
  quantity_requested: string;
}

export interface Indent {
  id: string;
  department_id: string;
  status: IndentStatus;
  approved_by: string | null;
  items: IndentItem[];
}

export interface CreateIndentInput {
  department_id: string;
  items: Array<{ item_id: string; quantity_requested: string }>;
}

export interface Adjustment {
  id: string;
  item_id: string;
  batch_id: string;
  quantity_change: string;
  reason: string;
  first_approver_id: string;
  second_approver_id: string | null;
  status: AdjustmentStatus;
}

export interface CreateAdjustmentInput {
  item_id: string;
  batch_id: string;
  quantity_change: string;
  reason: string;
  /**
   * A DIFFERENT person from whoever is submitting.
   *
   * Four database CHECK constraints enforce the separation of duties:
   * created_by <> first_approver_id, created_by <> second_approver_id,
   * first_approver_id <> second_approver_id, and status cannot reach
   * 'approved' without a second approver. The creator can be neither
   * approver. Three distinct people, minimum, before stock moves on paper
   * without moving in the store — which is how shrinkage gets concealed.
   */
  first_approver_id: string;
}

export interface ApprovalDecision {
  approve: boolean;
  reason: string | null;
}

/* -------------------------------------------------- list rows (read side) */
/*
 * These carry display NAMES joined server-side. The alternative — ids plus a
 * lookup per row in the client — is an N+1 on every render, and worse, an
 * approval screen that renders a UUID is one nobody can act on.
 */

export interface GrnListRow {
  id: string;
  supplier_id: string;
  supplier_name: string;
  invoice_number: string | null;
  received_date: string;
  status: GrnStatus;
  line_count: number;
  created_at: string;
  updated_at: string;
}

export interface IndentListRow {
  id: string;
  department_id: string;
  department_name: string;
  status: IndentStatus;
  approved_by: string | null;
  approved_by_name: string | null;
  line_count: number;
  created_at: string;
}

export interface AdjustmentListRow {
  id: string;
  item_id: string;
  item_name: string;
  batch_id: string;
  batch_number: string;
  expiry_date: string;
  /** Signed decimal string. Negative is a write-down. */
  quantity_change: string;
  /** What the batch holds now — context a reviewer needs to judge the change. */
  quantity_on_hand: string;
  reason: string;
  status: AdjustmentStatus;
  created_by: string;
  created_by_name: string;
  first_approver_id: string;
  first_approver_name: string;
  second_approver_id: string | null;
  second_approver_name: string | null;
  created_at: string;
}

/* ------------------------------------------------- procurement upstream */
/*
 * Purchase orders and stock transfers. Shapes from app/inventory/schemas.py.
 *
 * Quantities are Decimal server-side, so STRINGS on the wire. Never parseFloat
 * one for display — a quantity that has been through a float is a quantity you
 * cannot reconcile against the stock ledger.
 */

export type PurchaseOrderStatus =
  | "draft"
  | "approved"
  | "sent"
  | "partially_received"
  | "received"
  | "cancelled";

/** Only these three are reachable via the transition endpoint. */
export type PurchaseOrderTransition = "approved" | "sent" | "cancelled";

export interface PurchaseOrderItem {
  id: string;
  item_id: string;
  item_name: string;
  quantity: string;
  /** How much has arrived on verified GRNs. Drives the outstanding figure. */
  received_quantity: string;
  unit_price: string | null;
}

export interface PurchaseOrder {
  id: string;
  po_number: string;
  supplier_id: string;
  supplier_name: string;
  status: PurchaseOrderStatus;
  approved_by: string | null;
  expected_date: string | null;
  created_at: string;
  updated_at: string;
  items: PurchaseOrderItem[];
}

export interface CreatePurchaseOrderInput {
  supplier_id: string;
  expected_date: string | null;
  items: Array<{ item_id: string; quantity: string; unit_price: string | null }>;
}

export type StockTransferStatus =
  | "draft"
  | "dispatched"
  | "received"
  | "cancelled";

export interface StockTransferItem {
  id: string;
  item_id: string;
  item_name: string;
  /** Transfers move a SPECIFIC batch, not a quantity of an item — expiry
   *  travels with the goods, so the batch is part of what is being moved. */
  batch_id: string;
  batch_number: string;
  quantity: string;
}

export interface StockTransfer {
  id: string;
  from_location_id: string;
  from_location_name: string;
  to_location_id: string;
  to_location_name: string;
  status: StockTransferStatus;
  created_by: string;
  created_at: string;
  updated_at: string;
  items: StockTransferItem[];
}

export interface CreateStockTransferInput {
  from_location_id: string;
  to_location_id: string;
  items: Array<{ item_id: string; batch_id: string; quantity: string }>;
}
