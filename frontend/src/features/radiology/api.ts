/**
 * Radiology. Every call here is facility-scoped server-side; none sends one.
 *
 * The workflow is placed -> scheduled -> scanned -> reporting -> released, and
 * each transition has exactly one endpoint. `schedule` was missing entirely
 * until this screen was built: items are created `placed`, scan-complete
 * refuses anything not `scheduled`, and nothing set that status — so no scan
 * could ever be completed. See app/radiology/router.py:schedule_scan.
 */
import { api } from "@/lib/api";

import type {
  RadiologyOrderItem,
  RadiologyOrderItemList,
  RadiologyReport,
  RadiologyReportHistory,
} from "./types";

/** The department worklist. Facility-scoped; status narrows it server-side. */
export function listRadiologyWork(status?: string): Promise<RadiologyOrderItemList> {
  const params = new URLSearchParams({ page: "1", page_size: "100" });
  if (status && status !== "all") params.set("status", status);
  return api<RadiologyOrderItemList>(`/radiology/order-items?${params.toString()}`);
}

/**
 * Book a scan onto a machine and a slot.
 *
 * Only from `placed` — re-scheduling is refused, because it has to say what
 * happened to the original slot and that is a different operation.
 */
export function scheduleScan(
  itemId: string,
  scheduledAt: string,
  machineId: string,
): Promise<RadiologyOrderItem> {
  return api<RadiologyOrderItem>(`/radiology/order-items/${itemId}/schedule`, {
    method: "PUT",
    body: JSON.stringify({ scheduled_at: scheduledAt, machine_id: machineId }),
  });
}

/**
 * Mark the scan performed. `completed_at` defaults to now server-side.
 *
 * This is what starts the turnaround clock: `tat_minutes` on a signed report is
 * measured from here, so a tech marking a batch complete at end of shift
 * understates every TAT in it.
 */
export function markScanComplete(itemId: string): Promise<RadiologyOrderItem> {
  return api<RadiologyOrderItem>(`/radiology/order-items/${itemId}/scan-complete`, {
    method: "PUT",
    body: JSON.stringify({}),
  });
}

/** Every version of the report, newest first. Empty until one is drafted. */
export function getRadiologyReports(itemId: string): Promise<RadiologyReportHistory> {
  return api<RadiologyReportHistory>(`/radiology/order-items/${itemId}/reports`);
}

/** Draft a preliminary report. Moves the item to `reporting`. */
export function draftRadiologyReport(
  itemId: string,
  findings: string,
  impression: string,
  pacsStudyUid?: string,
): Promise<RadiologyReport> {
  return api<RadiologyReport>(`/radiology/order-items/${itemId}/reports`, {
    method: "POST",
    idempotencyKey: null,
    body: JSON.stringify({
      findings,
      impression,
      pacs_study_uid: pacsStudyUid?.trim() || null,
    }),
  });
}

/**
 * Sign off — supersedes the preliminary version with a `final` one and moves
 * the item to `released`.
 *
 * Reports are append-only and versioned: signing does not edit the draft, it
 * writes version N+1 and flips `is_current`. The preliminary read stays
 * readable, which is the point — a revised finding is a clinically meaningful
 * event, not an embarrassment to overwrite.
 */
export function signOffRadiologyReport(
  itemId: string,
  findings?: string,
  impression?: string,
): Promise<RadiologyReport> {
  return api<RadiologyReport>(`/radiology/order-items/${itemId}/reports/sign-off`, {
    method: "PUT",
    body: JSON.stringify({
      findings: findings?.trim() || null,
      impression: impression?.trim() || null,
    }),
  });
}

/** FHIR DiagnosticReport bundle for the current signed report on this item. */
export function getRadiologyFhirBundle(itemId: string): Promise<Record<string, unknown>> {
  return api<Record<string, unknown>>(`/radiology/order-items/${itemId}/fhir-bundle`);
}
