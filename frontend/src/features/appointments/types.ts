export type AppointmentStatus =
  | "booked"
  | "confirmed"
  | "checked_in"
  | "completed"
  | "cancelled"
  | "no_show"
  | "rescheduled";

export interface AppointmentService {
  id: string;
  facility_id: string;
  department_id?: string | null;
  name: string;
  duration_minutes: number;
  is_active: boolean;
  description?: string | null;
}

export interface AppointmentServiceCreate {
  name: string;
  duration_minutes: number;
  department_id?: string | null;
  description?: string | null;
}

export interface Appointment {
  id: string;
  facility_id: string;
  patient_id: string;
  department_id: string;
  doctor_user_id?: string | null;
  service_id?: string | null;
  service_name: string;
  duration_minutes: number;
  appointment_date: string; // YYYY-MM-DD
  start_time: string; // HH:MM
  end_time: string; // HH:MM
  status: AppointmentStatus;
  is_walk_in: boolean;
  is_teleconsult: boolean;
  teleconsult_status?: string | null;
  notes?: string | null;
  follow_up_from_visit_id?: string | null;
  visit_id?: string | null;
  token_id?: string | null;
  cancellation_reason?: string | null;
  created_at: string;
  patient_name?: string | null;
  patient_uhid?: string | null;
  doctor_name?: string | null;
  department_name?: string | null;
}

export interface AppointmentCreate {
  patient_id: string;
  department_id: string;
  doctor_user_id?: string | null;
  service_id?: string | null;
  service_name?: string;
  duration_minutes?: number;
  appointment_date: string; // YYYY-MM-DD
  start_time: string; // HH:MM
  is_walk_in?: boolean;
  is_teleconsult?: boolean;
  notes?: string | null;
  follow_up_from_visit_id?: string | null;
}

export interface AppointmentUpdate {
  appointment_date?: string;
  start_time?: string;
  duration_minutes?: number;
  doctor_user_id?: string | null;
  status?: AppointmentStatus;
  cancellation_reason?: string | null;
  notes?: string | null;
}

export interface AppointmentCheckInRequest {
  queue_id?: string | null;
  priority?: "normal" | "urgent" | "vip" | "emergency";
}

export interface AppointmentCheckInResult {
  appointment_id: string;
  status: AppointmentStatus;
  visit_id: string;
  visit_number: string;
  token_id?: string | null;
  token_display?: string | null;
}
