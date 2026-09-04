// FACILITY_ID / FACILITY_CODE re-exported MOCK_FACILITY_* and had no
// consumers once the audit endpoints started scoping server-side from the
// token. Removed (P1.1) — never send a facility from the browser.
import type { AccessChannel, AuditAction, FileAccessAction, VerificationStatus } from "./types";

export const AUDIT_ACTION_LABELS: Record<string, string> = {
  create: "Create",
  update: "Update",
  delete: "Delete",
  erase: "Erase",
  login: "Login",
  logout: "Logout",
  view: "View",
  export: "Export",
  print: "Print",
  break_glass_access: "Break-glass access",
  uhid_merge: "UHID merge",
  thid_merge: "THID merge",
  thid_unmerge: "THID unmerge",
  approve: "Approve",
  dispense: "Dispense",
  return: "Return",
  role_change: "Role change",
};

export const FILE_ACCESS_ACTION_LABELS: Record<FileAccessAction, string> = {
  view: "View",
  download: "Download",
  upload: "Upload",
  delete_attempt: "Delete attempt",
};

export const ACCESS_CHANNEL_LABELS: Record<AccessChannel, string> = {
  ui: "UI",
  api: "API",
  abdm_hiu: "ABDM HIU",
  export: "Export",
};

export const VERIFICATION_STATUS_LABELS: Record<VerificationStatus, string> = {
  pending: "Pending",
  verified: "Verified",
  failed: "Failed",
};

// EVERY action the backend can write, taken from app/audit/actions.py.
//
// This was a hand-picked list of six that included "merge" — an action the
// backend has never written. Real merges are recorded as uhid_merge /
// thid_merge / thid_unmerge, so filtering for "Merge" returned nothing and
// read as "no merges happened" rather than "wrong filter name". It also
// omitted delete, erase, print, break-glass, approve, dispense, return and
// role_change, hiding records that do exist.
//
// tests/audit-action-vocabulary.test.mjs fails if this drifts from the enum
// again — the list is long enough that nobody will catch it by eye.
export const COMMON_AUDIT_ACTIONS: AuditAction[] = [
  "approve",
  "break_glass_access",
  "create",
  "delete",
  "dispense",
  "erase",
  "export",
  "login",
  "logout",
  "print",
  "return",
  "role_change",
  "thid_merge",
  "thid_unmerge",
  "uhid_merge",
  "update",
  "view",
];

export const COMMON_RESOURCE_TYPES = [
  "patients",
  "visits",
  "invoices",
  "lab_orders",
  "radiology_orders",
  "users",
];
