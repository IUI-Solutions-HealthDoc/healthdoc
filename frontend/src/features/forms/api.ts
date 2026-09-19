import { api } from "@/lib/api";
import type {
  ApplyOrderSetRequest,
  ApplyOrderSetResult,
  ClinicalOrderSet,
  CsvImportResult,
  CsvValidationResult,
  FormDefinition,
  FormSubmission,
  FormSubmissionCreate,
} from "./types";

export function fetchFormDefinitions(status: string = "published"): Promise<FormDefinition[]> {
  return api<FormDefinition[]>(`/forms/definitions?status=${encodeURIComponent(status)}`);
}

export function submitForm(payload: FormSubmissionCreate): Promise<FormSubmission> {
  return api<FormSubmission>("/forms/submissions", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function fetchPatientSubmissions(patientId: string): Promise<FormSubmission[]> {
  return api<FormSubmission[]>(`/forms/patients/${patientId}`);
}

export function fetchOrderSets(category?: string): Promise<ClinicalOrderSet[]> {
  const q = new URLSearchParams();
  if (category) q.set("category", category);
  return api<ClinicalOrderSet[]>(`/order-sets?${q.toString()}`);
}

export function applyOrderSet(
  code: string,
  payload: ApplyOrderSetRequest
): Promise<ApplyOrderSetResult> {
  return api<ApplyOrderSetResult>(`/order-sets/${encodeURIComponent(code)}/apply`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function validateCsv(
  csvContent: string,
  entityType: string
): Promise<CsvValidationResult> {
  return api<CsvValidationResult>("/admin/csv/validate", {
    method: "POST",
    body: JSON.stringify({ csv_content: csvContent, entity_type: entityType }),
  });
}

export function importCsv(
  csvContent: string,
  entityType: string
): Promise<CsvImportResult> {
  return api<CsvImportResult>("/admin/csv/import", {
    method: "POST",
    body: JSON.stringify({ csv_content: csvContent, entity_type: entityType }),
  });
}

export function exportCsvUrl(entityType: string = "vaccines"): string {
  return `/api/admin/csv/export?entity_type=${encodeURIComponent(entityType)}`;
}
