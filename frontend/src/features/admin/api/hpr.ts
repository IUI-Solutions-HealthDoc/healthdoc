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
  return (await api<{ data: HprOption[] }>(`/abdm/hpr/master/districts?state_id=${encodeURIComponent(stateId)}`)).data;
}

// ------------------------------------------------------------- HPID creation (HPR-002 to 011)
// The professional authenticates with Aadhaar on NHA's own page; HealthDoc
// never sees the Aadhaar number or its OTP.

export interface HpidKyc {
  name: string; first_name: string; middle_name: string; last_name: string; gender: string;
  birth_date: string; year_of_birth: string; address: string; state_name: string; district_name: string;
  pincode: string; email: string; photo: string;
}
export type HpidCheck =
  | { authenticated: false }
  | { authenticated: true; existing_hpr_id: string }
  | { authenticated: true; kyc: HpidKyc; aadhaar_mobile_hint: string | null; suggestions: string[]; mobile_verified: boolean };
export interface HpidCreate {
  session_id: string; hpr_id: string; email: string; password: string;
  category_code: number; subcategory_code: number; state_code: string; district_code: string;
}

export function startHpid() {
  return api<{ session_id: string; url: string }>("/abdm/hpr/hpid/start", { method: "POST", idempotencyKey: null });
}
export function checkHpid(sessionId: string): Promise<HpidCheck> {
  return api<HpidCheck>("/abdm/hpr/hpid/check", { method: "POST", body: JSON.stringify({ session_id: sessionId }), idempotencyKey: null });
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
