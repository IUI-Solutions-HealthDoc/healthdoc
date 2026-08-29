import { api } from "@/lib/api";

import type {
  LabMisSummary,
  LabOrderItem,
  LabOrderItemList,
  LabResult,
  LabResultHistory,
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
