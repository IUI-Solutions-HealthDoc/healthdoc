import { api } from "@/lib/api";

export interface ExternalResultInput {
  provider_name: string | null;
  summary: string;
  observed_on: string | null;
  result_file_id?: string | null;
}

export interface ExternalResult extends ExternalResultInput {
  id: string;
  order_id: string;
  result_file_id: string | null;
  recorded_by: string;
  recorded_at: string;
  created_at: string;
}

export async function listExternalResults(orderId: string): Promise<ExternalResult[]> {
  const response = await api<{ items: ExternalResult[] }>(`/orders/${encodeURIComponent(orderId)}/external-results`);
  if (!Array.isArray(response?.items) || response.items.some((row) => row.order_id !== orderId)) {
    throw new Error("Invalid external-result history");
  }
  return response.items;
}

export async function recordExternalResult(orderId: string, input: ExternalResultInput, key: string) {
  const result = await api<ExternalResult>(`/orders/${encodeURIComponent(orderId)}/external-results`, {
    method: "POST", body: JSON.stringify(input), idempotencyKey: key,
  });
  if (result.order_id !== orderId) throw new Error("Invalid external-result receipt");
  return result;
}
