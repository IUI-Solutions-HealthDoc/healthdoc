/**
 * Audit DTOs — GET /audit/logs matches BE AuditLogOut (§4.4).
 * data_access / file_access / integrity are schema-ahead (no live BE routes yet).
 */

/**
 * Mirrors app/audit/actions.py exactly.
 *
 * It previously listed "merge" and "delete_attempt", neither of which the
 * backend has ever written, while omitting nine that it does. The dropdown
 * built from it therefore offered filters that matched nothing and hid
 * records that existed.
 *
 * tests/audit-action-vocabulary.test.mjs compares this list against the
 * Python enum and fails on any drift in either direction.
 */
export type AuditAction =
  | "approve"
  | "break_glass_access"
  | "create"
  | "delete"
  | "dispense"
  | "erase"
  | "export"
  | "login"
  | "logout"
  | "print"
  | "return"
  | "role_change"
  | "thid_merge"
  | "thid_unmerge"
  | "uhid_merge"
  | "update"
  | "view";

export type VerificationStatus = "pending" | "verified" | "failed";

export type FileAccessAction = "view" | "download" | "upload" | "delete_attempt";

export type AccessChannel = "ui" | "api" | "abdm_hiu" | "export";

/** GET /audit/logs — AuditLogOut (slim). */
export type AuditLog = {
  id: string;
  user_id: string | null;
  role: string | null;
  action: AuditAction | string;
  resource_type: string;
  resource_id: string | null;
  patient_id: string | null;
  old_value: Record<string, unknown> | null;
  new_value: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
  entry_hash: string | null;
  /** FE join helpers — not returned by BE */
  user_display?: string;
  patient_display?: string;
};

export type AuditLogListResponse = {
  items: AuditLog[];
  page: number;
  page_size: number;
  total: number;
};

/** Schema §4.4 data_access_log — GET /audit/data-access. The endpoint is live
 *  (audit/compliance_router.py); this comment previously said 'not implemented
 *  on BE yet' while the file's own filter comment 20 lines below already
 *  described the real server parameter. */
export type DataAccessLog = {
  id: string;
  user_id: string;
  role: string;
  resource_type: string;
  resource_id: string | null;
  patient_id: string;
  purpose_code: string;
  access_channel: AccessChannel;
  emergency_access: boolean;
  consent_verified: boolean;
  accessed_at: string;
  user_display?: string;
  patient_display?: string;
};

/** Schema-ahead — archives / integrity not exposed by live audit router. */
export type AuditLogArchive = {
  id: string;
  facility_id: string;
  partition_name: string;
  period_start: string;
  period_end: string;
  row_count: number;
  object_storage_bucket: string;
  object_storage_key: string;
  archive_file_hash: string;
  archived_at: string;
  verified_at: string | null;
  verification_status: VerificationStatus;
};

export type AuditIntegrityCheck = {
  id: string;
  facility_id: string;
  partition_name: string;
  checked_at: string;
  rows_checked: number;
  chain_valid: boolean;
  signatures_valid: number;
  signatures_invalid: number;
  first_mismatch_id: string | null;
  alerted: boolean;
};

export type FileAccessLog = {
  id: string;
  file_id: string;
  user_id: string;
  action: FileAccessAction;
  ip_address: string | null;
  accessed_at: string;
  user_display?: string;
  file_name?: string;
};

export type AuditLogFilters = {
  query?: string;
  action?: string | "all";
  resource_type?: string | "all";
  user_id?: string;
  patient_id?: string;
  from?: string;
  to?: string;
  page?: number;
  page_size?: number;
};

export type FileAccessFilters = {
  query?: string;
  action?: FileAccessAction | "all";
};

export type DataAccessFilters = {
  /** Client-side over the loaded page — no server equivalent. */
  query?: string;
  /** Client-side over the loaded page — no server equivalent. */
  access_channel?: AccessChannel | "all";
  /** Real server filter: GET /audit/data-access?consent_id=. */
  consent_id?: string;
};
