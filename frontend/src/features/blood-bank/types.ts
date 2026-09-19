export type BloodGroup = "A+" | "A-" | "B+" | "B-" | "AB+" | "AB-" | "O+" | "O-";
export type BloodComponentType = "whole_blood" | "packed_rbc" | "fresh_frozen_plasma" | "platelets" | "cryoprecipitate";
export type BloodUnitStatus = "quarantine" | "available" | "reserved" | "issued" | "expired" | "discarded";
export type ScreeningStatus = "pending" | "passed" | "reactive_failed";

export interface BloodDonor {
  id: string;
  donor_number?: string;
  full_name: string;
  age?: number;
  age_years?: number;
  gender?: string;
  sex?: string;
  blood_group: string;
  rh_factor?: string;
  contact_phone?: string | null;
  mobile?: string | null;
  email?: string | null;
  is_eligible: boolean;
  ineligibility_reason?: string | null;
  remarks?: string | null;
  last_donation_date?: string | null;
  next_eligible_date?: string | null;
  created_at?: string;
}

export interface BloodDonorCreate {
  full_name: string;
  age: number;
  gender: string;
  blood_group: string;
  rh_factor: string;
  contact_phone?: string | null;
  is_eligible?: boolean;
  ineligibility_reason?: string | null;
  last_donation_date?: string | null;
}

export interface BloodUnit {
  id: string;
  unit_number?: string;
  bag_number?: string;
  donor_id: string | null;
  blood_group: string;
  rh_factor?: string;
  component_type?: string;
  volume_ml: number;
  collection_date?: string;
  collected_at?: string;
  expiry_date: string;
  status: string;
  screening_status: string;
  facility_id?: string;
  issued_to_patient_id?: string | null;
}

export function formatBloodGroup(bg: string, rh?: string): string {
  if (rh) return `${bg}${rh}`;
  if (!bg) return "—";
  const normalized = bg.toUpperCase();
  if (normalized.includes("_POS") || normalized.includes("+")) {
    return normalized.replace("_POS", "+");
  }
  if (normalized.includes("_NEG") || normalized.includes("-")) {
    return normalized.replace("_NEG", "-");
  }
  return bg;
}

export interface BloodUnitCreate {
  unit_number: string;
  donor_id?: string | null;
  blood_group: string;
  rh_factor: string;
  component_type: string;
  volume_ml?: number;
  collection_date: string;
  expiry_date: string;
  screening_status?: string;
  facility_id?: string;
}

export interface BloodCrossmatch {
  id: string;
  patient_id: string;
  blood_unit_id: string;
  compatibility_result: "compatible" | "incompatible" | "pending";
  crossmatched_by_staff_id: string;
  crossmatched_at: string;
  status: "reserved" | "issued" | "cancelled";
  issue_slip_number: string | null;
  issued_to_ward: string | null;
  issued_at: string | null;
  notes: string | null;
  unit_number?: string | null;
  blood_group?: string | null;
  component_type?: string | null;
}

export interface BloodCrossmatchCreate {
  patient_id: string;
  blood_unit_id: string;
  compatibility_result: "compatible" | "incompatible";
  notes?: string | null;
}

export interface BloodIssueRequest {
  crossmatch_id: string;
  issued_to_ward: string;
  notes?: string | null;
}
