import { api } from "@/lib/api";

/** ABDM M4 Health Facility Registry, through HealthDoc's admin-only proxy. */
export interface HfrOption { code: string; value?: string; name?: string }
export interface HfrFacility {
  facilityId: string;
  facilityName: string;
  facilityStatus?: string | null;
  facilityType?: string | null;
  ownership?: string | null;
  stateName?: string | null;
  districtName?: string | null;
  address?: string | null;
  pincode?: string | null;
}
export interface HfrSearch {
  facility_id?: string;
  facility_name?: string;
  ownership_code?: string;
  state_lgd_code?: string;
  district_lgd_code?: string;
  subdistrict_lgd_code?: string;
  pincode?: string;
  page?: number;
}
export interface HfrSearchResult {
  facilities: HfrFacility[];
  page: number;
  results_per_page: number;
  total: number | null;
  pages: number | null;
}
export interface HfrBridgeService { type: "HIP" | "HIU"; hip_name: string; active: boolean }

export async function hfrMaster(kind: string): Promise<HfrOption[]> {
  return (await api<{ data: HfrOption[] }>(`/abdm/hfr/master/${encodeURIComponent(kind)}`)).data;
}
export async function hfrStates(): Promise<HfrOption[]> {
  return (await api<{ states: HfrOption[] }>("/abdm/hfr/lgd/states")).states;
}
export async function hfrDistricts(stateCode: string): Promise<HfrOption[]> {
  return (await api<{ districts: HfrOption[] }>(`/abdm/hfr/lgd/districts?state_code=${encodeURIComponent(stateCode)}`)).districts;
}
export async function hfrSubdistricts(districtCode: string): Promise<HfrOption[]> {
  return (await api<{ subdistricts: HfrOption[] }>(`/abdm/hfr/lgd/subdistricts?district_code=${encodeURIComponent(districtCode)}`)).subdistricts;
}
export function searchHfr(criteria: HfrSearch): Promise<HfrSearchResult> {
  // A search: POST keeps criteria out of the URL; nothing is written.
  return api<HfrSearchResult>("/abdm/hfr/facilities/search", { method: "POST", body: JSON.stringify(criteria), idempotencyKey: null });
}
export function linkHfrBridge(facilityId: string, services: HfrBridgeService[], idempotencyKey: string) {
  return api<{ facility_id: string; facility_name: string; bridge_id: string }>("/abdm/hfr/bridge-link", {
    method: "POST",
    body: JSON.stringify({ facility_id: facilityId, services }),
    idempotencyKey,
  });
}

/** The facility manager's HPR login; HealthDoc keeps the token, never the browser. */
export type HprSession =
  | { logged_in: false }
  | { logged_in: true; hpr_id: string; hpr_id_number: string | null; expires_at: number };

export function hprLoginState(): Promise<HprSession> {
  return api<HprSession>("/abdm/hfr/hpr-login");
}
export function startHprOtp(hprId: string, method: "AADHAAR_OTP") {
  return api<{ session_id: string; masked_mobile: string | null }>("/abdm/hfr/hpr-login/otp", {
    method: "POST", body: JSON.stringify({ hpr_id: hprId, method }), idempotencyKey: null,
  });
}
export function verifyHprOtp(sessionId: string, otp: string): Promise<HprSession> {
  return api<HprSession>("/abdm/hfr/hpr-login/verify", {
    method: "POST", body: JSON.stringify({ session_id: sessionId, otp }), idempotencyKey: null,
  });
}
export function hprPasswordLogin(hprId: string, password: string): Promise<HprSession> {
  return api<HprSession>("/abdm/hfr/hpr-login/password", {
    method: "POST", body: JSON.stringify({ hpr_id: hprId, password }), idempotencyKey: null,
  });
}
export function hprLogout(): Promise<HprSession> {
  return api<HprSession>("/abdm/hfr/hpr-login", { method: "DELETE" });
}

// ------------------------------------------------------------- registration
// HFR-010 to 117. Every list comes from HFR; the manager must be signed in to HPR.

export async function hfrFacilityTypes(ownershipCode: string, systemOfMedicineCode: string): Promise<HfrOption[]> {
  const query = `ownership_code=${encodeURIComponent(ownershipCode)}&system_of_medicine_code=${encodeURIComponent(systemOfMedicineCode)}`;
  return (await api<{ data: HfrOption[] }>(`/abdm/hfr/facility-types?${query}`)).data;
}
export async function hfrFacilitySubtypes(facilityTypeCode: string): Promise<HfrOption[]> {
  return (await api<{ data: HfrOption[] }>(`/abdm/hfr/facility-subtypes?facility_type_code=${encodeURIComponent(facilityTypeCode)}`)).data;
}
export async function hfrOwnerSubtypes(ownershipCode: string, subtypeCode: string): Promise<HfrOption[]> {
  const query = `ownership_code=${encodeURIComponent(ownershipCode)}&owner_subtype_code=${encodeURIComponent(subtypeCode)}`;
  return (await api<{ data: HfrOption[] }>(`/abdm/hfr/owner-subtypes?${query}`)).data;
}
export async function hfrSpecialities(systemOfMedicineCode: string): Promise<HfrOption[]> {
  return (await api<{ data: HfrOption[] }>(`/abdm/hfr/specialities?system_of_medicine_code=${encodeURIComponent(systemOfMedicineCode)}`)).data;
}

export interface HfrUpload { name: string; content: string }
export interface HfrTiming { days: string[]; hours: string }
export interface HfrBasicInformation {
  tracking_id: string;
  name: string;
  address: {
    state_code: string; district_code: string; sub_district_code: string; region: string;
    address_line1: string; address_line2: string; pincode: string; latitude: string; longitude: string;
  };
  contact: { email: string; mobile: string; website: string; landline: string; std_code: string };
  ownership_code: string;
  ownership_subtype_code: string;
  ownership_subtype_code2: string;
  systems_of_medicine: string[];
  types_of_service: string[];
  facility_type_code: string;
  facility_subtype_code: string;
  speciality_type: string;
  operational_status: string;
  timings: HfrTiming[];
  board_photo: HfrUpload | null;
  building_photo: HfrUpload | null;
  address_proofs: { type: string; attachment: HfrUpload }[];
}
export interface HfrServiceCount { service: string; count: number }
export interface HfrAdditionalInformation {
  tracking_id: string;
  nhrr_id: string; nin: string; abpmjay_id: string; rohini_id: string;
  echs_id: string; cghs_id: string; cea_registration: string; state_insurance_scheme_id: string;
  general: { dialysis: string; pharmacy: string; blood_bank: string; cath_lab: string; diagnostic_lab: string; imaging: string };
  imaging_services: HfrServiceCount[];
}
export interface HfrDetailedInformation {
  tracking_id: string;
  specialities: { system_of_medicine: string; available: "Y" | "N"; codes: string[] }[];
  infrastructure: Record<string, number>;
  imaging_services: HfrServiceCount[];
  diagnostic_services: string[];
}
export interface HfrStepSaved { tracking_id: string; status: string | null; message: string | null }

// One call per step, so the contract check can match each to its route.
export function saveHfrBasic(body: HfrBasicInformation, idempotencyKey: string): Promise<HfrStepSaved> {
  return api<HfrStepSaved>("/abdm/hfr/registration/basic", { method: "POST", body: JSON.stringify(body), idempotencyKey });
}
export function saveHfrAdditional(body: HfrAdditionalInformation, idempotencyKey: string): Promise<HfrStepSaved> {
  return api<HfrStepSaved>("/abdm/hfr/registration/additional", { method: "POST", body: JSON.stringify(body), idempotencyKey });
}
export function saveHfrDetailed(body: HfrDetailedInformation, idempotencyKey: string): Promise<HfrStepSaved> {
  return api<HfrStepSaved>("/abdm/hfr/registration/detailed", { method: "POST", body: JSON.stringify(body), idempotencyKey });
}
export function submitHfrFacility(trackingId: string, idempotencyKey: string) {
  return api<{ facility_id: string; status: string | null; message: string | null }>("/abdm/hfr/registration/submit", {
    method: "POST", body: JSON.stringify({ tracking_id: trackingId }), idempotencyKey,
  });
}

// ------------------------------------------------------------- editing a registered facility
// HFR-064 to 114. HFR returns no saved details, so HealthDoc keeps what it sent
// (images excluded) and an edit opens with it.

export interface HfrRegistrationSummary {
  tracking_id: string;
  facility_id: string | null;
  facility_name: string | null;
  status: string | null;
  submitted_at: string | null;
  updated_at: string;
}
export interface HfrSavedRegistration extends HfrRegistrationSummary {
  basic: Omit<HfrBasicInformation, "tracking_id" | "board_photo" | "building_photo" | "address_proofs"> | null;
  additional: Omit<HfrAdditionalInformation, "tracking_id"> | null;
  detailed: Omit<HfrDetailedInformation, "tracking_id"> | null;
}

export async function listHfrRegistrations(): Promise<HfrRegistrationSummary[]> {
  return (await api<{ registrations: HfrRegistrationSummary[] }>("/abdm/hfr/registrations")).registrations;
}
export function getHfrRegistration(trackingId: string): Promise<HfrSavedRegistration> {
  return api<HfrSavedRegistration>(`/abdm/hfr/registrations/${encodeURIComponent(trackingId)}`);
}
