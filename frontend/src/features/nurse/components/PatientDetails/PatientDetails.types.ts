export type Sex = "male" | "female" | "other" | "unknown";

export interface Patient {
  id: string;
  uhid: string | null; 
  thid: string | null;
  full_name: string;
  sex: Sex;
  dob: string | null;
  age_years: number | null; 
  guardian_name: string | null;
  guardian_relationship: string | null;
  mobile: string | null;
  photo_file_id?: string | null;
  address_line?: string | null;
  village_town?: string | null;
  district?: string | null;
  state_code?: string | null;
  pincode?: string | null;
}
export interface PatientAdmissionContext {
  ward_name?: string;
  bed_number?: string;
  admitted_at?: string;
  diagnosis_text?: string;
}

export interface PatientDetailsProps {
  patient: (Patient & PatientAdmissionContext) | null;
}