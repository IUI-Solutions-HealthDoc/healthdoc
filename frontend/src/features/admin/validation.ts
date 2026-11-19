import type { RealmRole, User } from "./types";
import { translate } from "@/lib/i18n";

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
  if (next && !EMAIL_PATTERN.test(next)) return translate("admin.msg.enterAValidEmailAddress");
  return undefined;
}

function optionalMobile(value: string): string | undefined {
  const next = value.trim();
  if (next && !MOBILE_PATTERN.test(next)) {
    return translate("admin.msg.useIndianE164Format91");
  }
  return undefined;
}

function usernameError(value: string): string | undefined {
  const next = value.trim();
  if (!next) return translate("admin.msg.usernameIsRequired");
  if (next.length < 3) return translate("admin.msg.usernameMustBeAtLeast3");
  if (next.length > 100) return translate("admin.msg.usernameMustBeAtMost100");
  if (!USERNAME_PATTERN.test(next)) {
    return translate("admin.msg.useLettersNumbersDotsHyphensOr");
  }
  return undefined;
}

function roleError(roles: RealmRole[]): string | undefined {
  if (roles.length === 0) return translate("admin.msg.selectAtLeastOneStaffRole");
  if (roles.some((role) => !FACILITY_STAFF_ROLES.includes(role))) {
    return translate("admin.msg.patientAndPlatformSuperadminRolesCannot");
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
    fullName: values.fullName.trim() ? "" : translate("admin.msg.fullNameIsRequired"),
    email: optionalEmail(values.email) ?? "",
    mobile: optionalMobile(values.mobile) ?? "",
    temporaryPassword:
      values.temporaryPassword.length >= 8
        ? ""
        : translate("admin.msg.temporaryPasswordMustBeAtLeast"),
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
    fullName: values.fullName.trim() ? "" : translate("admin.msg.fullNameIsRequired"),
    username: usernameError(values.username) ?? "",
    email: optionalEmail(values.email) ?? "",
    mobile: optionalMobile(values.mobile) ?? "",
    justification:
      values.justification.trim().length >= 10
        ? ""
        : translate("admin.msg.explainWhyThisAccountIsNeeded"),
    roles: roleError(values.roles) ?? "",
  });
}

export function validateUserProfile(user: User): FieldErrors {
  const registrationErrors: FieldErrors = {};
  const kind = user.registration_identifier_type?.trim() ?? "";
  const system = user.registration_identifier_system?.trim() ?? "";
  if (kind || system) {
    if (!kind || kind.length > 50) registrationErrors.registration_identifier_type = translate("admin.msg.enterTheVerifiedIdentifierTypeUp");
    if (!user.registration_number?.trim() || user.registration_number.trim().length > 50) registrationErrors.registration_number = translate("admin.msg.enterTheClinicianSRealRegistration");
    try {
      const uri = new URL(system);
      if (!/^https?:$/.test(uri.protocol) || !uri.hostname || uri.username || uri.password || uri.search || uri.hash || /\s/.test(system) || system.length > 255) throw new Error("invalid");
    } catch {
      registrationErrors.registration_identifier_system = translate("admin.msg.enterTheIssuingRegistrySHttp");
    }
  }
  return compact({
    ...registrationErrors,
    full_name: user.full_name.trim() ? "" : translate("admin.msg.fullNameIsRequired"),
    email: optionalEmail(user.email ?? "") ?? "",
    mobile: optionalMobile(user.mobile ?? "") ?? "",
  });
}
