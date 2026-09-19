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
  specimen_status?: "pending_collection" | "collected" | "received" | "rejected" | "recollected" | string;
  rejection_reason?: string | null;
  recollected_from_id?: string | null;
  created_at: string;
}

export interface LabSpecimenEvent {
  id: string;
  lab_order_item_id: string;
  event_type: "collected" | "received" | "rejected" | "recollected" | string;
  rejection_reason: string | null;
  notes: string | null;
  performed_by: string;
  created_at: string;
}

export interface CriticalAlert {
  id: string;
  facility_id: string;
  patient_id: string;
  visit_id: string | null;
  order_id: string;
  test_code: string;
  analyte_code: string;
  analyte_name: string;
  value: number;
  unit: string | null;
  critical_low: number | null;
  critical_high: number | null;
  severity: string;
  status: "unacknowledged" | "acknowledged" | string;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  acknowledgement_note: string | null;
  created_at: string;
}

export interface CriticalAlertList {
  items: CriticalAlert[];
  cursor: string | null;
  total: number;
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

export interface LabAnalyte {
  id: string;
  test_code: string;
  analyte_code: string;
  analyte_name: string;
  value_type: "numeric" | "text" | string;
  unit: string | null;
  reference_low: number | null;
  reference_high: number | null;
  critical_low: number | null;
  critical_high: number | null;
  is_required: boolean;
  version: number;
}

export interface LabAnalyteList {
  items: LabAnalyte[];
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
