import { api } from "@/lib/api";

export type PlatformFacility = {
  id: string;
  code: string;
  name: string;
  state_code: string;
  district: string | null;
  facility_type: string | null;
  hfr_facility_id: string | null;
  timezone: string;
  is_active: boolean;
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
