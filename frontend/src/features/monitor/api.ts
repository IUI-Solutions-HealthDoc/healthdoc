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
  equipment_down: number | null;
  critical_equipment_down: number | null;
  adoption?: Partial<Record<AdoptionKey, number>> | null;
}

export type AdoptionKey = "registrations" | "abha_linked" | "scan_share" | "prescriptions" | "abdm_records";

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
    equipment_down: number;
    adoption?: Partial<Record<AdoptionKey, number>>;
  };
  facilities: MonitorFacilityRow[];
}

export function getMonitorBoard(district: string | null): Promise<MonitorBoard> {
  const query = new URLSearchParams();
  if (district) query.set("district", district);
  return api<MonitorBoard>(`/monitor/board?${query.toString()}`);
}

export interface MonitorFacilityDetail {
  facility: MonitorFacilityRow;
  equipment: { name: string; category: string; location: string | null; critical: boolean; status: string; since: string; reason: string | null }[];
  staff: { name: string; designation: string | null; department: string | null; shift: string | null; active_today: boolean; waiting: number }[];
  wards: { ward: string; department: string | null; beds: number; occupied: number; free: number; maintenance: number }[];
  stock_short: { item: string; strength: string | null; available: string; reorder_level: string }[];
  expiring: { item: string; batch: string; expiry: string; quantity: string }[];
  list_limit: number;
}

export function getMonitorFacility(facilityId: string): Promise<MonitorFacilityDetail> {
  return api<MonitorFacilityDetail>(`/monitor/facilities/${facilityId}`);
}

export interface MonitorTrends {
  week_ending: string;
  small_cell_below: number;
  spike_rule: string;
  trends: {
    district: string | null;
    icd_version: string;
    icd_code: string;
    title: string | null;
    /** A number, or "<5": small exact counts are never sent. */
    this_week: string;
    last_week: string;
    spike: boolean;
  }[];
}

export function getMonitorTrends(district: string | null): Promise<MonitorTrends> {
  const query = new URLSearchParams();
  if (district) query.set("district", district);
  return api<MonitorTrends>(`/monitor/trends?${query.toString()}`);
}

export interface MonitorActivity {
  facility_id: string;
  facility_name: string;
  day: string;
  first_patient: string | null;
  first_at: string | null;
  last_patient: string | null;
  last_at: string | null;
  patients: number;
  counts: Record<string, number>;
  truncated: boolean;
  events: { at: string; kind: string; patient: string; detail: string; staff: string | null }[];
  privacy_note: string;
}

/** Each call is written to the facility's audit log: load it on request only. */
export function getMonitorActivity(facilityId: string, day: string | null): Promise<MonitorActivity> {
  const query = new URLSearchParams();
  if (day) query.set("day", day);
  return api<MonitorActivity>(`/monitor/facilities/${facilityId}/activity?${query.toString()}`);
}
