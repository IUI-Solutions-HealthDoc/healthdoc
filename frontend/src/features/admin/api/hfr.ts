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
export function startHprOtp(hprId: string, method: "AADHAAR_OTP" | "MOBILE_OTP") {
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
