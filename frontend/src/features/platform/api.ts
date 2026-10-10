import { api } from "@/lib/api";

export type PlatformFacility = {
  id: string;
  code: string;
  name: string;
  name_hi?: string | null;
  state_code: string;
  district: string | null;
  facility_type: string | null;
  hfr_facility_id: string | null;
  timezone: string;
  is_active: boolean;
  /** Listed on the public /availability page. */
  publish_availability?: boolean;
};

export type PlatformFacilityList = {
  items: PlatformFacility[];
  total: number;
  page: number;
  page_size: number;
};

export function listPlatformFacilities(search = ""): Promise<PlatformFacilityList> {
  const params = new URLSearchParams({ page: "1", page_size: "100" });
  if (search.trim()) params.set("search", search.trim());
  return api<PlatformFacilityList>(`/platform/facilities?${params.toString()}`);
}

export type PlatformFacilityCreate = {
  code: string; name: string; state_code: string; timezone?: string; district?: string | null;
  ownership?: "government" | "private" | null; hfr_facility_id?: string | null;
};

export function createPlatformFacility(body: PlatformFacilityCreate): Promise<PlatformFacility> {
  // A repeat is refused by the unique code, so no Idempotency-Key is needed.
  return api<PlatformFacility>("/platform/facilities", { method: "POST", body: JSON.stringify(body), idempotencyKey: null });
}

export function updatePlatformFacility(
  id: string, body: { hfr_facility_id?: string | null; name?: string; is_active?: boolean; publish_availability?: boolean },
): Promise<PlatformFacility> {
  return api<PlatformFacility>(`/platform/facilities/${id}`, { method: "PATCH", body: JSON.stringify(body) });
}

export function createPlatformFacilityAdmin(
  id: string, body: { username: string; full_name: string; email?: string | null; temporary_password: string },
): Promise<{ id: string; username: string }> {
  return api(`/platform/facilities/${id}/admins`, { method: "POST", body: JSON.stringify(body), idempotencyKey: null });
}

export type CopiedSetup = {
  departments: number; rooms: number; wards: number; stock_locations: number; tariff_rows: number;
};

export function copyPlatformFacilitySetup(id: string, sourceFacilityId: string): Promise<CopiedSetup> {
  return api<CopiedSetup>(`/platform/facilities/${id}/copy-setup`, {
    method: "POST", body: JSON.stringify({ source_facility_id: sourceFacilityId }), idempotencyKey: null,
  });
}
