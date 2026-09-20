/**
 * Reports MIS types.
 * - kpi_snapshots shape for future GET /reports/kpis?period= (schema; BE stub today)
 * - Billing finance MIS: see @/features/billing types DailyRevenue* / Pending* / Scheme*
 */

export type { KpiChartPoint, KpiSnapshot } from "@/types/kpi";

/** Documented example kpi_codes from schema kpi_snapshots. */
export type CoreKpiCode =
  | "avg_opd_wait_minutes"
  | "sharp_injury_count";

/** UI / API period presets mapped to ?period= (not a DB enum). */
export type KpiPeriod = "today" | "7d" | "30d" | "custom";

export type KpiListResponse = {
  items: import("@/types/kpi").KpiSnapshot[];
  period_start: string;
  period_end: string;
  no_snapshots: boolean;
};

export type KpiCatalogItem = {
  kpi_code: string;
  name: string;
  category: string;
  unit: string;
  description: string;
  formula: string;
};

export type ReceptionistSummary = {
  facility_id: string;
  report_date: string;
  total_registered: number;
  waiting: number;
  in_consultation: number;
  completed: number;
  cancelled_or_lwbs: number;
  average_wait_minutes: number | null;
};

export type EdCensus = {
  facility_id: string;
  as_of: string;
  total_emergency_today: number;
  active_patients: number;
  lwbs_count: number;
  admitted_to_ipd: number;
  triage_acuity_distribution: Record<string, number>;
};

export type KpiProduceRequest = {
  period_start: string;
  period_end: string;
  kpi_codes?: string[];
};

export type KpiProduceResponse = {
  facility_id: string;
  period_start: string;
  period_end: string;
  snapshots_created: number;
  items: import("@/types/kpi").KpiSnapshot[];
};
