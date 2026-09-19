import { api } from "@/lib/api";

import type {
  DispenseInput,
  DispenseItemResult,
  DispenseResult,
  ExpiryTrackerResponse,
  MedicineSearchResponse,
  PendingSubstitutionResponse,
  PrescriptionDetail,
  PrescriptionQueueResponse,
  ReorderAlertsResponse,
  PharmacyReturn,
  PharmacyReturnListResponse,
  PharmacyReturnCreateInput,
} from "./types";

export function listPrescriptionQueue(params: {
  status?: string;
  page?: number;
  page_size?: number;
} = {}): Promise<PrescriptionQueueResponse> {
  const query = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: String(params.page_size ?? 20),
    ...(params.status ? { status: params.status } : {}),
  });
  return api<PrescriptionQueueResponse>(`/pharmacy/queue?${query}`);
}

export function searchMedicines(term: string): Promise<MedicineSearchResponse> {
  return api<MedicineSearchResponse>(
    `/pharmacy/medicines/search?q=${encodeURIComponent(term)}`,
  );
}

export function getPrescription(prescriptionId: string): Promise<PrescriptionDetail> {
  return api<PrescriptionDetail>(`/orders/prescriptions/${prescriptionId}`);
}

export function createDispense(
  payload: DispenseInput,
  idempotencyKey: string,
): Promise<DispenseResult> {
  return api<DispenseResult>("/pharmacy/dispenses", {
    method: "POST",
    idempotencyKey,
    body: JSON.stringify(payload),
  });
}

export function listPendingSubstitutions(): Promise<PendingSubstitutionResponse> {
  return api<PendingSubstitutionResponse>("/pharmacy/substitutions/pending");
}

export function decideSubstitution(
  itemId: string,
  approved: boolean,
  rejectionReason?: string,
): Promise<DispenseItemResult> {
  return api<DispenseItemResult>(`/pharmacy/dispenses/items/${itemId}/approve`, {
    method: "POST",
    idempotencyKey: null,
    body: JSON.stringify({
      approved,
      ...(approved ? {} : { rejection_reason: rejectionReason }),
    }),
  });
}

export function expiryTracker(thresholdDays = 90): Promise<ExpiryTrackerResponse> {
  // 90 by default so the screen can bucket 30/60/90 from one request rather
  // than three — the server filters, the client groups.
  return api<ExpiryTrackerResponse>(
    `/pharmacy/expiry-tracker?threshold_days=${thresholdDays}`,
  );
}

export function listReorderAlerts(): Promise<ReorderAlertsResponse> {
  return api<ReorderAlertsResponse>("/pharmacy/inventory/reorder-alerts");
}

export function listPharmacyReturns(params: {
  disposition?: string;
  patient_id?: string;
} = {}): Promise<PharmacyReturnListResponse> {
  const query = new URLSearchParams();
  if (params.disposition && params.disposition !== "all") query.set("disposition", params.disposition);
  if (params.patient_id) query.set("patient_id", params.patient_id);
  const qStr = query.toString();
  return api<PharmacyReturnListResponse>(`/pharmacy/returns?${qStr}`);
}

export function createPharmacyReturn(payload: PharmacyReturnCreateInput): Promise<PharmacyReturn> {
  return api<PharmacyReturn>("/pharmacy/returns", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

