/**
 * Control room reads (realm role `monitor`).
 *
 * The server decides which facilities are in view from the officer's granted
 * area; the district filter only narrows inside it. Nothing here identifies a
 * patient: the board is counts per facility.
 */
import { api } from "@/lib/api";

export type MonitorStatus = "red" | "amber" | "green" | "grey";

export interface MonitorFacilityRow {
  facility_id: string;
  code: string;
  name: string;
  district: string | null;
  facility_type: string | null;
  status: MonitorStatus;
  reasons: string[];
  captured_at: string | null;
  opd_today: number | null;
  queue_waiting: number | null;
  emergency_open: number | null;
  admitted_now: number | null;
  beds_total: number | null;
  bed_occupancy_percent: number | null;
  lab_pending: number | null;
  stock_below_reorder: number | null;
  batches_expiring_30d: number | null;
  staff_rostered_today: number | null;
}

export interface MonitorBoard {
  areas: { state_code: string; district: string | null }[];
  districts: string[];
  generated_at: string;
  thresholds: {
    bed_red_percent: number;
    bed_amber_percent: number;
    stock_red_items: number;
    not_reporting_after_minutes: number;
  };
  totals: {
    facilities: number;
    reporting: number;
    red: number;
    amber: number;
    green: number;
    grey: number;
    opd_today: number;
    emergency_open: number;
    admitted_now: number;
    beds_total: number;
    stock_below_reorder: number;
  };
  facilities: MonitorFacilityRow[];
}

export function getMonitorBoard(district: string | null): Promise<MonitorBoard> {
  const query = new URLSearchParams();
  if (district) query.set("district", district);
  return api<MonitorBoard>(`/monitor/board?${query.toString()}`);
}
