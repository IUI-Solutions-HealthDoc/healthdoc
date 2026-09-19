import { api } from "@/lib/api";
import type {
  CompleteOtCaseInput,
  CreateOtScheduleInput,
  OtSchedule,
  OtScheduleDetail,
  UpdateWhoChecklistInput,
} from "./types";

export async function listOtSchedules(filters?: {
  theatre_number?: string;
  status?: string;
}): Promise<OtSchedule[]> {
  const params = new URLSearchParams();
  if (filters?.theatre_number) params.set("theatre_number", filters.theatre_number);
  if (filters?.status) params.set("status", filters.status);
  return api<OtSchedule[]>(`/ot/schedules?${params.toString()}`);
}

export async function createOtSchedule(body: CreateOtScheduleInput): Promise<OtSchedule> {
  return api<OtSchedule>("/ot/schedules", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getOtSchedule(scheduleId: string): Promise<OtScheduleDetail> {
  return api<OtScheduleDetail>(`/ot/schedules/${scheduleId}`);
}

export async function updateWhoChecklist(
  scheduleId: string,
  body: UpdateWhoChecklistInput,
): Promise<OtSchedule> {
  return api<OtSchedule>(`/ot/schedules/${scheduleId}/checklist`, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

export async function startOtCase(scheduleId: string): Promise<OtSchedule> {
  return api<OtSchedule>(`/ot/schedules/${scheduleId}/start`, {
    method: "POST",
  });
}

export async function completeOtCase(
  scheduleId: string,
  body: CompleteOtCaseInput,
): Promise<OtScheduleDetail> {
  return api<OtScheduleDetail>(`/ot/schedules/${scheduleId}/complete`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function cancelOtCase(scheduleId: string, cancelReason: string): Promise<OtSchedule> {
  return api<OtSchedule>(`/ot/schedules/${scheduleId}/cancel`, {
    method: "POST",
    body: JSON.stringify({ cancel_reason: cancelReason }),
  });
}

export async function getTheatreDayList(targetDate?: string): Promise<Record<string, OtSchedule[]>> {
  const query = targetDate ? `?target_date=${encodeURIComponent(targetDate)}` : "";
  return api<Record<string, OtSchedule[]>>(`/ot/day-list${query}`);
}
