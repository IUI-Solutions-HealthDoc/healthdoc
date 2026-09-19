/**
 * Facility KPI snapshots. Retired from fixtures (P1.1).
 *
 * `app/reports/router.py` was a ping stub — the last module in the product with
 * no endpoints — while `kpi_snapshots` has existed since migration 0025. Built
 * alongside this change.
 *
 * This reads STORED snapshots and does not compute anything. A snapshot is a
 * value someone committed for a period that has ended; recomputing it on read
 * would silently move a figure a hospital may already have reported externally.
 * Live numbers belong in billing MIS, which is explicitly a live view.
 */
import { api } from "@/lib/api";
import type { KpiListResponse, KpiPeriod } from "../types";

/** UI period -> the window the endpoint understands. */
const PERIOD_TO_SPAN: Record<Exclude<KpiPeriod, "custom">, string> = {
  today: "daily",
  "7d": "weekly",
  "30d": "monthly",
};

/**
 * GET /reports/kpis — facility-scoped server-side; no facility is sent.
 *
 * `no_snapshots` is returned alongside the items and MUST be surfaced. It
 * distinguishes "nobody has computed this yet" from "the measured value was
 * zero" — a chart cannot show the difference, and rendering one as the other
 * tells a hospital its infection rate is nil when nothing has ever measured it.
 *
 * Snapshots are written by whatever job owns each KPI. That job does not exist
 * yet, so an empty result is the expected state today, not an error.
 */
export async function listKpis(
  period: KpiPeriod,
  from?: string,
  to?: string,
): Promise<KpiListResponse> {
  const params = new URLSearchParams();
  if (period === "custom" && from && to) {
    params.set("date_from", from);
    params.set("date_to", to);
  } else {
    params.set("period", PERIOD_TO_SPAN[period as Exclude<KpiPeriod, "custom">] ?? "monthly");
  }

  const response = await api<{
    items: KpiListResponse["items"];
    period_start: string;
    period_end: string;
    no_snapshots: boolean;
  }>(`/reports/kpis?${params.toString()}`);

  return {
    items: response.items,
    period_start: response.period_start,
    period_end: response.period_end,
    no_snapshots: response.no_snapshots,
  };
}

/**
 * GET /reports/kpis/codes — which codes this facility actually has data for.
 *
 * Derived from the data, not a hardcoded catalogue: a fixed list would show a
 * hospital metrics nobody computes for it, each rendering as an empty chart
 * indistinguishable from a real zero.
 */
export async function listKpiCodes(): Promise<string[]> {
  const response = await api<{ items: string[] }>("/reports/kpis/codes");
  return response.items;
}

/**
  * GET /reports/kpis/catalog — metadata catalog of all standard KPIs.
  */
export async function getKpiCatalog(): Promise<import("../types").KpiCatalogItem[]> {
  return api<import("../types").KpiCatalogItem[]>("/reports/kpis/catalog");
}

/**
  * POST /reports/kpis/produce — calculate and commit closed-period snapshots.
  */
export async function produceKpis(
  body: import("../types").KpiProduceRequest,
): Promise<import("../types").KpiProduceResponse> {
  return api<import("../types").KpiProduceResponse>("/reports/kpis/produce", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
  * GET /reports/receptionist-summary — live front desk tracker for today.
  */
export async function getReceptionistSummary(
  forDate?: string,
): Promise<import("../types").ReceptionistSummary> {
  const query = forDate ? `?for_date=${encodeURIComponent(forDate)}` : "";
  return api<import("../types").ReceptionistSummary>(`/reports/receptionist-summary${query}`);
}

/**
  * GET /reports/ed-census — live emergency census and triage acuity.
  */
export async function getEdCensus(): Promise<import("../types").EdCensus> {
  return api<import("../types").EdCensus>("/reports/ed-census");
}
