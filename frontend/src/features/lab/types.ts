export interface LabOrderItem {
  id: string;
  order_id: string;
  accession_number: string;
  test_code: string | null;
  test_name: string;
  sample_type: string;
  barcode: string | null;
  collected_at: string | null;
  department_id: string | null;
  status: "placed" | "in_progress" | "completed" | "released" | string;
  estimated_minutes: number | null;
  created_at: string;
}

export interface LabOrderItemList {
  items: LabOrderItem[];
  page: number;
  page_size: number;
  total: number;
}

export interface LabResult {
  id: string;
  lab_order_item_id: string;
  version: number;
  is_current: boolean;
  result_data: Record<string, unknown>;
  remarks: string | null;
  amendment_reason: string | null;
  status: "preliminary" | "final" | "corrected" | string;
  created_by: string;
  created_at: string;
  tat_minutes: number | null;
}

export interface LabResultHistory {
  items: LabResult[];
}

export interface CriticalLabAlert {
  lab_order_item_id: string;
  accession_number: string;
}

export interface LabWorklistParams {
  page?: number;
  page_size?: number;
  status?: string;
}

export interface LabTatByTest {
  test_name: string;
  sample_count: number;
  avg_tat_minutes: number | null;
  median_tat_minutes: number | null;
}

export interface LabStatusCount {
  status: string;
  count: number;
}

export interface LabPanicFrequency {
  test_name: string;
  critical_count: number;
  total_count: number;
  panic_rate_pct: number;
}

export interface LabMisSummary {
  date_from: string;
  date_to: string;
  tat_by_test: LabTatByTest[];
  order_counts_by_status: LabStatusCount[];
  total_orders: number;
  total_results: number;
  panic_frequency: LabPanicFrequency[];
}
