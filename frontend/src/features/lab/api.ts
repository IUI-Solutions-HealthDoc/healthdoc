import { api } from "@/lib/api";

import type {
  CriticalAlert,
  CriticalAlertList,
  LabAnalyteList,
  LabMisSummary,
  LabOrderItem,
  LabOrderItemList,
  LabResult,
  LabResultHistory,
  LabSpecimenEvent,
  LabWorklistParams,
} from "./types";


function worklistQuery(params: LabWorklistParams = {}): string {
  const search = new URLSearchParams({
    page: String(params.page ?? 1),
    page_size: String(params.page_size ?? 20),
  });
  if (params.status && params.status !== "all") {
    search.set("status", params.status);
  }
  return search.toString();
}

export function listLabWork(params: LabWorklistParams = {}): Promise<LabOrderItemList> {
  return api<LabOrderItemList>(`/pathology/order-items?${worklistQuery(params)}`);
}

export function collectLabSample(itemId: string, barcode: string): Promise<LabOrderItem> {
  return api<LabOrderItem>(`/pathology/order-items/${itemId}/sample-collection`, {
    method: "PUT",
    body: JSON.stringify({ barcode }),
  });
}

export function enterLabResult(
  itemId: string,
  resultData: Record<string, unknown>,
  remarks: string,
): Promise<LabResult> {
  return api<LabResult>(`/pathology/order-items/${itemId}/results`, {
    method: "POST",
    idempotencyKey: null,
    body: JSON.stringify({ result_data: resultData, remarks: remarks.trim() || null }),
  });
}

export function verifyLabResult(itemId: string): Promise<LabResult> {
  return api<LabResult>(`/pathology/order-items/${itemId}/results/verify`, {
    method: "PUT",
    body: JSON.stringify({}),
  });
}

export function amendLabResult(
  itemId: string,
  amendmentReason: string,
  resultData: Record<string, unknown> | null,
  remarks: string | null,
): Promise<LabResult> {
  return api<LabResult>(`/pathology/order-items/${itemId}/results/amend`, {
    method: "PUT",
    body: JSON.stringify({
      amendment_reason: amendmentReason.trim(),
      result_data: resultData,
      remarks: remarks?.trim() || null,
    }),
  });
}

export function getLabResultHistory(itemId: string): Promise<LabResultHistory> {
  return api<LabResultHistory>(`/pathology/order-items/${itemId}/results/history`);
}

export function getLabMisSummary(dateFrom: string, dateTo: string): Promise<LabMisSummary> {
  const params = new URLSearchParams({
    date_from: dateFrom,
    date_to: dateTo,
  });
  return api<LabMisSummary>(`/pathology/mis/summary?${params.toString()}`);
}

export function getTestAnalytes(testCode: string): Promise<LabAnalyteList> {
  return api<LabAnalyteList>(`/pathology/catalogue/${encodeURIComponent(testCode)}/analytes`);
}

export function receiveLabSpecimen(itemId: string): Promise<LabOrderItem> {
  return api<LabOrderItem>(`/pathology/order-items/${itemId}/specimen/receive`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function rejectLabSpecimen(
  itemId: string,
  rejectionReason: string,
  notes?: string,
): Promise<LabOrderItem> {
  return api<LabOrderItem>(`/pathology/order-items/${itemId}/specimen/reject`, {
    method: "POST",
    body: JSON.stringify({
      rejection_reason: rejectionReason,
      notes: notes?.trim() || null,
    }),
  });
}

export function recollectLabSpecimen(itemId: string): Promise<LabOrderItem> {
  return api<LabOrderItem>(`/pathology/order-items/${itemId}/specimen/recollect`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export function listSpecimenEvents(itemId: string): Promise<LabSpecimenEvent[]> {
  return api<LabSpecimenEvent[]>(`/pathology/order-items/${itemId}/specimen/events`);
}

export function listCriticalAlerts(
  status?: string,
  sinceCursor?: string,
): Promise<CriticalAlertList> {
  const search = new URLSearchParams();
  if (status && status !== "all") search.set("status", status);
  if (sinceCursor) search.set("since_cursor", sinceCursor);
  const q = search.toString();
  return api<CriticalAlertList>(`/pathology/critical-alerts${q ? `?${q}` : ""}`);
}

export function acknowledgeCriticalAlert(
  alertId: string,
  note?: string,
): Promise<CriticalAlert> {
  return api<CriticalAlert>(`/pathology/critical-alerts/${alertId}/acknowledge`, {
    method: "POST",
    body: JSON.stringify({ acknowledgement_note: note?.trim() || null }),
  });
}

