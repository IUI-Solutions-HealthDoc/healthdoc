import type { ModuleCode, RealmRole } from "./types";
import { translate } from "@/lib/i18n";

// Retired (P1.1):
//
//   FACILITY_ID / FACILITY_CODE / FACILITY_DISPLAY_NAME re-exported
//   MOCK_FACILITY_*. Nothing on the wire told the browser which facility it was
//   in until GET /users/me existed. Use useCurrentUser() — and never send a
//   facility from the browser; the server derives it from the token.
//
//   MOCK_SESSION_ADMIN_USER_ID / MOCK_APPROVER_USER_ID were two hardcoded ids
//   that made "approver != requester" true by construction, so the screen
//   advertised maker-checker while guaranteeing it trivially. Both sides now
//   come from the token and the server compares them.

/** v3.13 — exactly five optional ModuleCode values. */
export const MODULE_CODES: ModuleCode[] = [
  "lab",
  "radiology",
  "pharmacy",
  "ot",
  "blood_bank",
];

export const MODULE_CODE_LABELS: Record<ModuleCode, string> = {
  lab: "Lab",
  get radiology() { return translate("sidebar.radiology"); },
  get pharmacy() { return translate("doctor.orderType.pharmacy"); },
  ot: "OT",
  get blood_bank() { return translate("admin.msg.bloodBank"); },
};

/** Core modules that can never be disabled (schema text — display legend only). */
export const CORE_ALWAYS_ON_MODULES = [
  "patients",
  "registration",
  "encounters/opd",
  "queue",
  "departments",
  "billing",
  "consent",
  "audit",
  "files",
  "users",
  "notifications",
  "inventory",
  "ipd",
  "emergency",
  "patient_portal",
  "abdm",
  "refunds",
] as const;

export const REALM_ROLES: RealmRole[] = [
  "receptionist",
  "doctor",
  "nurse",
  "lab_tech",
  "radiology_tech",
  "pharmacist",
  "emergency",
  "supervisor",
  "admin",
  "hod",
  "auditor",
  "patient",
  "superadmin",
  "monitor",
];

export const REALM_ROLE_LABELS: Record<RealmRole, string> = {
  get receptionist() { return translate("role.receptionist"); },
  get doctor() { return translate("common.doctor"); },
  get nurse() { return translate("role.nurse"); },
  get lab_tech() { return translate("admin.msg.labTech"); },
  get radiology_tech() { return translate("admin.msg.radiologyTech"); },
  get pharmacist() { return translate("role.pharmacist"); },
  get emergency() { return translate("role.emergency"); },
  get supervisor() { return translate("role.supervisor"); },
  get billing() { return translate("admin.msg.billingDesk"); },
  get admin() { return translate("role.admin"); },
  hod: "HOD",
  get auditor() { return translate("role.auditor"); },
  get patient() { return translate("common.patient"); },
  get superadmin() { return translate("role.superadmin"); },
  get monitor() { return translate("role.monitor"); },
};

/**
 * Read-only reference: realm role × ModuleCode (and core clinical).
 * Derived only from role names + module codes in the schema — not a DB ACL table.
 */
export type MatrixCapability =
  | ModuleCode
  | "facilities"
  | "patients"
  | "registration"
  | "opd"
  | "queue"
  | "billing"
  | "consent"
  | "audit"
  | "users"
  | "inventory"
  | "ipd"
  | "emergency";

export const MATRIX_CAPABILITIES: MatrixCapability[] = [
  "facilities",
  "patients",
  "registration",
  "opd",
  "queue",
  "billing",
  "lab",
  "radiology",
  "pharmacy",
  "inventory",
  "ipd",
  "ot",
  "blood_bank",
  "emergency",
  "consent",
  "audit",
  "users",
];

export const MATRIX_CAPABILITY_LABELS: Record<MatrixCapability, string> = {
  get facilities() { return translate("sidebar.facilities"); },
  get patients() { return translate("admin.msg.patients"); },
  get registration() { return translate("sidebar.registration"); },
  opd: "OPD",
  get queue() { return translate("nav.queue"); },
  get billing() { return translate("nav.billing"); },
  lab: "Lab",
  get radiology() { return translate("sidebar.radiology"); },
  get pharmacy() { return translate("doctor.orderType.pharmacy"); },
  get inventory() { return translate("sidebar.inventory"); },
  ipd: "IPD",
  ot: "OT",
  get blood_bank() { return translate("doctor.orderType.blood"); },
  get emergency() { return translate("role.emergency"); },
  get consent() { return translate("nav.consent"); },
  get audit() { return translate("area.audit"); },
  get users() { return translate("sidebar.users"); },
};

/** Which ModuleCode / core areas each realm role typically touches (reference only). */
export const ROLE_CAPABILITY_MAP: Record<RealmRole, MatrixCapability[]> = {
  receptionist: ["patients", "registration", "opd", "queue"],
  doctor: ["patients", "registration", "opd", "queue", "lab", "radiology", "pharmacy", "ipd", "ot", "emergency"],
  nurse: ["patients", "opd", "ipd", "emergency", "pharmacy"],
  lab_tech: ["patients", "lab"],
  radiology_tech: ["patients", "radiology"],
  //: `billing` here is the over-the-counter medicine counter only — the API
  //: refuses a pharmacist any invoice carrying a non-pharmacy charge.
  pharmacist: ["patients", "pharmacy", "inventory", "billing"],
  emergency: ["patients", "registration", "emergency", "opd"],
  supervisor: ["patients", "registration", "opd", "queue", "lab", "radiology", "pharmacy", "ipd", "audit"],
  //: Raising, issuing and settling invoices, plus the tariff catalogue. The
  //: only role besides admin that may bill anything other than medicines.
  billing: ["billing", "patients"],
  admin: ["users", "billing", "inventory", "audit", "consent"],
  hod: ["patients", "opd", "queue", "lab", "radiology", "pharmacy", "ipd", "ot"],
  auditor: ["audit", "consent", "billing"],
  patient: ["patients"],
  superadmin: ["facilities"],
  //: Counts per facility in a granted state or district; no patient data.
  monitor: ["facilities"],
};

export const APPROVAL_STATUS_LABELS: Record<"pending" | "approved" | "rejected", string> = {
  get pending() { return translate("doctor.soapStatusPending"); },
  get approved() { return translate("admin.accountRequests.status.approved"); },
  get rejected() { return translate("admin.accountRequests.status.rejected"); },
};
