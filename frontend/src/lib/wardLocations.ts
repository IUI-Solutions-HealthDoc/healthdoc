/**
 * Wards and beds as places, with no occupant: what the kitchen, laundry and
 * housekeeping screens pick from. HOD and the services supervisor may read
 * these; the bed grid (which names each patient) stays clinical.
 */
import { api } from "@/lib/api";

export interface LocationBed {
  bed_id: string;
  bed_number: string;
  status: string;
}

export interface WardLocation {
  ward_id: string;
  ward_name: string;
  beds: LocationBed[];
}

export function getWardLocations(): Promise<WardLocation[]> {
  return api<WardLocation[]>("/wards/locations");
}
