export interface FormFieldOption {
  label: string;
  value: string;
}

export interface FormFieldDef {
  id: string;
  label: string;
  type: "text" | "number" | "select" | "checkbox" | "textarea" | "date";
  required?: boolean;
  options?: FormFieldOption[];
  placeholder?: string;
}

export interface FormDefinition {
  id: string;
  code: string;
  title: string;
  version: number;
  status: "draft" | "published" | "retired";
  fields_schema: FormFieldDef[];
  created_by: string;
  created_at: string;
}

export interface FormSubmissionCreate {
  patient_id: string;
  visit_id?: string | null;
  form_id: string;
  form_data: Record<string, unknown>;
}

export interface FormSubmission {
  id: string;
  patient_id: string;
  visit_id: string | null;
  form_id: string;
  form_version: number;
  form_data: Record<string, unknown>;
  submitted_by: string;
  submitted_at: string;
  created_at: string;
}

export interface OrderItem {
  type: "lab" | "radiology" | "pharmacy" | "procedure";
  code: string;
  name: string;
  dosage?: string;
  frequency?: string;
  duration?: string;
  instructions?: string;
}

export interface ClinicalOrderSet {
  id: string;
  code: string;
  title: string;
  category: string;
  orders: OrderItem[];
  is_active: boolean;
  created_at: string;
}

export interface ApplyOrderSetRequest {
  patient_id: string;
  visit_id: string;
}

export interface ApplyOrderSetResult {
  order_set_code: string;
  patient_id: string;
  visit_id: string;
  orders_applied: OrderItem[];
  message: string;
}

export interface CsvValidationResult {
  valid: boolean;
  entity_type: string;
  row_count: number;
  columns: string[];
  errors: string[];
  warnings: string[];
}

export interface CsvImportResult {
  entity_type: string;
  imported_count: number;
  message: string;
}
