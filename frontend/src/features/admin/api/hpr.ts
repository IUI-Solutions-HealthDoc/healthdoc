import { api } from "@/lib/api";

/** ABDM M4 Healthcare Professionals Registry, through HealthDoc's admin-only proxy. */
export interface HprOption { code: string; label: string }
export interface HprCategory extends HprOption { subcategories: HprOption[] }

export async function hprCategories(): Promise<HprCategory[]> {
  return (await api<{ data: HprCategory[] }>("/abdm/hpr/master/categories")).data;
}
export async function hprStates(): Promise<HprOption[]> {
  return (await api<{ data: HprOption[] }>("/abdm/hpr/master/states")).data;
}
export async function hprDistricts(stateId: string): Promise<HprOption[]> {
  return (await api<{ data: HprOption[] }>(`/abdm/hpr/master/districts?state_code=${encodeURIComponent(stateId)}`)).data;
}

// ------------------------------------------------------------- HPID creation (HPR-002 to 011)
// The Aadhaar is verified on NHA's own page; HealthDoc never sees the number.

export interface HpidKyc {
  name: string; first_name: string; middle_name: string; last_name: string; gender: string;
  birth_date: string; address: string; state_name: string; district_name: string;
  pincode: string; email: string; photo: string; mobile_hint: string | null;
}
export type HpidVerified =
  | { existing: false; kyc: HpidKyc; suggestions: string[]; mobile_verified: boolean }
  | { existing: true; signed_in: boolean; hpr_id?: string; hpr_id_number: string; kyc: HpidKyc };
export interface HpidCreate {
  session_id: string; hpr_id: string; email: string; password: string;
  category_code: number; subcategory_code: number; state_id: string; district_id: string;
  role: "PROFESSIONAL" | "FACILITY_MANAGER" | "BOTH";
}

/** NHA's own Aadhaar page: consent, Aadhaar number, captcha and OTP. The
 * admin's page still waiting comes back, so a reload does not orphan it;
 * fresh (after Cancel) opens a new one. */
export function startHpidLink(fresh = false) {
  return api<{ session_id: string; url: string }>("/abdm/hpr/hpid/link", {
    method: "POST", body: JSON.stringify({ fresh }), idempotencyKey: null,
  });
}
export function checkHpidLink(sessionId: string): Promise<{ authenticated: false } | ({ authenticated: true } & HpidVerified)> {
  return api<{ authenticated: false } | ({ authenticated: true } & HpidVerified)>("/abdm/hpr/hpid/link/check", {
    method: "POST", body: JSON.stringify({ session_id: sessionId }), idempotencyKey: null,
  });
}
export function verifyHpidMobile(sessionId: string, mobile: string) {
  return api<{ mobile_verified: boolean; otp_sent: boolean }>("/abdm/hpr/hpid/mobile", {
    method: "POST", body: JSON.stringify({ session_id: sessionId, mobile }), idempotencyKey: null,
  });
}
export function confirmHpidMobile(sessionId: string, otp: string) {
  return api<{ mobile_verified: boolean }>("/abdm/hpr/hpid/mobile/verify", {
    method: "POST", body: JSON.stringify({ session_id: sessionId, otp }), idempotencyKey: null,
  });
}
export function createHpid(body: HpidCreate) {
  return api<{ hpr_id: string; hpr_id_number: string; logged_in: true; expires_at: number }>("/abdm/hpr/hpid/create", {
    method: "POST", body: JSON.stringify(body), idempotencyKey: null,
  });
}

// ------------------------------------------------------------- registration in HPR (HPR-018 to 079)

export interface HprSystem extends HprOption { hpr_type: string | null }
export interface HprCouncil extends HprOption { state_id: string | null; system_of_medicine_id: number | null }
export interface HprRegistrationOptions {
  salutations: HprOption[]; categories: HprOption[]; doctor_systems: HprOption[]; nurse_types: HprOption[];
  pharmacist_type: HprOption; work_status: HprOption[]; government_types: HprOption[];
  purposes: string[]; not_working_reasons: string[]; months: string[];
}
export async function hprSubDistricts(districtId: string): Promise<HprOption[]> {
  return (await api<{ data: HprOption[] }>(`/abdm/hpr/master/sub-districts?district_code=${encodeURIComponent(districtId)}`)).data;
}
export async function hprCountries(): Promise<HprOption[]> {
  return (await api<{ data: HprOption[] }>("/abdm/hpr/master/countries")).data;
}
export async function hprLanguages(): Promise<HprOption[]> {
  return (await api<{ data: HprOption[] }>("/abdm/hpr/master/languages")).data;
}
export async function hprSystems(): Promise<HprSystem[]> {
  return (await api<{ data: HprSystem[] }>("/abdm/hpr/master/systems-of-medicine")).data;
}
export async function hprCouncils(kind: "medical" | "nurse"): Promise<HprCouncil[]> {
  return (await api<{ data: HprCouncil[] }>(`/abdm/hpr/master/councils?kind=${kind}`)).data;
}
export async function hprCourses(systemOfMedicine: string, hprType: "doctor" | "nurse" | "pharmacist"): Promise<HprOption[]> {
  const query = `system_of_medicine=${encodeURIComponent(systemOfMedicine)}&hpr_type=${hprType}&all_courses=true`;
  return (await api<{ data: HprOption[] }>(`/abdm/hpr/master/courses?${query}`)).data;
}
export async function hprColleges(stateId: string, systemOfMedicine: string): Promise<HprOption[]> {
  const query = `state_code=${encodeURIComponent(stateId)}&system_of_medicine=${encodeURIComponent(systemOfMedicine)}`;
  return (await api<{ data: HprOption[] }>(`/abdm/hpr/master/colleges?${query}`)).data;
}
export async function hprUniversities(collegeId: string): Promise<HprOption[]> {
  return (await api<{ data: HprOption[] }>(`/abdm/hpr/master/universities?college_code=${encodeURIComponent(collegeId)}`)).data;
}
export function hprRegistrationOptions(): Promise<HprRegistrationOptions> {
  return api<HprRegistrationOptions>("/abdm/hpr/master/registration-options");
}

export interface HprProfile extends HpidKyc { hpr_id: string; hpr_id_number: string | null }
export function hprProfile(): Promise<HprProfile> {
  return api<HprProfile>("/abdm/hpr/profile");
}
export function hprProfessional(): Promise<{ practitioner: Record<string, unknown> | null }> {
  return api<{ practitioner: Record<string, unknown> | null }>("/abdm/hpr/professional");
}

export interface HprDocument { file_type: "pdf" | "png" | "jpeg" | "jpg"; content: string }
export interface HprQualification {
  degree: number; country: string; state: string; college: number; university: number; year: number;
  month: string | null; certificate: HprDocument; name_differs: boolean; name_change_proof: HprDocument | null;
}
export interface HprProfessionalForm {
  salutation: number; category: number; subcategory: number; nationality: string;
  father_name: string; mother_name: string; spouse_name: string; languages: number[];
  communication_address: { name: string; address: string; country: string; state: string; district: string; sub_district: string; city: string; pincode: string } | null;
  official_mobile: string; official_email: string; public_mobile: string; public_email: string; landline: string; landline_code: string;
  registration: {
    council: number; number: string; registered_on: string; certificate: HprDocument; renewable: boolean;
    renewal_due: string | null; name_differs: boolean; name_change_proof: HprDocument | null; qualifications: HprQualification[];
  };
  work: {
    working: boolean; reason_not_working: string; purpose: string | null; status: string | null;
    government_type: string | null; ministry: string; proof: HprDocument | null;
    facility_id: string | null; department: string; designation: string;
  };
  show_photo: boolean; public_profile: boolean;
}
export interface HprSubmitted { reference_number: string | null; status: string | null; message: string | null; hpr_id: string | null; hpr_id_number: string | null }
export function registerHprProfessional(body: HprProfessionalForm, idempotencyKey: string) {
  return api<HprSubmitted>("/abdm/hpr/professional", { method: "POST", body: JSON.stringify(body), idempotencyKey });
}
export function updateHprProfessional(body: HprProfessionalForm, idempotencyKey: string) {
  return api<HprSubmitted>("/abdm/hpr/professional/update", { method: "POST", body: JSON.stringify(body), idempotencyKey });
}
