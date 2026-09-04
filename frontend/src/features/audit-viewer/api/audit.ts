/**
 * The auditor's console. Retired from fixtures (P1.1).
 *
 * Two of these eight calls had a backend (`/audit/logs` and its CSV export).
 * The other six read tables that have existed since 0003, 0004 and 0019 —
 * data_access_log, file_access_log, audit_integrity_checks, audit_log_archive
 * — with no endpoint over any of them. Those four were built alongside this
 * change; the remaining two are explained below.
 *
 * Everything here is read-only and auditor/admin gated, and every query is
 * scoped to the caller's facility server-side. No call sends a facility.
 */
import { API_BASE_URL, ApiError, api, getAccessToken } from "@/lib/api";
import type {
  AuditIntegrityCheck,
  AuditLog,
  AuditLogArchive,
  AuditLogFilters,
  AuditLogListResponse,
  DataAccessFilters,
  DataAccessLog,
  FileAccessFilters,
  FileAccessLog,
} from "../types";

function auditParams(filters: AuditLogFilters): URLSearchParams {
  const params = new URLSearchParams();
  if (filters.user_id) params.set("user_id", filters.user_id);
  if (filters.patient_id) params.set("patient_id", filters.patient_id);
  // The UI calls these from/to; the endpoint calls them date_from/date_to.
  // Mapped rather than renamed on the type, because the screen's labels are
  // fine and the wire name is the server's to choose.
  if (filters.from) params.set("date_from", filters.from);
  if (filters.to) params.set("date_to", filters.to);
  // "all" is the dropdown's own placeholder, not a resource type the server
  // has ever stored. Sending it asks for rows whose resource_type is literally
  // "all", which matches nothing — so the DEFAULT view of the audit trail came
  // back empty and read as "no audit entries", with 200+ rows sitting in the
  // table.
  //
  // This guard was already here and correct. It was defeated by an unguarded
  // `params.set("resource_type", ...)` a few lines above, which set the value
  // first; a second set() cannot unset what the first one wrote. That
  // duplicate is now gone. Any future filter added here must be set in exactly
  // one place, for the same reason.
  if (filters.resource_type && filters.resource_type !== "all") {
    params.set("resource_type", filters.resource_type);
  }
  return params;
}

/**
 * Narrow the loaded page by the filters the SERVER does not support.
 *
 * `query` and `action` are UI controls with no server equivalent.
 * app/audit/router.py is explicit that adding an `action` filter — or any
 * filter beyond user_id/patient_id/resource_type/date range — is a product
 * decision for the Tech Lead rather than something to add silently, so they are
 * applied here instead.
 *
 * THIS NARROWS ONLY WHAT WAS FETCHED. With page_size capped at 100, a match on
 * page two is not found. That is a real limitation and the reason these belong
 * server-side eventually; it is written down rather than hidden because the
 * alternative — a search box that quietly reports "no results" — is worse.
 */
function refineLoadedPage(rows: AuditLog[], filters: AuditLogFilters): AuditLog[] {
  const q = filters.query?.trim().toLowerCase() ?? "";
  return rows.filter((row) => {
    if (filters.action && filters.action !== "all" && row.action !== filters.action) {
      return false;
    }
    if (!q) return true;
    return [row.id, row.user_id, row.role, row.action, row.resource_type, row.resource_id]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(q);
  });
}

/**
 * GET /audit/logs.
 *
 * Only the five filters the backend accepts are sent. app/audit/router.py's
 * docstring is explicit that anything beyond them — an `action` filter,
 * cross-facility visibility — is a product decision rather than something to
 * add silently, so a filter the fixture supported client-side and the server
 * does not is deliberately dropped rather than faked over one page.
 */
export async function listAuditLogs(
  filters: AuditLogFilters = {},
): Promise<AuditLogListResponse> {
  const params = auditParams(filters);
  params.set("page", String(filters.page ?? 1));
  params.set("page_size", String(Math.min(filters.page_size ?? 100, 100)));

  const page = await api<AuditLogListResponse>(`/audit/logs?${params.toString()}`);
  return { ...page, items: refineLoadedPage(page.items, filters) };
}

/**
 * One entry by id.
 *
 * There is no GET /audit/logs/{id}. Rather than invent one for a row the list
 * already returns in full, this narrows the list by the filters that identify
 * it. Returns null when the entry is not in the caller's facility — the same
 * answer as "no such entry", which is correct for an audit read.
 */
export async function getAuditEntry(
  id: string,
  filters: AuditLogFilters = {},
): Promise<AuditLog | null> {
  const page = await listAuditLogs({ ...filters, page_size: 100 });
  return page.items.find((entry) => entry.id === id) ?? null;
}

/**
 * GET /audit/logs/export — CSV.
 *
 * A separate endpoint rather than `?format=csv`, per §4.3: large exports are
 * explicit and audited. Requesting one writes an audit_logs row of its own
 * before the stream starts, so this call is itself a recorded event.
 */
export async function exportAuditLogsCsv(
  filters: AuditLogFilters = {},
): Promise<string> {
  // Raw fetch, not api(): the client unwraps a JSON envelope and this endpoint
  // streams CSV. Reusing it would throw "Malformed response" on a successful
  // export.
  const token = getAccessToken();
  const response = await fetch(
    `${API_BASE_URL}/audit/logs/export?${auditParams(filters).toString()}`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );
  if (!response.ok) {
    throw new ApiError(response.status, "Audit export failed");
  }
  return response.text();
}


/**
 * GET /audit/data-access — the DPDP ledger.
 *
 * `unattributed_in_page` counts rows whose patient_id is null. data_access_log
 * has no facility_id, so scope resolves through the patient; a row with no
 * patient cannot be attributed that way and is included rather than dropped.
 * Surface that number — an access ledger that quietly omits entries is worse
 * than one showing entries that need interpreting.
 */
export async function listDataAccessLogs(
  filters: DataAccessFilters = {},
): Promise<{ items: DataAccessLog[]; unattributed_in_page: number }> {
  const params = new URLSearchParams();
  if (filters.consent_id) params.set("consent_id", filters.consent_id);
  params.set("page", "1");
  params.set("page_size", "100");

  const response = await api<{
    items: DataAccessLog[];
    unattributed_in_page: number;
  }>(`/audit/data-access?${params.toString()}`);

  // access_channel / query have no server equivalent, so they narrow the
  // loaded page here — the same treatment refineLoadedPage gives audit logs
  // and listFileAccessLogs gives file access.
  //
  // The comment above USED to say exactly that while the function returned the
  // response untouched, so the search box and the channel dropdown moved,
  // refetched, and changed nothing. A control that looks like it filters and
  // does not is worse than no control: on an audit screen it reads as "these
  // are all the matching records" when it means "these are all the records".
  //
  // Same page-one limitation as the others, and written down for the same
  // reason: a match on page two is not found.
  const q = filters.query?.trim().toLowerCase() ?? "";
  const channel = filters.access_channel;
  const items = response.items.filter((row) => {
    if (channel && channel !== "all" && row.access_channel !== channel) return false;
    if (!q) return true;
    return [row.id, row.user_id, row.patient_id, row.access_channel, row.purpose_code, row.resource_type]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(q);
  });

  return { ...response, items };
}

/** GET /audit/file-access — who downloaded which file, scoped via files.facility_id. */
export async function listFileAccessLogs(
  filters: FileAccessFilters = {},
): Promise<FileAccessLog[]> {
  const params = new URLSearchParams();
  // action / query have no server equivalent — see refineLoadedPage.
  params.set("page", "1");
  params.set("page_size", "100");

  const response = await api<{ items: FileAccessLog[] }>(
    `/audit/file-access?${params.toString()}`,
  );

  // action / query narrow the loaded page only — the endpoint accepts neither,
  // and adding filters to the audit reads is the documented Tech Lead decision.
  const q = filters.query?.trim().toLowerCase() ?? "";
  return response.items.filter((row) => {
    if (filters.action && filters.action !== "all" && row.action !== filters.action) {
      return false;
    }
    if (!q) return true;
    return [row.id, row.file_id, row.user_id, row.action, row.ip_address]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(q);
  });
}

/**
 * GET /audit/integrity-checks — hash-chain verification history.
 *
 * `any_chain_invalid` is computed over the whole history rather than the page:
 * a chain that broke three months ago is still broken, and the screen should
 * lead with that instead of making an auditor page backwards to find it.
 */
export async function listIntegrityChecks(): Promise<{
  items: AuditIntegrityCheck[];
  any_chain_invalid: boolean;
}> {
  return api<{ items: AuditIntegrityCheck[]; any_chain_invalid: boolean }>(
    "/audit/integrity-checks",
  );
}

/** GET /audit/archives — partitions in object storage and whether they verified. */
export async function listArchives(): Promise<AuditLogArchive[]> {
  const response = await api<{ items: AuditLogArchive[] }>("/audit/archives");
  return response.items;
}


/**
 * GET /audit/resource-types — the resource types this facility actually has
 * rows for.
 *
 * The dropdown used to be a hand-kept list of six. The table holds more than
 * that and three of the six matched nothing, so the filter offered dead
 * options and hid most of the data at the same time. A list maintained by hand
 * cannot track a vocabulary that grows whenever a model opts into auditing.
 */
export async function listAuditResourceTypes(): Promise<string[]> {
  const response = await api<{ items: string[] }>("/audit/resource-types");
  return response.items;
}
