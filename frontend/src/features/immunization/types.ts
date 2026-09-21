// Wire contracts mirror backend/app/immunization/schemas.py.
export interface Vaccine {
 id: string; code: string; name: string; target_disease: string;
 standard_doses: number; min_age_days: number; max_age_days: number | null;
 route: string; site: string; dose_quantity: string; is_active: boolean;
}
export interface ImmunizationRecord {
 id: string; patient_id: string; vaccine_id: string; vaccine_code: string;
 dose_number: number; administered_at: string; batch_number: string; expiry_date: string;
 manufacturer: string | null; site: string | null; route: string | null;
 administered_by: string; adverse_reaction: string | null; notes: string | null; created_at: string;
}
export interface ImmunizationRecordCreate {
 patient_id: string; vaccine_code: string; dose_number: number; administered_at?: string;
 batch_number: string; expiry_date: string; manufacturer?: string | null;
 site?: string | null; route?: string | null; adverse_reaction?: string | null;
}
export interface DueVaccineItem {
 vaccine_code: string; vaccine_name: string; dose_number: number;
 target_disease: string; min_age_days: number; status: string; due_date: string | null;
}
export interface PatientImmunizationSchedule {
 patient_id: string; patient_name: string; dob: string | null; age_days: number | null;
 administered: ImmunizationRecord[]; due: DueVaccineItem[];
}
export interface ImmunizationCertificate {
 patient_id: string; patient_name: string; dob: string | null; gender: string | null;
 abha_number: string | null; facility_name: string; certificate_id: string;
 generated_at: string; records: ImmunizationRecord[];
}
