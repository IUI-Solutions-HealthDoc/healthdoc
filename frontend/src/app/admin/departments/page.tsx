"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import {
  createDepartment,
  createRoom,
  listDepartments,
  listRooms,
  updateDepartment,
  updateRoom,
  type Department,
  type Room,
} from "@/features/admin/api/departments";
import { ApiError } from "@/lib/api";

export default function Page() {
  const [departments, setDepartments] = useState<Department[] | null>(null);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [roomDepartment, setRoomDepartment] = useState("");
  const [roomNumber, setRoomNumber] = useState("");
  const [busy, setBusy] = useState(false);
  const [showDepartmentForm, setShowDepartmentForm] = useState(false);
  const [showRoomForm, setShowRoomForm] = useState(false);
  const [departmentFormError, setDepartmentFormError] = useState<string | null>(null);
  const [roomFormError, setRoomFormError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [departmentResponse, roomResponse] = await Promise.all([
        listDepartments(),
        listRooms(),
      ]);
      setDepartments(departmentResponse.items);
      setRooms(roomResponse.items);
      setRoomDepartment((current) => current || departmentResponse.items[0]?.id || "");
      setError(null);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Could not load departments");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function addDepartment(event: React.FormEvent) {
    event.preventDefault();
    const nextName = name.trim();
    const nextCode = code.trim().toUpperCase();
    if (nextName.length < 2) {
      setDepartmentFormError("Department name must be at least 2 characters.");
      return;
    }
    if (!/^[A-Z0-9_-]{2,12}$/.test(nextCode)) {
      setDepartmentFormError("Code must be 2–12 letters, numbers, hyphens or underscores.");
      return;
    }
    setBusy(true);
    setError(null);
    setDepartmentFormError(null);
    try {
      const created = await createDepartment(nextName, nextCode);
      setDepartments((current) => [...(current ?? []), created]);
      setName("");
      setCode("");
      setRoomDepartment((current) => current || created.id);
      setMessage("Department created in your facility.");
      setShowDepartmentForm(false);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Department could not be created");
    } finally {
      setBusy(false);
    }
  }

  async function addRoom(event: React.FormEvent) {
    event.preventDefault();
    if (!roomDepartment) {
      setRoomFormError("Select a department.");
      return;
    }
    if (roomNumber.trim().length < 1) {
      setRoomFormError("Room number or name is required.");
      return;
    }
    setBusy(true);
    setError(null);
    setRoomFormError(null);
    try {
      const created = await createRoom(roomDepartment, roomNumber.trim());
      setRooms((current) => [...current, created]);
      setRoomNumber("");
      setMessage("Room created.");
      setShowRoomForm(false);
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Room could not be created");
    } finally {
      setBusy(false);
    }
  }

  async function toggleDepartment(department: Department) {
    try {
      const updated = await updateDepartment(department.id, { is_active: !department.is_active });
      setDepartments((current) =>
        current?.map((item) => (item.id === updated.id ? updated : item)) ?? [],
      );
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Department update failed");
    }
  }

  async function toggleRoom(room: Room) {
    try {
      const updated = await updateRoom(room.id, { is_active: !room.is_active });
      setRooms((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } catch (reason) {
      setError(reason instanceof ApiError ? reason.message : "Room update failed");
    }
  }

  return (
    <div className="space-y-8 p-6">
      <div>
        <Link href="/admin" className="mb-3 inline-block text-sm font-medium text-primary underline">
          ← Back to administration
        </Link>
        <h1 className="text-3xl font-semibold">Departments and rooms</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          All records and mutations are restricted to the signed-in administrator’s facility.
        </p>
      </div>

      {error ? (
        <p role="alert" className="rounded-md bg-danger-muted p-3 text-sm text-danger">
          {error}
        </p>
      ) : null}
      {message ? (
        <p role="status" className="rounded-md bg-success-muted p-3 text-sm text-success">
          {message}
        </p>
      ) : null}

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => setShowDepartmentForm((current) => !current)}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
          aria-expanded={showDepartmentForm}
        >
          {showDepartmentForm ? "Cancel department" : "Create department"}
        </button>
        <button
          type="button"
          onClick={() => setShowRoomForm((current) => !current)}
          className="rounded-md border border-border px-4 py-2 text-sm font-medium"
          aria-expanded={showRoomForm}
          disabled={!departments?.some((department) => department.is_active)}
        >
          {showRoomForm ? "Cancel room" : "Create room"}
        </button>
      </div>

      {showDepartmentForm || showRoomForm ? (
        <div className="grid gap-6 lg:grid-cols-2">
        {showDepartmentForm ? (
          <form onSubmit={addDepartment} className="surface-card space-y-4 p-5">
          <h2 className="text-lg font-medium">Create department</h2>
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">Name</span>
            <input
              required
              className="w-full rounded-md border border-border px-3 py-2"
              value={name}
              onChange={(event) => {
                setName(event.target.value);
                setDepartmentFormError(null);
              }}
              minLength={2}
            />
          </label>
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">Code</span>
            <input
              required
              className="w-full rounded-md border border-border px-3 py-2 uppercase"
              value={code}
              onChange={(event) => {
                setCode(event.target.value);
                setDepartmentFormError(null);
              }}
              minLength={2}
              maxLength={12}
              pattern="[A-Za-z0-9_-]+"
            />
          </label>
          {departmentFormError ? (
            <p role="alert" className="text-sm text-danger">{departmentFormError}</p>
          ) : null}
          <button
            type="submit"
            disabled={busy}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            Create department
          </button>
        </form>
        ) : null}

        {showRoomForm ? (
          <form onSubmit={addRoom} className="surface-card space-y-4 p-5">
          <h2 className="text-lg font-medium">Create room</h2>
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">Department</span>
            <select
              required
              className="w-full rounded-md border border-border px-3 py-2"
              value={roomDepartment}
              onChange={(event) => {
                setRoomDepartment(event.target.value);
                setRoomFormError(null);
              }}
            >
              <option value="">Select</option>
              {departments?.filter((department) => department.is_active).map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1 text-sm">
            <span className="text-muted-foreground">Room number/name</span>
            <input
              required
              className="w-full rounded-md border border-border px-3 py-2"
              value={roomNumber}
              onChange={(event) => {
                setRoomNumber(event.target.value);
                setRoomFormError(null);
              }}
            />
          </label>
          {roomFormError ? (
            <p role="alert" className="text-sm text-danger">{roomFormError}</p>
          ) : null}
          <button
            type="submit"
            disabled={busy || !roomDepartment}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            Create room
          </button>
        </form>
        ) : null}
        </div>
      ) : null}

      {departments === null ? <p className="text-sm text-muted-foreground">Loading…</p> : null}
      <div className="surface-card overflow-hidden">
        <div className="border-b border-border px-5 py-4">
          <h2 className="text-lg font-medium">Configured departments</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {departments?.length ?? 0} department{departments?.length === 1 ? "" : "s"}
          </p>
        </div>
        <div className="divide-y divide-border">
        {departments?.map((department) => {
          const departmentRooms = rooms.filter((room) => room.department_id === department.id);
          return (
            <section key={department.id} className="p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="font-medium">{department.name}</h2>
                  <p className="text-sm text-muted-foreground">
                    {department.code} · {departmentRooms.length} room
                    {departmentRooms.length === 1 ? "" : "s"}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void toggleDepartment(department)}
                  className={`rounded-full px-3 py-1 text-xs font-medium ${
                    department.is_active
                      ? "bg-success-muted text-success"
                      : "bg-muted text-muted-foreground"
                  }`}
                >
                  {department.is_active ? "Active" : "Inactive"}
                </button>
              </div>
              {departmentRooms.length > 0 ? (
                <ul className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {departmentRooms.map((room) => (
                    <li
                      key={room.id}
                      className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm"
                    >
                      <span>{room.room_number}</span>
                      <button
                        type="button"
                        className="text-xs underline"
                        onClick={() => void toggleRoom(room)}
                      >
                        {room.is_active ? "Deactivate" : "Activate"}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-4 text-sm text-muted-foreground">No rooms configured.</p>
              )}
            </section>
          );
        })}
        </div>
      </div>
    </div>
  );
}
