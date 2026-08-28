import type { RealmRole, User } from "./types";

export type FieldErrors = Record<string, string>;

export const FACILITY_STAFF_ROLES: readonly RealmRole[] = [
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
];

const USERNAME_PATTERN = /^[A-Za-z0-9._-]+$/;
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MOBILE_PATTERN = /^\+91\d{10}$/;

function optionalEmail(value: string): string | undefined {
  const next = value.trim();
  if (next && !EMAIL_PATTERN.test(next)) return "Enter a valid email address.";
  return undefined;
}

function optionalMobile(value: string): string | undefined {
  const next = value.trim();
  if (next && !MOBILE_PATTERN.test(next)) {
    return "Use Indian E.164 format: +91 followed by 10 digits.";
  }
  return undefined;
}

function usernameError(value: string): string | undefined {
  const next = value.trim();
  if (!next) return "Username is required.";
  if (next.length < 3) return "Username must be at least 3 characters.";
  if (next.length > 100) return "Username must be at most 100 characters.";
  if (!USERNAME_PATTERN.test(next)) {
    return "Use letters, numbers, dots, hyphens or underscores only; spaces are not allowed.";
  }
  return undefined;
}

function roleError(roles: RealmRole[]): string | undefined {
  if (roles.length === 0) return "Select at least one staff role.";
  if (roles.some((role) => !FACILITY_STAFF_ROLES.includes(role))) {
    return "Patient and platform-superadmin roles cannot be created in a facility staffing flow.";
  }
  return undefined;
}

function compact(errors: FieldErrors): FieldErrors {
  return Object.fromEntries(Object.entries(errors).filter(([, value]) => Boolean(value)));
}

export function validateCreateUser(values: {
  username: string;
  fullName: string;
  email: string;
  mobile: string;
  temporaryPassword: string;
  roles: RealmRole[];
}): FieldErrors {
  return compact({
    username: usernameError(values.username) ?? "",
    fullName: values.fullName.trim() ? "" : "Full name is required.",
    email: optionalEmail(values.email) ?? "",
    mobile: optionalMobile(values.mobile) ?? "",
    temporaryPassword:
      values.temporaryPassword.length >= 8
        ? ""
        : "Temporary password must be at least 8 characters.",
    roles: roleError(values.roles) ?? "",
  });
}

export function validateAccountRequest(values: {
  fullName: string;
  username: string;
  email: string;
  mobile: string;
  justification: string;
  roles: RealmRole[];
}): FieldErrors {
  return compact({
    fullName: values.fullName.trim() ? "" : "Full name is required.",
    username: usernameError(values.username) ?? "",
    email: optionalEmail(values.email) ?? "",
    mobile: optionalMobile(values.mobile) ?? "",
    justification:
      values.justification.trim().length >= 10
        ? ""
        : "Explain why this account is needed in at least 10 characters.",
    roles: roleError(values.roles) ?? "",
  });
}

export function validateUserProfile(user: User): FieldErrors {
  return compact({
    full_name: user.full_name.trim() ? "" : "Full name is required.",
    email: optionalEmail(user.email ?? "") ?? "",
    mobile: optionalMobile(user.mobile ?? "") ?? "",
  });
}
