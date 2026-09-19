export interface Vaccine {
  id: string;
  code: string;
  name: string;
  target_disease: string;
  schedule_age_months: number;
  dose_number: number;
  route: string;
  site: string | null;
  is_active: boolean;
}

export interface ImmunizationRecord {
  id: string;
  patient_id: string;
  vaccine_id: string;
  dose_number: number;
  administered_date: string;
  batch_number: string;
  expiry_date: string | null;
  manufacturer: string | null;
  site: string | null;
  route: string | null;
  adverse_reaction: string | null;
  facility_id: string;
  administered_by_staff_id: string;
  created_at: string;
  vaccine_name?: string | null;
  vaccine_code?: string | null;
}

export interface ImmunizationRecordCreate {
  patient_id: string;
  vaccine_id: string;
  dose_number: number;
  administered_date: string;
  batch_number: string;
  expiry_date?: string | null;
  manufacturer?: string | null;
  site?: string | null;
  route?: string | null;
  adverse_reaction?: string | null;
}

export interface DueVaccineItem {
  vaccine_id: string;
  vaccine_name: string;
  vaccine_code: string;
  dose_number: number;
  due_at_months: number;
  route: string;
  site: string | null;
  status: "due" | "overdue" | "scheduled";
}

export interface PatientImmunizationSchedule {
  patient_id: string;
  records: ImmunizationRecord[];
  due_vaccines: DueVaccineItem[];
  overdue_vaccines: DueVaccineItem[];
}

export interface ImmunizationCertificate {
  certificate_id: string;
  facility_name: string;
  facility_id: string;
  generated_at: string;
  patient: {
    id: string;
    uhid: string;
    full_name: string;
    birth_date: string;
    gender: string;
  };
  vaccinations: Array<{
    vaccine_name: string;
    vaccine_code: string;
    dose_number: number;
    administered_date: string;
    batch_number: string;
    manufacturer: string | null;
  }>;
  digital_signature_hash: string;
}
