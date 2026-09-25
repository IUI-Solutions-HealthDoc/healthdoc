import { api, newIdempotencyKey } from "@/lib/api";

export interface Department {
  id: string;
  name: string;
  name_hi?: string | null;
  code: string;
  facility_id: string;
  is_active: boolean;
}

export interface Room {
  id: string;
  department_id: string;
  room_number: string;
  is_active: boolean;
}

interface ListResponse<T> {
  items: T[];
  page: number;
  page_size: number;
  total: number;
}

export function listDepartments(): Promise<ListResponse<Department>> {
  return api<ListResponse<Department>>("/departments?page=1&page_size=100");
}

export function listRooms(): Promise<ListResponse<Room>> {
  return api<ListResponse<Room>>("/departments/rooms?page=1&page_size=100");
}

export function createDepartment(
  name: string,
  code: string,
  name_hi?: string | null,
): Promise<Department> {
  return api<Department>("/departments", {
    method: "POST",
    idempotencyKey: newIdempotencyKey(),
    body: JSON.stringify({
      name,
      code,
      ...(name_hi && name_hi.trim() ? { name_hi: name_hi.trim() } : {}),
    }),
  });
}

export function updateDepartment(
  departmentId: string,
  payload: Partial<Pick<Department, "name" | "code" | "is_active">>,
): Promise<Department> {
  return api<Department>(`/departments/${departmentId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export function createRoom(departmentId: string, roomNumber: string): Promise<Room> {
  return api<Room>("/departments/rooms", {
    method: "POST",
    idempotencyKey: newIdempotencyKey(),
    body: JSON.stringify({ department_id: departmentId, room_number: roomNumber }),
  });
}

export function updateRoom(
  roomId: string,
  payload: Partial<Pick<Room, "room_number" | "is_active">>,
): Promise<Room> {
  return api<Room>(`/departments/rooms/${roomId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}
