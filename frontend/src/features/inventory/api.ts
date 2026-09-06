/**
 * Procurement API. Every path is under /pharmacy — see types.ts.
 *
 * Every mutation here is idempotent server-side and the key is MANDATORY: the
 * handlers 400 without an Idempotency-Key header. That is not ceremony. A
 * retried GRN verification would post the same delivery to stock twice, and
 * because inventory_batches.quantity is maintained by a trigger on every
 * stock_ledger insert, the second post is silently absorbed as real stock that
 * never physically arrived.
 */
import { api, newIdempotencyKey } from "@/lib/api";

import type {
  Adjustment,
  ApproverCandidate,
  CreatePurchaseOrderInput,
  CreateStockTransferInput,
  PurchaseOrder,
  PurchaseOrderStatus,
  PurchaseOrderTransition,
  StockTransfer,
  StockTransferStatus,
  AdjustmentListRow,
  AdjustmentStatus,
  GrnListRow,
  GrnStatus,
  IndentListRow,
  IndentStatus,
  ApprovalDecision,
  CreateAdjustmentInput,
  CreateGrnInput,
  CreateIndentInput,
  Grn,
  Indent,
  StockLocation,
  Supplier,
} from "./types";

/* ------------------------------------------------------------------ master */

/** Suppliers this facility buys from. Inactive ones are excluded server-side. */
export async function listSuppliers(): Promise<Supplier[]> {
  const response = await api<{ items: Supplier[] }>("/pharmacy/suppliers");
  return response.items;
}

/** Where stock can physically sit. Verification posts a GRN into one of these. */
export async function listStockLocations(): Promise<StockLocation[]> {
  const response = await api<{ items: StockLocation[] }>("/pharmacy/stock-locations");
  return response.items;
}

/* --------------------------------------------------------------------- GRN */

/**
 * POST /pharmacy/grn — records that a delivery arrived.
 *
 * This does NOT put anything into stock. The GRN is a document about a
 * delivery; verification is what posts it. The screen has to keep those
 * separate or a storekeeper will believe stock is dispensable the moment the
 * boxes are logged.
 */
export function createGrn(input: CreateGrnInput): Promise<Grn> {
  return api<Grn>("/pharmacy/grn", {
    method: "POST",
    body: JSON.stringify(input),
    idempotencyKey: newIdempotencyKey(),
  });
}

/**
 * POST /pharmacy/grn/{id}/verify — the step that actually creates stock.
 *
 * Creates a batch per line and writes a `purchase` row to stock_ledger, which
 * is what the trigger turns into an increase in inventory_batches.quantity.
 * Refused unless the GRN is 'draft' or 'received' (409), so a second
 * verification of the same delivery cannot double the stock.
 */
export function verifyGrn(grnId: string, stockLocationId: string): Promise<Grn> {
  return api<Grn>(`/pharmacy/grn/${grnId}/verify`, {
    method: "POST",
    body: JSON.stringify({ stock_location_id: stockLocationId }),
    idempotencyKey: newIdempotencyKey(),
  });
}

/* ----------------------------------------------------------------- indents */

/** POST /pharmacy/indents — a department asks the store for stock. */
export function createIndent(input: CreateIndentInput): Promise<Indent> {
  return api<Indent>("/pharmacy/indents", {
    method: "POST",
    body: JSON.stringify(input),
    idempotencyKey: newIdempotencyKey(),
  });
}

/**
 * POST /pharmacy/indents/{id}/approve — HOD only.
 *
 * Not pharmacist, not admin: the endpoint is gated to `hod` alone. The head of
 * the requesting department owns the budget, so approval is a departmental
 * decision rather than a storekeeping one.
 */
export function decideIndent(
  indentId: string,
  decision: ApprovalDecision,
): Promise<Indent> {
  return api<Indent>(`/pharmacy/indents/${indentId}/approve`, {
    method: "POST",
    body: JSON.stringify(decision),
    idempotencyKey: newIdempotencyKey(),
  });
}

/** POST /pharmacy/indents/{id}/issue — pharmacy hands the stock over. */
export function issueIndent(indentId: string): Promise<Indent> {
  return api<Indent>(`/pharmacy/indents/${indentId}/issue`, {
    method: "POST",
    body: JSON.stringify({}),
    idempotencyKey: newIdempotencyKey(),
  });
}

/* ------------------------------------------------------------- adjustments */

/**
 * POST /pharmacy/adjustments — proposes a correction to a batch quantity.
 *
 * Creates a PENDING row. Nothing moves until a second approver signs, and the
 * server refuses 422 if the named first approver is the submitter.
 */
export function createAdjustment(input: CreateAdjustmentInput): Promise<Adjustment> {
  return api<Adjustment>("/pharmacy/adjustments", {
    method: "POST",
    body: JSON.stringify(input),
    idempotencyKey: newIdempotencyKey(),
  });
}

/** POST /pharmacy/adjustments/{id}/approve — the second signature. */
export function decideAdjustment(
  adjustmentId: string,
  decision: ApprovalDecision,
): Promise<Adjustment> {
  return api<Adjustment>(`/pharmacy/adjustments/${adjustmentId}/approve`, {
    method: "POST",
    body: JSON.stringify(decision),
    idempotencyKey: newIdempotencyKey(),
  });
}

/* --------------------------------------------------------------- read side */
/*
 * The `?` stays inside the template literal rather than being folded into an
 * interpolated suffix. scripts/check_frontend_contracts.py matches a call by
 * its literal path prefix and truncates at the query string; building the URL
 * as `${base}${qs}` leaves it with `/pharmacy/grn{param}`, which matches no
 * route and fails the contract gate. An empty query string is harmless.
 */

function statusQuery(status?: string): string {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  return params.toString();
}

/** GET /pharmacy/grn — facility-scoped, newest first. */
export async function listGrns(status?: GrnStatus): Promise<GrnListRow[]> {
  const response = await api<{ items: GrnListRow[] }>(
    `/pharmacy/grn?${statusQuery(status)}`,
  );
  return response.items;
}

/** GET /pharmacy/indents — the HOD's approval worklist. */
export async function listIndents(status?: IndentStatus): Promise<IndentListRow[]> {
  const response = await api<{ items: IndentListRow[] }>(
    `/pharmacy/indents?${statusQuery(status)}`,
  );
  return response.items;
}

/** GET /pharmacy/adjustments — the second approver's worklist. */
export async function listAdjustments(status?: AdjustmentStatus): Promise<AdjustmentListRow[]> {
  const response = await api<{ items: AdjustmentListRow[] }>(
    `/pharmacy/adjustments?${statusQuery(status)}`,
  );
  return response.items;
}

/* ------------------------------------------------- procurement upstream */
/*
 * admin/pharmacist gated. Paged reads: page_size is capped at 100 server-side.
 */

export async function listPurchaseOrders(status?: PurchaseOrderStatus): Promise<PurchaseOrder[]> {
  const params = new URLSearchParams({ page: "1", page_size: "50" });
  if (status) params.set("status", status);
  const response = await api<{ items: PurchaseOrder[] }>(
    `/inventory/purchase-orders?${params.toString()}`,
  );
  return response.items;
}

export function createPurchaseOrder(input: CreatePurchaseOrderInput): Promise<PurchaseOrder> {
  return api<PurchaseOrder>("/inventory/purchase-orders", {
    method: "POST",
    body: JSON.stringify(input),
    idempotencyKey: newIdempotencyKey(),
  });
}

/**
 * draft -> approved -> sent, or cancelled.
 *
 * `received` and `partially_received` are NOT reachable here and are absent
 * from the type: those are set by the server when a GRN linked to this order is
 * verified. A screen that let a clerk mark an order received by hand would let
 * the paperwork claim goods arrived that no GRN ever recorded.
 */
export function transitionPurchaseOrder(
  purchaseOrderId: string,
  targetStatus: PurchaseOrderTransition,
): Promise<PurchaseOrder> {
  return api<PurchaseOrder>(`/inventory/purchase-orders/${purchaseOrderId}/transition`, {
    method: "POST",
    body: JSON.stringify({ target_status: targetStatus }),
    idempotencyKey: newIdempotencyKey(),
  });
}

export async function listStockTransfers(status?: StockTransferStatus): Promise<StockTransfer[]> {
  const params = new URLSearchParams({ page: "1", page_size: "50" });
  if (status) params.set("status", status);
  const response = await api<{ items: StockTransfer[] }>(
    `/inventory/stock-transfers?${params.toString()}`,
  );
  return response.items;
}

export function createStockTransfer(input: CreateStockTransferInput): Promise<StockTransfer> {
  return api<StockTransfer>("/inventory/stock-transfers", {
    method: "POST",
    body: JSON.stringify(input),
    idempotencyKey: newIdempotencyKey(),
  });
}

/** Stock leaves the source location. */
export function dispatchStockTransfer(transferId: string): Promise<StockTransfer> {
  return api<StockTransfer>(`/inventory/stock-transfers/${transferId}/dispatch`, {
    method: "POST",
    body: JSON.stringify({}),
    idempotencyKey: newIdempotencyKey(),
  });
}

/** Stock arrives at the destination. Separate from dispatch on purpose: goods
 *  in transit belong to neither location, and collapsing the two steps would
 *  make a lost consignment invisible. */
export function receiveStockTransfer(transferId: string): Promise<StockTransfer> {
  return api<StockTransfer>(`/inventory/stock-transfers/${transferId}/receive`, {
    method: "POST",
    body: JSON.stringify({}),
    idempotencyKey: newIdempotencyKey(),
  });
}

export function cancelStockTransfer(transferId: string): Promise<StockTransfer> {
  return api<StockTransfer>(`/inventory/stock-transfers/${transferId}/cancel`, {
    method: "POST",
    body: JSON.stringify({}),
    idempotencyKey: newIdempotencyKey(),
  });
}

/**
 * First-approver candidates for a stock adjustment.
 *
 * Not `GET /users`: that route is gated `admin`, so the pharmacist who owns
 * this screen got 403 on every keystroke and the picker rendered an empty
 * list. This route is gated `pharmacist, admin` and returns only what the
 * picker shows.
 */
export async function listAdjustmentCandidates(
  search: string,
): Promise<ApproverCandidate[]> {
  const params = new URLSearchParams();
  if (search.trim()) params.set("search", search.trim());
  const page = await api<{ items: ApproverCandidate[] }>(
    `/pharmacy/adjustment-candidates?${params.toString()}`,
  );
  return page.items;
}
