import { api, newIdempotencyKey } from "@/lib/api";
import type {
  Appointment,
  AppointmentCheckInRequest,
  AppointmentCheckInResult,
  AppointmentCreate,
  AppointmentService,
  AppointmentServiceCreate,
  AppointmentUpdate,
  BookableProviders,
} from "./types";

// Every write takes the caller's key so a retry of the same action replays the
// first result instead of booking or checking in twice. The default only
// covers callers that cannot retry.

export async function listAppointmentServices(): Promise<AppointmentService[]> {
  const res = await api<AppointmentService[]>("/appointments/services");
  return Array.isArray(res) ? res : [];
}

export async function createAppointmentService(
  payload: AppointmentServiceCreate,
  idempotencyKey: string = newIdempotencyKey(),
): Promise<AppointmentService> {
  return await api<AppointmentService>("/appointments/services", {
    method: "POST",
    idempotencyKey,
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

/** Staff rostered and available on the booking date, optionally in one department. */
export async function listBookableProviders(
  serviceDate: string,
  departmentId?: string,
): Promise<BookableProviders> {
  const params = new URLSearchParams({ service_date: serviceDate });
  if (departmentId) params.set("department_id", departmentId);
  return await api<BookableProviders>(`/queue/bookable-providers?${params.toString()}`);
}

export async function createAppointment(
  payload: AppointmentCreate,
  idempotencyKey: string = newIdempotencyKey(),
): Promise<Appointment> {
  return await api<Appointment>("/appointments", {
    method: "POST",
    idempotencyKey,
    body: JSON.stringify(payload),
  });
}

export async function updateAppointment(
  appointmentId: string,
  payload: AppointmentUpdate,
  idempotencyKey: string = newIdempotencyKey(),
): Promise<Appointment> {
  return await api<Appointment>(`/appointments/${appointmentId}`, {
    method: "PATCH",
    idempotencyKey,
    body: JSON.stringify(payload),
  });
}

export async function checkInAppointment(
  appointmentId: string,
  payload: AppointmentCheckInRequest,
  idempotencyKey: string = newIdempotencyKey(),
): Promise<AppointmentCheckInResult> {
  return await api<AppointmentCheckInResult>(`/appointments/${appointmentId}/check-in`, {
    method: "POST",
    idempotencyKey,
    body: JSON.stringify(payload),
  });
}
