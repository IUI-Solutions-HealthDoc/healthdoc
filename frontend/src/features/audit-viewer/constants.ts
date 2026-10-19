// FACILITY_ID / FACILITY_CODE re-exported MOCK_FACILITY_* and had no
// consumers once the audit endpoints started scoping server-side from the
// token. Removed (P1.1) — never send a facility from the browser.
import type { AccessChannel, AuditAction, FileAccessAction, VerificationStatus } from "./types";
import { translate } from "@/lib/i18n";

export const AUDIT_ACTION_LABELS: Record<string, string> = {
  get create() { return translate("audit.msg.create"); },
  get update() { return translate("audit.msg.update"); },
  get delete() { return translate("common.delete"); },
  get erase() { return translate("audit.msg.erase"); },
  get login() { return translate("audit.msg.login"); },
  get logout() { return translate("audit.msg.logout"); },
  get view() { return translate("audit.msg.view"); },
  get export() { return translate("consent.access.export"); },
  get print() { return translate("common.ui.print"); },
  break_glass_access: "Break-glass access",
  uhid_merge: "UHID merge",
  thid_merge: "THID merge",
  thid_unmerge: "THID unmerge",
  get approve() { return translate("common.approve"); },
  get dispense() { return translate("sidebar.dispense"); },
  get return() { return translate("audit.msg.return"); },
  get role_change() { return translate("audit.msg.roleChange"); },
};

export const FILE_ACCESS_ACTION_LABELS: Record<FileAccessAction, string> = {
  get view() { return translate("audit.msg.view"); },
  get download() { return translate("forms.ui.download"); },
  get upload() { return translate("audit.msg.upload"); },
  get delete_attempt() { return translate("audit.msg.deleteAttempt"); },
};

export const ACCESS_CHANNEL_LABELS: Record<AccessChannel, string> = {
  ui: "UI",
  api: "API",
  abdm_hiu: "ABDM HIU",
  get export() { return translate("consent.access.export"); },
};

export const VERIFICATION_STATUS_LABELS: Record<VerificationStatus, string> = {
  get pending() { return translate("doctor.soapStatusPending"); },
  get verified() { return translate("consent.verified"); },
  get failed() { return translate("bloodBank.screening.failed"); },
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
