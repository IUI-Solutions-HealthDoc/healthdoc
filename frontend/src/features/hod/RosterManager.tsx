"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { toast } from "@/components/ui/toast";
import { ApiError, newIdempotencyKey } from "@/lib/api";

import {
  createRosterEntry,
  listRoster,
  listRosterCandidates,
  listRosterRooms,
  setRosterAvailability,
} from "./api";
import type {
  RosterCandidate,
  RosterEntry,
  RosterRoom,
  RosterShift,
} from "./types";

interface RosterManagerProps {
  departmentId: string;
  today: string;
}

const SHIFTS: ReadonlyArray<{ value: RosterShift; label: string }> = [
  { value: "morning", label: "Morning" },
  { value: "evening", label: "Evening" },
  { value: "night", label: "Night" },
];

function requestMessage(reason: unknown, fallback: string): string {
  if (reason instanceof ApiError && reason.code === 409) {
    return "That staff member is already rostered for this date and shift.";
  }
  return reason instanceof ApiError ? reason.message : fallback;
}

/**
 * The write side of the HOD roster.
 *
 * Morning OPD previously relied on seed_dev_data.py because the product could
 * only display a roster. This form uses the existing POST/PATCH routes so a
 * real HOD can recover an empty day without a SQL seed or an engineer.
 */
export function RosterManager({ departmentId, today }: RosterManagerProps) {
  const [rosterDate, setRosterDate] = useState(today);
  const [staffId, setStaffId] = useState("");
  const [roomId, setRoomId] = useState("");
  const [shift, setShift] = useState<RosterShift>("morning");
  const [candidates, setCandidates] = useState<RosterCandidate[]>([]);
  const [rooms, setRooms] = useState<RosterRoom[]>([]);
  const [entries, setEntries] = useState<RosterEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [createKey, setCreateKey] = useState(() => newIdempotencyKey());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [staff, activeRooms, roster] = await Promise.all([
        listRosterCandidates(departmentId),
        listRosterRooms(departmentId),
        listRoster(departmentId, rosterDate),
      ]);
      setCandidates(staff);
      setRooms(activeRooms);
      setEntries(roster);
      setStaffId((current) =>
        staff.some((candidate) => candidate.staff_user_id === current)
          ? current
          : (staff[0]?.staff_user_id ?? ""),
      );
      setRoomId((current) =>
        activeRooms.some((room) => room.id === current) ? current : "",
      );
      setError(null);
    } catch (reason) {
      setError(requestMessage(reason, "Could not load the roster."));
    } finally {
      setLoading(false);
    }
  }, [departmentId, rosterDate]);

  useEffect(() => {
    void load();
  }, [load]);

  const candidateById = useMemo(
    () => new Map(candidates.map((candidate) => [candidate.staff_user_id, candidate])),
    [candidates],
  );
  const roomById = useMemo(
    () => new Map(rooms.map((room) => [room.id, room])),
    [rooms],
  );

  const handleCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!staffId) {
      setFieldError("Select a staff member before adding the roster entry.");
      return;
    }
    if (!rosterDate || rosterDate < today) {
      setFieldError("Choose today or a future roster date.");
      return;
    }

    setSaving(true);
    setFieldError(null);
    setError(null);
    try {
      await createRosterEntry(
        {
          staff_user_id: staffId,
          department_id: departmentId,
          room_id: roomId || null,
          shift,
          roster_date: rosterDate,
        },
        createKey,
      );
      const selected = candidateById.get(staffId);
      toast.success(
        "Roster entry added",
        `${selected?.staff_name ?? "Staff member"} · ${shift}`,
      );
      setCreateKey(newIdempotencyKey());
      setEntries(await listRoster(departmentId, rosterDate));
    } catch (reason) {
      setError(requestMessage(reason, "Could not add the roster entry."));
    } finally {
      setSaving(false);
    }
  };

  const handleAvailability = async (entry: RosterEntry) => {
    setUpdatingId(entry.id);
    setError(null);
    try {
      const updated = await setRosterAvailability(entry.id, !entry.is_available);
      setEntries((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
      toast.success(
        updated.is_available ? "Staff marked available" : "Staff marked unavailable",
      );
    } catch (reason) {
      setError(requestMessage(reason, "Could not update availability."));
    } finally {
      setUpdatingId(null);
    }
  };

  return (
    <section className="space-y-4" aria-labelledby="roster-heading">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="roster-heading" className="text-xl font-semibold">Department roster</h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Add staff here before reception opens the day&apos;s OPD queues. Room assignment is
            optional and only active staff from this department are shown.
          </p>
        </div>
        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">View date</span>
          <input
            type="date"
            min={today}
            value={rosterDate}
            onChange={(event) => setRosterDate(event.target.value)}
            className="block rounded-md border border-border bg-background px-3 py-2"
          />
        </label>
      </div>

      {error ? (
        <p role="alert" className="rounded-md bg-danger-muted p-3 text-sm text-danger">
          {error}
        </p>
      ) : null}

      <form
        className="surface-card grid gap-4 p-5 md:grid-cols-[2fr_1fr_1fr_auto] md:items-end"
        onSubmit={(event) => void handleCreate(event)}
        noValidate
      >
        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">Staff member</span>
          <select
            value={staffId}
            onChange={(event) => {
              setStaffId(event.target.value);
              setFieldError(null);
            }}
            disabled={loading || candidates.length === 0}
            aria-invalid={Boolean(fieldError && !staffId)}
            className="w-full rounded-md border border-border bg-background px-3 py-2 disabled:opacity-60"
          >
            {candidates.length === 0 ? <option value="">No active staff found</option> : null}
            {candidates.map((candidate) => (
              <option key={candidate.staff_user_id} value={candidate.staff_user_id}>
                {candidate.staff_name}
                {candidate.designation ? ` · ${candidate.designation}` : ""}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">Shift</span>
          <select
            value={shift}
            onChange={(event) => setShift(event.target.value as RosterShift)}
            className="w-full rounded-md border border-border bg-background px-3 py-2"
          >
            {SHIFTS.map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
        </label>

        <label className="space-y-1 text-sm">
          <span className="text-muted-foreground">Room (optional)</span>
          <select
            value={roomId}
            onChange={(event) => setRoomId(event.target.value)}
            className="w-full rounded-md border border-border bg-background px-3 py-2"
          >
            <option value="">No room assigned</option>
            {rooms.map((room) => (
              <option key={room.id} value={room.id}>{room.room_number}</option>
            ))}
          </select>
        </label>

        <button
          type="submit"
          disabled={saving || loading || candidates.length === 0}
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {saving ? "Adding…" : "Add to roster"}
        </button>

        {fieldError ? (
          <p role="alert" className="text-sm text-danger md:col-span-4">{fieldError}</p>
        ) : null}
        {!loading && candidates.length === 0 ? (
          <p className="text-sm text-muted-foreground md:col-span-4">
            An administrator must attach active staff to this department before they can be
            rostered. No database seed is required.
          </p>
        ) : null}
      </form>

      {loading ? <p className="text-sm text-muted-foreground">Loading roster…</p> : null}
      {!loading && entries.length === 0 ? (
        <p className="rounded border border-dashed border-border p-4 text-sm text-muted-foreground">
          No roster entries for {rosterDate}. Add the first entry above so reception can open
          the OPD queue.
        </p>
      ) : null}
      {entries.length > 0 ? (
        <div className="surface-card overflow-hidden">
          <table className="min-w-full border-collapse text-sm">
            <thead className="bg-muted">
              <tr>
                <th className="px-4 py-3 text-left">Staff</th>
                <th className="px-4 py-3 text-left">Shift</th>
                <th className="px-4 py-3 text-left">Room</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => {
                const candidate = candidateById.get(entry.staff_user_id);
                const room = entry.room_id ? roomById.get(entry.room_id) : null;
                return (
                  <tr key={entry.id} className="border-b border-border last:border-none">
                    <td className="px-4 py-3">
                      <span className="font-medium">
                        {candidate?.staff_name ?? "Staff record unavailable"}
                      </span>
                      {candidate?.designation ? (
                        <span className="block text-xs text-muted-foreground">
                          {candidate.designation}
                        </span>
                      ) : null}
                    </td>
                    <td className="px-4 py-3 capitalize">{entry.shift}</td>
                    <td className="px-4 py-3">{room?.room_number ?? "—"}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded px-2 py-0.5 text-xs ${
                          entry.is_available
                            ? "bg-green-100 text-green-800"
                            : "bg-amber-100 text-amber-900"
                        }`}
                      >
                        {entry.is_available ? "available" : "unavailable"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        disabled={updatingId !== null}
                        onClick={() => void handleAvailability(entry)}
                        className="text-sm underline disabled:opacity-50"
                      >
                        {updatingId === entry.id
                          ? "Updating…"
                          : entry.is_available
                            ? "Mark unavailable"
                            : "Mark available"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
