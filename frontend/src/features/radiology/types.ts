/** Mirrors backend app/radiology/schemas.py. */

/** radiology_order_items.status — placed -> scheduled -> scanned -> reporting -> released. */
export type RadiologyStatus =
  | "placed"
  | "scheduled"
  | "scanned"
  | "reporting"
  | "released"
  | "cancelled";

export type Modality = "xray" | "ct" | "mri" | "usg" | "mammo";

export interface RadiologyOrderItem {
  id: string;
  order_id: string;
  accession_number: string;
  modality: Modality | string;
  scan_type: string;
  machine_id: string | null;
  pacs_study_uid: string | null;
  scheduled_at: string | null;
  scan_completed_at: string | null;
  status: RadiologyStatus | string;
  created_at: string;
}

export interface RadiologyOrderItemList {
  items: RadiologyOrderItem[];
  page: number;
  page_size: number;
  total: number;
}

/** radiology_reports — append-only and versioned, like lab_results. */
export interface RadiologyReport {
  id: string;
  radiology_order_item_id: string;
  version: number;
  is_current: boolean;
  findings: string;
  impression: string;
  status: string;
  created_by: string;
  created_at: string;
  /** Turnaround: report created_at minus scan_completed_at. Signed reports only. */
  tat_minutes: number | null;
}

export interface RadiologyReportHistory {
  items: RadiologyReport[];
}
