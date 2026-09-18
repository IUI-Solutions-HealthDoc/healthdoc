import { api } from "@/lib/api";
import type {
  Appointment,
  AppointmentCheckInRequest,
  AppointmentCheckInResult,
  AppointmentCreate,
  AppointmentService,
  AppointmentServiceCreate,
  AppointmentUpdate,
} from "./types";

export async function listAppointmentServices(): Promise<AppointmentService[]> {
  const res = await api<AppointmentService[]>("/appointments/services");
  return Array.isArray(res) ? res : [];
}

export async function createAppointmentService(
  payload: AppointmentServiceCreate,
): Promise<AppointmentService> {
  return await api<AppointmentService>("/appointments/services", {
    method: "POST",
    idempotencyKey: crypto.randomUUID(),
    body: JSON.stringify(payload),
  });
}

export async function listAppointments(filters: {
  date_from?: string;
  date_to?: string;
  department_id?: string;
  doctor_user_id?: string;
  patient_id?: string;
  status?: string;
} = {}): Promise<Appointment[]> {
  const params = new URLSearchParams();
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  if (filters.department_id) params.set("department_id", filters.department_id);
  if (filters.doctor_user_id) params.set("doctor_user_id", filters.doctor_user_id);
  if (filters.patient_id) params.set("patient_id", filters.patient_id);
  if (filters.status) params.set("status", filters.status);

  const qs = params.toString();
  const url = qs ? `/appointments?${qs}` : "/appointments";
  const res = await api<Appointment[]>(url);
  return Array.isArray(res) ? res : [];
}

export async function createAppointment(payload: AppointmentCreate): Promise<Appointment> {
  return await api<Appointment>("/appointments", {
    method: "POST",
    idempotencyKey: crypto.randomUUID(),
    body: JSON.stringify(payload),
  });
}

export async function updateAppointment(
  appointmentId: string,
  payload: AppointmentUpdate,
): Promise<Appointment> {
  return await api<Appointment>(`/appointments/${appointmentId}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function checkInAppointment(
  appointmentId: string,
  payload: AppointmentCheckInRequest,
): Promise<AppointmentCheckInResult> {
  return await api<AppointmentCheckInResult>(`/appointments/${appointmentId}/check-in`, {
    method: "POST",
    idempotencyKey: crypto.randomUUID(),
    body: JSON.stringify(payload),
  });
}
