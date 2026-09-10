import { api } from "@/lib/api";
import type { PlacedOrder } from "../types";

export type ReferralState = "pending" | "completed" | "cancelled" | "all";
export interface ExternalReferral extends Omit<PlacedOrder, "item_label" | "detail_status"> {
  fulfilment_mode: "external_referral";
  patient_id: string;
  encounter_id: string;
  patient_name: string;
  patient_identifier: string | null;
  visit_number: string;
  result_count: number;
  last_received_at: string | null;
}
export interface ReferralPage {
  items: ExternalReferral[];
  total: number;
  limit: number;
  offset: number;
}

export async function listExternalReferrals(state: ReferralState, offset: number, limit = 25): Promise<ReferralPage> {
  const params = new URLSearchParams({ state, offset: String(offset), limit: String(limit) });
  const page = await api<ReferralPage>(`/orders/external-referrals?${params}`);
  if (!Array.isArray(page?.items) || !Number.isSafeInteger(page.total) || page.total < 0 ||
      page.offset !== offset || page.limit !== limit || page.items.length > limit ||
      page.items.some((row) => row.fulfilment_mode !== "external_referral" || !row.patient_id || !row.id)) {
    throw new Error("Invalid external-referral page");
  }
  return page;
}
