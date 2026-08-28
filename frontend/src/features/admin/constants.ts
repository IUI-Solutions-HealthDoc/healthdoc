import type { ModuleCode, RealmRole } from "./types";

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
  radiology: "Radiology",
  pharmacy: "Pharmacy",
  ot: "OT",
  blood_bank: "Blood bank",
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
];

export const REALM_ROLE_LABELS: Record<RealmRole, string> = {
  receptionist: "Receptionist",
  doctor: "Doctor",
  nurse: "Nurse",
  lab_tech: "Lab tech",
  radiology_tech: "Radiology tech",
  pharmacist: "Pharmacist",
  emergency: "Emergency",
  supervisor: "Supervisor",
  admin: "Admin",
  hod: "HOD",
  auditor: "Auditor",
  patient: "Patient",
  superadmin: "Superadmin",
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
  facilities: "Facilities",
  patients: "Patients",
  registration: "Registration",
  opd: "OPD",
  queue: "Queue",
  billing: "Billing",
  lab: "Lab",
  radiology: "Radiology",
  pharmacy: "Pharmacy",
  inventory: "Inventory",
  ipd: "IPD",
  ot: "OT",
  blood_bank: "Blood",
  emergency: "Emergency",
  consent: "Consent",
  audit: "Audit",
  users: "Users",
};

/** Which ModuleCode / core areas each realm role typically touches (reference only). */
export const ROLE_CAPABILITY_MAP: Record<RealmRole, MatrixCapability[]> = {
  receptionist: ["patients", "registration", "opd", "queue", "billing"],
  doctor: ["patients", "registration", "opd", "queue", "lab", "radiology", "pharmacy", "ipd", "ot", "emergency"],
  nurse: ["patients", "opd", "ipd", "emergency", "pharmacy"],
  lab_tech: ["patients", "lab"],
  radiology_tech: ["patients", "radiology"],
  pharmacist: ["patients", "pharmacy", "inventory"],
  emergency: ["patients", "registration", "emergency", "opd"],
  supervisor: ["patients", "registration", "opd", "queue", "billing", "lab", "radiology", "pharmacy", "ipd", "audit"],
  admin: ["users", "billing", "inventory", "audit", "consent"],
  hod: ["patients", "opd", "queue", "lab", "radiology", "pharmacy", "ipd", "ot"],
  auditor: ["audit", "consent", "billing"],
  patient: ["patients"],
  superadmin: ["facilities"],
};

export const APPROVAL_STATUS_LABELS: Record<"pending" | "approved" | "rejected", string> = {
  pending: "Pending",
  approved: "Approved",
  rejected: "Rejected",
};
